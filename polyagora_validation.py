"""
PolyAgora V7.10 — strategy validation layer
=============================================

The validation machinery a candidate alpha sleeve must clear before the
Strategy Sleeve Registry (`polyagora_sleeve_registry.py`) will admit it.
Implements the doc-1 (`docs/AI Quant System.pdf`) pieces PolyAgora was
missing — most importantly the **Deflated Sharpe Ratio**, a hard
statistical gate that corrects a candidate's Sharpe for the
multiple-testing selection bias incurred when many strategies are tried
and the best is kept.

Self-contained: no scipy. The standard-normal CDF is computed from
`math.erf`.

Components
----------
    performance_metrics   extended metrics — Sharpe, Sortino, Calmar,
                          skew, excess kurtosis, hit rate, profit factor
    deflated_sharpe       multiple-testing-corrected Sharpe gate
    realistic_cost_bps    size/vol/venue-decomposed transaction cost
    cost_adjust           apply a turnover-based cost haircut to returns
    walk_forward_degradation   OOS/IS Sharpe degradation on a temporal split
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

TRADING_DAYS = 252
_EULER_GAMMA = 0.5772156649015329


def _norm_cdf(x: float) -> float:
    """Standard-normal CDF via the error function (scipy-free)."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


# =============================================================================
# Extended performance metrics
# =============================================================================

def performance_metrics(returns: pd.Series, annualization: int = TRADING_DAYS) -> dict:
    """Extended metric set for a daily return series (doc-1 `metrics that
    matter`). Returns Sharpe / Sortino / Calmar plus the three metrics
    the doc flags as most-ignored: excess kurtosis (hidden crash risk),
    Calmar (LP-facing recovery), and profit factor (robust trend vs
    fragile mean-reversion)."""
    r = returns.dropna()
    if len(r) < 30 or r.std() == 0:
        return {"sharpe": 0.0, "reason": "insufficient_data", "n": len(r)}

    mu, sigma = r.mean(), r.std()
    mean_ann = mu * annualization
    vol_ann = sigma * math.sqrt(annualization)
    sharpe = mean_ann / vol_ann

    downside = r[r < 0]
    sortino = (mean_ann / (downside.std() * math.sqrt(annualization))
               if len(downside) > 1 and downside.std() > 0 else float("inf"))

    eq = (1.0 + r).cumprod()
    max_dd = float((eq / eq.cummax() - 1.0).min())
    cagr = eq.iloc[-1] ** (annualization / len(r)) - 1.0
    calmar = cagr / abs(max_dd) if max_dd < -1e-9 else float("inf")

    skew = float(((r - mu) ** 3).mean() / sigma ** 3)
    excess_kurt = float(((r - mu) ** 4).mean() / sigma ** 4 - 3.0)

    hit_rate = float((r > 0).mean())
    avg_win = float(r[r > 0].mean()) if (r > 0).any() else 0.0
    avg_loss = float(r[r < 0].mean()) if (r < 0).any() else 0.0
    profit_factor = (
        abs(avg_win * hit_rate) / abs(avg_loss * (1.0 - hit_rate))
        if avg_loss != 0 and hit_rate < 1.0 else float("inf")
    )

    return {
        "sharpe": float(sharpe), "sortino": float(sortino), "calmar": float(calmar),
        "cagr": float(cagr), "vol_ann": float(vol_ann), "max_drawdown": max_dd,
        "skewness": skew, "excess_kurtosis": excess_kurt,
        "hit_rate": hit_rate, "avg_win": avg_win, "avg_loss": avg_loss,
        "profit_factor": float(profit_factor), "n": int(len(r)),
    }


# =============================================================================
# Deflated Sharpe Ratio — the multiple-testing gate
# =============================================================================

@dataclass
class DSRResult:
    observed_sharpe: float       # annualized
    expected_max_null: float     # annualized Sharpe expected from luck alone
    dsr_pvalue: float            # P(true Sharpe > expected_max_null)
    n_trials: int
    verdict: str                 # "pass" if dsr_pvalue > 0.95 else "reject"


