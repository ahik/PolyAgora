"""PolyAgora Phase-II — Layer 1: Governance Core (V6.2 re-base).

Implements execution-graph Steps 2-6 (Impl Spec §2) on the **13 partner
futures** (working assumption A1, confirmed). Re-bases the spec's Governance
Core on `polyagora_v62_engine.py`:

  - Step 2  Polygon Projection      reuse v62 `build_exogenous_x` + `compute_coordinate`
  - Step 3  VAIDM Classification    new six-axis classifier (A2 — computed in-house)
  - Step 4  Survival Matrix S_ij    v62 co-survival formula, futures-native
  - Step 5  Admissibility (13x5)    new `derive_admissibility_from_survival()`
  - Step 6  Block / 5-mode Zone     new 5-mode classifier (extends v62 `star_zone`)

Layer 1 emits, as first-class outputs: `X_t`, the VAIDM reading, `S_ij`, the
13x5 admissibility matrix `A`, the scalar `beta_t`, the active block, the
5-mode zone, and a base allocation `base_w`.

PHASE-1 SCOPE NOTE. `derive_admissibility_from_survival` and the base
allocation are first-cut re-base implementations — survival-derived, valid,
and runnable. Phase 2 ("reproduce the V7.10 moat") refines them; the §12.2
regression band is the acceptance gate for that refinement.

Anti-hindsight: the polygon features are already `shift(1)`-lagged inside
`build_exogenous_x`; the survival matrix reads realized rows <= t-1 only.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from polyagora_v62_engine import (
    EngineConfig as V62Config,
    block_scores_from_x,
    build_exogenous_x,
    compute_coordinate,
)

BLOCKS = ["A", "B", "C", "D", "G"]
STAR_BLOCKS = ["A", "B", "C", "D"]          # non-boundary regime blocks


# =============================================================================
# Step 3 — VAIDM six-axis classifier (computed in-house, A2)
# =============================================================================

def classify_vaidm(x_row: pd.Series) -> tuple[str, float, np.ndarray]:
    """Six-axis VAIDM vector + class + intensity from the macro panel.

    Phase-1 v1: macro-panel proxies for the six axes. Per the answered Q1,
    VAIDM stays endogenous — `f(macro panel, cross-asset stress, realized
    PnL, fragmentation, transition dynamics)`; richer topology evolves later.
    """
    vix = float(x_row["vix"])
    spy = float(x_row["spy_trend_63d"])
    hyg = float(x_row["hyg_trend_63d"])
    tlt = float(x_row["tlt_trend_63d"])
    gcr = float(x_row["gold_copper_ratio"])
    axes = np.array([
        np.tanh((vix - 18.0) / 12.0),        # 1 volatility level
        np.tanh(-5.0 * min(spy, 0.0)),       # 2 equity-drawdown pressure
        np.tanh(-8.0 * min(hyg, 0.0)),       # 3 credit stress
        np.tanh(3.0 * max(tlt, 0.0)),        # 4 flight-to-quality
        np.tanh((gcr - 4.5) / 4.5),          # 5 macro divergence (gold/copper)
        np.tanh(2.0 * (vix - 25.0) / 12.0),  # 6 rupture proximity
    ])
    intensity = float(np.clip(np.maximum(axes, 0.0).mean(), 0.0, 1.0))
    if vix >= 34.0 or intensity > 0.75:
        cls = "RUPTURE"
    elif vix >= 26.0 or intensity > 0.50:
        cls = "HIGH_STRESS"
    elif intensity > 0.25:
        cls = "ELEVATED"
    else:
        cls = "BENIGN"
    return cls, intensity, axes


# =============================================================================
# Step 4 — Survival matrix S_ij (v62 co-survival, futures-native)
# =============================================================================

def survival_matrix(
    window: pd.DataFrame, universe: list[str], min_obs: int = 40
) -> pd.DataFrame:
    """Continuous 13x13 co-survival matrix (v62 `rolling_survival_matrix`).

    S_ij high when futures i and j co-survive: positively correlated, not
    jointly negative, co-performing. `window` must be realized rows <= t-1.
    """
    r = window.reindex(columns=universe).fillna(0.0)
    n = len(universe)
    if len(r) < min_obs:
        return pd.DataFrame(np.eye(n), index=universe, columns=universe)
    X = r.values.astype(float)
    with np.errstate(divide="ignore", invalid="ignore"):
        corr = np.nan_to_num(np.corrcoef(X, rowvar=False), nan=0.0,
                             posinf=0.0, neginf=0.0)
    neg = (X < 0.0).astype(float)
    pos = (X > 0.0).astype(float)
    corr_score = (corr + 1.0) / 2.0
    joint_bad = neg.T @ neg / len(r)
    co_pos = pos.T @ pos / len(r)
    score = np.clip(0.40 * corr_score + 0.40 * (1.0 - joint_bad)
                    + 0.20 * co_pos, 0.0, 1.0)
    np.fill_diagonal(score, 1.0)
    return pd.DataFrame(score, index=universe, columns=universe)


# =============================================================================
# Step 5 — Admissibility derivation (13x5)
# =============================================================================

def derive_admissibility_from_survival(
    X_t: np.ndarray, S_ij: pd.DataFrame, universe: list[str]
) -> pd.DataFrame:
    """13x5 admissibility matrix `A` (futures x blocks).

    Phase-1 v1 re-base: `A[i, b] = block_score_b(X_t) · cohesion_i(S_ij)`,
    where cohesion is future i's mean co-survival. This is the survival-
    *modulated* polygon prior the Impl-Spec §5 footnote describes, in its
    simplest separable form. Phase 2 refines toward a non-separable
    block-internal-cohesion form.
    """
    bscores = block_scores_from_x(np.asarray(X_t, dtype=float))
    cohesion = S_ij.mean(axis=1).reindex(universe).fillna(0.0).clip(0.0, 1.0)
    return pd.DataFrame(
        {b: cohesion.values * float(bscores.get(b, 0.0)) for b in BLOCKS},
        index=universe,
    )


# =============================================================================
# Step 6 — 5-mode zone classifier
# =============================================================================

def classify_zone(
    strength: float, delta: float, vix: float, block_changed: bool,
    *, z1: float = 0.58, z2: float = 0.34, boundary_vix: float = 35.0,
) -> str:
    """The 5-mode zone classifier (Impl Spec §9, definitions per Q3).

    BOUNDARY  — VIX past the boundary threshold (rupture geometry).
    BUFFER    — the active block just flipped: corridor-ambiguity dwell;
                "do not collapse possibility space too early".
    LOCAL_STAR — strong, stable local star.
    TRANSITION — a star exists but is fading/emerging.
    LEAST_BAD  — degraded admissibility without rupture; constrained
                 continuity (not bearishness).
    """
    if vix >= boundary_vix:
        return "BOUNDARY"
    if block_changed:
        return "BUFFER"
    if strength >= z1 and delta >= -0.08:
        return "LOCAL_STAR"
    if strength >= z2:
        return "TRANSITION"
    return "LEAST_BAD"


# =============================================================================
# Layer 1 — Governance Core
# =============================================================================

class GovernanceCore:
    """Layer 1. Runs execution-graph Steps 2-6 and emits the governance state.

    Holds the precomputed polygon-feature panel and the small amount of
    cross-bar state (EWM beta, previous block/strength) needed for the zone
    classifier and beta smoothing.
    """

    def __init__(
        self,
        macro_panel: pd.DataFrame,
        universe: list[str],
        *,
        v62cfg: V62Config | None = None,
        survival_window: int = 126,
        beta_halflife: float = 10.0,
    ) -> None:
        self.cfg = v62cfg or V62Config()
        self.universe = list(universe)
        self.survival_window = survival_window
        # Step 1/2 — polygon features (shift(1)-lagged inside build_exogenous_x).
        self.X_5d = build_exogenous_x(macro_panel, self.cfg).sort_index()
        self._beta_alpha = 1.0 - float(np.exp(-np.log(2.0) / beta_halflife))
        self._beta_prev: float | None = None
        self._prev_block: str | None = None
        self._prev_strength: float | None = None

    def run(self, state, history: pd.DataFrame):
        """Populate the Layer-1 fields of `state` for bar `state.date`."""
        t = state.date

        # --- Step 2 — Polygon projection ------------------------------------
        idx = self.X_5d.index.asof(t)
        if idx is None or pd.isna(idx):
            # Pre-history: no polygon yet — park in cash, neutral governance.
            state.X_t = np.zeros(5)
            state.S_ij = pd.DataFrame(np.eye(len(self.universe)),
                                      index=self.universe, columns=self.universe)
            state.A = pd.DataFrame(0.0, index=self.universe, columns=BLOCKS)
            state.base_w = pd.Series(0.0, index=self.universe)
            state.log["governance"] = "pre-history (cash)"
            return state
        x_row = self.X_5d.loc[idx]
        X_t = compute_coordinate(x_row)
        state.X_t = X_t

        # --- Step 3 — VAIDM classification ----------------------------------
        state.vaidm_class, state.vaidm_intensity, state.vaidm_axes = \
            classify_vaidm(x_row)

        # --- Step 4 — Survival matrix update (realized <= t-1) --------------
        window = history.iloc[:-1].tail(self.survival_window)
        state.S_ij = survival_matrix(window, self.universe)

        # --- Step 5 — Admissibility derivation (13x5) -----------------------
        state.A = derive_admissibility_from_survival(X_t, state.S_ij, self.universe)

        # --- Step 6 — Block / zone classification ---------------------------
        bscores = block_scores_from_x(X_t)                  # star scores A-D
        block = max(STAR_BLOCKS, key=lambda b: bscores.get(b, 0.0))
        strength = float(bscores.get(block, 0.0))
        delta = (strength - self._prev_strength
                 if self._prev_strength is not None else 0.0)
        block_changed = self._prev_block is not None and block != self._prev_block
        vix = float(x_row["vix"])
        state.block_t = block
        state.zone_t = classify_zone(strength, delta, vix, block_changed,
                                     boundary_vix=self.cfg.boundary_vix)

        # --- beta-admissibility: recoverable-admissibility scalar -----------
        # Active-block strength discounted by VAIDM stress; crushed at the
        # boundary so the system de-risks into rupture geometry.
        boundary = vix >= self.cfg.boundary_vix
        beta_raw = strength * (1.0 - state.vaidm_intensity) * (0.2 if boundary else 1.0)
        beta = (beta_raw if self._beta_prev is None
                else self._beta_alpha * beta_raw
                + (1.0 - self._beta_alpha) * self._beta_prev)
        state.beta_t = float(np.clip(beta, 0.0, 1.0))

        # --- base allocation: admissibility in the active block, scaled by beta
        a_block = state.A[block].clip(lower=0.0)
        gross = float(a_block.sum())
        state.base_w = (a_block / gross * state.beta_t if gross > 1e-12
                        else pd.Series(0.0, index=self.universe))

        state.log["governance"] = (
            f"block={block} strength={strength:.3f} zone={state.zone_t} "
            f"vaidm={state.vaidm_class} beta={state.beta_t:.3f}"
        )
        self._beta_prev = state.beta_t
        self._prev_block = block
        self._prev_strength = strength
        return state
