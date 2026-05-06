"""
PolyAgora V6.3 — Partner-Delivery Allocation Engine
====================================================

Targets the basis-portfolio benchmark in
`Agur/baseline_pnl_partner_delivery.xlsx`.

Universe: 13 single-asset futures (BTC, CL, DX, ES, FESX, FGBL, GC, HG,
NKD, SI, TN, ZS, ZW), each pre-scaled to 10% annual vol.

Convention (from the partner README):
    weights.loc[T] is decided at close of T using `realized_pnl` rows
    with index <= T, and is scored by `forward_pnl.loc[T]`. The
    `forward_pnl` sheet is **never** read inside the signal pipeline.

Main entry points:
    load_partner_xlsx(path) -> PartnerData
    compute_weights(data, signal_fn, cfg) -> pd.DataFrame
    evaluate(weights, data.forward_pnl) -> EvalResult
    summary_row(name, returns)
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, NamedTuple

import numpy as np
import pandas as pd


UNIVERSE: list[str] = [
    "BTC", "CL", "DX", "ES", "FESX", "FGBL", "GC",
    "HG", "NKD", "SI", "TN", "ZS", "ZW",
]

# Synthetic cash slot. Engine-internal: not a column in the partner workbook,
# but materializes in the emitted weights panel as the residual capital not
# deployed into real assets. Returns are zero on both realized and forward
# (no risk-free rate assumed). Always live; immune to inception/NaN rules.
CASH: str = "CASH"

# Spec envelope (per partner CTO, 2026-05-05):
#   |w_real_i| in [-1, 1] per asset, w_cash in [0, 1],
#   sum(|w_real|) + w_cash = 1.0 (capital budget).
# The engine enforces this for every emitted weight row.

ASSET_VOL_TARGET: float = 0.10  # each asset is pre-scaled to 10% annual vol
TRADING_DAYS: int = 252


@dataclass
class EngineConfig:
    momentum_lookback: int = 252
    momentum_skip: int = 21
    vol_lookback: int = 63
    weight_clip: float = 1.0      # per-asset abs cap (spec envelope)
    gross_cap: float = 1.0        # capital budget: sum(|w_real|) + cash = gross_cap


# Signal contract:
#   signal_fn(history, live_assets, cfg) -> pd.Series
# where:
#   history       — realized_pnl rows up to and including T (DatetimeIndex,
#                   columns UNIVERSE), NaNs preserved. Forward_pnl is never
#                   visible here.
#   live_assets   — list[str] of assets whose inception <= T.
#   returns       — pd.Series indexed by live_assets. The engine renormalizes
#                   the raw scores to sum to 1 across live assets via
#                   `raw * (budget / raw.sum())`. Mixed-sign scores can yield
#                   unstable gross exposure under that rule — for long/short
#                   signals, return weights that already sum to ~1 (the engine
#                   will pass them through unchanged when sum ≈ budget).
SignalFn = Callable[[pd.DataFrame, list[str], EngineConfig], pd.Series]


class PartnerData(NamedTuple):
    realized_pnl: pd.DataFrame   # train/calibrate ONLY
    forward_pnl: pd.DataFrame    # eval ONLY
    inception: pd.Series         # ticker -> first-usable date
    universe: list[str]


# =============================================================================
# I/O
# =============================================================================

def load_partner_xlsx(path: str | Path) -> PartnerData:
    xl = pd.ExcelFile(path)
    realized = pd.read_excel(xl, sheet_name="realized_pnl", parse_dates=["trading_date"])
    forward = pd.read_excel(xl, sheet_name="forward_pnl", parse_dates=["trading_date"])
    inc = pd.read_excel(xl, sheet_name="inception_dates")

    realized = realized.set_index("trading_date").sort_index()
    forward = forward.set_index("trading_date").sort_index()

    missing = set(UNIVERSE) - set(realized.columns)
    if missing:
        raise ValueError(f"realized_pnl missing universe columns: {sorted(missing)}")
    if not realized.index.equals(forward.index):
        raise ValueError("realized_pnl and forward_pnl have mismatched date indices")

    realized = realized[UNIVERSE]
    forward = forward[UNIVERSE]

    inc = inc.set_index("Ticker")["Inception Date"]
    inc = pd.to_datetime(inc).reindex(UNIVERSE)
    if inc.isna().any():
        raise ValueError(f"inception missing for: {inc[inc.isna()].index.tolist()}")

    return PartnerData(realized, forward, inc, list(UNIVERSE))


def inception_mask(data: PartnerData) -> pd.DataFrame:
    """True where the asset is live (inception_date <= row date)."""
    dates = data.realized_pnl.index
    return pd.DataFrame(
        {a: dates >= data.inception[a] for a in data.universe},
        index=dates,
    )


# =============================================================================
# Weight construction
# =============================================================================

def compute_weights(
    data: PartnerData,
    signal_fn: SignalFn,
    cfg: EngineConfig | None = None,
) -> pd.DataFrame:
    """
    Iterate dates T, calling signal_fn with realized history up to T.

    Capital-budget envelope (per partner CTO 2026-05-05):
      |w_real| in [-1,1] per asset, w_cash in [0,1],
      sum(|w_real|) + w_cash = cfg.gross_cap (default 1.0).

    NaN handling per partner README:
      Type 1 (pre-inception)             -> zero weight on that asset.
      Type 2 (post-inception, NaN today) -> freeze previous weight on that asset;
                                            its |frozen| consumes capital budget.

    The engine emits a weights panel with columns UNIVERSE + [CASH]. Cash is
    the residual capital not deployed: cash = gross_cap - sum(|w_real|).

    Look-ahead guards:
      - signal_fn is given history = realized.loc[:t] and never sees forward_pnl.
      - Each iteration asserts history.index[-1] == t and that the returned
        Series is indexed by a subset of `active` (no future or non-live names).
      - forward_pnl is hashed before/after the loop; mutation raises.
    """
    cfg = cfg or EngineConfig()
    realized = data.realized_pnl
    universe = data.universe
    live = inception_mask(data)
    dates = realized.index
    budget_total = float(cfg.gross_cap)

    forward_hash_before = int(pd.util.hash_pandas_object(data.forward_pnl, index=True).sum())

    cols = list(universe) + [CASH]
    weights = pd.DataFrame(0.0, index=dates, columns=cols)
    prev_w = pd.Series(0.0, index=cols)
    prev_w.loc[CASH] = budget_total  # before any signal fires we hold full cash

    for t in dates:
        live_today = [a for a in universe if live.at[t, a]]
        nan_today = [a for a in live_today if pd.isna(realized.at[t, a])]
        active = [a for a in live_today if a not in nan_today]
        active_set = set(active)

        # Type 2 (post-inception NaN): hold the prior weight on that asset.
        # Capital used by frozen positions is |frozen| (gross), not net.
        frozen = prev_w.reindex(nan_today).fillna(0.0)
        frozen_gross = float(frozen.abs().sum())
        budget = max(0.0, budget_total - frozen_gross)  # remaining gross budget

        if active and budget > 1e-12:
            history = realized.loc[:t]
            if history.empty or history.index[-1] != t:
                raise RuntimeError(f"history alignment broken at {t}: tail={history.index[-1] if len(history) else None}")
            raw = signal_fn(history, active, cfg)
            extra = set(raw.dropna().index) - active_set
            if extra:
                raise ValueError(
                    f"signal_fn returned weights for non-active assets at {t.date()}: {sorted(extra)}"
                )
            raw = raw.reindex(active).astype(float).fillna(0.0)
            raw = raw.clip(lower=-cfg.weight_clip, upper=cfg.weight_clip)

            raw_gross = float(raw.abs().sum())
            if raw_gross > budget + 1e-12:
                # Over-budget: scale all weights down so gross == budget.
                w_active = raw * (budget / raw_gross)
            else:
                # Under-budget: pass through; cash absorbs the slack.
                w_active = raw
        else:
            w_active = pd.Series(0.0, index=active)

        row = pd.Series(0.0, index=cols)
        if len(frozen):
            row.loc[frozen.index] = frozen.values
        if len(w_active):
            row.loc[w_active.index] = w_active.values

        gross_real = float(row[universe].abs().sum())
        # Floating-point safety: clamp cash into [0, budget_total].
        row.loc[CASH] = max(0.0, min(budget_total, budget_total - gross_real))

        weights.loc[t] = row.values
        prev_w = row

    forward_hash_after = int(pd.util.hash_pandas_object(data.forward_pnl, index=True).sum())
    if forward_hash_after != forward_hash_before:
        raise RuntimeError(
            "forward_pnl was mutated during compute_weights — look-ahead leak suspected"
        )
    return weights


# =============================================================================
# Baseline signal functions
# =============================================================================

def equal_weight_signal(
    history: pd.DataFrame, live: list[str], cfg: EngineConfig
) -> pd.Series:
    return pd.Series(1.0, index=live)


def momentum_signal(
    history: pd.DataFrame, live: list[str], cfg: EngineConfig
) -> pd.Series:
    """
    12-1 momentum, long-only on assets with positive cumulative return.

    Pre-normalizes to gross=1 so the engine fully deploys (no incidental cash).
    Cumulative returns are scores, not capital fractions; without this
    normalization the new capital-budget engine would treat small score
    magnitudes as literal under-deployment.
    """
    if len(history) < cfg.momentum_lookback + cfg.momentum_skip:
        return pd.Series(1.0, index=live)
    window = history.iloc[-(cfg.momentum_lookback + cfg.momentum_skip):-cfg.momentum_skip]
    cum = window[live].sum(axis=0, min_count=cfg.momentum_lookback // 2).fillna(0.0)
    raw = cum.clip(lower=0.0)
    gross = float(raw.abs().sum())
    if gross > 1e-12:
        return raw / gross
    return pd.Series(1.0, index=live)  # no positive momentum -> fall back to EW


def inverse_vol_signal(
    history: pd.DataFrame, live: list[str], cfg: EngineConfig
) -> pd.Series:
    if len(history) < cfg.vol_lookback:
        return pd.Series(1.0, index=live)
    vol = history[live].iloc[-cfg.vol_lookback:].std()
    inv = 1.0 / vol.replace(0.0, np.nan)
    return inv.fillna(0.0)


# =============================================================================
# PolyAgora signal — maps v62 regime blocks to the 13-asset partner universe
# =============================================================================
#
# Each block template is a unit-sum vector over UNIVERSE. The signal at date T
# is the convex combination of templates weighted by v62's block probabilities
# at T. Because templates and probabilities each sum to 1, the resulting raw
# signal sums to 1 over the universe; the v63 engine then drops pre-inception
# names and rescales to the live budget.
#
# Block intuition (anchors from polyagora_v62_engine.BLOCKS):
#   A Vol-Carry        — calm, low VIX, healthy credit. Long risk + bonds.
#   B Commodity Stress — high VIX, gold > copper, equities/credit weak.
#                        Long commods + DX, short equities/bonds/copper.
#   C Momentum         — strong SPY uptrend. Long equities + procyclical commods.
#   D Low-Vol          — very low VIX, mild trend. Long bonds + equities + DX.
#   G Boundary         — VIX spike. Defensive: long bonds/gold/DX, short risk.

POLYAGORA_TEMPLATES: dict[str, dict[str, float]] = {
    "A": {  # Vol-Carry — long-only, broadly diversified, modest commodities
        "ES": 0.18, "FESX": 0.13, "NKD": 0.13,
        "FGBL": 0.12, "TN": 0.12,
        "DX": 0.10,
        "CL": 0.05, "GC": 0.05, "HG": 0.04,
        "ZS": 0.04, "ZW": 0.04,
        "SI": 0.0, "BTC": 0.0,
    },
    "B": {  # Commodity Stress — original (longs 1.20 / shorts -0.20, gross 1.40)
            # squashed to gross=1 to fit the capital-budget envelope. Long/short
            # ratios preserved; net falls from 1.0 to ~0.714. Cash falls out as
            # the engine's gross-budget residual when this template is active.
        "CL":  0.18357, "GC":  0.18357, "SI": 0.12214, "DX": 0.12214,
        "ZS":  0.09214, "ZW":  0.09214, "BTC": 0.06143,
        "ES": -0.03571, "FESX": -0.02857, "NKD": -0.01786,
        "FGBL": -0.01786, "TN": -0.01786, "HG": -0.025,
    },
    "C": {  # Momentum — long equities + procyclical, no bonds
        "ES": 0.22, "FESX": 0.16, "NKD": 0.14,
        "HG": 0.10, "CL": 0.10,
        "BTC": 0.08, "DX": 0.06,
        "GC": 0.04, "SI": 0.04,
        "ZS": 0.03, "ZW": 0.03,
        "FGBL": 0.0, "TN": 0.0,
    },
    "D": {  # Low-Vol — long bonds + equities + DX, lighter commods
        "FGBL": 0.18, "TN": 0.18,
        "ES": 0.16, "FESX": 0.10, "NKD": 0.10,
        "DX": 0.10,
        "GC": 0.06, "HG": 0.04, "CL": 0.04,
        "ZS": 0.02, "ZW": 0.02,
        "SI": 0.0, "BTC": 0.0,
    },
    "G": {  # Boundary — flight to safety, original gross 1.70 squashed to 1.0
            # to fit the capital-budget envelope. Long/short ratios preserved;
            # net falls from 1.0 to ~0.588. Cash falls out as the engine's
            # gross-budget residual when this template is active.
        "FGBL": 0.17647, "TN": 0.17647, "GC": 0.17647,
        "DX":   0.11765, "SI": 0.05882,
        "CL":   0.02941, "ZS": 0.02941, "ZW": 0.02941,
        "ES":  -0.05882, "FESX": -0.04706, "NKD": -0.02941,
        "HG":  -0.04118, "BTC": -0.02941,
    },
}


NEUTRAL_TEMPLATE: dict[str, float] = {
    # Defensive baseline — what the gated signal blends toward when β is low.
    # Long bonds + GC + DX + light equities. Sums to 1.
    "FGBL": 0.20, "TN": 0.20, "GC": 0.15, "DX": 0.10,
    "ES": 0.05, "FESX": 0.05, "NKD": 0.05,
    "CL": 0.05, "HG": 0.03, "SI": 0.03,
    "ZS": 0.03, "ZW": 0.03, "BTC": 0.03,
}


def _validate_templates() -> None:
    """Enforce capital-budget envelope: each template's gross sum ≤ 1.0."""
    for name, t in POLYAGORA_TEMPLATES.items():
        missing = set(UNIVERSE) - set(t)
        if missing:
            raise ValueError(f"Template {name} missing assets: {sorted(missing)}")
        gross = sum(abs(v) for v in t.values())
        if gross > 1.0 + 1e-6:
            raise ValueError(
                f"Template {name} has gross {gross:.4f} > 1.0; "
                f"squash to gross<=1 to fit the capital-budget envelope"
            )
    n_gross = sum(abs(v) for v in NEUTRAL_TEMPLATE.values())
    if n_gross > 1.0 + 1e-6:
        raise ValueError(f"NEUTRAL_TEMPLATE gross {n_gross:.4f} > 1.0")


