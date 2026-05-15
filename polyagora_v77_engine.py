"""
PolyAgora V7.7 — ADD-lite topology deformation + Kelly capital sizing
======================================================================

V7.7 adds two **downstream overlays** on top of the frozen V7.6α
meta-steered blend. Neither overlay touches regime/block/star/manifold
construction — they act only on the already-computed blended weight
panel, after the meta-allocator and before final allocation. Both
deform *capital intensity*, never direction: a real-asset weight row is
only ever scaled toward CASH, its signs and relative proportions
untouched.

Feature 1 — ADD-lite  (docs: `Classical ADD to Lite-ADD`, `Lite-ADD in Flow`)
-----------------------------------------------------------------------------
A low-frequency topology-deformation field

    ADD_lite = w_C·C + w_S·S + w_B·B + w_R·R + w_P·P + w_F·F   ∈ [0, 1]

over six interpretable segments. Per `Lite-ADD in Flow`, ADD-lite is
**external** to the endogenous polygon geometry — every component here
is derived from market data only (the 13-asset partner realized PnL),
never from v75/v76 internal diagnostics. Rising ADD-lite means future
maneuverability is compressing; the overlay responds by scaling gross
exposure down toward CASH ("be less aggressive", not "go long/short").

    C  Corridor compression     HHI of trailing per-asset volatility
    S  Synchronization stress   mean pairwise cross-asset correlation
    B  Breadth degeneration     share of assets NOT in a positive trend
    R  Recoverability degrad.   fraction of window spent in drawdown
    P  Path-dependence concen.  lag-1 autocorrelation of the proxy curve
    F  Fragility asymmetry      negative skew + downside/upside vol ratio

Weights are frozen and equal (1/6 each) — interpretable, never
optimized against forward returns (spec §10 guardrail).

Feature 2 — Kelly  (docs: `Kelly Integration Spec`, `kelly_56.pdf`)
-------------------------------------------------------------------
Capital-intensity sizing downstream of governance:

    f_t = mode_mult · f*_t · Φ_t          (spec §9, §19 Mode A)
    f*_t = kelly_gain · μ_t / σ²_t        (classical continuous Kelly)
    Φ_t  = φ_Z · φ_R · φ_B · φ_V · φ_M    (governance deformation field)

f* is the classical edge/variance term; Φ ∈ [0,1] is the
*recoverability-aware governance gate* that — unlike ADD-lite — reads
the **internal** geometry (v75/v76 diagnostics + base-portfolio
trajectory). f_t is the fraction of the capital budget deployed into
real assets; the remainder parks in CASH.

Anti-hindsight
--------------
ADD-lite components read realized PnL only; Kelly's f* reads the base
portfolio's `returns.shift(1)`. Both the final ADD_lite series and the
final f_t series are `.shift(1)`-ed before being applied, so the scale
multiplying `weights[t]` depends only on information realized ≤ t-1.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from polyagora_v63_partner_engine import CASH, TRADING_DAYS, UNIVERSE


# =============================================================================
# Shared overlay primitive
# =============================================================================

def apply_gross_scale(weights: pd.DataFrame, scale: pd.Series) -> pd.DataFrame:
    """Scale a (UNIVERSE + CASH) weight panel's real gross by `scale ∈ [0,1]`.

    Each real-asset weight at row t is multiplied by `scale[t]`; CASH
    absorbs the freed budget so the capital-budget envelope
    `Σ|w_real| + w_cash = 1` still holds exactly. Signs and relative
    proportions of the real weights are untouched — this deforms
    capital intensity, never direction.
    """
    real = [c for c in weights.columns if c != CASH]
    s = scale.reindex(weights.index).fillna(1.0).clip(0.0, 1.0)
    out = weights.copy()
    out[real] = weights[real].mul(s, axis=0)
    new_gross = out[real].abs().sum(axis=1)
    out[CASH] = (1.0 - new_gross).clip(lower=0.0)
    return out


def _proxy_returns(realized_pnl: pd.DataFrame) -> pd.Series:
    """Equal-weight live-universe proxy daily return — realized PnL only."""
    return realized_pnl.mean(axis=1, skipna=True).fillna(0.0)


# =============================================================================
# Feature 1 — ADD-lite topology deformation field
# =============================================================================

@dataclass
class ADDLiteConfig:
    """ADD-lite dials. Component weights are frozen and equal — the spec
    forbids optimizing them against forward returns; they exist to be
    interpretable, not fitted.

    `add_sensitivity` (k) maps the field to a gross scale:
        scale = 1 - k · ADD_lite      (clipped to [scale_floor, 1])
    so the maximum de-grossing at ADD_lite = 1 is `k`, never to zero.
    """
    vol_lookback: int = 63       # C: trailing per-asset vol window
    corr_lookback: int = 63      # S: rolling cross-asset correlation window
    breadth_lookback: int = 126  # B: trend-participation window
    dd_lookback: int = 63        # R: drawdown-persistence window
    dd_threshold: float = 0.02   # R: depth that counts as "in drawdown"
    path_lookback: int = 63      # P: autocorrelation window
    frag_lookback: int = 126     # F: skew / downside-vol window
    smooth_halflife: float = 21.0  # low-frequency EWM on the composite

    w_C: float = 1.0 / 6
    w_S: float = 1.0 / 6
    w_B: float = 1.0 / 6
    w_R: float = 1.0 / 6
    w_P: float = 1.0 / 6
    w_F: float = 1.0 / 6

    add_sensitivity: float = 0.6   # k in scale = 1 - k·ADD_lite
    scale_floor: float = 0.20      # never de-gross below 20% of base


def _hhi_normalized(frame: pd.DataFrame) -> pd.Series:
    """Row-wise Herfindahl concentration of a non-negative frame,
    rescaled from [1/n, 1] to [0, 1] using each row's live-column count."""
    n = frame.notna().sum(axis=1).clip(lower=1)
    total = frame.sum(axis=1)
    shares = frame.div(total.where(total > 0, np.nan), axis=0)
    hhi = (shares ** 2).sum(axis=1)
    lo = 1.0 / n
    return ((hhi - lo) / (1.0 - lo)).clip(0.0, 1.0).fillna(0.0)


