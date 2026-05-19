"""PolyAgora Phase-II — Layer 2: Convexity Sleeves (Deliverable C).

The typed sleeve catalog, two candidate convexity sleeves, the admission
pipeline, and the per-zone blend layer (Impl Spec §8-§9).

  - make_xs_expansion_signal  : Type-B — cross-sectional expansion. Long the
        top-quartile / short the bottom-quartile of trailing risk-adjusted
        return. Market-direction-neutral by construction (the only way to
        harvest reflation dispersion AND clear the Corr-SPY gate).
  - make_breakout_signal      : Type-C — transition breakout. Time-series
        breakout; the Layer-2 zone logic favours it only in TRANSITION.
  - admit_sleeve              : the 6-gate admission (registry gates 1-5 +
        Fragility Audit) + Type-I/II ERQ classification.
  - ConvexitySleeves          : Layer-2 — blends admitted sleeves into the
        book at per-zone caps.

Honest scoping: whether a candidate is admitted is decided by the gates —
a rejection is the machinery working (cf. the V7.10 mean-reversion
rejection), not a failure of this module.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from polyagora_v63_partner_engine import CASH, EngineConfig, SignalFn
from polyagora_sleeve_registry import GateConfig, SleeveSpec, evaluate_sleeve
from polyagora.regression import CRISIS_WINDOWS, metrics

_EPS = 1e-9

# Per-zone sleeve caps by type (Impl Spec §9). BUFFER ("hold") is not emitted
# by the moat base provider, so it is absent here.
ZONE_CAP: dict[str, dict[str, float]] = {
    "LOCAL_STAR": {"A": 0.10, "B": 0.25, "C": 0.10, "D": 0.00},
    "TRANSITION": {"A": 0.15, "B": 0.12, "C": 0.25, "D": 0.05},
    "LEAST_BAD":  {"A": 0.20, "B": 0.05, "C": 0.10, "D": 0.10},
    "BOUNDARY":   {"A": 0.25, "B": 0.00, "C": 0.00, "D": 0.25},
}


# =============================================================================
# Candidate sleeve signals
# =============================================================================

def make_xs_expansion_signal(lookback: int = 126, vol_window: int = 63) -> SignalFn:
    """Type-B — cross-sectional expansion (long winners / short losers).

    Ranks live futures by trailing `lookback`-day return / trailing vol,
    cross-sectionally standardizes, and deploys long/short at gross 1.
    Direction-neutral, so it harvests dispersion without equity beta.
    Anti-hindsight: reads realized history <= t only.
    """
    def _signal(history: pd.DataFrame, live: list[str], cfg: EngineConfig) -> pd.Series:
        if len(history) < lookback or len(live) < 4:
            return pd.Series(0.0, index=live)
        win = history[live]
        cum = win.iloc[-lookback:].sum(min_count=lookback // 2)
        vol = win.iloc[-vol_window:].std()
        risk_adj = (cum / (vol + _EPS)).dropna()
        if len(risk_adj) < 4 or risk_adj.std() < _EPS:
            return pd.Series(0.0, index=live)
        z = (risk_adj - risk_adj.mean()) / risk_adj.std()
        gross = float(z.abs().sum())
        if gross < _EPS:
            return pd.Series(0.0, index=live)
        return (z / gross).reindex(live).fillna(0.0)

    return _signal


def make_breakout_signal(fast: int = 21, slow: int = 126) -> SignalFn:
    """Type-C — transition breakout (fast trend vs slow baseline).

    Long futures whose fast cumulative return clears their slow baseline,
    short the converse; gross 1. The Layer-2 zone logic favours this sleeve
    in TRANSITION and gates it off under BOUNDARY. Anti-hindsight.
    """
    def _signal(history: pd.DataFrame, live: list[str], cfg: EngineConfig) -> pd.Series:
        if len(history) < slow or len(live) < 4:
            return pd.Series(0.0, index=live)
        win = history[live]
        fast_r = win.iloc[-fast:].sum()
        slow_r = win.iloc[-slow:].sum() * (fast / slow)
        sig = np.sign((fast_r - slow_r).fillna(0.0))
        gross = float(sig.abs().sum())
        if gross < _EPS:
            return pd.Series(0.0, index=live)
        return (sig / gross).reindex(live).fillna(0.0)

    return _signal


# =============================================================================
# ERQ classification of a sleeve (Type-I irreversible vs Type-II recoverable)
# =============================================================================

def sleeve_erq(weights: pd.DataFrame, universe: list[str]) -> float:
    """Structural ERQ of a sleeve weight panel (Impl Spec §5, geometric mean).

    Computed from position structure only — short fraction (forced
    traversal), concentration (corridor width), turnover (liquidity),
    boundedness. The geometry-coupled components E/F are set neutral here
    (a standalone sleeve has no market-state context).
    """
    w = weights[universe].fillna(0.0)
    gross = w.abs().sum(axis=1).replace(0.0, np.nan)
    short = (-w).clip(lower=0.0).sum(axis=1)
    shares = w.abs().div(gross, axis=0)
    hhi = (shares ** 2).sum(axis=1)
    n = len(universe)
    turnover = w.diff().abs().sum(axis=1)
    erq_A = (1.0 - short / gross).clip(0.0, 1.0).mean()
    erq_B = (1.0 - (hhi - 1.0 / n) / (1.0 - 1.0 / n)).clip(0.0, 1.0).mean()
    erq_C = (1.0 - turnover.clip(0.0, 1.0)).mean()
    erq_D = 1.0                       # gross-1 sleeve — bounded by construction
    comps = [max(float(x), _EPS) for x in (erq_A, erq_B, erq_C, erq_D, 0.75, 0.75)]
    return float(np.prod(comps) ** (1.0 / 6.0))


# =============================================================================
# Admission — 6 gates (registry gates 1-5 + Fragility Audit) + ERQ class
# =============================================================================

def fragility_audit(sleeve_returns: pd.Series, min_window_dd: float = -0.25) -> bool:
    """Gate 6 — Fragility Audit. The sleeve must not suffer a ruinous
    drawdown in any rupture window (GFC / COVID / 2022)."""
    for _, (a, b) in CRISIS_WINDOWS.items():
        seg = sleeve_returns.loc[a:b]
        if len(seg) and metrics(seg)["max_dd"] < min_window_dd:
            return False
    return True


class AdmissionResult:
    """Outcome of running a candidate sleeve through the 6-gate pipeline."""

    def __init__(self, spec, evaluation, fragility_ok, erq, theta_erq,
                 panel, sleeve_returns):
        self.spec = spec
        self.evaluation = evaluation
        self.fragility_ok = fragility_ok
        self.erq = erq
        self.erq_class = "Type-II" if erq > theta_erq else "Type-I"
        self.panel = panel
        self.sleeve_returns = sleeve_returns
        self.admitted = bool(evaluation.admitted and fragility_ok)
        self.base_weight = float(evaluation.base_weight) if self.admitted else 0.0

    def summary(self) -> str:
        g = self.evaluation.gates
        gates = "  ".join(f"{k}={'P' if v else 'F'}" for k, v in g.items())
        return (f"[{'ADMITTED' if self.admitted else 'REJECTED'}] "
                f"{self.spec.strategy_id} ({self.spec.sleeve_type}, {self.erq_class}, "
                f"ERQ={self.erq:.3f})\n    gates 1-5: {gates}  "
                f"fragility={'P' if self.fragility_ok else 'F'}  "
                f"base_weight={self.base_weight:.3f}")


def admit_sleeve(spec: SleeveSpec, panel: pd.DataFrame, sleeve_returns: pd.Series,
                 book_returns: pd.Series, universe: list[str], *,
                 theta_erq: float = 0.70,
                 cfg: GateConfig | None = None) -> AdmissionResult:
    """Run a candidate through the 6-gate pipeline + ERQ classification."""
    evaluation = evaluate_sleeve(spec, sleeve_returns, book_returns, cfg or GateConfig())
    fragility_ok = fragility_audit(sleeve_returns)
    erq = sleeve_erq(panel, universe)
    return AdmissionResult(spec, evaluation, fragility_ok, erq, theta_erq,
                           panel, sleeve_returns)


# =============================================================================
# Layer 2 — Convexity Sleeves blend
# =============================================================================

class ConvexitySleeves:
    """Layer 2. Blends admitted sleeves into the book at per-zone caps."""

    def __init__(self, admitted: list[AdmissionResult], universe: list[str]) -> None:
        self.universe = list(universe)
        self.admitted = [a for a in admitted if a.admitted]

    def run_add(self, state, history):
        state.log["L2_add"] = "ADD passthrough (moat base already ADD-filtered)"
        return state

    def run_sleeves(self, state, history):
        if not self.admitted:
            state.pi_t = pd.Series(dtype=float)
            state.log["L2_sleeves"] = "no admitted sleeves"
            return state
        t = state.date
        book = state.base_w.reindex(self.universe).fillna(0.0)
        shares = {}
        for sl in self.admitted:
            cap = ZONE_CAP.get(state.zone_t, {}).get(sl.spec.sleeve_type, 0.0)
            share = sl.base_weight * cap
            if share <= _EPS or t not in sl.panel.index:
                continue
            sw = sl.panel.loc[t].reindex(self.universe).fillna(0.0)
            book = (1.0 - share) * book + share * sw
            shares[sl.spec.strategy_id] = share
        state.base_w = book
        state.pi_t = pd.Series(shares, dtype=float)
        state.log["L2_sleeves"] = (f"blended {len(shares)} sleeve(s): "
                                   + ", ".join(f"{k}={v:.3f}" for k, v in shares.items())
                                   if shares else "sleeves zone-capped to 0")
        return state
