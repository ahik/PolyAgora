"""
PolyAgora V7.8 — asset-level ADD-lite + conditional soft Kelly
================================================================

V7.8 keeps the frozen V7.6α meta-steered blend as the governance base
and refines the two V7.7 overlays per `docs/PolyAgora V7.8 Absolute
Return Mode.pdf` and `docs/Keep V7.7-ADD.pdf`. The V7.7 evaluation
validated ADD-lite but found Kelly "too blunt" — the μ/σ²·Φ sizing was
a permanent brake that moved too much capital to CASH and killed
compounding. V7.8 fixes both overlays:

Change 1 — ADD-lite becomes per-asset continuous deformation (spec §9)
----------------------------------------------------------------------
V7.7 ADD-lite was a single portfolio-level scalar scaling the whole
book's gross. V7.8 makes it an **asset-level** field:

    ADD_{i,t} ∈ [0, 1]        w'_{i,t} = w_{i,t} · (1 - λ · ADD_{i,t})

Per spec §9 this "preserves convex winners, avoids flattening,
localizes the fragility response, preserves asymmetry" — a fragile
asset is trimmed without flattening the assets that are still convex.
ADD-lite stays **external** to the endogenous geometry: every segment
is derived from the 13-asset realized PnL only. Five segments:

    crowd_i      per-asset crowding   — asset i's mean correlation
                                        to the rest of the universe
    recov_i      recoverability loss  — asset i's drawdown persistence
    momsat_i     momentum saturation  — asset i's trend extension
    fragility_i  volatility asymmetry — asset i's downside/upside vol
    breadth_t    breadth degeneration — shared cross-sectional term

Change 2 — Kelly becomes conditional, not continuous (spec §11–§12)
-------------------------------------------------------------------
V7.7's `f_t = mode_mult·(μ/σ²)·Φ` is removed entirely — spec §11 flags
classical μ/σ² as "unstable under noisy estimates" (excessive cash,
dead convexity, reduced CAGR). V7.8 Kelly is the spec §12 gate:

    K_t = max(0, 1 - γ · (ADD_book,t - baseline_t)_+ )
    w''_{i,t} = K_t · w'_{i,t}

with γ ∈ [0.2, 0.5]. `ADD_book` is the book's gross-weighted ADD
exposure; `baseline` is its own trailing median. Kelly is therefore
**inert (K = 1) at or below baseline fragility** and trims only — and
gently — when fragility climbs above the book's own norm. This is the
"conditional, not permanent" Kelly: a soft convexity-preserving gate
keyed to the ADD field, never a continuous μ/σ² brake.

Anti-hindsight
--------------
ADD-lite segments read realized PnL only; the composite field is
EWM-smoothed and `.shift(1)`-ed, so the deformation applied to
`weights[t]` uses information realized ≤ t-1.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from polyagora_v63_partner_engine import CASH, UNIVERSE


# =============================================================================
# Overlay primitives
# =============================================================================

def apply_asset_deformation(
    weights: pd.DataFrame, add_field: pd.DataFrame, lam: float
) -> pd.DataFrame:
    """Per-asset continuous deformation `w'_i = w_i·(1 - λ·ADD_i)` (spec §9).

    Each real-asset weight is scaled by its *own* ADD-lite value; CASH
    absorbs the freed budget so `Σ|w_real| + w_cash = 1` still holds.
    Signs and the relative ranking of un-fragile assets are preserved —
    only fragile assets are trimmed, not the whole book.
    """
    real = [c for c in weights.columns if c != CASH]
    add = add_field.reindex(index=weights.index, columns=real).fillna(0.0)
    scale = (1.0 - lam * add).clip(lower=0.0, upper=1.0)
    out = weights.copy()
    out[real] = weights[real].mul(scale)
    out[CASH] = (1.0 - out[real].abs().sum(axis=1)).clip(lower=0.0)
    return out


def apply_kelly_gate(weights: pd.DataFrame, kelly: pd.Series) -> pd.DataFrame:
    """Apply the scalar conditional-Kelly gate `w'' = K_t·w'` (spec §12)."""
    real = [c for c in weights.columns if c != CASH]
    k = kelly.reindex(weights.index).fillna(1.0).clip(0.0, 1.0)
    out = weights.copy()
    out[real] = weights[real].mul(k, axis=0)
    out[CASH] = (1.0 - out[real].abs().sum(axis=1)).clip(lower=0.0)
    return out


# =============================================================================
# Feature 1 — asset-level ADD-lite field
# =============================================================================

@dataclass
class ADDLiteV78Config:
    """Asset-level ADD-lite dials. Segment weights are frozen and equal —
    never optimized against forward returns (spec §10 guardrail).

    `lam` (λ) is the per-asset deformation strength `w' = w(1-λ·ADD_i)`;
    a single uniform λ is used (spec writes λ_i to leave per-asset
    tuning open — kept uniform here as the interpretable default).
    """
    crowd_lookback: int = 63
    recov_lookback: int = 63
    recov_threshold: float = 0.02
    momsat_lookback: int = 63
    frag_lookback: int = 126
    breadth_lookback: int = 126
    smooth_halflife: float = 21.0

    w_crowd: float = 0.20
    w_recov: float = 0.20
    w_momsat: float = 0.20
    w_frag: float = 0.20
    w_breadth: float = 0.20

    lam: float = 0.6   # deformation strength


def _per_asset_crowding(realized: pd.DataFrame, lookback: int) -> pd.DataFrame:
    """crowd_{i,t} — asset i's mean correlation to the rest of the universe
    over a trailing window. High = asset i is moving with the crowd
    (correlation compression, spec §10)."""
    cols = list(realized.columns)
    vals = realized.values
    n_rows, n = vals.shape
    out = np.zeros((n_rows, n))
    for t in range(n_rows):
        if t + 1 < lookback:
            continue
        win = vals[t + 1 - lookback: t + 1]
        ok = np.isfinite(win).sum(axis=0) >= lookback // 2
        if ok.sum() < 2:
            continue
        sub = np.where(np.isfinite(win), win, np.nan)
        cm = pd.DataFrame(sub).corr().to_numpy(copy=True)
        np.fill_diagonal(cm, np.nan)
        # All-NaN rows (assets not yet live) → 0; nanmean would warn.
        valid = np.isfinite(cm).any(axis=1)
        row_mean = np.zeros(n)
        if valid.any():
            row_mean[valid] = np.nanmean(cm[valid], axis=1)
        out[t] = np.where(np.isfinite(row_mean), row_mean, 0.0)
    return pd.DataFrame(out, index=realized.index, columns=cols).clip(0.0, 1.0)


def compute_add_lite_field(
    realized_pnl: pd.DataFrame, cfg: ADDLiteV78Config | None = None
) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    """The asset-level ADD-lite field `ADD_{i,t} ∈ [0,1]` plus its segments.

    Returns (ADD_field, segments) where ADD_field is a [dates × UNIVERSE]
    panel (EWM-smoothed, `.shift(1)`-ed for anti-hindsight) and segments
    is a dict of the five raw component panels.
    """
    cfg = cfg or ADDLiteV78Config()
    r = realized_pnl[UNIVERSE]
    idx = r.index

    # crowd_i — per-asset crowding (mean correlation to the universe).
    crowd = _per_asset_crowding(r, cfg.crowd_lookback)

    # recov_i — per-asset drawdown persistence (recoverability loss).
    eq = (1.0 + r.fillna(0.0)).cumprod()
    dd = eq / eq.cummax() - 1.0
    in_dd = (dd < -cfg.recov_threshold).astype(float)
    recov = in_dd.rolling(cfg.recov_lookback,
                          min_periods=cfg.recov_lookback // 2).mean().fillna(0.0)

    # momsat_i — per-asset momentum saturation (trend extension as a
    # cumulative-move t-stat, squashed into [0,1]).
    cum = r.rolling(cfg.momsat_lookback, min_periods=cfg.momsat_lookback // 2).sum()
    sd = r.rolling(cfg.momsat_lookback, min_periods=cfg.momsat_lookback // 2).std()
    tstat = cum.abs() / (sd * np.sqrt(cfg.momsat_lookback) + 1e-9)
    momsat = (tstat / 3.0).clip(0.0, 1.0).fillna(0.0)

    # fragility_i — per-asset volatility asymmetry (negative skew +
    # downside/upside vol ratio).
    skew = r.rolling(cfg.frag_lookback, min_periods=cfg.frag_lookback // 2).skew()
    f_skew = (-skew / 2.0).clip(0.0, 1.0).fillna(0.0)
    dv = r.where(r < 0).rolling(cfg.frag_lookback,
                                min_periods=cfg.frag_lookback // 4).std()
    uv = r.where(r > 0).rolling(cfg.frag_lookback,
                                min_periods=cfg.frag_lookback // 4).std()
    f_asym = (dv / uv.replace(0.0, np.nan) - 1.0).clip(0.0, 1.0).fillna(0.0)
    fragility = (0.5 * f_skew + 0.5 * f_asym).clip(0.0, 1.0)

    # breadth_t — shared cross-sectional term (share of assets not in a
    # positive trend), broadcast to every asset.
    cum_b = r.rolling(cfg.breadth_lookback,
                      min_periods=cfg.breadth_lookback // 2).sum()
    live = cum_b.notna().sum(axis=1).clip(lower=1)
    breadth_scalar = (1.0 - (cum_b > 0).sum(axis=1) / live).clip(0.0, 1.0)
    breadth = pd.DataFrame(
        np.repeat(breadth_scalar.values[:, None], len(UNIVERSE), axis=1),
        index=idx, columns=UNIVERSE,
    )

    segments = {"crowd": crowd, "recov": recov, "momsat": momsat,
                "fragility": fragility, "breadth": breadth}

    raw = (cfg.w_crowd * crowd + cfg.w_recov * recov + cfg.w_momsat * momsat
           + cfg.w_frag * fragility + cfg.w_breadth * breadth).clip(0.0, 1.0)
    smooth = raw.ewm(halflife=cfg.smooth_halflife, adjust=False).mean()
    add_field = smooth.shift(1).fillna(0.0).clip(0.0, 1.0)
    return add_field, segments


# =============================================================================
# Feature 2 — conditional soft Kelly gate
# =============================================================================

@dataclass
class KellyV78Config:
    """Conditional-Kelly dials (spec §12).

    `gamma` ∈ [0.2, 0.5] — the spec's recommended band; the gate trims at
    most γ per unit of above-baseline ADD. `baseline_window` sets the
    trailing window whose median defines "normal" book fragility: Kelly
    is inert at or below it and trims only above it.
    """
    gamma: float = 0.35
    baseline_window: int = 252
    baseline_min_periods: int = 63
    kelly_min: float = 0.0
    kelly_cap: float = 1.0


def compute_book_add(base_weights: pd.DataFrame, add_field: pd.DataFrame) -> pd.Series:
    """`ADD_book,t` — the book's gross-weighted ADD-lite exposure.

    Weights each asset's ADD by the share of real gross it carries in
    the (pre-deformation) base book, so the scalar reflects the fragility
    the portfolio is actually exposed to.
    """
    real = [c for c in base_weights.columns if c != CASH]
    add = add_field.reindex(index=base_weights.index, columns=real).fillna(0.0)
    absw = base_weights[real].abs()
    gross = absw.sum(axis=1)
    weighted = (absw * add).sum(axis=1) / gross.where(gross > 1e-12, np.nan)
    # When the book is all-cash, no real fragility is being carried.
    return weighted.fillna(0.0).clip(0.0, 1.0)


def compute_conditional_kelly(
    book_add: pd.Series, cfg: KellyV78Config | None = None
) -> tuple[pd.Series, pd.DataFrame]:
    """Conditional soft-Kelly gate `K_t = max(0, 1 - γ·(ADD_book - baseline)_+)`.

    Baseline = trailing median of `book_add`. The gate equals 1 (Kelly
    fully passive — "conditional, not continuous") whenever book
    fragility sits at or below its own norm, and trims gently above it.
    Returns (K_t, detail-frame).
    """
    cfg = cfg or KellyV78Config()
    baseline = book_add.rolling(cfg.baseline_window,
                                min_periods=cfg.baseline_min_periods).median()
    baseline = baseline.fillna(book_add.expanding(min_periods=1).median())
    excess = (book_add - baseline).clip(lower=0.0)
    K = (1.0 - cfg.gamma * excess).clip(lower=cfg.kelly_min, upper=cfg.kelly_cap)
    detail = pd.DataFrame(
        {"book_add": book_add, "baseline": baseline,
         "excess": excess, "K_kelly": K},
        index=book_add.index,
    )
    return K, detail
