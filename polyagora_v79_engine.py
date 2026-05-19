"""
PolyAgora V7.9 — governed convexity re-entry / defensive rotation
===================================================================

V7.9 is the **winners-consolidated** line. The cross-method study
(`Allocation_Method_Study.md`) found that of the whole V6.3→V7.8 tree
only a handful of methods are non-redundant: the V7.6α governance base,
the four frozen manifolds, and the V7.8 asset-level ADD-lite core
(v78-ADD) — every other variant is either a 0.98+ correlated near-clone
or a dominated research branch. V7.9 keeps only those winners and adds
the single improvement the study identified.

The improvement — a **governed defensive rotation with convexity
re-entry** — addresses §13 of `docs/PolyAgora Multi-Sleeve Alpha
Architecture.pdf` ("the system suppresses risk but re-enters too
slowly", flagged there as the critical component missing from V7.8)
and §14's runtime-zone model:

    Zone 1 Stable      d ≈ 0      full convex deployment (v78-ADD)
    Zone 2 Transition  d rising   partial rotation toward defensive
    Zone 3 Stress      d high     defensive rotation dominant
    Zone 4 Rupture     d at cap   maximum defensive weight

    w_v79,t = (1 - d_t) · w_v78ADD,t  +  d_t · w_defensive,t

The rotation weight d_t is driven by the **ADD-lite book fragility
field** — the internal governed signal, not a lagged price trend. The
study's V7.9 recommendation #1 was precisely this: drive the tilt off
the recoverability field rather than a raw trend. Because the ADD-lite
book field tracks *current* fragility and mean-reverts as conditions
heal, re-entry is prompt — the §13 "re-enters too slowly" fix — without
a separate fast/slow asymmetry.

Both blended panels (v78-ADD and the defensive manifold) are on the
capital-budget envelope (Σ|w_real| + w_cash = 1), so the convex
combination stays in-envelope by construction. The rotation deforms
*which manifold carries the book*, never individual asset directions.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from polyagora_v63_partner_engine import CASH


@dataclass
class RotationConfig:
    """V7.9 defensive-rotation dials.

    `rot_gain` maps above-baseline book fragility to rotation weight;
    `d_max` caps the defensive share (study's TILT candidate used 0.6).
    `baseline_window` is the trailing window whose median defines
    "normal" book fragility — rotation is zero at or below it (Zone 1)
    and climbs above it (Zones 2-4).

    Defaults `rot_gain=1.0, d_max=0.6` are the balanced setting from the
    parameter sweep: it lifts Sharpe (0.83→0.87) and Sortino *and*
    Calmar over v78-ADD with only ~0.6pp extra drawdown. Higher gains
    chase raw Sharpe but rotate too hard into `defensive` — which is
    itself the 2022 rate-shock victim — degrading Calmar and the
    rate-shock regime. Keep `rot_gain` low.
    """
    rot_gain: float = 1.0
    d_max: float = 0.60
    baseline_window: int = 252
    baseline_min_periods: int = 63


# Zone thresholds on the normalized stress measure, for reporting only.
ZONE_EDGES = (0.15, 0.45, 0.80)   # Stable | Transition | Stress | Rupture
ZONE_NAMES = ("1-Stable", "2-Transition", "3-Stress", "4-Rupture")


def compute_rotation(
    book_add: pd.Series, cfg: RotationConfig | None = None
) -> tuple[pd.Series, pd.DataFrame]:
    """Defensive-rotation weight `d_t` ∈ [0, d_max] from the ADD-lite book
    fragility field.

        baseline_t = trailing median of book_add
        stress_t   = (book_add_t - baseline_t)_+ / baseline_t
        d_t        = clip(rot_gain · stress_t, 0, d_max)

    Returns (d_t, detail) where detail also carries the normalized
    stress level and the discrete runtime zone (§14) for reporting.
    """
    cfg = cfg or RotationConfig()
    baseline = book_add.rolling(cfg.baseline_window,
                                min_periods=cfg.baseline_min_periods).median()
    baseline = baseline.fillna(book_add.expanding(min_periods=1).median())
    excess = (book_add - baseline).clip(lower=0.0)
    stress = (excess / baseline.where(baseline > 1e-9, np.nan)).fillna(0.0)
    d = (cfg.rot_gain * stress).clip(lower=0.0, upper=cfg.d_max)

    zone_idx = np.digitize(d.values / max(cfg.d_max, 1e-9), ZONE_EDGES)
    zone = pd.Series([ZONE_NAMES[min(i, 3)] for i in zone_idx], index=book_add.index)
    detail = pd.DataFrame(
        {"book_add": book_add, "baseline": baseline, "stress": stress,
         "d_rotation": d, "zone": zone},
        index=book_add.index,
    )
    return d, detail


def apply_rotation(
    core_weights: pd.DataFrame,
    defensive_weights: pd.DataFrame,
    d: pd.Series,
) -> pd.DataFrame:
    """Blend the convex core panel with the defensive manifold panel:
    `w = (1 - d_t)·core + d_t·defensive`.

    Both inputs are full (UNIVERSE + CASH) weight panels already on the
    capital-budget envelope, so the per-row convex combination is itself
    in-envelope. `d` is reindexed to the core panel and clipped to [0,1].
    """
    cols = list(core_weights.columns)
    dv = d.reindex(core_weights.index).fillna(0.0).clip(0.0, 1.0)
    core = core_weights
    defn = defensive_weights.reindex(index=core.index, columns=cols).fillna(0.0)
    out = core.mul(1.0 - dv, axis=0) + defn.mul(dv, axis=0)
    # Floating-point safety: re-clamp CASH so each row sums to exactly 1.
    real = [c for c in cols if c != CASH]
    out[CASH] = (1.0 - out[real].abs().sum(axis=1)).clip(lower=0.0)
    return out
