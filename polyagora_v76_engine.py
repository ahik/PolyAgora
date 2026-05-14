"""
PolyAgora V7.6α — Meta-Regime Steering Layer (minimum-viable cut)
==================================================================

Implements the first-cut steering layer described in
`docs/PolyAgora_Meta_Regime_Steering_Layer_V0.1.pdf` §17:

    Initial version should only use:
      - PolyAgora V7 (mapped to v74d_q here)
      - Momentum (mapped to momentum_12_1 baseline)
      - Defensive / CHASH (new — `defensive_signal`)

    Do NOT yet add: carry, convexity overlays, macro engines, online
    learning, MRTP machinery. First validate manifold-steering stability,
    recoverability advantage, admissibility quality, transition handling.

This module deliberately ignores the full MRTP score (αS + βF − γD) for
the first cut and uses the *simplest defensible* admissibility proxy:
backward-looking rolling Sharpe per manifold, softmax-blended with a
small floor, then EWM-smoothed to enforce the "slower / coarser"
layer-separation principle (spec §4).

Anti-hindsight invariant: meta-allocator at time `t` reads each
manifold's `returns.shift(1)` — never `returns[t]` itself, which depends
on `forward_pnl[t]`.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from polyagora_v63_partner_engine import CASH, EngineConfig, SignalFn, TRADING_DAYS


# =============================================================================
# Manifold M3: Defensive / CHASH — frozen, deliberately simple
# =============================================================================

DEFENSIVE_TARGET: dict[str, float] = {
    "TN":   0.40,   # 10y US notes
    "FGBL": 0.20,   # 10y Bund
    "GC":   0.20,   # Gold
    "DX":   0.20,   # USD index
}


def defensive_signal(
    history: pd.DataFrame, live: list[str], cfg: EngineConfig
) -> pd.Series:
    """Frozen defensive mix: long bonds + gold + USD.

    Restricted to {TN, FGBL, GC, DX}. Renormalizes over the subset that
    is live today; if none are live, returns zeros so the engine parks
    everything in CASH.
    """
    members = {a: w for a, w in DEFENSIVE_TARGET.items() if a in live}
    if not members:
        return pd.Series(0.0, index=live)
    s = sum(members.values())
    return pd.Series({a: members.get(a, 0.0) / s for a in live})


# =============================================================================
# Manifold M4: Pure CASH — the absorbing rest-state
# =============================================================================

def cash_signal(
    history: pd.DataFrame, live: list[str], cfg: EngineConfig
) -> pd.Series:
    """Zero real-asset weights → engine parks gross_cap entirely in CASH.

    Returns are zero by construction (CASH contributes nothing to
    `evaluate`). In the meta-allocator this gives Sharpe ≈ 0, which
    dominates only when every other manifold has negative rolling
    Sharpe — the spec §3.3 "Defensive / CHASH" role under collapse
    geometry, in its most stripped-down form.
    """
    return pd.Series(0.0, index=live)


# =============================================================================
# Meta-allocator
# =============================================================================

@dataclass
class MetaConfig:
    """V7.6α meta-allocator dials.

    All defaults chosen to satisfy spec §4 layer-separation: slow
    (halflife 10d), coarse (3 manifolds), low-entropy (λ=2 — softmax
    moderately sharp but not bang-bang).

    `min_floor`: minimum allocation per manifold after EWM smoothing,
    enforced before final renormalization. Prevents any manifold from
    fully starving — needed so the meta layer can react when its
    out-of-favor manifold suddenly catches up.

    `eval_lag`: bars between when W_i is computed and when it's applied.
    `eval_lag=1` means W computed from `returns_i ≤ t-1` is applied to
    `manifold_weights_i[t]` — the natural pairing since manifold weights
    at t already encode realized info ≤ t-1.
    """
    lookback: int = 63           # ~3 months for rolling Sharpe
    lam: float = 2.0             # softmax temperature
    ewm_halflife: float = 10.0   # smoothing on W_i(t)
    min_floor: float = 0.05      # minimum manifold allocation (5%)


def _rolling_sharpe(returns: pd.Series, lookback: int) -> pd.Series:
    """Backward-looking annualized Sharpe on `returns.shift(1)`.

    Shift(1) is the anti-hindsight gate: at row t we only see
    returns realized up to and including t-1.
    """
    r = returns.shift(1)
    mu = r.rolling(lookback, min_periods=lookback // 2).mean()
    sd = r.rolling(lookback, min_periods=lookback // 2).std()
    sharpe = (mu * TRADING_DAYS) / (sd * np.sqrt(TRADING_DAYS) + 1e-9)
    return sharpe.fillna(0.0)


def compute_manifold_allocations(
    manifold_returns: dict[str, pd.Series],
    cfg: MetaConfig | None = None,
) -> pd.DataFrame:
    """Compute W_i(t) — manifold allocation weights over time.

    Pipeline at time t (anti-hindsight: all inputs read returns ≤ t-1):
        s_i(t)  = rolling Sharpe over [t-lookback, t-1] for manifold i
        z_i(t)  = exp(λ · s_i(t))
        W_i(t)  = z_i(t) / Σ_j z_j(t)
        W̃_i(t) = EWM(W_i(t), halflife)
        W̃_i    = max(W̃_i, min_floor), then renormalize so Σ_i = 1

    Returns a DataFrame indexed by the common date index, columns =
    manifold names, rows summing to 1.0 by construction.
    """
    cfg = cfg or MetaConfig()
    names = list(manifold_returns.keys())
    common_idx = None
    for r in manifold_returns.values():
        common_idx = r.index if common_idx is None else common_idx.intersection(r.index)
    if common_idx is None or len(common_idx) == 0:
        raise ValueError("manifold_returns must share a non-empty date index")

    sharpe = pd.DataFrame(
        {n: _rolling_sharpe(manifold_returns[n].reindex(common_idx).fillna(0.0), cfg.lookback)
         for n in names},
        index=common_idx,
    )

    z = np.exp(cfg.lam * sharpe.values)
    W = z / z.sum(axis=1, keepdims=True)
    W = pd.DataFrame(W, index=common_idx, columns=names)

    W_smooth = W.ewm(halflife=cfg.ewm_halflife, adjust=False).mean()

    if cfg.min_floor > 0:
        W_smooth = W_smooth.clip(lower=cfg.min_floor)
        W_smooth = W_smooth.div(W_smooth.sum(axis=1), axis=0)

    return W_smooth


def _sigmoid(x):
    return 1.0 / (1.0 + np.exp(-np.asarray(x)))


# =============================================================================
# MRTP-lite: regime-conditioned admissibility from v75 diagnostics
# =============================================================================

@dataclass
class AdmissibilityConfig:
    """Sigmoid-shape parameters for the regime → A_i map.

    All four manifolds share a common floor (default 0.10) so no manifold
    is ever fully starved — the gate biases the softmax rather than
    cliff-cutting it.

    Each per-manifold scale/bias controls "where on the regime axis the
    sigmoid crosses 0.5":
        a_i(t) = floor + (1 - floor) · σ(scale_i · score_i(t) + bias_i)
    """
    floor: float = 0.10
    v74_scale: float = 2.0;   v74_bias: float = -0.5
    mom_scale: float = 3.0;   mom_bias: float = -0.5
    def_scale: float = 3.0;   def_bias: float = 0.0
    cash_scale: float = 3.0;  cash_bias: float = 0.0


def compute_regime_admissibility(
    diagnostics: pd.DataFrame,
    manifold_returns: dict[str, pd.Series],
    cfg: MetaConfig | None = None,
    adm_cfg: AdmissibilityConfig | None = None,
) -> pd.DataFrame:
    """A_i(t) per manifold from v75 regime coords + realized rolling Sharpes.

    Mapping (per spec §3 conceptual interpretation):
        v74d_q (V7 manifold)  ← high |dQ|, high d_RP    (transitions, fragmentation)
        momentum_12_1         ← |T| high AND dQ low      (persistent low-vol trends)
        defensive             ← V (VIX-z) elevated       (vol stress)
        cash                  ← worst realized Sharpe ≤ 0 (no good geometry available)

    All scores read v75 diagnostics at row t — v75 already enforces
    anti-hindsight (its diag at t depends only on realized ≤ t-1), so we
    pair diag[t] with manifold_weights[t] without additional shift.

    Returns a DataFrame indexed by the intersection of diag and
    manifold_returns indices, columns = manifold names, each row in
    [floor, 1.0]. NOT row-normalized — A is a multiplicative gate.
    """
    cfg = cfg or MetaConfig()
    adm_cfg = adm_cfg or AdmissibilityConfig()

    common_idx = diagnostics.index
    for r in manifold_returns.values():
        common_idx = common_idx.intersection(r.index)

    diag = diagnostics.reindex(common_idx)
    T = diag.get("T", pd.Series(0.0, index=common_idx)).astype(float).fillna(0.0)
    V = diag.get("V", pd.Series(0.0, index=common_idx)).astype(float).fillna(0.0)
    d_RP = diag.get("d_RP", pd.Series(0.0, index=common_idx)).astype(float).fillna(0.0)
    dQ = diag.get("dQ", pd.Series(0.0, index=common_idx)).astype(float).fillna(0.0)

    sharpes = pd.DataFrame(
        {n: _rolling_sharpe(manifold_returns[n].reindex(common_idx).fillna(0.0), cfg.lookback)
         for n in manifold_returns},
        index=common_idx,
    )

    f = adm_cfg.floor
    span = 1.0 - f

    score_v74 = 1.5 * dQ.clip(lower=0.0) + 1.0 * (d_RP - 0.4).clip(lower=0.0)
    a_v74 = f + span * _sigmoid(adm_cfg.v74_scale * score_v74 + adm_cfg.v74_bias)

    score_mom = T.abs() - 1.5 * dQ.clip(lower=0.0)
    a_mom = f + span * _sigmoid(adm_cfg.mom_scale * score_mom + adm_cfg.mom_bias)

    a_def = f + span * _sigmoid(adm_cfg.def_scale * V + adm_cfg.def_bias)

    worst = sharpes.max(axis=1).clip(lower=0.0)
    a_cash = f + span * _sigmoid(-adm_cfg.cash_scale * worst + adm_cfg.cash_bias)

    A = pd.DataFrame({
        "v74d_q":        a_v74,
        "momentum_12_1": a_mom,
        "defensive":     a_def,
        "cash":          a_cash,
    }, index=common_idx)

    available = [n for n in A.columns if n in manifold_returns]
    return A[available]


def compute_manifold_allocations_mrtp(
    manifold_returns: dict[str, pd.Series],
    admissibility: pd.DataFrame,
    cfg: MetaConfig | None = None,
) -> pd.DataFrame:
    """Spec §9 form: W_i = A_i · exp(λ · MRTP_i) / Σ_j  (MRTP_i ≈ rolling Sharpe)."""
    cfg = cfg or MetaConfig()
    names = list(manifold_returns.keys())
    common_idx = admissibility.index
    for r in manifold_returns.values():
        common_idx = common_idx.intersection(r.index)

    A = admissibility.reindex(common_idx)[names]
    sharpe = pd.DataFrame(
        {n: _rolling_sharpe(manifold_returns[n].reindex(common_idx).fillna(0.0), cfg.lookback)
         for n in names},
        index=common_idx,
    )

    z = A.values * np.exp(cfg.lam * sharpe.values)
    z_sum = z.sum(axis=1, keepdims=True)
    z_sum[z_sum < 1e-12] = 1e-12
    W = pd.DataFrame(z / z_sum, index=common_idx, columns=names)

    W = W.ewm(halflife=cfg.ewm_halflife, adjust=False).mean()
    if cfg.min_floor > 0:
        W = W.clip(lower=cfg.min_floor)
        W = W.div(W.sum(axis=1), axis=0)
    return W


def meta_blend_mrtp(
    manifold_weights: dict[str, pd.DataFrame],
    manifold_returns: dict[str, pd.Series],
    admissibility: pd.DataFrame,
    cfg: MetaConfig | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Spec §9–§10: admissibility-gated softmax blend over manifolds."""
    cfg = cfg or MetaConfig()
    W = compute_manifold_allocations_mrtp(manifold_returns, admissibility, cfg)

    names = list(manifold_weights.keys())
    columns = sorted(set().union(*[df.columns for df in manifold_weights.values()]))
    aligned = {
        n: manifold_weights[n].reindex(index=W.index, columns=columns).fillna(0.0)
        for n in names
    }
    combined = sum(aligned[n].mul(W[n], axis=0) for n in names)
    return combined, W


