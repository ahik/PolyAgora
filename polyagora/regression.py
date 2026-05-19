"""PolyAgora Phase-II — the §12.2 regression gate ("the crisis moat is sacred").

Phase 2 ("reproduce the V7.10 crisis moat") is gated by the regression
tolerance band of `Implementation_Spec.md` §12.2 — PolygonEye's answer to
open question Q5. A Phase-II runtime increment is accepted only if it holds
the V7.10 baseline within:

    Sharpe (full)      max -0.07 vs reference
    Max DD (full)      max +1.5 pp worse
    Corr SPY           max +0.03 higher
    Crisis windows     ZERO degradation (GFC / COVID / 2022) — sacred
    Recovery latency   max +15% longer

This module computes the band and emits a per-row PASS / FAIL verdict
against a captured V7.10 reference return stream.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import pandas as pd

TRADING_DAYS = 252

# Crisis windows (the v710-check REG windows).
CRISIS_WINDOWS: dict[str, tuple[str, str]] = {
    "GFC":   ("2008-04-01", "2009-03-31"),
    "COVID": ("2020-02-15", "2020-12-31"),
    "2022":  ("2022-01-01", "2022-12-31"),
}


def _max_underwater(returns: pd.Series) -> int:
    """Longest run of consecutive bars with equity below its running peak."""
    eq = (1.0 + returns.fillna(0.0)).cumprod()
    underwater = (eq < eq.cummax() - 1e-12).values
    best = run = 0
    for u in underwater:
        run = run + 1 if u else 0
        best = max(best, run)
    return int(best)


def metrics(returns: pd.Series, ann: int = TRADING_DAYS) -> dict:
    """Sharpe / Sortino / Calmar / CAGR / Max DD / max-underwater for a series."""
    r = returns.dropna()
    if len(r) < 30 or r.std() == 0:
        return {"sharpe": 0.0, "sortino": 0.0, "calmar": 0.0, "cagr": 0.0,
                "max_dd": 0.0, "max_underwater": 0, "n": int(len(r))}
    mu, sd = r.mean(), r.std()
    sharpe = (mu * ann) / (sd * math.sqrt(ann))
    down = r[r < 0]
    sortino = ((mu * ann) / (down.std() * math.sqrt(ann))
               if len(down) > 1 and down.std() > 0 else float("inf"))
    eq = (1.0 + r).cumprod()
    max_dd = float((eq / eq.cummax() - 1.0).min())
    cagr = float(eq.iloc[-1] ** (ann / len(r)) - 1.0)
    calmar = cagr / abs(max_dd) if max_dd < -1e-9 else float("inf")
    return {"sharpe": float(sharpe), "sortino": float(sortino),
            "calmar": float(calmar), "cagr": cagr, "max_dd": max_dd,
            "max_underwater": _max_underwater(r), "n": int(len(r))}


@dataclass
class BandCheck:
    metric: str
    reference: float
    candidate: float
    rule: str
    passed: bool


@dataclass
class RegressionResult:
    checks: list[BandCheck]

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks)

    def report(self) -> str:
        lines = [
            f"{'Metric':<26}{'Reference':>12}{'Candidate':>12}  "
            f"{'Rule':<24}{'Verdict':>8}",
            "-" * 92,
        ]
        for c in self.checks:
            lines.append(
                f"{c.metric:<26}{c.reference:>12.4f}{c.candidate:>12.4f}  "
                f"{c.rule:<24}{'PASS' if c.passed else 'FAIL':>8}"
            )
        lines.append("-" * 92)
        verdict = "PASS — moat preserved" if self.passed else "FAIL — moat regressed"
        lines.append(f"§12.2 REGRESSION GATE: {verdict}  "
                     f"({sum(c.passed for c in self.checks)}/{len(self.checks)} checks)")
        return "\n".join(lines)


class RegressionGate:
    """The §12.2 band, measured against a captured V7.10 reference series."""

    def __init__(self, reference: pd.Series, spy: pd.Series | None = None) -> None:
        self.reference = reference.dropna()
        self.spy = spy.dropna() if spy is not None else None
        self.ref_m = metrics(self.reference)

    def _corr_spy(self, r: pd.Series) -> float:
        if self.spy is None:
            return float("nan")
        j = pd.concat([r, self.spy], axis=1, join="inner").dropna()
        return float(j.iloc[:, 0].corr(j.iloc[:, 1])) if len(j) > 30 else float("nan")

    def evaluate(self, candidate: pd.Series) -> RegressionResult:
        cand = candidate.dropna()
        cm = metrics(cand)
        checks: list[BandCheck] = []

        # Full-window Sharpe — max -0.07.
        checks.append(BandCheck(
            "Sharpe (full)", self.ref_m["sharpe"], cm["sharpe"],
            "cand >= ref - 0.07", cm["sharpe"] >= self.ref_m["sharpe"] - 0.07))

        # Full-window Max DD — max +1.5 pp worse (drawdowns are negative).
        checks.append(BandCheck(
            "Max DD (full)", self.ref_m["max_dd"], cm["max_dd"],
            "cand >= ref - 1.5pp", cm["max_dd"] >= self.ref_m["max_dd"] - 0.015))

        # Corr SPY — max +0.03 higher.
        if self.spy is not None:
            rc, cc = self._corr_spy(self.reference), self._corr_spy(cand)
            checks.append(BandCheck(
                "Corr SPY", rc, cc, "cand <= ref + 0.03", cc <= rc + 0.03))

        # Crisis windows — ZERO degradation (Sharpe and Max DD), sacred.
        for name, (a, b) in CRISIS_WINDOWS.items():
            rm = metrics(self.reference.loc[a:b])
            cw = metrics(cand.loc[a:b])
            checks.append(BandCheck(
                f"{name} Sharpe", rm["sharpe"], cw["sharpe"],
                "cand >= ref (zero degr.)", cw["sharpe"] >= rm["sharpe"] - 1e-9))
            checks.append(BandCheck(
                f"{name} Max DD", rm["max_dd"], cw["max_dd"],
                "cand >= ref (zero degr.)", cw["max_dd"] >= rm["max_dd"] - 1e-9))

        # Recovery latency — max +15% longer underwater.
        checks.append(BandCheck(
            "Recovery latency (bars)", float(self.ref_m["max_underwater"]),
            float(cm["max_underwater"]), "cand <= ref x 1.15",
            cm["max_underwater"] <= self.ref_m["max_underwater"] * 1.15 + 1e-9))

        return RegressionResult(checks)
