"""
PolyAgora V7.3 — V6.3V Architecture (Continuous Fixed-Star Allocation Geometry)

Per `docs/PolyAgora-63V.pdf`. The V7-Lite/V7-Heavy survival-matrix line is
decommissioned (see "What Went Wrong in V7" in the same doc).

V7.3 keeps V6.3's master equation as the immutable base:

    w_t = β'_t · RegimeTilt_t + (1 − β'_t) · NeutralTemplate

and adds *additive* layers — never replacement allocators:

  1. Q polygons modulate β multiplicatively:
        β'_t = β_t · Q_VAIDM(t) · Q_ADD(t) · Q_Buffett(t)
     each Q_•(t) ∈ [floor, 1]; identity when polygon is disabled.

  2. Driver Seat parameter dials (no asset choices, just parameter deformation):
        - convexity_preference   tilts block-probability mass toward C / G
        - carry_preference       tilts block-probability mass toward A / D
        - boundary_sensitivity   scales β-gate thresholds (sooner / later)
        - recovery_aggression    scales cooldown decay (faster / slower)
        - max_defensive_contraction  floor on β'_t

Default driver config + identity Q polygons → V7.3 ≡ V6.3-gated. Higher
layers compose multiplicatively on top.

Anti-hindsight invariant: Q polygons read realized panel rows ≤ t−1 only;
no strategy PnL feeds the primary signal layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd

from polyagora_v63_partner_engine import (
    NEUTRAL_TEMPLATE,
    POLYAGORA_TEMPLATES,
    UNIVERSE,
    PolyagoraGateConfig,
    SignalFn,
    _compute_beta_from_market,
    _proxy_drawdown,
    _TEMPLATE_DF,
)


# =============================================================================
# Driver Seat — parameter dials (per doc p.12)
# =============================================================================

@dataclass
class V73DriverConfig:
    """
    V7.3 Driver Seat — parameter dials only. Defaults reduce V7.3 to V6.3-gated
    (no behavioral change vs base when Q polygons are also identity).

    All five dials change parameters / probabilities, never asset choices.
    """
    # Block-probability deformation. Range [-1, +1].
    # carry  > 0 : amplify A (Vol-Carry) and D (Low-Vol) probabilities
    # convex > 0 : amplify C (Momentum) and G (Boundary) probabilities
    convexity_preference: float = 0.0
    carry_preference: float = 0.0

    # boundary_sensitivity scales the V6.3 β-gate threshold severity.
    # > 1 : tighter — β reacts sooner (lower VIX / smaller SPY drop triggers)
    # < 1 : looser — β reacts later
    boundary_sensitivity: float = 1.0

    # recovery_aggression scales β recovery speed after a hard kill.
    # > 1 : shorter cooldown (faster recovery) and shorter EWM half-life
    # < 1 : longer cooldown
    recovery_aggression: float = 1.0

    # max_defensive_contraction is the FLOOR on β'_t. β' is clipped from below
    # by this value, even under stacked Q-polygon attenuation. Default 0 = no
    # floor. Setting >0 means the engine will never fully de-risk to neutral.
    max_defensive_contraction: float = 0.0


# =============================================================================
# Q polygons — admissibility multipliers on β
# =============================================================================

@dataclass
class QPolygonConfig:
    """
    Tunables for Q polygons. Defaults set so each Q ≤ 1 most days; with
    polygons disabled (or markets calm) Q ≡ 1 and V7.3 = V6.3-gated.
    """
    enable_vaidm: bool = True
    enable_add: bool = True
    enable_buffett: bool = False  # external valuation feed required to activate

    # VAIDM — cross-sectional dispersion gate over the realized panel.
    vaidm_dispersion_window: int = 20
    vaidm_dispersion_high: float = 0.030  # daily cross-sectional std → start gating
    vaidm_floor: float = 0.5

    # ADD — equal-weight market proxy drawdown gate.
    add_lookback: int = 252
    add_dd_ceiling: float = -0.03   # ≥ -3% → Q_ADD = 1.0
    add_dd_floor: float = -0.10     # ≤ -10% → Q_ADD = 0.0


def Q_VAIDM(history_lag: pd.DataFrame, cfg: QPolygonConfig) -> float:
    """
    Cross-sectional dispersion gate. Returns Q ∈ [vaidm_floor, 1].

    `history_lag` must already be sliced to ≤ t-1 by the caller.
    Q = 1 when realized cross-sectional std is below `vaidm_dispersion_high`,
    ramps down to `vaidm_floor` as dispersion exceeds the threshold.
    """
    if len(history_lag) < cfg.vaidm_dispersion_window:
        return 1.0
    window = history_lag.iloc[-cfg.vaidm_dispersion_window:]
    cross_vol = float(window.std(skipna=True).mean())
    if not np.isfinite(cross_vol) or cross_vol <= cfg.vaidm_dispersion_high:
        return 1.0
    excess = (cross_vol - cfg.vaidm_dispersion_high) / cfg.vaidm_dispersion_high
    return float(max(cfg.vaidm_floor, 1.0 - (1.0 - cfg.vaidm_floor) * excess))


def Q_ADD(history_lag: pd.DataFrame, cfg: QPolygonConfig) -> tuple[float, float]:
    """
    Equal-weight proxy drawdown gate. Returns (Q ∈ [0, 1], rolling_dd) so
    the runtime caller can record the drawdown for diagnostics.

    `history_lag` must already be sliced to ≤ t-1 by the caller.
    """
    if history_lag.empty:
        return 1.0, 0.0
    window = history_lag.tail(cfg.add_lookback)
    eq_returns = window.mean(axis=1, skipna=True).fillna(0.0)
    eq_curve = (1.0 + eq_returns).cumprod()
    if eq_curve.empty:
        return 1.0, 0.0
    dd = float((eq_curve / eq_curve.cummax() - 1.0).iloc[-1])
    if dd <= cfg.add_dd_floor:
        return 0.0, dd
    if dd >= cfg.add_dd_ceiling:
        return 1.0, dd
    return float((dd - cfg.add_dd_floor) / (cfg.add_dd_ceiling - cfg.add_dd_floor)), dd


def Q_BUFFETT(history_lag: pd.DataFrame, cfg: QPolygonConfig) -> float:
    """Placeholder. External valuation feed required for activation."""
    return 1.0


# =============================================================================
# Driver Seat application — gate-config and block-probability deformations
# =============================================================================

def _scale_gate_cfg(base: PolyagoraGateConfig, drivers: V73DriverConfig) -> PolyagoraGateConfig:
    """
    Apply boundary_sensitivity, recovery_aggression, and
    max_defensive_contraction to the V6.3 β-gate configuration.

    boundary_sensitivity > 1 ⇒ thresholds tighter (β kicks down sooner)
    recovery_aggression  > 1 ⇒ shorter cooldown + shorter EWM half-life
    max_defensive_contraction sets `min_beta` floor.
    """
    s = max(1e-3, drivers.boundary_sensitivity)
    r = max(1e-3, drivers.recovery_aggression)
    return PolyagoraGateConfig(
        # Volatility-side thresholds: divide by s to slide down (sooner)
        vix_soft_lo=base.vix_soft_lo / s,
        vix_soft_hi=base.vix_soft_hi / s,
        vix_hard_shock=base.vix_hard_shock / s,
        vix_hard_level=base.vix_hard_level / s,
        # Drawdown / SPY-side thresholds: multiply by s to make less negative (sooner)
        spy_5d_soft_floor=base.spy_5d_soft_floor * s,
        spy_5d_soft_ceiling=base.spy_5d_soft_ceiling * s,
        spy_1d_hard=base.spy_1d_hard * s,
        dd_soft_floor=base.dd_soft_floor * s,
        dd_soft_ceiling=base.dd_soft_ceiling * s,
        # Recovery dynamics: shorter cooldown + faster smoothing under r > 1
        cooldown_days=max(1, int(round(base.cooldown_days / r))),
        beta_smoothing_halflife=max(0.5, base.beta_smoothing_halflife / r),
        # min_beta is the β'_t floor under stress
        min_beta=max(base.min_beta, drivers.max_defensive_contraction),
    )


def _deform_block_probs(probs: pd.Series, drivers: V73DriverConfig) -> pd.Series:
    """
    Apply convexity_preference and carry_preference to V6.2 block probabilities.
    Preserves the Σ P_block = 1 invariant via per-row renormalization.

    A, D ← amplified by carry_preference
    C, G ← amplified by convexity_preference
    B   ← neutral to both dials
    """
    if drivers.convexity_preference == 0.0 and drivers.carry_preference == 0.0:
        return probs
    factors = pd.Series(1.0, index=probs.index)
    if "A" in factors.index:
        factors.loc["A"] *= 1.0 + drivers.carry_preference
    if "D" in factors.index:
        factors.loc["D"] *= 1.0 + drivers.carry_preference
    if "C" in factors.index:
        factors.loc["C"] *= 1.0 + drivers.convexity_preference
    if "G" in factors.index:
        factors.loc["G"] *= 1.0 + drivers.convexity_preference
    factors = factors.clip(lower=0.0)
    deformed = probs * factors
    s = float(deformed.sum())
    return deformed / s if s > 1e-12 else probs


# =============================================================================
# V7.3 signal factory
# =============================================================================

def make_v73_signal(
    market: pd.DataFrame,
    realized: pd.DataFrame,
    drivers: V73DriverConfig | None = None,
    q_cfg: QPolygonConfig | None = None,
    gate_cfg: PolyagoraGateConfig | None = None,
    v62_cfg=None,
) -> SignalFn:
    """
    V7.3 signal factory — V6.3V base with additive Q-polygon and Driver Seat layers.

    Pipeline at time t:
      1. β_t       from V6.3 _compute_beta_from_market on the (driver-scaled) gate
      2. Q_polys   computed from realized panel ≤ t-1
      3. β'_t      = max(max_defensive_contraction, β_t · Q_VAIDM · Q_ADD · Q_Buffett)
      4. probs     V6.2 block probabilities, deformed by convexity / carry preference
      5. tilt      Σ probs · TEMPLATE (renormalized to gross 1)
      6. w_t       β'_t · tilt + (1 − β'_t) · neutral

    Anti-hindsight: Q polygons slice realized.loc[:t].iloc[:-1] (≤ t-1). β is
    already shift(1)-ed inside _compute_beta_from_market.
    """
    from polyagora_v62_engine import (
        EngineConfig as V62EngineConfig,
        build_block_history,
        build_exogenous_x,
    )

    drivers = drivers or V73DriverConfig()
    q_cfg = q_cfg or QPolygonConfig()
    base_gate = gate_cfg or PolyagoraGateConfig()
    base_cfg = v62_cfg or V62EngineConfig()

    gate = _scale_gate_cfg(base_gate, drivers)

    X = build_exogenous_x(market, base_cfg)
    _, block_scores = build_block_history(X, base_cfg)
    block_scores = block_scores.sort_index()

    proxy_dd = _proxy_drawdown(realized)
    beta_series = _compute_beta_from_market(market, proxy_dd, gate).sort_index()

    neutral = pd.Series(NEUTRAL_TEMPLATE).reindex(UNIVERSE).fillna(0.0)

    diagnostics: list[dict] = []

    def _renorm_to_gross(s: pd.Series) -> pd.Series:
        gross = float(s.abs().sum())
        if not np.isfinite(gross) or gross < 1e-12:
            return pd.Series(1.0 / max(len(s), 1), index=s.index)
        return s / gross

    def _signal(history: pd.DataFrame, live: list[str], _cfg) -> pd.Series:
        t = history.index[-1]

        bs_idx = block_scores.index.asof(t)
        beta_idx = beta_series.index.asof(t)
        beta = float(beta_series.loc[beta_idx]) if pd.notna(beta_idx) else 0.0

        if pd.isna(bs_idx):
            return _renorm_to_gross(neutral.reindex(live).fillna(0.0))

        # Q polygons read history ≤ t-1 (history.iloc[:-1] drops row at t).
        history_lag = history.iloc[:-1]
        q_v = Q_VAIDM(history_lag, q_cfg) if q_cfg.enable_vaidm else 1.0
        q_a, dd = Q_ADD(history_lag, q_cfg) if q_cfg.enable_add else (1.0, 0.0)
        q_b = Q_BUFFETT(history_lag, q_cfg) if q_cfg.enable_buffett else 1.0
        q_t = q_v * q_a * q_b
        beta_prime = max(drivers.max_defensive_contraction, beta * q_t)

        probs = _deform_block_probs(block_scores.loc[bs_idx], drivers)
        tilt = _renorm_to_gross(_TEMPLATE_DF.dot(probs).reindex(live).fillna(0.0))
        neutral_live = _renorm_to_gross(neutral.reindex(live).fillna(0.0))

        weights_out = beta_prime * tilt + (1.0 - beta_prime) * neutral_live
        gross = float(weights_out.abs().sum())

        diagnostics.append({
            "date": t,
            "beta": beta,
            "q_vaidm": q_v,
            "q_add": q_a,
            "q_buffett": q_b,
            "q_combined": q_t,
            "beta_prime": beta_prime,
            "rolling_drawdown": dd,
            "gross": gross,
            "cash": max(0.0, 1.0 - gross),
        })

        return weights_out

    def diagnostics_df() -> pd.DataFrame:
        if not diagnostics:
            return pd.DataFrame(columns=[
                "beta", "q_vaidm", "q_add", "q_buffett", "q_combined",
                "beta_prime", "rolling_drawdown",
            ])
        return pd.DataFrame(diagnostics).set_index("date")

    _signal.diagnostics = diagnostics              # type: ignore[attr-defined]
    _signal.diagnostics_df = diagnostics_df        # type: ignore[attr-defined]
    return _signal
