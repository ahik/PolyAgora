"""
PolyAgora V7.10 — Strategy Sleeve Registry
============================================

The governance-side machinery from `docs/More Sleeves.pdf`. A candidate
alpha strategy never enters the book on its Sharpe alone — it enters as
a *sleeve* only after clearing an ordered gate pipeline:

    validation → Deflated Sharpe → regime / zone permission
               → correlation-to-book → Kelly sizing

"A strategy is judged not by Sharpe, but by whether it survives under
the active regime ordering." PolyAgora remains the semantic governance
engine deciding which sleeves are admissible, when they enter, how large
they get, and when they are killed.

Each accepted strategy is stored with the doc-2 metadata schema —
including a per-runtime-zone permission table (Zone 1 Stable → full …
Zone 4 Rupture → off) consistent with the V7.9 `RotationConfig` zones.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from polyagora_validation import (
    DegradationResult,
    DSRResult,
    deflated_sharpe,
    performance_metrics,
    walk_forward_degradation,
)


# Per-zone exposure multiplier (doc-2 zone_permission; V7.9 runtime zones).
ZONE_PERMISSION_DEFAULT: dict[str, float] = {
    "1-Stable": 1.00,      # full
    "2-Transition": 0.50,  # reduced
    "3-Stress": 0.20,      # minimal
    "4-Rupture": 0.00,     # off / hedged
}


@dataclass
class SleeveSpec:
    """Metadata for one candidate sleeve (doc-2 schema)."""
    strategy_id: str
    sleeve_type: str                       # momentum / mean_reversion / carry / ...
    horizon: str                           # e.g. "short" / "weekly" / "monthly"
    economic_mechanism: str                # WHY the edge should exist
    regime_affinity: list[str]             # regimes the sleeve is built for
    failure_modes: list[str]               # regimes / events that break it
    polyagora_block: str                   # mapped V6.2 block
    zone_permission: dict[str, float] = field(
        default_factory=lambda: dict(ZONE_PERMISSION_DEFAULT))


@dataclass
class GateConfig:
    """Sleeve-admission thresholds.

    On the role of the DSR gate: doc-1's hard `DSR > 0.95` belongs to the
    upstream *AI strategy factory*, where it kills the best-of-1000
    data-mined survivors. doc-2 — the PolyAgora *registry* — never sets
    that bar: it stores the DSR as a validation metric and admits a
    sleeve on regime fit, correlation and governance. Here the DSR is
    therefore a **noise floor** (the edge must be more-likely-than-not
    real, `dsr > dsr_floor`) plus a reported number — not a hard 0.95
    wall that would reject every genuine *diversifier* whose value is
    portfolio contribution rather than standalone significance.
    """
    n_trials: int = 12            # multiple-testing count for the DSR
    dsr_floor: float = 0.50       # DSR noise floor — reject pure-luck candidates
    max_corr_to_book: float = 0.70  # doc-2 correlation-to-book ceiling
    min_sharpe: float = 0.20      # a sleeve with no standalone edge is not alpha
    base_weight: float = 0.25     # max book share a single first sleeve may take


@dataclass
class SleeveEvaluation:
    """Outcome of running a candidate through the gate pipeline."""
    spec: SleeveSpec
    metrics: dict
    dsr: DSRResult
    degradation: DegradationResult
    corr_to_book: float
    contribution: dict            # book vs blended Sharpe/Sortino at base_weight
    gates: dict[str, bool]        # per-gate pass/fail
    admitted: bool
    base_weight: float            # registry-assigned book share (pre-zone)
    notes: list[str]

    def summary(self) -> str:
        g = "  ".join(f"{k}={'PASS' if v else 'FAIL'}" for k, v in self.gates.items())
        verdict = "ADMITTED" if self.admitted else "REJECTED"
        c = self.contribution
        return (f"[{verdict}] {self.spec.strategy_id} ({self.spec.sleeve_type})\n"
                f"    gates: {g}\n"
                f"    Sharpe={self.metrics.get('sharpe', 0):.3f}  "
                f"DSR={self.dsr.dsr_pvalue:.3f}  "
                f"corr_to_book={self.corr_to_book:.3f}  "
                f"degradation={self.degradation.degradation_ratio:.2f} "
                f"({self.degradation.verdict})\n"
                f"    contribution @w={self.base_weight:.3f}: "
                f"Sharpe {c.get('book_sharpe', 0):.3f}→{c.get('blend_sharpe', 0):.3f}  "
                f"Sortino {c.get('book_sortino', 0):.3f}→{c.get('blend_sortino', 0):.3f}"
                + ("  notes: " + "; ".join(self.notes) if self.notes else ""))


def evaluate_sleeve(
    spec: SleeveSpec,
    sleeve_returns: pd.Series,
    book_returns: pd.Series,
    cfg: GateConfig | None = None,
) -> SleeveEvaluation:
    """Run a candidate sleeve through the ordered gate pipeline (doc-2).

    `sleeve_returns` should already be net of transaction cost (use
    `polyagora_validation.cost_adjust`). `book_returns` is the current
    book the sleeve would join (here: v79).

    Gates: validation → DSR noise floor → correlation-to-book →
    walk-forward degradation → **contribution**. The contribution gate
    is doc-2's governing principle — "a strategy is judged by whether it
    survives under the active regime ordering" — operationalized as:
    blending the sleeve into the book at its registry weight must not
    degrade risk-adjusted return. All gates must pass for admission.
    """
    cfg = cfg or GateConfig()
    notes: list[str] = []

    metrics = performance_metrics(sleeve_returns)
    dsr = deflated_sharpe(sleeve_returns, cfg.n_trials)
    degradation = walk_forward_degradation(sleeve_returns)

    joined = pd.concat([sleeve_returns, book_returns], axis=1, join="inner").dropna()
    corr = float(joined.iloc[:, 0].corr(joined.iloc[:, 1])) if len(joined) > 30 else 1.0

    # Registry weight: a diversifying sleeve earns more of the cap; a
    # sleeve that merely re-expresses the book earns little. Pre-zone.
    diversification = max(0.0, 1.0 - abs(corr))
    base_weight = cfg.base_weight * diversification

    # Contribution: blend the sleeve into the book at its registry
    # weight. Returns are linear in weights, so the blended return is
    # the convex combination of the two return streams.
    book_m = performance_metrics(joined.iloc[:, 1])
    blend = (1.0 - base_weight) * joined.iloc[:, 1] + base_weight * joined.iloc[:, 0]
    blend_m = performance_metrics(blend)
    contribution = {
        "blend_weight": float(base_weight),
        "book_sharpe": book_m.get("sharpe", 0.0),
        "blend_sharpe": blend_m.get("sharpe", 0.0),
        "book_sortino": book_m.get("sortino", 0.0),
        "blend_sortino": blend_m.get("sortino", 0.0),
    }

    # Gate 1 — validation: a real, finite standalone edge.
    g_validation = (metrics.get("sharpe", 0.0) >= cfg.min_sharpe
                    and metrics.get("n", 0) >= 252)
    if not g_validation:
        notes.append("standalone Sharpe below floor or too short")

    # Gate 2 — DSR noise floor: the edge is more likely than not real.
    g_dsr = dsr.dsr_pvalue > cfg.dsr_floor
    if not g_dsr:
        notes.append(f"DSR {dsr.dsr_pvalue:.2f} ≤ {cfg.dsr_floor} "
                     f"(edge not separable from best-of-{cfg.n_trials} luck)")

    # Gate 3 — correlation-to-book: adds an independent return stream.
    g_corr = abs(corr) < cfg.max_corr_to_book
    if not g_corr:
        notes.append(f"|corr to book| {abs(corr):.2f} ≥ {cfg.max_corr_to_book}")

    # Gate 4 — regime robustness: OOS does not collapse vs IS.
    g_degr = degradation.verdict in ("healthy", "suspicious")
    if not g_degr:
        notes.append(f"OOS/IS degradation {degradation.degradation_ratio:.2f} — fragile")

    # Gate 5 — contribution: the sleeve must not degrade the book.
    g_contrib = (blend_m.get("sharpe", 0.0) >= book_m.get("sharpe", 0.0)
                 and blend_m.get("sortino", 0.0) >= book_m.get("sortino", 0.0))
    if not g_contrib:
        notes.append("blending the sleeve degrades book Sharpe/Sortino")

    gates = {"validation": g_validation, "deflated_sharpe": g_dsr,
             "correlation": g_corr, "degradation": g_degr,
             "contribution": g_contrib}
    admitted = all(gates.values())
    if not admitted:
        base_weight = 0.0

    return SleeveEvaluation(
        spec=spec, metrics=metrics, dsr=dsr, degradation=degradation,
        corr_to_book=corr, contribution=contribution, gates=gates,
        admitted=admitted, base_weight=float(base_weight), notes=notes,
    )


class SleeveRegistry:
    """Container for evaluated sleeves and the admitted set."""

    def __init__(self) -> None:
        self.evaluations: list[SleeveEvaluation] = []

    def register(self, evaluation: SleeveEvaluation) -> None:
        self.evaluations.append(evaluation)

    @property
    def admitted(self) -> list[SleeveEvaluation]:
        return [e for e in self.evaluations if e.admitted]

    def report(self) -> str:
        lines = [f"Strategy Sleeve Registry — {len(self.evaluations)} evaluated, "
                 f"{len(self.admitted)} admitted", "=" * 64]
        lines += [e.summary() for e in self.evaluations]
        return "\n".join(lines)