_validate_templates()

_TEMPLATE_DF: pd.DataFrame = pd.DataFrame(
    {b: pd.Series(t).reindex(UNIVERSE) for b, t in POLYAGORA_TEMPLATES.items()}
)


@dataclass
class PolyagoraGateConfig:
    """β-throttle parameters, ported from v62 carry-core (CarryCoreConfig)."""
    vix_soft_lo: float = 18.0
    vix_soft_hi: float = 48.0
    spy_5d_soft_floor: float = -0.07
    spy_5d_soft_ceiling: float = -0.02
    dd_soft_floor: float = -0.08
    dd_soft_ceiling: float = -0.05

    vix_hard_shock: float = 0.50  # 5-day VIX percent change triggering hard kill
    vix_hard_level: float = 25.0
    spy_1d_hard: float = -0.03
    cooldown_days: int = 20

    beta_smoothing_halflife: float = 3.0
    min_beta: float = 0.0  # set >0 to keep the signal tilt active during stress


def _compute_beta_from_market(
    market: pd.DataFrame,
    proxy_drawdown: pd.Series,
    cfg: PolyagoraGateConfig,
) -> pd.Series:
    """v62 carry-core β series: gates × hard-kill × cooldown × EWM × shift(1)."""
    vix = market["VIX"].astype(float)
    spy = market["SPY"].astype(float)

    vix_5d_chg = vix.pct_change(5)
    spy_5d_ret = spy.pct_change(5)
    spy_1d_ret = spy.pct_change(1)

    vix_gate = (1.0 - (vix - cfg.vix_soft_lo) / (cfg.vix_soft_hi - cfg.vix_soft_lo)).clip(0.0, 1.0)
    spy_gate = ((spy_5d_ret - cfg.spy_5d_soft_floor) / (cfg.spy_5d_soft_ceiling - cfg.spy_5d_soft_floor)).clip(0.0, 1.0)
    dd_aligned = proxy_drawdown.reindex(market.index, method="ffill")
    dd_gate = ((dd_aligned - cfg.dd_soft_floor) / (cfg.dd_soft_ceiling - cfg.dd_soft_floor)).clip(0.0, 1.0)

    soft_beta = (vix_gate * spy_gate * dd_gate).fillna(0.0)

    hard_kill = (
        ((vix_5d_chg >= cfg.vix_hard_shock) & (vix >= cfg.vix_hard_level))
        | (spy_1d_ret <= cfg.spy_1d_hard)
    ).fillna(False)

    cooldown = pd.Series(0, index=market.index, dtype=int)
    counter = 0
    for t in market.index:
        if bool(hard_kill.loc[t]):
            counter = cfg.cooldown_days
        cooldown.loc[t] = counter
        if counter > 0:
            counter -= 1

    cooldown_scale = (1.0 - cooldown.astype(float) / cfg.cooldown_days).clip(0.0, 1.0)
    raw_beta = (soft_beta * cooldown_scale).clip(cfg.min_beta, 1.0)

    if cfg.beta_smoothing_halflife > 0:
        beta = raw_beta.ewm(halflife=cfg.beta_smoothing_halflife, adjust=False).mean()
    else:
        beta = raw_beta

    return beta.shift(1).fillna(cfg.min_beta).clip(cfg.min_beta, 1.0)