def _mean_pairwise_corr(realized_pnl: pd.DataFrame, lookback: int) -> pd.Series:
    """Rolling mean off-diagonal correlation across the 13 assets.

    High values = trajectories synchronizing (local optimization turning
    globally fragile, ADD-lite spec §9 'S' segment).
    """
    idx = realized_pnl.index
    vals = realized_pnl.values
    n_rows, n_assets = vals.shape
    out = np.zeros(n_rows)
    for i in range(n_rows):
        if i + 1 < lookback:
            continue
        win = vals[i + 1 - lookback: i + 1]
        # keep assets with enough non-NaN observations in the window
        ok = np.isfinite(win).sum(axis=0) >= lookback // 2
        sub = win[:, ok]
        if sub.shape[1] < 2:
            continue
        sub = np.where(np.isfinite(sub), sub, np.nan)
        cm = pd.DataFrame(sub).corr().values
        m = ~np.eye(cm.shape[0], dtype=bool)
        vals_off = cm[m]
        vals_off = vals_off[np.isfinite(vals_off)]
        if len(vals_off):
            out[i] = float(np.mean(vals_off))
    return pd.Series(out, index=idx).clip(0.0, 1.0)


def _rolling_autocorr1(s: pd.Series, lookback: int) -> pd.Series:
    """Rolling lag-1 autocorrelation, clipped to [0, 1] (only positive
    persistence counts as path-dependence)."""
    def _ac(window):
        x = window[np.isfinite(window)]
        if len(x) < lookback // 2 or np.std(x) < 1e-12:
            return 0.0
        return float(np.corrcoef(x[:-1], x[1:])[0, 1])

    return (
        s.rolling(lookback, min_periods=lookback // 2)
        .apply(_ac, raw=True)
        .clip(0.0, 1.0)
        .fillna(0.0)
    )


def compute_add_lite_components(
    realized_pnl: pd.DataFrame, cfg: ADDLiteConfig | None = None
) -> pd.DataFrame:
    """The six ADD-lite segments, each a Series in [0, 1] (higher = more
    topology degeneration). Derived from the 13-asset realized PnL only —
    ADD-lite is external to the endogenous PolyAgora geometry.
    """
    cfg = cfg or ADDLiteConfig()
    r = realized_pnl[UNIVERSE]
    idx = r.index

    # C — corridor compression: concentration of trailing per-asset vol.
    vol = r.abs().rolling(cfg.vol_lookback, min_periods=cfg.vol_lookback // 2).sum()
    C = _hhi_normalized(vol)

    # S — synchronization stress: mean pairwise cross-asset correlation.
    S = _mean_pairwise_corr(r, cfg.corr_lookback)

    # B — breadth degeneration: share of assets NOT in a positive trend.
    cum = r.rolling(cfg.breadth_lookback, min_periods=cfg.breadth_lookback // 2).sum()
    live = cum.notna().sum(axis=1).clip(lower=1)
    breadth = (cum > 0).sum(axis=1) / live
    B = (1.0 - breadth).clip(0.0, 1.0)

    # R — recoverability degradation: fraction of window spent in drawdown.
    proxy = _proxy_returns(r)
    eq = (1.0 + proxy).cumprod()
    dd = eq / eq.cummax() - 1.0
    in_dd = (dd < -cfg.dd_threshold).astype(float)
    R = in_dd.rolling(cfg.dd_lookback, min_periods=cfg.dd_lookback // 2).mean().fillna(0.0)

    # P — path-dependence concentration: positive autocorrelation of the
    #     proxy curve (system riding one continuation trajectory).
    P = _rolling_autocorr1(proxy, cfg.path_lookback)

    # F — fragility asymmetry: negative skew + downside/upside vol ratio.
    skew = proxy.rolling(cfg.frag_lookback, min_periods=cfg.frag_lookback // 2).skew()
    f_skew = (-skew / 2.0).clip(0.0, 1.0).fillna(0.0)
    down = proxy.where(proxy < 0)
    up = proxy.where(proxy > 0)
    dv = down.rolling(cfg.frag_lookback, min_periods=cfg.frag_lookback // 4).std()
    uv = up.rolling(cfg.frag_lookback, min_periods=cfg.frag_lookback // 4).std()
    f_asym = (dv / uv.replace(0.0, np.nan) - 1.0).clip(0.0, 1.0).fillna(0.0)
    F = (0.5 * f_skew + 0.5 * f_asym).clip(0.0, 1.0)

    return pd.DataFrame(
        {"C": C, "S": S, "B": B, "R": R, "P": P, "F": F}, index=idx
    ).fillna(0.0)


def compute_add_lite(
    realized_pnl: pd.DataFrame, cfg: ADDLiteConfig | None = None
) -> tuple[pd.Series, pd.DataFrame]:
    """ADD-lite composite ∈ [0, 1] plus the component panel.

    Composite = frozen-weighted sum of the six segments, EWM-smoothed
    (low-frequency, spec §10) and shifted one bar so the field applied
    to `weights[t]` uses only realized info ≤ t-1.
    """
    cfg = cfg or ADDLiteConfig()
    comp = compute_add_lite_components(realized_pnl, cfg)
    w = pd.Series(
        {"C": cfg.w_C, "S": cfg.w_S, "B": cfg.w_B,
         "R": cfg.w_R, "P": cfg.w_P, "F": cfg.w_F}
    )
    raw = comp.mul(w, axis=1).sum(axis=1).clip(0.0, 1.0)
    smooth = raw.ewm(halflife=cfg.smooth_halflife, adjust=False).mean()
    add_lite = smooth.shift(1).fillna(0.0).clip(0.0, 1.0)
    comp = comp.assign(ADD_lite_raw=raw, ADD_lite=add_lite)
    return add_lite, comp


def add_lite_scale(add_lite: pd.Series, cfg: ADDLiteConfig | None = None) -> pd.Series:
    """Map the ADD-lite field to a gross scale: `1 - k·ADD_lite`, floored."""
    cfg = cfg or ADDLiteConfig()
    return (1.0 - cfg.add_sensitivity * add_lite).clip(lower=cfg.scale_floor, upper=1.0)


# =============================================================================
# Feature 2 — Kelly capital-intensity sizing
# =============================================================================

@dataclass
class KellyConfig:
    """Kelly dials. `kelly_gain` folds the spec's λ scaling — it is the
    one knob controlling how large the raw f* term runs; the runner
    prints the realized f_t distribution so it can be tuned.

    Mode A (Conservative, spec §19) is the default: `mode_mult = 0.25`.
    `kelly_cap = 1.0` reflects the partner capital-budget envelope — the
    engine cannot lever real gross beyond the budget.

    Φ-gate calibration: each governance gate is built by ranking its
    stress driver against a trailing `phi_rank_window` of its own
    history. The calm half of that distribution (rank ≤ 0.5) leaves the
    gate at 1.0; the gate falls linearly to `phi_floor` as the driver
    climbs to the top of its range. This makes the gates regime-relative
    and self-calibrating rather than dependent on hand-tuned constants.
    """
    musigma_lookback: int = 63
    kelly_gain: float = 1.0       # λ-equivalent scaling on μ/σ²
    mode_mult: float = 0.25       # Mode A — Conservative (production-safe)
    kelly_cap: float = 1.0        # max deployed fraction (envelope)
    kelly_min: float = 0.0        # min deployed fraction
    phi_floor: float = 0.10       # per-gate floor — no single gate fully kills f
    phi_rank_window: int = 504    # ~2y trailing window for gate self-calibration
    phi_smooth_halflife: float = 5.0  # regime hysteresis on Φ
    sharpe_lookback: int = 63     # φ_M trajectory-quality window


def _sigmoid(x) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.asarray(x, dtype=float)))


def compute_governance_phi(
    base_returns: pd.Series,
    diagnostics: pd.DataFrame | None,
    add_components: pd.DataFrame,
    cfg: KellyConfig | None = None,
) -> pd.DataFrame:
    """The Φ governance deformation field and its five sub-gates.

    Each gate is driven by one *stress signal* (higher = worse). The
    signal is ranked against a trailing window of its own history; the
    gate sits at 1.0 while the signal is in the calm half of that
    distribution and falls linearly to `phi_floor` as it climbs to the
    top. Unlike ADD-lite, Φ reads the **internal** geometry — v75/v76
    diagnostics plus the base portfolio's own trajectory:

        φ_Z  zone stability     d_RP + |dQ|                (diagnostics)
        φ_R  recoverability     ADD-lite R segment
        φ_B  block coherence    -M_herfindahl              (diagnostics)
        φ_V  veto proximity     1 - engine gross           (diagnostics)
        φ_M  trajectory quality -base-portfolio Sharpe

    Φ is the **geometric mean** of the five gates. Spec §10 writes Φ as
    a raw product; the geometric mean places Φ on the spec §11
    operational scale (≈0.8–1.0 in a stable star, collapsing toward the
    floor as gates bite) — a raw product of five sub-unity gates would
    sit near 0.1 even in calm regimes. Geometric mean preserves the key
    property that any single gate hitting the floor drags Φ down hard.

    When diagnostics are absent the geometry-sourced gates fall back to
    a benign 1.0 so Φ stays dominated by φ_R / φ_M.
    """
    cfg = cfg or KellyConfig()
    idx = base_returns.index

    def _stress_gate(stress: pd.Series) -> pd.Series:
        """Map a stress signal to a gate ∈ [phi_floor, 1] via its own
        trailing-window rank: calm half → 1.0, top of range → floor."""
        rank = (stress.rolling(cfg.phi_rank_window,
                               min_periods=cfg.phi_rank_window // 4)
                .rank(pct=True).fillna(0.5))
        bite = (2.0 * (rank - 0.5)).clip(0.0, 1.0)
        return (1.0 - (1.0 - cfg.phi_floor) * bite).clip(cfg.phi_floor, 1.0)

    has_diag = diagnostics is not None

    # φ_Z — zone stability: rising regime-displacement / Q-shift = stress.
    if has_diag and {"d_RP", "dQ"}.issubset(diagnostics.columns):
        d_RP = diagnostics["d_RP"].reindex(idx).astype(float).fillna(0.0)
        dQ = diagnostics["dQ"].reindex(idx).astype(float).fillna(0.0)
        phi_Z = _stress_gate(d_RP.clip(lower=0.0) + dQ.abs())
    else:
        phi_Z = pd.Series(1.0, index=idx)

    # φ_R — recoverability: the ADD-lite R segment is the stress signal.
    phi_R = _stress_gate(add_components["R"].reindex(idx).fillna(0.0))

    # φ_B — block coherence: weakening coherence (low M_herfindahl) = stress.
    if has_diag and "M_herfindahl" in diagnostics.columns:
        hhi = diagnostics["M_herfindahl"].reindex(idx).astype(float).fillna(0.5)
        phi_B = _stress_gate(-hhi)
    else:
        phi_B = pd.Series(1.0, index=idx)

    # φ_V — veto proximity: low engine deployment (low gross) = near veto.
    if has_diag and "gross" in diagnostics.columns:
        gross = diagnostics["gross"].reindex(idx).astype(float).fillna(1.0)
        phi_V = _stress_gate(1.0 - gross.clip(0.0, 1.0))
    else:
        phi_V = pd.Series(1.0, index=idx)

    # φ_M — trajectory quality: a falling base-portfolio Sharpe = stress.
    #       Sharpe reads returns.shift(1) (anti-hindsight).
    r = base_returns.shift(1)
    mu = r.rolling(cfg.sharpe_lookback, min_periods=cfg.sharpe_lookback // 2).mean()
    sd = r.rolling(cfg.sharpe_lookback, min_periods=cfg.sharpe_lookback // 2).std()
    sharpe = (mu * TRADING_DAYS) / (sd * np.sqrt(TRADING_DAYS) + 1e-9)
    phi_M = _stress_gate(-sharpe.fillna(0.0))

    phi = pd.DataFrame(
        {"phi_Z": phi_Z, "phi_R": phi_R, "phi_B": phi_B,
         "phi_V": phi_V, "phi_M": phi_M},
        index=idx,
    )
    gates = ["phi_Z", "phi_R", "phi_B", "phi_V", "phi_M"]
    phi["Phi"] = np.exp(np.log(phi[gates].clip(lower=1e-9)).mean(axis=1))
    if cfg.phi_smooth_halflife > 0:
        phi["Phi"] = phi["Phi"].ewm(
            halflife=cfg.phi_smooth_halflife, adjust=False).mean()
    return phi


def compute_kelly_fraction(
    base_returns: pd.Series,
    phi: pd.Series,
    cfg: KellyConfig | None = None,
) -> tuple[pd.Series, pd.DataFrame]:
    """Kelly deployed-capital fraction f_t ∈ [kelly_min, kelly_cap].

        f*_t = kelly_gain · μ_t / σ²_t          (continuous Kelly)
        f_t  = clip(mode_mult · f*_t · Φ_t)

    μ, σ² are rolling moments of `base_returns.shift(1)` — anti-hindsight.
    The final f_t is `.shift(1)`-ed so it applies one bar after the
    information it is built on. Returns (f_t, detail-frame).
    """
    cfg = cfg or KellyConfig()
    r = base_returns.shift(1)
    mu = r.rolling(cfg.musigma_lookback, min_periods=cfg.musigma_lookback // 2).mean()
    var = r.rolling(cfg.musigma_lookback, min_periods=cfg.musigma_lookback // 2).var()

    f_star = cfg.kelly_gain * mu / (var + 1e-9)
    f_star = f_star.replace([np.inf, -np.inf], np.nan).fillna(0.0)

    phi_aligned = phi.reindex(base_returns.index).fillna(cfg.phi_floor)
    f_raw = cfg.mode_mult * f_star * phi_aligned
    f_t = f_raw.clip(lower=cfg.kelly_min, upper=cfg.kelly_cap)
    f_t = f_t.shift(1).fillna(cfg.kelly_min).clip(cfg.kelly_min, cfg.kelly_cap)

    detail = pd.DataFrame(
        {"mu": mu, "var": var, "f_star": f_star, "Phi": phi_aligned,
         "f_raw": f_raw, "f_kelly": f_t},
        index=base_returns.index,
    )
    return f_t, detail
