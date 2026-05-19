"""
PolyAgora V7.10 — mean-reversion sleeve + governed sleeve blend
=================================================================

V7.10 operationalizes the multi-sleeve architecture: it adds the first
genuine **alpha sleeve** and the machinery to admit it. The
cross-method study, the Multi-Sleeve doc and the V7.9 addendum all named
the same #1 next step — a mean-reversion sleeve, "naturally
anti-correlated to momentum … extremely valuable" — because the V7.9
winner set fails correlation governance (avg pairwise correlation 0.64).

This module provides:

  - `make_mean_reversion_signal` — a short-horizon **cross-sectional
    reversal** sleeve over the 13-asset universe: fade the relative
    winners, buy the relative losers. Genuinely anti-momentum, so a
    candidate independent return stream.
  - `blend_sleeve` — the governed blend that folds an admitted sleeve
    into the v79 book at a registry-assigned, runtime-zone-scaled
    weight (doc-2 zone_permission: full in Zone 1 … off in Zone 4).

The sleeve is only a *candidate* here — `polyagora_sleeve_registry.py`
decides admission via the validation / DSR / correlation gates.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from polyagora_v63_partner_engine import CASH, EngineConfig, SignalFn


def make_mean_reversion_signal(lookback: int = 10) -> SignalFn:
    """Build a cross-sectional short-horizon reversal SignalFn.

    At each date the signal ranks the live assets by trailing
    `lookback`-day cumulative realized return, cross-sectionally
    demeans and standardizes, and takes the **negative** — long the
    relative losers, short the relative winners. Weights are normalized
    to gross 1 (long/short), so the engine deploys the sleeve fully.

    Anti-hindsight: only `history` (realized PnL ≤ t) is read. Before
    `lookback` rows of history the sleeve is flat (engine parks in cash).
    """
    def _signal(history: pd.DataFrame, live: list[str], cfg: EngineConfig) -> pd.Series:
        if len(history) < lookback or len(live) < 2:
            return pd.Series(0.0, index=live)
        window = history[live].iloc[-lookback:]
        cum = window.sum(axis=0, min_count=max(1, lookback // 2))
        cum = cum.dropna()
        if len(cum) < 2:
            return pd.Series(0.0, index=live)
        dev = cum - cum.mean()
        sd = dev.std()
        if not np.isfinite(sd) or sd < 1e-12:
            return pd.Series(0.0, index=live)
        score = -(dev / sd)                       # reversal: fade the move
        gross = float(score.abs().sum())
        if gross < 1e-12:
            return pd.Series(0.0, index=live)
        return (score / gross).reindex(live).fillna(0.0)

    return _signal


def make_trend_sleeve_signal(
    assets: list[str], lookback: int = 252, skip: int = 21
) -> SignalFn:
    """Build a time-series trend (crisis-trend) SignalFn over `assets`.

    Per asset, take the sign of the trailing `lookback`-day cumulative
    realized return ending `skip` days ago (a 12-1-style trend filter);
    long the up-trends, short the down-trends; normalize to gross 1.

    Restricted to the safe-haven subset {TN, FGBL, ...}, this is a
    fixed-income / crisis-trend sleeve: it goes *short* bonds when bonds
    trend down — so it earns in the 2022 rate shock, the regime every
    other PolyAgora component loses. Long-only manifolds cannot do this.
    Low-turnover (12-month signal) — survives realistic cost.

    Anti-hindsight: only `history` (realized PnL ≤ t) is read.
    """
    def _signal(history: pd.DataFrame, live: list[str], cfg: EngineConfig) -> pd.Series:
        use = [a for a in assets if a in live]
        if len(history) < lookback + skip or not use:
            return pd.Series(0.0, index=live)
        window = history[use].iloc[-(lookback + skip):-skip]
        mom = window.sum(axis=0, min_count=max(1, lookback // 2))
        sig = np.sign(mom).fillna(0.0)
        gross = float(sig.abs().sum())
        if gross < 1e-12:
            return pd.Series(0.0, index=live)
        return (sig / gross).reindex(live).fillna(0.0)

    return _signal


def zone_scaled_weight(
    base_weight: float,
    zone: pd.Series,
    zone_permission: dict[str, float],
) -> pd.Series:
    """Per-day sleeve weight = `base_weight · zone_permission[zone_t]`.

    The runtime zone comes from the V7.9 rotation detail; the
    permission table is the sleeve's doc-2 metadata (full in Zone 1,
    reduced in Zone 2, minimal in Zone 3, off in Zone 4).
    """
    mult = zone.map(zone_permission).astype(float).fillna(0.0)
    return (base_weight * mult).clip(0.0, 1.0)


def blend_sleeve(
    book_weights: pd.DataFrame,
    sleeve_weights: pd.DataFrame,
    sleeve_weight: pd.Series,
) -> pd.DataFrame:
    """Governed blend: `w = (1 − sₜ)·book + sₜ·sleeve`.

    Both panels are full (UNIVERSE + CASH) and on the capital-budget
    envelope, so the per-row convex combination is in-envelope. `sₜ` is
    the per-day, zone-scaled sleeve share from `zone_scaled_weight`.
    CASH is re-derived for floating-point safety.
    """
    cols = list(book_weights.columns)
    s = sleeve_weight.reindex(book_weights.index).fillna(0.0).clip(0.0, 1.0)
    book = book_weights
    sleeve = sleeve_weights.reindex(index=book.index, columns=cols).fillna(0.0)
    out = book.mul(1.0 - s, axis=0) + sleeve.mul(s, axis=0)
    real = [c for c in cols if c != CASH]
    out[CASH] = (1.0 - out[real].abs().sum(axis=1)).clip(lower=0.0)
    return out