def _proxy_drawdown(realized: pd.DataFrame) -> pd.Series:
    """Equal-weight live-universe proxy drawdown — uses realized_pnl only."""
    eq_returns = realized.mean(axis=1, skipna=True).fillna(0.0)
    eq_curve = (1.0 + eq_returns).cumprod()
    return eq_curve / eq_curve.cummax() - 1.0


def make_polyagora_signal(
    market: pd.DataFrame,
    v62_cfg=None,
) -> SignalFn:
    """
    Build a SignalFn that allocates over the 13-asset universe by mixing
    block-specific templates with v62's regime probabilities.

    `market` must have columns VIX, SPY, HYG, TLT, GLD, CPER (the v62
    convention). Block scores will only be available after v62's trend
    lookback warms up (~63 trading days into the market history). On dates
    before that, the signal falls back to equal-weight on live assets.
    """
    from polyagora_v62_engine import (  # local import: optional dependency
        EngineConfig as V62EngineConfig,
        build_block_history,
        build_exogenous_x,
    )

    cfg = v62_cfg or V62EngineConfig()
    X = build_exogenous_x(market, cfg)
    _, block_scores = build_block_history(X, cfg)
    block_scores = block_scores.sort_index()

    def _signal(history: pd.DataFrame, live: list[str], _cfg: EngineConfig) -> pd.Series:
        t = history.index[-1]
        idx = block_scores.index.asof(t)
        if pd.isna(idx):
            return pd.Series(1.0, index=live)
        probs = block_scores.loc[idx]
        tilt = _TEMPLATE_DF.dot(probs)
        return tilt.reindex(live).fillna(0.0)

    return _signal


