"""
sweep_carry_core.py

Sensitivity sweep for the PolyAgora V6.2 Carry-Core overlay.

Sweeps the carry budget cap and kill-switch thresholds, reporting full-period
stats plus crash-window behavior (Feb 2020 COVID, Feb 2018 Volmageddon,
Aug 2015 vol spike) for each variant.

Reads cached engine outputs (weights, market panel, AGUR returns) — does not
re-run the engine. Run after run_polyagora_v62_real_yahoo.py.

Outputs:
    polyagora_v62_yahoo_outputs/sweep_carry_core_v62_yahoo.csv
    Console table summarizing the sweep
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

from polyagora_carry_core import build_carry_core, CarryCoreConfig
from polyagora_v62_engine import AGOR_STRATEGIES
from run_polyagora_v62_real_yahoo import (
    load_agur_strategy_returns,
    resolve_agur_base,
    OUTPUT_DIR,
    MARKET_CSV,
    WEIGHTS_CSV,
)


SWEEP_CSV = OUTPUT_DIR / "sweep_carry_core_v62_yahoo.csv"

STRESS_WINDOWS = {
    "covid_2020": ("2020-02-19", "2020-04-30"),
    "volmageddon_2018": ("2018-01-26", "2018-02-28"),
    "aug_2015": ("2015-08-01", "2015-09-30"),
}


def _stats(r: pd.Series) -> dict:
    eq = (1.0 + r).cumprod()
    days = (eq.index[-1] - eq.index[0]).days
    cagr = float(eq.iloc[-1] ** (365.25 / days) - 1.0) if days > 0 else float("nan")
    vol = float(r.std() * np.sqrt(252))
    sharpe = float(r.mean() * 252 / vol) if vol > 0 else float("nan")
    dd = float((eq / eq.cummax() - 1.0).min())
    return {
        "cagr": cagr,
        "vol": vol,
        "sharpe": sharpe,
        "max_dd": dd,
    }


def _stress(r: pd.Series, lo: str, hi: str) -> dict:
    sub = r.loc[lo:hi]
    if sub.empty:
        return {"return": float("nan"), "max_dd": float("nan")}
    eq = (1.0 + sub).cumprod()
    return {
        "return": float(eq.iloc[-1] - 1.0),
        "max_dd": float((eq / eq.cummax() - 1.0).min()),
    }


def _evaluate(label: str, cfg: CarryCoreConfig, market, agur_returns, weights) -> dict:
    cc = build_carry_core(market, agur_returns, weights, AGOR_STRATEGIES, cfg)
    r = cc.returns
    row = {
        "variant": label,
        "cap": cfg.cap,
        "vix_hard_shock": cfg.vix_hard_shock,
        "vix_hard_level": cfg.vix_hard_level,
        "spy_1d_hard": cfg.spy_1d_hard,
        "cooldown_days": cfg.cooldown_days,
        "beta_smoothing_halflife": cfg.beta_smoothing_halflife,
    }
    row.update(_stats(r))
    avg_overlay = float(cc.diagnostics["overlay_total"].mean())
    avg_beta = float(cc.diagnostics["beta"].mean())
    row.update({"avg_overlay": avg_overlay, "avg_beta": avg_beta})
    for label_w, (lo, hi) in STRESS_WINDOWS.items():
        s = _stress(r, lo, hi)
        row[f"{label_w}_ret"] = s["return"]
        row[f"{label_w}_dd"] = s["max_dd"]
    return row


def main() -> None:
    market = pd.read_csv(MARKET_CSV, parse_dates=["date"]).set_index("date")
    weights = pd.read_csv(WEIGHTS_CSV, parse_dates=["date"]).set_index("date")
    agur_returns = load_agur_strategy_returns(resolve_agur_base())

    common = weights.index.intersection(agur_returns.index).intersection(market.index)
    market = market.loc[common]
    weights = weights.loc[common]
    agur_returns = agur_returns.loc[common]

    base = CarryCoreConfig()
    rows = []

    aligned_b = weights[AGOR_STRATEGIES].shift(1).fillna(0.0)
    turn_b = (weights[AGOR_STRATEGIES] - weights[AGOR_STRATEGIES].shift(1)).abs().sum(axis=1).fillna(0.0)
    ret_b = (aligned_b * agur_returns[AGOR_STRATEGIES]).sum(axis=1) - turn_b * (base.transaction_cost_bps / 10000.0)
    baseline_row = {
        "variant": "baseline_no_overlay",
        "cap": 0.0,
        "vix_hard_shock": np.nan,
        "vix_hard_level": np.nan,
        "spy_1d_hard": np.nan,
        "cooldown_days": np.nan,
        "beta_smoothing_halflife": np.nan,
        "avg_overlay": 0.0,
        "avg_beta": 0.0,
    }
    baseline_row.update(_stats(ret_b))
    for label_w, (lo, hi) in STRESS_WINDOWS.items():
        s = _stress(ret_b, lo, hi)
        baseline_row[f"{label_w}_ret"] = s["return"]
        baseline_row[f"{label_w}_dd"] = s["max_dd"]
    rows.append(baseline_row)

    rows.append(_evaluate("default", base, market, agur_returns, weights))

    for cap in [0.05, 0.075, 0.10, 0.125, 0.15, 0.20]:
        cfg = replace(base, cap=cap)
        rows.append(_evaluate(f"cap_{cap:.3f}", cfg, market, agur_returns, weights))

    for spy_hard in [-0.02, -0.025, -0.03, -0.04, -0.05]:
        cfg = replace(base, spy_1d_hard=spy_hard)
        rows.append(_evaluate(f"spy_hard_{spy_hard:+.3f}", cfg, market, agur_returns, weights))

    for vix_shock, vix_level in [(0.40, 20.0), (0.50, 25.0), (0.60, 30.0), (0.75, 35.0)]:
        cfg = replace(base, vix_hard_shock=vix_shock, vix_hard_level=vix_level)
        rows.append(_evaluate(f"vix_kill_{vix_shock:.2f}_{vix_level:.0f}", cfg, market, agur_returns, weights))

    for cooldown in [5, 10, 20, 30, 45]:
        cfg = replace(base, cooldown_days=cooldown)
        rows.append(_evaluate(f"cooldown_{cooldown}", cfg, market, agur_returns, weights))

    for halflife in [0.0, 1.0, 3.0, 5.0, 10.0]:
        cfg = replace(base, beta_smoothing_halflife=halflife)
        rows.append(_evaluate(f"smooth_hl_{halflife:.1f}", cfg, market, agur_returns, weights))

    grid_caps = [0.05, 0.10, 0.15]
    grid_cooldowns = [10, 20, 30]
    for cap in grid_caps:
        for cooldown in grid_cooldowns:
            cfg = replace(base, cap=cap, cooldown_days=cooldown)
            rows.append(_evaluate(f"grid_cap{cap:.2f}_cd{cooldown}", cfg, market, agur_returns, weights))

    df = pd.DataFrame(rows)
    df.to_csv(SWEEP_CSV, index=False, float_format="%.6f")
    print(f"Saved sweep: {SWEEP_CSV}\n")

    pretty = df[[
        "variant", "cap", "spy_1d_hard", "vix_hard_shock", "vix_hard_level",
        "cooldown_days", "beta_smoothing_halflife",
        "cagr", "vol", "sharpe", "max_dd", "avg_overlay",
        "covid_2020_ret", "covid_2020_dd",
        "volmageddon_2018_ret", "volmageddon_2018_dd",
        "aug_2015_ret", "aug_2015_dd",
    ]].copy()
    fmt = {
        "cap": lambda x: f"{x:.3f}",
        "spy_1d_hard": lambda x: f"{x:+.3f}" if pd.notna(x) else "",
        "vix_hard_shock": lambda x: f"{x:.2f}" if pd.notna(x) else "",
        "vix_hard_level": lambda x: f"{x:.0f}" if pd.notna(x) else "",
        "cooldown_days": lambda x: f"{x:.0f}" if pd.notna(x) else "",
        "beta_smoothing_halflife": lambda x: f"{x:.1f}" if pd.notna(x) else "",
        "cagr": lambda x: f"{x:.2%}",
        "vol": lambda x: f"{x:.2%}",
        "sharpe": lambda x: f"{x:.2f}",
        "max_dd": lambda x: f"{x:.2%}",
        "avg_overlay": lambda x: f"{x:.2%}",
        "covid_2020_ret": lambda x: f"{x:+.2%}",
        "covid_2020_dd": lambda x: f"{x:.2%}",
        "volmageddon_2018_ret": lambda x: f"{x:+.2%}",
        "volmageddon_2018_dd": lambda x: f"{x:.2%}",
        "aug_2015_ret": lambda x: f"{x:+.2%}",
        "aug_2015_dd": lambda x: f"{x:.2%}",
    }
    for c, fn in fmt.items():
        pretty[c] = pretty[c].map(fn)
    print(pretty.to_string(index=False))


if __name__ == "__main__":
    main()