# =============================================================================
# v76γ: Full MRTP score — S (stability) + F (future maneuverability) − D (damage)
# =============================================================================

@dataclass
class MrtpConfig:
    """Spec §8 MRTP_i = α·S_i + β·F_i − γ·D_i.

    All term inputs read realized data ≤ t-1. `F_i` is "forward-looking"
    in the spec sense — it estimates *expected future regime persistence*
    via lag-autocorrelation of a regime coord, where the autocorrelation
    is computed on the past window. Never reads future returns.
    `D_i` is regime-bin-mismatch CVaR — "what is i's typical tail loss
    over historical days whose (V, T)-regime sign differs from today's?"

    Defaults: equal weight on S/F, slightly underweight D (it's the
    most noisy term because CVaR on small conditional subsets is jumpy).
    """
    alpha: float = 1.0
    beta:  float = 1.0
    gamma: float = 0.5
    s_lookback: int = 63
    f_lookback: int = 252
    f_lag: int = 21
    d_lookback: int = 252
    d_quantile: float = 0.05


def _rolling_autocorr(s: pd.Series, lookback: int, lag: int) -> pd.Series:
    """Lag-`lag` autocorrelation of `s` over a rolling [t-lookback, t-1] window.

    Anti-hindsight via shift(1). Returns Series in [-1, 1].
    Slow path (rolling.apply) but acceptable at 4669 rows × few manifolds.
    """
    s_lag = s.shift(1)

    def _ac(window):
        x = window.values
        x = x[~np.isnan(x)]
        if len(x) < max(lag * 2, 30) or np.std(x) < 1e-9:
            return 0.0
        return float(np.corrcoef(x[:-lag], x[lag:])[0, 1])

    return (
        s_lag.rolling(lookback, min_periods=max(lag * 2, lookback // 4))
        .apply(_ac, raw=False)
        .fillna(0.0)
    )


def _conditional_cvar(
    manifold_returns: dict[str, pd.Series],
    V: pd.Series,
    T: pd.Series,
    lookback: int,
    quantile: float,
) -> pd.DataFrame:
    """D_i(t) = -CVaR(quantile) of manifold-i returns on past days where the
    (sign(V), sign(T)) regime bin DIFFERS from today's bin.

    All inputs `.shift(1)`-lagged → anti-hindsight.
    Returns DataFrame with one column per manifold, all values ≥ 0 (loss
    magnitudes; bigger = more expected damage if today's regime call flips).
    """
    V_lag = V.shift(1).fillna(0.0)
    T_lag = T.shift(1).fillna(0.0)
    bin_V = np.sign(V_lag.values).astype(int)
    bin_T = np.sign(T_lag.values).astype(int)
    n = len(V_lag)

    out: dict[str, pd.Series] = {}
    for name, r in manifold_returns.items():
        r_lag = r.shift(1).values
        d = np.zeros(n)
        for i in range(lookback, n):
            cur_v = bin_V[i]
            cur_t = bin_T[i]
            start = i - lookback
            past_v = bin_V[start:i]
            past_t = bin_T[start:i]
            mask = (past_v != cur_v) | (past_t != cur_t)
            if mask.sum() < 10:
                continue
            adverse = r_lag[start:i][mask]
            adverse = adverse[~np.isnan(adverse)]
            if len(adverse) == 0:
                continue
            cutoff = np.quantile(adverse, quantile)
            tail = adverse[adverse <= cutoff]
            if len(tail) > 0:
                d[i] = -float(np.mean(tail))
        out[name] = pd.Series(d, index=r.index)
    return pd.DataFrame(out)


def compute_mrtp_score(
    diagnostics: pd.DataFrame,
    manifold_returns: dict[str, pd.Series],
    cfg: MrtpConfig | None = None,
) -> pd.DataFrame:
    """Full spec §8 score: MRTP_i = α·S̃_i + β·F̃_i − γ·D̃_i.

    Each component is normalized to ~[-1, 1] before combining:
        S̃ = tanh(Sharpe / 2)        — Sharpe in [-2, 2] → [-0.96, 0.96]
        F̃ = autocorr                 — already in [-1, 1]
        D̃ = tanh(50 · CVaR_loss)    — daily loss magnitudes → [0, ~1]

    F_i mapping (regime-persistence proxy for the regime that favors i):
        v74d_q   ← persistence of dQ  (transition activity)
        momentum ← persistence of T   (trend coord)
        defensive← persistence of V   (VIX-z)
        cash     ← negative max-S̃ across other manifolds (option value when nobody wins)
    """
    cfg = cfg or MrtpConfig()

    common_idx = diagnostics.index
    for r in manifold_returns.values():
        common_idx = common_idx.intersection(r.index)
    diag = diagnostics.reindex(common_idx)
    returns_aligned = {n: r.reindex(common_idx).fillna(0.0) for n, r in manifold_returns.items()}

    T = diag.get("T", pd.Series(0.0, index=common_idx)).astype(float).fillna(0.0)
    V = diag.get("V", pd.Series(0.0, index=common_idx)).astype(float).fillna(0.0)
    dQ = diag.get("dQ", pd.Series(0.0, index=common_idx)).astype(float).fillna(0.0)

    # --- S: stability via rolling Sharpe -------------------------------------
    S = pd.DataFrame(
        {n: _rolling_sharpe(r, cfg.s_lookback) for n, r in returns_aligned.items()},
        index=common_idx,
    )
    S_norm = np.tanh(S / 2.0)

    # --- F: regime-persistence autocorr (forward-looking interpretation,
    #        backward-looking data inputs) -----------------------------------
    F = pd.DataFrame(index=common_idx)
    persistence_dQ = _rolling_autocorr(dQ, cfg.f_lookback, cfg.f_lag)
    persistence_T  = _rolling_autocorr(T,  cfg.f_lookback, cfg.f_lag)
    persistence_V  = _rolling_autocorr(V,  cfg.f_lookback, cfg.f_lag)

    for n in manifold_returns:
        if n == "v74d_q":
            F[n] = persistence_dQ
        elif n == "momentum_12_1":
            F[n] = persistence_T
        elif n == "defensive":
            F[n] = persistence_V
        elif n == "cash":
            F[n] = (-S_norm.drop(columns=["cash"], errors="ignore").max(axis=1)).clip(-1.0, 1.0)
        else:
            F[n] = 0.0
    F = F[list(manifold_returns)]

    # --- D: conditional CVaR over regime-mismatch past days ------------------
    D_raw = _conditional_cvar(
        returns_aligned, V, T, cfg.d_lookback, cfg.d_quantile,
    )
    D_norm = np.tanh(D_raw * 50.0).reindex(columns=list(manifold_returns)).fillna(0.0)

    MRTP = cfg.alpha * S_norm + cfg.beta * F - cfg.gamma * D_norm
    return MRTP


def meta_blend_gamma(
    manifold_weights: dict[str, pd.DataFrame],
    manifold_returns: dict[str, pd.Series],
    admissibility: pd.DataFrame,
    mrtp_score: pd.DataFrame,
    cfg: MetaConfig | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Spec §9 with full MRTP score: W_i = A_i · exp(λ · MRTP_i) / Σ_j ..."""
    cfg = cfg or MetaConfig()
    names = list(manifold_returns.keys())
    common_idx = admissibility.index.intersection(mrtp_score.index)
    for r in manifold_returns.values():
        common_idx = common_idx.intersection(r.index)

    A = admissibility.reindex(common_idx)[names]
    MRTP = mrtp_score.reindex(common_idx)[names]
    z = A.values * np.exp(cfg.lam * MRTP.values)
    z_sum = z.sum(axis=1, keepdims=True)
    z_sum[z_sum < 1e-12] = 1e-12
    W = pd.DataFrame(z / z_sum, index=common_idx, columns=names)

    W = W.ewm(halflife=cfg.ewm_halflife, adjust=False).mean()
    if cfg.min_floor > 0:
        W = W.clip(lower=cfg.min_floor)
        W = W.div(W.sum(axis=1), axis=0)

    columns = sorted(set().union(*[df.columns for df in manifold_weights.values()]))
    aligned = {
        n: manifold_weights[n].reindex(index=W.index, columns=columns).fillna(0.0)
        for n in names
    }
    combined = sum(aligned[n].mul(W[n], axis=0) for n in names)
    return combined, W


def meta_blend(
    manifold_weights: dict[str, pd.DataFrame],
    manifold_returns: dict[str, pd.Series],
    cfg: MetaConfig | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Blend manifold weight panels by W_i(t).

    Spec §10:
        w_final(t) = Σ_i W_i(t) · w_i^assets(t)

    Returns (combined_weights, manifold_allocations). The combined
    weights panel has the same columns as the input manifold panels —
    no rescaling beyond what the meta-allocation arithmetic produces
    naturally (each manifold panel is already on the same gross_cap
    envelope, and Σ_i W_i = 1, so the blend stays in-envelope row-wise
    up to floating-point noise).
    """
    cfg = cfg or MetaConfig()
    W = compute_manifold_allocations(manifold_returns, cfg)

    names = list(manifold_weights.keys())
    columns = None
    for df in manifold_weights.values():
        columns = df.columns if columns is None else columns.union(df.columns)
    columns = list(columns)

    # Align all manifold weight panels to the same (date × columns) shape,
    # zero-fill anything missing.
    aligned = {
        n: manifold_weights[n].reindex(index=W.index, columns=columns).fillna(0.0)
        for n in names
    }

    combined = sum(
        aligned[n].mul(W[n], axis=0) for n in names
    )
    return combined, W