def make_polyagora_signal_gated(
    market: pd.DataFrame,
    realized: pd.DataFrame,
    v62_cfg=None,
    gate_cfg: PolyagoraGateConfig | None = None,
) -> SignalFn:
    """
    PolyAgora regime tilt blended toward NEUTRAL_TEMPLATE by a v62-style β.

    weights_t = β_t · regime_tilt_t  +  (1 − β_t) · neutral_t

    β_t is built from VIX/SPY/drawdown soft gates × hard-kill cooldown × EWM,
    then shift(1)-ed so it depends only on data through t-1. The drawdown
    gate uses an equal-weight proxy on realized_pnl (no forward leak).
    Pre-2013 (before market warmup) falls back to neutral_t.
    """
    from polyagora_v62_engine import (
        EngineConfig as V62EngineConfig,
        build_block_history,
        build_exogenous_x,
    )

    base_cfg = v62_cfg or V62EngineConfig()
    gate = gate_cfg or PolyagoraGateConfig()

    X = build_exogenous_x(market, base_cfg)
    _, block_scores = build_block_history(X, base_cfg)
    block_scores = block_scores.sort_index()

    proxy_dd = _proxy_drawdown(realized)
    beta_series = _compute_beta_from_market(market, proxy_dd, gate)
    beta_series = beta_series.sort_index()

    neutral = pd.Series(NEUTRAL_TEMPLATE).reindex(UNIVERSE).fillna(0.0)

    def _renorm_to_gross(s: pd.Series) -> pd.Series:
        """
        Gross-budget renorm: scale s so sum(|s|) == 1. Long/short ratios are
        preserved; net is whatever falls out. Under the capital-budget envelope
        this leaves room for cash to absorb the slack when β·tilt + (1-β)·neutral
        produces opposing positions that partially cancel.
        """
        gross = float(s.abs().sum())
        if not np.isfinite(gross) or gross < 1e-12:
            return pd.Series(1.0 / max(len(s), 1), index=s.index)
        return s / gross

    def _signal(history: pd.DataFrame, live: list[str], _cfg: EngineConfig) -> pd.Series:
        t = history.index[-1]

        bs_idx = block_scores.index.asof(t)
        beta_idx = beta_series.index.asof(t)
        beta = float(beta_series.loc[beta_idx]) if pd.notna(beta_idx) else 0.0

        if pd.isna(bs_idx):
            return _renorm_to_gross(neutral.reindex(live).fillna(0.0))

        probs = block_scores.loc[bs_idx]
        tilt = _renorm_to_gross(_TEMPLATE_DF.dot(probs).reindex(live).fillna(0.0))
        neutral_live = _renorm_to_gross(neutral.reindex(live).fillna(0.0))
        return beta * tilt + (1.0 - beta) * neutral_live

    return _signal


