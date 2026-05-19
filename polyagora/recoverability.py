"""PolyAgora Phase-II — Layer 5 (Recoverability Geometry) + Layer 5A (ERQ).

Phase 3. Replaces the `RecoverabilityGeometryStub` / `ExposureRecoverabilityStub`
of `polyagora.layers` with the real measurement layers:

  Layer 5  — RecoverabilityGeometry : market-state geometry  C_t, P_t, F_t, R_t
             (Impl Spec §4 — five estimators -> four runtime variables)
  Layer 5A — ExposureRecoverability : per-exposure ERQ in [0,1]
             (Impl Spec §5 — six components, geometric mean)

These are *measurement* layers: they populate state but do NOT deform the
allocation. The allocation is touched only by Layers 3/4 (MRTP, Kelly —
Phase 4). Hence integrating them must leave the §12.2 moat gate at 10/10.

Both layers are self-contained — they reuse the universe-independent V6.2
geometry primitives (polygon, survival matrix, block scores) and read
realized PnL <= t-1 only. They do not depend on which base provider runs.
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
from polyagora.governance.core import survival_matrix

_EPS = 1e-9
STAR_BLOCKS = ["A", "B", "C", "D"]


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + np.exp(-x))


# =============================================================================
# Layer 5 — Recoverability Geometry  (Impl Spec §4)
# =============================================================================

class RecoverabilityGeometry:
    """Layer 5. Market-state recoverability geometry — `C_t, P_t, F_t, R_t`.

    Estimator constants follow Impl Spec §4; they are first-cut (Phase-3)
    values, refined under Deliverable E. `R_t` is kept a vector
    `{reentry, persist}` per the spec.
    """

    def __init__(
        self,
        macro_panel: pd.DataFrame,
        universe: list[str],
        *,
        survival_window: int = 126,
        kappa_c: float = 3.0,       # corridor-width gain
        theta_c: float = 0.15,      # block-admissibility floor
        slope_k: int = 4,           # ridge-pressure slope window (weeks)
        kappa_p: float = 25.0,      # ridge-pressure slope gain
        disp_window: int = 21,      # cross-sectional dispersion lookback
        theta_beta: float = 0.30,   # admissibility threshold
        persist_window: int = 63,   # admissibility hit-rate window (~1 quarter)
        memory_m: int = 504,        # re-entry base-rate memory (~2 years)
        horizon_h: int = 42,        # re-entry horizon (~2 months)
    ) -> None:
        self.universe = list(universe)
        self.survival_window = survival_window
        self.kappa_c, self.theta_c = kappa_c, theta_c
        self.slope_k, self.kappa_p = slope_k, kappa_p
        self.disp_window = disp_window
        self.theta_beta = theta_beta
        self.persist_window = persist_window
        self.memory_m, self.horizon_h = memory_m, horizon_h
        self.X_5d = build_exogenous_x(macro_panel, V62Config()).sort_index()
        # cross-bar history
        self._wmin: list[float] = []
        self._csstd: list[float] = []
        self._admiss: list[float] = []

    # -- estimators ----------------------------------------------------------
    def _corridor_width(self, p: np.ndarray, admiss: float) -> float:
        """C_t = tanh(kappa_c * (N_eff/4) * depth * admiss)."""
        pn = p / max(p.sum(), _EPS)
        n_eff = float(np.exp(-np.sum(pn * np.log(pn + _EPS))))
        depth = float(np.sum(np.clip(pn - self.theta_c, 0.0, None)))
        return float(np.tanh(self.kappa_c * (n_eff / 4.0) * depth * admiss))

    def _ridge_pressure(self, w_min: float) -> float:
        """P_t = w_lvl*(1-W_min) + w_slp*kappa_p*slope  (slope = cohesion erosion)."""
        self._wmin.append(w_min)
        level = 1.0 - w_min
        k = self.slope_k
        if len(self._wmin) > k:
            slope = max(0.0, (self._wmin[-1 - k] - w_min) / k)
        else:
            slope = 0.0
        return float(0.5 * level + 0.5 * np.clip(self.kappa_p * slope, 0.0, 1.0))

    def _fragmentation(self, S_off: np.ndarray, cs_std: float) -> float:
        """F_t = 0.5*incoherence + 0.5*z_clip(cross-sectional dispersion)."""
        incoh = 1.0 - float(S_off.mean())
        self._csstd.append(cs_std)
        if len(self._csstd) >= 30:
            arr = np.array(self._csstd)
            mu, sd = arr.mean(), arr.std()
            disp = _sigmoid((cs_std - mu) / sd) if sd > _EPS else 0.5
        else:
            disp = 0.5
        return float(0.5 * incoh + 0.5 * disp)

    def _recoverability(self, admiss: float) -> dict:
        """R_t vector — re-entry base rate + admissibility persistence.

        Re-formalized in Phase 3: the original streak/tanh form saturated
        and did not respond across regimes (0/3 in-range falsification —
        Impl Spec §2.2, "rejected, not calibrated"). `persist` is now the
        recent hit-rate of admissibility above threshold — bounded [0,1]
        and responsive within `persist_window`. `reentry` is the empirical
        recover-within-`H` base rate, with a neutral 0.5 default (vs the
        old 1.0, which inflated R through calm periods).
        """
        self._admiss.append(admiss)
        hist = np.array(self._admiss[-self.memory_m:])
        above = hist > self.theta_beta
        # persistence: fraction of the recent window with admissibility up
        recent = above[-self.persist_window:]
        persist = float(recent.mean()) if recent.size else 0.5
        # re-entry: P(recover within H | contracted) over the memory window
        episodes = recovered = 0
        H = self.horizon_h
        for j in np.where(~above)[0]:
            episodes += 1
            if np.any(above[j + 1: j + 1 + H]):
                recovered += 1
        reentry = recovered / episodes if episodes else 0.5
        return {"reentry": float(reentry), "persist": persist}

    # -- per-bar -------------------------------------------------------------
    def run(self, state, history: pd.DataFrame):
        t = state.date
        idx = self.X_5d.index.asof(t)
        if idx is None or pd.isna(idx):
            state.log["L5_recoverability"] = "pre-history (neutral)"
            return state
        X_t = compute_coordinate(self.X_5d.loc[idx])
        if state.X_t is None:
            state.X_t = X_t

        # survival matrix (realized <= t-1) — also published to the state
        S = survival_matrix(
            history.iloc[:-1].tail(self.survival_window), self.universe)
        state.S_ij = S
        eye = np.eye(len(self.universe), dtype=bool)
        S_off = S.values[~eye]

        # block scores -> corridor admissibility scalar
        bs = block_scores_from_x(X_t)
        p = np.array([float(bs.get(b, 0.0)) for b in STAR_BLOCKS])
        strength = float(p.max()) if p.sum() > _EPS else 0.0
        admiss = strength * (1.0 - state.vaidm_intensity)

        # cross-sectional return dispersion (realized <= t-1)
        win = history.iloc[:-1].tail(self.disp_window)[self.universe]
        cum = win.sum(axis=0)
        cs_std = float(cum.std()) if len(win) >= 5 else 0.0

        state.C_t = self._corridor_width(p, admiss)
        state.P_t = self._ridge_pressure(float(S_off.min())
                                         if S_off.size else 1.0)
        state.F_t = self._fragmentation(S_off, cs_std)
        state.R_t = self._recoverability(admiss)
        state.log["L5_recoverability"] = (
            f"C={state.C_t:.3f} P={state.P_t:.3f} F={state.F_t:.3f} "
            f"R=({state.R_t['reentry']:.2f},{state.R_t['persist']:.2f})")
        return state


# =============================================================================
# Layer 5A — Exposure Recoverability Quality (ERQ)  (Impl Spec §5)
# =============================================================================

class ExposureRecoverability:
    """Layer 5A. Scores the current book's position structure — `ERQ in [0,1]`.

    Six components, geometric mean (Impl Spec §5) — so one recoverability-
    destroying property craters the score. v1 proxies over the futures
    position structure (A1 data limit: no options/ADV; puts/calls are the
    conceptual benchmark, not inputs). With no sleeves yet (Phase 3), the
    single scored exposure is the book itself.
    """

    def __init__(self, universe: list[str], *, turnover_ref: float = 1.0) -> None:
        self.universe = list(universe)
        self.turnover_ref = turnover_ref
        self._prev_w: pd.Series | None = None

    def _components(self, w: pd.Series, state) -> dict:
        w = w.reindex(self.universe).fillna(0.0)
        gross = float(w.abs().sum())
        n = len(self.universe)
        if gross <= _EPS:
            return {k: 1.0 for k in "ABCDEF"}     # all-cash: maximally recoverable

        short = float((-w).clip(lower=0.0).sum())
        shares = w.abs() / gross
        hhi = float((shares ** 2).sum())
        turnover = (float((w - self._prev_w.reindex(self.universe).fillna(0.0))
                          .abs().sum()) if self._prev_w is not None else 0.0)

        return {
            # A — forced traversal: short legs require a future buyback corridor
            "A": float(np.clip(1.0 - short / gross, 0.0, 1.0)),
            # B — corridor width: name concentration (Herfindahl)
            "B": float(np.clip(1.0 - (hhi - 1.0 / n) / (1.0 - 1.0 / n), 0.0, 1.0)),
            # C — liquidity survivability: turnover proxy (lower = unwindable)
            "C": float(np.clip(1.0 - turnover / self.turnover_ref, 0.0, 1.0)),
            # D — boundedness: leverage past the 1.0x capital budget
            "D": float(np.clip(1.0 - max(0.0, gross - 1.0) / 0.25, 0.0, 1.0)),
            # E — re-entry flexibility: cash buffer + corridor width
            "E": float(np.clip(0.5 * (1.0 - min(gross, 1.0))
                               + 0.5 * state.C_t, 0.0, 1.0)),
            # F — correlation-rupture robustness: 1 - fragmentation field
            "F": float(np.clip(1.0 - state.F_t, 0.0, 1.0)),
        }

    def run(self, state, history: pd.DataFrame):
        w = state.base_w if state.base_w is not None else pd.Series(
            0.0, index=self.universe)
        comp = self._components(w, state)
        erq = float(np.prod([max(c, _EPS) for c in comp.values()]) ** (1.0 / 6.0))
        state.erq = {"book": erq, **{f"erq_{k}": v for k, v in comp.items()}}
        state.log["L5A_erq"] = (
            f"book ERQ={erq:.3f}  "
            + " ".join(f"{k}={comp[k]:.2f}" for k in "ABCDEF"))
        self._prev_w = w.reindex(self.universe).fillna(0.0)
        return state
