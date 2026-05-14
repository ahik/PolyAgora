"""
PolyAgora V7.5α₁ — Momentum-as-Polygon-Coordinate Engine
=========================================================

Per `docs/PolyAgora_V7_5_Spec.md`. Single-layer change vs V7.4c: promote
Momentum Persistence (M) from the eigenfield universe Φ into the Reference
Polygon itself as a 6th coordinate.

    RP = (M, V, T, G, C, R) ∈ [-1, 1]⁶

    M_t = tanh( median_i z_cs( (EMA_short_i(t) − EMA_long_i(t)) / σ_i(t) ) )

Computed from the realized strategy panel, shift(1)-lagged so the value at
row t reads realized rows ≤ t-1. `MOM12_1` (the synthetic stream) is *not*
a column in `realized`, so it is naturally excluded from the cross-section
that defines M.

Soft top-K block aggregation, zone classifier, MOM12_1 decomposition, and
the Driver Seat dials from V7.4b/V7.4c are inherited verbatim.

Continuity anchor: with `momentum_sensitivity = 0`, the M column of the
admissibility coefficients is zeroed out and V7.5α₁ produces *byte-identical*
admissibility to V7.4c. This is the V7.4c-recovery point for Test 1.

Two variants are registered:
  - `v75`             — Φ retains MOM12_1 (14 strategies). Momentum represented
                        at both the polygon (M) and eigenfield (MOM12_1) layers.
  - `v75_no_mom_eigen` — Φ drops MOM12_1 (13 strategies). M lives only in RP.

The empirical winner becomes the V7.5 default after the validation pack.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from polyagora_v63_partner_engine import (
    EngineConfig as V63EngineConfig,
    SignalFn,
    _proxy_drawdown,
)
from polyagora_v74_engine import (
    MOM_NAME,
    STRATEGIES as STRATEGIES_V74,
    CATEGORY as CATEGORY_V74,
    ZONE_GROSS_BASE,
    V74DriverConfig,
    _block_internal_survival,
    _block_membership,
    _category_multipliers,
    _classify_zone,
    _momentum_portfolio,
    _structural_prior,
    _synth_mom_pnl,
)
from polyagora_v74b_engine import (
    CATEGORY_BLOCKS as CATEGORY_BLOCKS_V74,
    _block_label,
)


# =============================================================================
# Driver Seat — V7.5 adds α_M on top of V7.4
# =============================================================================

@dataclass
class V75DriverConfig(V74DriverConfig):
    """V7.5 Driver Seat — V7.4 dials + momentum_sensitivity (α_M).

    `momentum_sensitivity` scales the M column of the admissibility
    coefficients. Defaults to 1.0 (M fully active); set to 0.0 to recover
    V7.4c-equivalent admissibility — the continuity anchor verified by
    Test 1 of the validation pack.
    """
    momentum_sensitivity: float = 1.0


# =============================================================================
# Admissibility coefficients (6 axes × 5 categories, spec §5)
# =============================================================================

# Coordinate order is (M, V, T, G, C, R). V/T/G/C/R columns are identical to
# V7.4c (`polyagora_v74_engine.py:95–102`); the M column is new.
#
# Option B retune (2026-05-12): the spec §5 first pass had persistence=+1.5,
# defensive=-1.0 which over-concentrated the top-K aggregation in trend
# regimes. Rebalanced so persistence still leads but defensive isn't crushed:
#   persistence +1.0 (was +1.5), carry +0.25 (was 0), defensive -0.5
#   (was -1.0). Range tightened from [-1.0, +1.5] to [-0.5, +1.0].
ADMISSIBILITY_COEFS_V75: dict[str, np.ndarray] = {
    "persistence": np.array([+1.00, -1.5, +2.5, -0.5, +1.0, -0.5]),
    "carry":       np.array([+0.25, -1.0, +0.5, -0.5, +1.5, -2.0]),
    "defensive":   np.array([-0.50, +1.0, -0.5, +0.5, -0.5, +1.0]),
    "convexity":   np.array([-0.50, +2.0, -0.5, +1.5, -0.5, +0.5]),
    "stress":      np.array([-0.50, +1.0, -0.5, +2.0, -0.5, +0.5]),
}


# =============================================================================
# Momentum Persistence M_t — the 6th polygon coordinate (spec §4)
# =============================================================================

EMA_SHORT_HALFLIFE: int = 63
EMA_LONG_HALFLIFE: int = 252
ROLLING_VOL_WINDOW: int = 63


def build_m_series(
    realized: pd.DataFrame,
    *,
    short_halflife: int = EMA_SHORT_HALFLIFE,
    long_halflife: int = EMA_LONG_HALFLIFE,
    vol_window: int = ROLLING_VOL_WINDOW,
) -> pd.Series:
    """M_t — Momentum Persistence polygon coordinate (spec §4).

    Per strategy i in `realized.columns`:
        m_i(t) = (EMA_short_i(t) − EMA_long_i(t)) / σ_i(t)
        m_i_z(t) = cross-sectional z-score of m_i(t) across strategies
        M_t = tanh( median_i m_i_z(t) )

    `MOM12_1` is not a column in `realized`, so it is naturally excluded from
    the cross-section — no self-reference.

    The returned series is `.shift(1)`-lagged: M_t at row t depends solely on
    realized rows ≤ t-1 (anti-hindsight invariant #9, spec §7).
    """
    panel = realized.astype(float)

    ema_short = panel.ewm(halflife=short_halflife, adjust=False).mean()
    ema_long = panel.ewm(halflife=long_halflife, adjust=False).mean()
    sigma = panel.rolling(window=vol_window, min_periods=vol_window // 2).std()

    m_per_strategy = (ema_short - ema_long) / (sigma + 1e-9)

    cs_mean = m_per_strategy.mean(axis=1)
    cs_std = m_per_strategy.std(axis=1).replace(0.0, np.nan)
    m_z = m_per_strategy.sub(cs_mean, axis=0).div(cs_std, axis=0)
    cs_median = m_z.median(axis=1)

    M = np.tanh(cs_median.fillna(0.0))
    return M.shift(1).fillna(0.0)


def _admissibility_v75(
    coord_6d: np.ndarray,
    category_for: dict[str, str],
    strategies: list[str],
    momentum_sensitivity: float,
) -> dict[str, float]:
    """A_i(t) = σ(coef · X_t) with the M column scaled by `momentum_sensitivity`.

    Setting `momentum_sensitivity = 0` zeroes the M contribution and reduces
    V7.5α₁ to V7.4c admissibility.
    """
    cat_a: dict[str, float] = {}
    for cat, coef in ADMISSIBILITY_COEFS_V75.items():
        coef_scaled = coef.copy()
        coef_scaled[0] *= momentum_sensitivity
        z = float(coef_scaled @ coord_6d)
        cat_a[cat] = 1.0 / (1.0 + np.exp(-z))
    return {s: cat_a[category_for[s]] for s in strategies}


# =============================================================================
# Universe (Φ) construction — switch between v75 and v75_no_mom_eigen
# =============================================================================

def _build_universe(
    include_mom_eigen: bool,
) -> tuple[list[str], dict[str, str], dict[str, list[str]], pd.DataFrame]:
    """Returns (strategies, category_map, category_blocks, S_prior).

    `include_mom_eigen=False` drops MOM12_1 from Φ, the persistence category
    block, and the structural prior matrix — momentum then lives *only* on
    the polygon (M axis).
    """
    if include_mom_eigen:
        return (
            list(STRATEGIES_V74),
            dict(CATEGORY_V74),
            {k: list(v) for k, v in CATEGORY_BLOCKS_V74.items()},
            _structural_prior(),
        )
    strategies = [s for s in STRATEGIES_V74 if s != MOM_NAME]
    category = {s: c for s, c in CATEGORY_V74.items() if s != MOM_NAME}
    category_blocks = {
        cat: [s for s in members if s != MOM_NAME]
        for cat, members in CATEGORY_BLOCKS_V74.items()
    }
    s_prior_full = _structural_prior()
    s_prior = s_prior_full.drop(index=MOM_NAME, columns=MOM_NAME)
    return strategies, category, category_blocks, s_prior


# =============================================================================
# Empirical survival R_t (parameterized over arbitrary strategy list)
# =============================================================================

def _empirical_survival_v75(
    history_lag: pd.DataFrame,
    mom_pnl_lag: pd.Series | None,
    window: int,
    strategies: list[str],
) -> pd.DataFrame:
    """Rolling pairwise survivability (corr+1)/2 over `strategies`.

    If `MOM12_1` is in `strategies`, the synthetic stream is stitched in as
    a 14th column. Otherwise only `realized.columns` participate.
    """
    n = len(strategies)
    if len(history_lag) < window // 2:
        return pd.DataFrame(
            np.full((n, n), 0.5), index=strategies, columns=strategies
        )

    panel = history_lag.tail(window).copy()
    if MOM_NAME in strategies:
        if mom_pnl_lag is None or mom_pnl_lag.empty:
            panel[MOM_NAME] = 0.0
        else:
            panel[MOM_NAME] = mom_pnl_lag.reindex(panel.index)
    panel = panel[strategies]
    corr = panel.corr().fillna(0.0)
    R_arr = ((corr.values + 1.0) / 2.0).clip(0.0, 1.0)
    np.fill_diagonal(R_arr, 1.0)
    return pd.DataFrame(R_arr, index=strategies, columns=strategies)


# =============================================================================
# Soft top-K block aggregation (parameterized over arbitrary strategy list)
# =============================================================================

def _soft_membership_v75(
    adm: dict[str, float],
    W: pd.DataFrame,
    blocks: list[list[str]],
    *,
    top_k: int,
    tau: float,
    strategies: list[str],
) -> tuple[dict[str, float], list[dict]]:
    """V7.4b soft top-K membership, parameterized over `strategies`."""
    scored: list[tuple[list[str], float, float, float]] = []
    for members in blocks:
        if not members:
            continue
        gamma = _block_internal_survival(W, members)
        mu = _block_membership(adm, members)
        scored.append((members, mu * gamma, gamma, mu))
    scored.sort(key=lambda r: r[1], reverse=True)
    K = max(1, min(top_k, len(scored)))
    top = scored[:K]

    Qs = np.array([r[1] for r in top], dtype=float)
    z = tau * Qs
    z = z - float(z.max())
    rho = np.exp(z)
    rho = rho / rho.sum()

    M: dict[str, float] = {s: 0.0 for s in strategies}
    for (members, _, _, _), w in zip(top, rho):
        w_f = float(w)
        for s in members:
            if s in M:
                M[s] += w_f

    top_summary = [
        {
            "label": _block_label(r[0]),
            "members": list(r[0]),
            "size": len(r[0]),
            "Q": float(r[1]),
            "gamma": float(r[2]),
            "mu": float(r[3]),
            "rho": float(w),
        }
        for r, w in zip(top, rho)
    ]
    return M, top_summary


# =============================================================================
# V7.5 signal factory
# =============================================================================

def make_v75_signal(
    market: pd.DataFrame,
    realized: pd.DataFrame,
    drivers: V75DriverConfig | None = None,
    *,
    include_mom_eigen: bool = True,
    top_k: int = 2,
    tau: float = 4.0,
    survival_window: int = 60,
    lam: float = 0.6,
    zone_smoothing_halflife: float = 5.0,
    v62_cfg=None,
) -> SignalFn:
    """V7.5α₁ signal factory — Momentum-as-Polygon-Coordinate.

    Pipeline at time t:
      X_5d_t     = (V, T, G, C, R)  from build_exogenous_x (shift_lag already applied)
      M_t        = market-level momentum-persistence scalar (shift(1)-lagged)
      coord_6d_t = (M, V, T, G, C, R)
      A_i(t)     = σ(coef_v75 · coord_6d_t)         spec §5; α_M scales M column
      R_t        = rolling corr over Φ, realized ≤ t-1
      W_t        = λ S₀ + (1-λ) R_t
      Soft top-K blocks over disjoint category blocks
      Z_t        = _classify_zone(γ, µ, X_5d, ∆Q, drivers, proxy_dd)  spec §8
      g_smooth   = EWM(g(Z_t))
      p_i(t)     = A_i · M_i_soft · G_cat(Driver Seat)
      w_raw_i(t) = g_smooth · p_i / Σ_j p_j
      MOM12_1 decomposition if include_mom_eigen.

    Anti-hindsight invariants 1–8 inherited; 9–10 verified here:
      - M_t reads realized.iloc[:-1] via shift(1) inside build_m_series.
      - MOM12_1 is excluded from M's cross-section (not a column in realized).
    """
    from polyagora_v62_engine import (
        EngineConfig as V62EngineConfig,
        build_exogenous_x,
    )

    drivers = drivers or V75DriverConfig()
    base_cfg = v62_cfg or V62EngineConfig()

    strategies, category, category_blocks, s_prior = _build_universe(include_mom_eigen)

    X_5d = build_exogenous_x(market, base_cfg).sort_index()
    m_series = build_m_series(realized).sort_index()
    mom_pnl_full = _synth_mom_pnl(realized).sort_index() if include_mom_eigen else None
    proxy_dd_full = _proxy_drawdown(realized).sort_index()

    cat_mult = _category_multipliers(drivers)
    halflife = max(0.5, zone_smoothing_halflife / max(1e-3, drivers.recovery_aggression))
    alpha = 1.0 - float(np.exp(-np.log(2.0) / halflife))

    state: dict[str, float | None] = {"last_g_smooth": None, "last_Q1": None}
    diagnostics: list[dict] = []

    def _equal_live(live: list[str]) -> pd.Series:
        if not live:
            return pd.Series(dtype=float)
        return pd.Series(1.0 / len(live), index=live)

    def _signal(history: pd.DataFrame, live: list[str], _cfg: V63EngineConfig) -> pd.Series:
        t = history.index[-1]

        x_idx = X_5d.index.asof(t)
        if pd.isna(x_idx):
            return _equal_live(live)
        x_row = X_5d.loc[x_idx]
        V_ = float(np.tanh((float(x_row["vix"]) - 18.0) / 10.0))
        T_ = float(np.tanh(5.0 * float(x_row["spy_trend_63d"])))
        G_ = float(np.tanh(2.0 * (float(x_row["gold_copper_ratio"]) - 4.5) / 4.5))
        C_ = float(np.tanh(10.0 * float(x_row["hyg_trend_63d"])))
        R_ = float(-np.tanh(5.0 * float(x_row["tlt_trend_63d"])))

        m_idx = m_series.index.asof(t)
        M_ = float(m_series.loc[m_idx]) if pd.notna(m_idx) else 0.0

        coord_6d = np.array([M_, V_, T_, G_, C_, R_])
        d_RP = float(np.max(np.abs(coord_6d)))

        adm = _admissibility_v75(coord_6d, category, strategies, drivers.momentum_sensitivity)

        history_lag = history.iloc[:-1]
        if mom_pnl_full is not None and t in mom_pnl_full.index:
            mom_pnl_lag = mom_pnl_full.loc[:t].iloc[:-1]
        else:
            mom_pnl_lag = mom_pnl_full

        R_emp = _empirical_survival_v75(history_lag, mom_pnl_lag, survival_window, strategies)
        W = lam * s_prior + (1.0 - lam) * R_emp

        blocks = [list(members) for members in category_blocks.values() if members]
        n_blocks = len(blocks)
        M_soft, top = _soft_membership_v75(
            adm, W, blocks, top_k=top_k, tau=tau, strategies=strategies
        )

        Q1 = top[0]["Q"]
        gamma1 = top[0]["gamma"] if top[0]["size"] > 1 else top[0]["mu"]
        mu1 = top[0]["mu"]
        last_Q1 = state["last_Q1"]
        dQ = abs(Q1 - last_Q1) if last_Q1 is not None else 0.0
        state["last_Q1"] = Q1

        if t in proxy_dd_full.index:
            dd_lag = proxy_dd_full.loc[:t].iloc[:-1]
            proxy_dd = float(dd_lag.iloc[-1]) if len(dd_lag) else 0.0
        else:
            proxy_dd = 0.0

        # Zone classifier uses (V, T, G, C, R) — M is not in zone logic (spec §8).
        coord_5d_for_zone = np.array([V_, T_, G_, C_, R_])
        Z = _classify_zone(gamma1, mu1, coord_5d_for_zone, dQ, drivers, proxy_dd=proxy_dd)
        g_raw = ZONE_GROSS_BASE[Z]
        last_g = state["last_g_smooth"]
        g_smooth = (alpha * g_raw + (1.0 - alpha) * last_g) if last_g is not None else g_raw
        state["last_g_smooth"] = g_smooth

        p: dict[str, float] = {
            s: adm[s] * cat_mult[category[s]] * M_soft[s] for s in strategies
        }
        total = sum(p.values())
        if total < 1e-12:
            diagnostics.append({
                "date": t, "M": M_, "V": V_, "T": T_, "G": G_, "C": C_, "R": R_,
                "Z": Z, "g_zone_raw": g_raw, "g_zone": g_smooth,
                "Q_top1": Q1, "gamma_top1": gamma1, "mu_top1": mu1,
                "block_top1": top[0]["label"], "size_top1": top[0]["size"],
                "rho_top1": top[0]["rho"], "n_blocks": n_blocks,
                "alpha_M": drivers.momentum_sensitivity,
                "fallback": "neutral",
            })
            return _equal_live(live)
        w_strategy = {s: g_smooth * p[s] / total for s in strategies}

        # MOM12_1 decomposition — only when MOM12_1 is in Φ.
        mom_contrib: dict[str, float] = {a: 0.0 for a in live}
        w_mom = 0.0
        if include_mom_eigen:
            w_mom = w_strategy.pop(MOM_NAME, 0.0)
            if w_mom > 1e-12:
                mom_port = _momentum_portfolio(history, live)
                for a in live:
                    share = w_mom * float(mom_port.get(a, 0.0))
                    mom_contrib[a] = share
                    w_strategy[a] = w_strategy.get(a, 0.0) + share

        out = pd.Series({a: w_strategy.get(a, 0.0) for a in live})

        m_arr = np.array([M_soft[s] for s in strategies], dtype=float)
        m_norm = m_arr / max(m_arr.sum(), 1e-12)
        herfindahl_M = float((m_norm ** 2).sum())

        diag: dict = {
            "date": t,
            "M": M_, "V": V_, "T": T_, "G": G_, "C": C_, "R": R_, "d_RP": d_RP,
            "Z": Z, "g_zone_raw": g_raw, "g_zone": g_smooth, "dQ": dQ,
            "block_top1": top[0]["label"], "size_top1": top[0]["size"],
            "Q_top1": Q1, "gamma_top1": gamma1, "mu_top1": mu1,
            "rho_top1": top[0]["rho"],
            "A_persistence": adm.get("ES", 0.0),
            "A_carry":       adm.get("TN", 0.0),
            "A_defensive":   adm.get("GC", 0.0),
            "A_convexity":   adm.get("SI", 0.0),
            "A_stress":      adm.get("CL", 0.0),
            "w_mom": w_mom, "gross": float(out.abs().sum()),
            "M_herfindahl": herfindahl_M,
            "n_blocks": n_blocks,
            "alpha_M": drivers.momentum_sensitivity,
            "include_mom_eigen": include_mom_eigen,
            **{f"mom_{a}": v for a, v in mom_contrib.items()},
        }
        if include_mom_eigen:
            diag["A_mom"] = adm.get(MOM_NAME, 0.0)
        if len(top) > 1:
            diag.update({
                "block_top2": top[1]["label"], "size_top2": top[1]["size"],
                "Q_top2": top[1]["Q"], "rho_top2": top[1]["rho"],
            })
        if len(top) > 2:
            diag.update({
                "block_top3": top[2]["label"], "size_top3": top[2]["size"],
                "Q_top3": top[2]["Q"], "rho_top3": top[2]["rho"],
            })
        diagnostics.append(diag)
        return out

    def diagnostics_df() -> pd.DataFrame:
        if not diagnostics:
            return pd.DataFrame()
        return pd.DataFrame(diagnostics).set_index("date")

    _signal.diagnostics = diagnostics              # type: ignore[attr-defined]
    _signal.diagnostics_df = diagnostics_df        # type: ignore[attr-defined]
    return _signal


# =============================================================================
# V7.5 + V7.3 Q polygons (VAIDM, ADD, Buffett) wrapper
# =============================================================================

def make_v75_q_signal(
    market: pd.DataFrame,
    realized: pd.DataFrame,
    drivers: V75DriverConfig | None = None,
    *,
    q_cfg=None,
    **v75_kwargs,
) -> SignalFn:
    """Wrap `make_v75_signal` with V7.3 Q-polygon multipliers.

    The underlying V7.5 engine selects assets and sizes positions via the
    manifold (admissibility × soft membership × Driver Seat × zone gate).
    This wrapper then multiplies the entire weight vector by

        Q_t = Q_VAIDM(t) · Q_ADD(t) · Q_Buffett(t)

    before returning, applied as a pure gross-exposure scalar. The V7.5
    engine's asset *selection* is unchanged; only *how much gross to
    deploy* is gated further by the Q polygons.

    Anti-hindsight: Q polygons read `history.iloc[:-1]` only — same rule
    as the underlying V7.5 engine, inherited from V7.3.

    `q_cfg=None` defaults to `QPolygonConfig()` (VAIDM + ADD enabled,
    Buffett disabled). Pass a custom config to toggle individual polygons.
    """
    from polyagora_v73_engine import (
        Q_ADD as _Q_ADD,
        Q_BUFFETT as _Q_BUFFETT,
        QPolygonConfig,
        Q_VAIDM as _Q_VAIDM,
    )

    q_cfg = q_cfg or QPolygonConfig()
    base_sig = make_v75_signal(market, realized, drivers=drivers, **v75_kwargs)

    q_diagnostics: list[dict] = []

    def _signal(history: pd.DataFrame, live: list[str], _cfg: V63EngineConfig) -> pd.Series:
        t = history.index[-1]
        w = base_sig(history, live, _cfg)

        history_lag = history.iloc[:-1]
        q_v = _Q_VAIDM(history_lag, q_cfg) if q_cfg.enable_vaidm else 1.0
        q_a, dd = _Q_ADD(history_lag, q_cfg) if q_cfg.enable_add else (1.0, 0.0)
        q_b = _Q_BUFFETT(history_lag, q_cfg) if q_cfg.enable_buffett else 1.0
        q_combined = float(q_v * q_a * q_b)

        q_diagnostics.append({
            "date": t,
            "q_vaidm": float(q_v),
            "q_add": float(q_a),
            "q_buffett": float(q_b),
            "q_combined": q_combined,
            "rolling_drawdown": float(dd),
        })
        return w * q_combined

    def diagnostics_df() -> pd.DataFrame:
        base_df = base_sig.diagnostics_df() if hasattr(base_sig, "diagnostics_df") else None
        if not q_diagnostics:
            return base_df if base_df is not None else pd.DataFrame()
        q_df = pd.DataFrame(q_diagnostics).set_index("date")
        if base_df is None or base_df.empty:
            return q_df
        return base_df.join(q_df, how="outer")

    _signal.diagnostics = q_diagnostics            # type: ignore[attr-defined]
    _signal.diagnostics_df = diagnostics_df        # type: ignore[attr-defined]
    return _signal


# =============================================================================
# Short-capable hybrid: V7.4d_q (manifold long) blended with V7.4b_template
# (V6.3 templates carrying shorts)
# =============================================================================

def make_v75_short_signal(
    market: pd.DataFrame,
    realized: pd.DataFrame,
    *,
    drivers: V75DriverConfig | None = None,
    q_cfg=None,
    alpha: float = 0.5,
    long_kwargs: dict | None = None,
) -> SignalFn:
    """Hybrid short-capable signal — V7.4d_q + V6.3-template overlay.

    Constructs two underlying signals:

      - **Long manifold** (`make_v75_q_signal`): V7.4d at α_M=0,
        include_mom_eigen=False, K=2, τ=2, λ=0.5, with VAIDM × ADD Q
        polygons. Latest V7.4-line winner; strictly long-only.

      - **Template overlay** (`make_v74b_signal` template branch): V6.3
        five-template mixture with V7.3 β-gate + VAIDM × ADD Q polygons —
        the V7.4b_template / V7.3-equivalent path that carries V6.3's
        Boundary (G) and Commodity-Stress (B) short positions.

    Final weight: `w_t = α · w_long_t + (1 - α) · w_template_t`.

    `α = 0.5` (default) gives equal contribution. Smaller `α` means more
    template overlay (more shorts during stress regimes). `α = 1.0` reduces
    to pure v74d_q; `α = 0.0` reduces to pure v74b_template.

    The result inherits all the latest improvements (VAIDM + ADD, V7.4d
    parameters on the manifold side, V7.4c-hardened zone classifier) and
    introduces *partial negative allocations* through the template overlay.
    """
    from polyagora_v73_engine import QPolygonConfig
    from polyagora_v74b_engine import V74bDriverConfig, make_v74b_signal

    q_cfg = q_cfg or QPolygonConfig()
    long_kwargs = long_kwargs or dict(
        include_mom_eigen=False, top_k=2, tau=2.0, lam=0.5,
    )

    long_sig = make_v75_q_signal(
        market, realized,
        drivers=drivers or V75DriverConfig(momentum_sensitivity=0.0),
        q_cfg=q_cfg,
        **long_kwargs,
    )
    overlay_sig = make_v74b_signal(
        market, realized, drivers=V74bDriverConfig(),
        block_source="template", top_k=5,
        gate_mode="beta", q_cfg=q_cfg,
    )

    diagnostics: list[dict] = []

    def _signal(history: pd.DataFrame, live: list[str], _cfg: V63EngineConfig) -> pd.Series:
        t = history.index[-1]
        w_long = long_sig(history, live, _cfg)
        w_overlay = overlay_sig(history, live, _cfg)
        common_idx = w_long.index.union(w_overlay.index)
        w_long = w_long.reindex(common_idx, fill_value=0.0)
        w_overlay = w_overlay.reindex(common_idx, fill_value=0.0)
        blended = alpha * w_long + (1.0 - alpha) * w_overlay

        diagnostics.append({
            "date": t,
            "alpha": float(alpha),
            "gross_long_leg": float(w_long.abs().sum()),
            "gross_overlay_leg": float(w_overlay.abs().sum()),
            "neg_in_overlay": float((w_overlay < -1e-9).sum()),
            "min_w_blended": float(blended.min()) if len(blended) else 0.0,
            "gross_blended": float(blended.abs().sum()),
        })
        return blended

    def diagnostics_df() -> pd.DataFrame:
        if not diagnostics:
            return pd.DataFrame()
        return pd.DataFrame(diagnostics).set_index("date")

    _signal.diagnostics = diagnostics              # type: ignore[attr-defined]
    _signal.diagnostics_df = diagnostics_df        # type: ignore[attr-defined]
    return _signal