# =============================================================================
# Evaluation (forward_pnl only)
# =============================================================================

@dataclass
class EvalResult:
    returns: pd.Series
    equity: pd.Series


def evaluate(weights: pd.DataFrame, forward_pnl: pd.DataFrame) -> EvalResult:
    if not weights.index.equals(forward_pnl.index):
        weights = weights.reindex(forward_pnl.index).fillna(0.0)
    # CASH contributes zero by construction; multiply only over real assets so
    # column shapes line up regardless of whether CASH is present in weights.
    real = [c for c in forward_pnl.columns if c in weights.columns]
    # forward_pnl NaN on an asset == not earned that day; treat as 0 contribution.
    contrib = weights[real].values * forward_pnl[real].fillna(0.0).values
    rets = pd.Series(contrib.sum(axis=1), index=forward_pnl.index, name="portfolio_return")
    equity = (1.0 + rets).cumprod()
    return EvalResult(returns=rets, equity=equity)


def summary_row(name: str, rets: pd.Series) -> dict:
    rets = rets.dropna()
    if rets.empty:
        return {"Series": name}
    equity = (1.0 + rets).cumprod()
    n = len(rets)
    cagr = equity.iloc[-1] ** (TRADING_DAYS / n) - 1.0
    vol = rets.std() * np.sqrt(TRADING_DAYS)
    sharpe = (rets.mean() * TRADING_DAYS) / vol if vol > 0 else np.nan
    dd = (equity / equity.cummax() - 1.0).min()
    return {
        "Series": name,
        "Total return": float(equity.iloc[-1] - 1.0),
        "CAGR": float(cagr),
        "Ann. vol": float(vol),
        "Sharpe": float(sharpe),
        "Max drawdown": float(dd),
    }
