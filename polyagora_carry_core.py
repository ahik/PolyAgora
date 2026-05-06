"""
polyagora_carry_core.py

Strategic carry-core overlay for PolyAgora V6.2.

Adds a capped, cash-funded carry sleeve on top of the baseline PolyAgora
weights. Composition is selected weekly from trailing-Sharpe across a small
basket of carry-natured strategies; budget (beta_t) is gated daily by VIX
level, VIX shock, SPY drawdown, SPY 1-day shock, and portfolio drawdown.

Designed to keep PolyAgora's geometry intact while reclaiming part of the
permanent-carry premium that drives the AGUR equal-weight benchmark, with
explicit protection against rapid market slides like February 2020.

Timing convention matches polyagora_v62_engine.run_backtest:
  weights are stamped at decision date t, then weights.shift(1) is applied
  when computing portfolio returns, so the carry overlay only uses
  market and strategy data through t-1.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


CARRY_SLEEVES: tuple[str, ...] = (
    "VIX Roll Yield",
    "Contango Roll Carry",
    "G10 FX Carry",
)


@dataclass
class CarryCoreConfig:
    sleeves: tuple[str, ...] = CARRY_SLEEVES
    cap: float = 0.10
    sharpe_lookback: int = 252
    sharpe_min_periods: int = 126
    composition_floor: float = 0.10

    vix_soft_lo: float = 18.0
    vix_soft_hi: float = 48.0
    spy_5d_soft_floor: float = -0.07
    spy_5d_soft_ceiling: float = -0.02
    dd_soft_floor: float = -0.08
    dd_soft_ceiling: float = -0.05

    vix_hard_shock: float = 0.50
    vix_hard_level: float = 25.0
    spy_1d_hard: float = -0.03
    cooldown_days: int = 20

    beta_smoothing_halflife: float = 3.0
    transaction_cost_bps: float = 10.0


@dataclass
class CarryCoreResult:
    weights: pd.DataFrame
    returns: pd.Series
    equity: pd.Series
    diagnostics: pd.DataFrame
    overlay: pd.DataFrame


def _trailing_sharpe(returns: pd.DataFrame, lookback: int, min_periods: int) -> pd.DataFrame:
    mean = returns.rolling(lookback, min_periods=min_periods).mean()
    std = returns.rolling(lookback, min_periods=min_periods).std()
    sharpe = (mean * np.sqrt(252)) / (std * np.sqrt(252) + 1e-9)
    return sharpe


def _composition_weekly(
    strategy_returns: pd.DataFrame,
    rebal_dates: pd.DatetimeIndex,
    cfg: CarryCoreConfig,
) -> pd.DataFrame:
    sleeves = list(cfg.sleeves)
    sub = strategy_returns[sleeves]
    sharpe = _trailing_sharpe(sub, cfg.sharpe_lookback, cfg.sharpe_min_periods)
    sharpe = sharpe.shift(1)

    rebal_idx = rebal_dates.intersection(sharpe.index)
    snap = sharpe.reindex(rebal_idx)

    raw = np.exp(snap.fillna(0.0))
    weights = raw.div(raw.sum(axis=1), axis=0)
    n = len(sleeves)
    floor = cfg.composition_floor / n
    weights = weights.clip(lower=floor)
    weights = weights.div(weights.sum(axis=1), axis=0)

    full = pd.DataFrame(
        np.nan, index=strategy_returns.index, columns=sleeves
    )
    full.loc[weights.index] = weights.values
    full = full.ffill().fillna(1.0 / n)
    return full


def _beta_series(
    market: pd.DataFrame,
    portfolio_dd: pd.Series,
    cfg: CarryCoreConfig,
) -> pd.DataFrame:
    vix = market["VIX"].astype(float)
    spy = market["SPY"].astype(float)

    vix_5d_chg = vix.pct_change(5)
    spy_5d_ret = spy.pct_change(5)
    spy_1d_ret = spy.pct_change(1)

    vix_gate = (1.0 - ((vix - cfg.vix_soft_lo) /
                       (cfg.vix_soft_hi - cfg.vix_soft_lo))).clip(0.0, 1.0)
    spy_gate = ((spy_5d_ret - cfg.spy_5d_soft_floor) /
                (cfg.spy_5d_soft_ceiling - cfg.spy_5d_soft_floor)).clip(0.0, 1.0)
    dd_gate = ((portfolio_dd - cfg.dd_soft_floor) /
               (cfg.dd_soft_ceiling - cfg.dd_soft_floor)).clip(0.0, 1.0)

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
    raw_beta = (soft_beta * cooldown_scale).clip(0.0, 1.0)

    if cfg.beta_smoothing_halflife > 0:
        beta = raw_beta.ewm(halflife=cfg.beta_smoothing_halflife, adjust=False).mean()
    else:
        beta = raw_beta

    beta = beta.shift(1).fillna(0.0)

    diag = pd.DataFrame({
        "vix": vix,
        "vix_5d_chg": vix_5d_chg,
        "spy_5d_ret": spy_5d_ret,
        "spy_1d_ret": spy_1d_ret,
        "vix_gate": vix_gate,
        "spy_gate": spy_gate,
        "dd_gate": dd_gate,
        "soft_beta": soft_beta,
        "hard_kill": hard_kill.astype(int),
        "cooldown": cooldown,
        "raw_beta": raw_beta,
        "beta": beta,
    })
    return diag


def _portfolio_drawdown(weights: pd.DataFrame, strategy_returns: pd.DataFrame, sleeves: list[str]) -> pd.Series:
    aligned = weights[sleeves].shift(1).fillna(0.0)
    daily = (aligned * strategy_returns[sleeves]).sum(axis=1)
    eq = (1.0 + daily).cumprod()
    dd = eq / eq.cummax() - 1.0
    return dd


def _detect_rebals(weights: pd.DataFrame, sleeves: list[str]) -> pd.DatetimeIndex:
    diff = weights[sleeves].diff().abs().sum(axis=1)
    rebals = weights.index[diff > 1e-10]
    if weights.index[0] not in rebals:
        rebals = pd.DatetimeIndex([weights.index[0]]).append(rebals)
    return rebals


def build_carry_core(
    market: pd.DataFrame,
    strategy_returns: pd.DataFrame,
    base_weights: pd.DataFrame,
    sleeves_universe: list[str],
    cfg: CarryCoreConfig | None = None,
) -> CarryCoreResult:
    cfg = cfg or CarryCoreConfig()
    sleeves = list(cfg.sleeves)

    base = base_weights.copy()
    common = base.index.intersection(strategy_returns.index).intersection(market.index)
    base = base.loc[common]
    sret = strategy_returns.reindex(common).fillna(0.0)
    mkt = market.reindex(common).ffill()

    rebals = _detect_rebals(base, sleeves_universe)
    composition = _composition_weekly(sret, rebals, cfg)
    composition = composition.reindex(common).ffill().fillna(1.0 / len(sleeves))

    base_dd = _portfolio_drawdown(base, sret, sleeves_universe)
    diag = _beta_series(mkt, base_dd, cfg)
    diag = diag.reindex(common).fillna(0.0)
    beta = diag["beta"]

    overlay = composition.mul(beta * cfg.cap, axis=0)
    overlay = overlay.reindex(columns=sleeves_universe).fillna(0.0)

    new_strat = base[sleeves_universe].add(overlay, fill_value=0.0)
    total = new_strat.sum(axis=1)
    over = (total - 1.0).clip(lower=0.0)

    has_overlay = overlay.sum(axis=1)
    scale = pd.Series(1.0, index=common)
    mask = (has_overlay > 0) & (over > 0)
    scale.loc[mask] = (overlay.loc[mask].sum(axis=1) - over.loc[mask]).clip(lower=0.0) / overlay.loc[mask].sum(axis=1)

    overlay_clipped = overlay.mul(scale, axis=0)
    new_strat = base[sleeves_universe].add(overlay_clipped, fill_value=0.0)

    weights = base.copy()
    weights[sleeves_universe] = new_strat[sleeves_universe]
    weights["CASH"] = (1.0 - weights[sleeves_universe].sum(axis=1)).clip(lower=0.0)

    aligned = weights[sleeves_universe].shift(1).fillna(0.0)
    turnover = (weights[sleeves_universe] - weights[sleeves_universe].shift(1)).abs().sum(axis=1).fillna(0.0)
    costs = turnover * (cfg.transaction_cost_bps / 10000.0)
    portfolio_returns = (aligned * sret[sleeves_universe]).sum(axis=1) - costs
    equity = (1.0 + portfolio_returns).cumprod()

    diag_full = diag.copy()
    diag_full["beta_effective"] = scale * beta
    diag_full["overlay_total"] = overlay_clipped.sum(axis=1)
    diag_full["base_dd"] = base_dd

    return CarryCoreResult(
        weights=weights,
        returns=portfolio_returns,
        equity=equity,
        diagnostics=diag_full,
        overlay=overlay_clipped,
    )