def deflated_sharpe(
    returns: pd.Series, n_trials: int, annualization: int = TRADING_DAYS
) -> DSRResult:
    """Deflated Sharpe Ratio (Bailey & López de Prado).

    Test N strategies with zero true edge and the best in-sample Sharpe
    can clear 3.5 by luck alone. The DSR asks: given that this candidate
    is the survivor of `n_trials` attempts, and given the higher moments
    of its own return distribution, what is the probability its *true*
    Sharpe exceeds the Sharpe a lucky null would have produced?

    Verdict `pass` iff dsr_pvalue > 0.95 — a hard gate, no override.
    """
    r = returns.dropna()
    n = len(r)
    if n < 30 or r.std() == 0:
        return DSRResult(0.0, 0.0, 0.0, n_trials, "reject")

    mu, sigma = r.mean(), r.std()
    sharpe_ann = (mu / sigma) * math.sqrt(annualization)
    skew = float(((r - mu) ** 3).mean() / sigma ** 3)
    kurt = float(((r - mu) ** 4).mean() / sigma ** 4)   # raw (not excess)

    sr_per = sharpe_ann / math.sqrt(annualization)       # per-period Sharpe
    log_n = math.log(max(n_trials, 2))

    # Standard error of the per-period Sharpe *estimate* over n observations
    # (the moment-corrected Lo / Mertens variance). The expected-maximum of
    # n_trials null Sharpes is measured in units of THIS standard error —
    # not 1/√annualization, which would inflate the null bar ~4× and reject
    # every real strategy.
    se = math.sqrt(
        max(1.0 - skew * sr_per + (kurt - 1.0) / 4.0 * sr_per ** 2, 1e-9)
        / (n - 1)
    )
    # Expected maximum of n_trials iid standard normals.
    e_max = math.sqrt(2.0 * log_n) - _EULER_GAMMA / math.sqrt(2.0 * log_n)
    sr0 = se * e_max                                     # expected-max null SR

    dsr = _norm_cdf((sr_per - sr0) / se)

    return DSRResult(
        observed_sharpe=float(sharpe_ann),
        expected_max_null=float(sr0 * math.sqrt(annualization)),
        dsr_pvalue=float(dsr),
        n_trials=int(n_trials),
        verdict="pass" if dsr > 0.95 else "reject",
    )


# =============================================================================
# Realistic transaction cost
# =============================================================================

def realistic_cost_bps(
    order_size: float, adv: float, current_vol: float, venue: str = "lit"
) -> float:
    """Size/volatility/venue-decomposed cost (doc-1 `realistic cost
    model`). A constant `fee_bps` is a lie — real cost is half-spread +
    square-root market impact + venue fee. `current_vol` is daily
    fractional vol; `adv` and `order_size` share units (e.g. notional).
    """
    spread_bps = 1.5 + 5.0 * current_vol
    impact_bps = 10.0 * math.sqrt(max(order_size, 0.0) / max(adv, 1e-9)) * 100.0
    venue_bps = {"lit": 0.3, "dark": 0.2, "rfq": 0.5}.get(venue, 0.3)
    return spread_bps / 2.0 + impact_bps + venue_bps


def cost_adjust(
    returns: pd.Series, weights: pd.DataFrame, cost_bps: float = 4.0
) -> pd.Series:
    """Net-of-cost returns: subtract `turnover · cost_bps` each day.

    Turnover is the per-bar L1 change in the real-asset weight vector.
    `cost_bps` is a flat round-trip estimate; for a size-aware figure
    feed `realistic_cost_bps` per asset. Used to evaluate higher-turnover
    candidate sleeves net of frictions before the registry admits them.
    """
    real = [c for c in weights.columns if c != "CASH"]
    turnover = weights[real].diff().abs().sum(axis=1).fillna(0.0)
    cost = turnover * (cost_bps / 1e4)
    return (returns - cost.reindex(returns.index).fillna(0.0)).rename(returns.name)


# =============================================================================
# Walk-forward degradation
# =============================================================================

@dataclass
class DegradationResult:
    is_sharpe: float
    oos_sharpe: float
    degradation_ratio: float     # oos / is
    verdict: str                 # healthy 0.5-1.3, else "fragile"/"suspicious"


def walk_forward_degradation(
    returns: pd.Series, split: float = 0.6, annualization: int = TRADING_DAYS
) -> DegradationResult:
    """In-sample vs out-of-sample Sharpe on a single temporal split.

    Degradation ratio = OOS Sharpe / IS Sharpe. Healthy ≈ 0.5–1.3;
    below 0.3 the candidate is overfit; far above 1.3 is suspicious
    (data error or a lucky OOS regime). PolyAgora sleeves are
    rule-based with frozen parameters, so this measures *regime
    robustness* of the rule rather than fit stability.
    """
    r = returns.dropna()
    if len(r) < 120:
        return DegradationResult(0.0, 0.0, 0.0, "insufficient_data")
    cut = int(len(r) * split)
    is_m = performance_metrics(r.iloc[:cut], annualization)
    oos_m = performance_metrics(r.iloc[cut:], annualization)
    is_sh = is_m.get("sharpe", 0.0)
    oos_sh = oos_m.get("sharpe", 0.0)
    ratio = oos_sh / is_sh if abs(is_sh) > 1e-6 else 0.0
    if ratio < 0.3:
        verdict = "fragile"
    elif ratio > 1.3:
        verdict = "suspicious"
    else:
        verdict = "healthy"
    return DegradationResult(float(is_sh), float(oos_sh), float(ratio), verdict)
