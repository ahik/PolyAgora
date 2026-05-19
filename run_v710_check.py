"""
V7.10 check — Strategy Sleeve Registry + first mean-reversion sleeve.

Builds the V7.9 book, constructs the first candidate alpha sleeve (a
short-horizon cross-sectional reversal), runs it through the Strategy
Sleeve Registry's gate pipeline (validation → Deflated Sharpe →
correlation-to-book → walk-forward degradation), and — only if all
gates pass — folds it into the book at a registry-assigned,
runtime-zone-scaled weight.

    v76α        governance base
    v78-ADD     asset-level ADD-lite core
    v79         + governed defensive rotation
    MR-sleeve   candidate mean-reversion sleeve (net of cost, standalone)
    v7.10       v79 + the sleeve IF the registry admits it; else = v79

The sleeve is evaluated net of transaction cost (doc-1 mandate). If the
registry rejects it, that is a valid outcome — the machinery caught a
candidate that does not survive the gates — and v7.10 falls back to v79.

Outputs land in `polyagora_v710_outputs/`.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from polyagora_v63_partner_engine import (
    UNIVERSE,
    EngineConfig,
    compute_weights,
    equal_weight_signal,
    evaluate,
    load_partner_xlsx,
    momentum_signal,
    summary_row,
)
from polyagora_v73_engine import QPolygonConfig
from polyagora_v75_engine import V75DriverConfig, make_v75_q_signal
from polyagora_v76_engine import MetaConfig, cash_signal, defensive_signal, meta_blend
from polyagora_v78_engine import (
    ADDLiteV78Config,
    apply_asset_deformation,
    compute_add_lite_field,
    compute_book_add,
)
from polyagora_v79_engine import RotationConfig, apply_rotation, compute_rotation
from polyagora_v710_engine import (
    blend_sleeve,
    make_mean_reversion_signal,
    make_trend_sleeve_signal,
    zone_scaled_weight,
)
from polyagora_sleeve_registry import (
    GateConfig,
    SleeveRegistry,
    SleeveSpec,
    evaluate_sleeve,
)
from polyagora_validation import cost_adjust


ROOT = Path(__file__).resolve().parent
DEFAULT_INPUT = ROOT / "Agur" / "baseline_pnl_partner_delivery.xlsx"
DEFAULT_MARKET = ROOT / "market_data" / "market_yahoo_vix_spy_hyg_tlt_gld_cper.csv"
DEFAULT_OUTPUT = ROOT / "polyagora_v710_outputs"


def _summary(name: str, rets: pd.Series, equity: pd.Series) -> dict:
    r = summary_row(name, rets)
    down = rets[rets < 0]
    sortino = ((rets.mean() * 252) / (down.std() * np.sqrt(252))
               if len(down) and down.std() > 0 else float("nan"))
    cagr = r.get("CAGR", float("nan"))
    mdd = abs(r.get("Max drawdown", float("nan")))
    r["Sortino"] = sortino
    r["Calmar"] = cagr / mdd if mdd > 1e-9 else float("nan")
    return r


def _crisis(returns: pd.Series, label: str, a: str, b: str) -> dict:
    sl = returns.loc[a:b]
    if sl.empty:
        return {"window": label, "n": 0}
    eq = (1 + sl).cumprod()
    return {"window": label, "n": len(sl),
            "sharpe": float((sl.mean() * 252) / (sl.std() * np.sqrt(252)))
            if sl.std() > 0 else float("nan"),
            "max_dd": float((eq / eq.cummax() - 1.0).min())}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    p.add_argument("--market", type=Path, default=DEFAULT_MARKET)
    p.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    p.add_argument("--n-trials", type=int, default=12,
                   help="multiple-testing count for the Deflated Sharpe gate")
    args = p.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)
    data = load_partner_xlsx(args.input)
    cfg = EngineConfig()
    market = pd.read_csv(args.market, parse_dates=["date"]).set_index("date")

    # --- V7.9 book (manifolds → v76α → v78-ADD → v79 rotation) --------------
    m1 = make_v75_q_signal(market, data.realized_pnl,
                           drivers=V75DriverConfig(momentum_sensitivity=0.0),
                           q_cfg=QPolygonConfig(), include_mom_eigen=False,
                           top_k=2, tau=2.0, lam=0.5)
    manifolds = {"v74d_q": m1, "momentum_12_1": momentum_signal,
                 "defensive": defensive_signal, "cash": cash_signal}
    print(f"[run] data: {data.realized_pnl.index.min().date()} -> "
          f"{data.realized_pnl.index.max().date()}  ({len(data.realized_pnl)} rows)")

    weights, returns = {}, {}
    for name, sig in manifolds.items():
        w = compute_weights(data, sig, cfg)
        weights[name] = w
        returns[name] = evaluate(w, data.forward_pnl).returns
        w.to_csv(args.output / f"weights_{name}.csv", index_label="trading_date")
        returns[name].to_csv(args.output / f"returns_{name}.csv", index_label="trading_date")

    meta_cfg = MetaConfig(lookback=63, lam=2.0, ewm_halflife=10.0, min_floor=0.15)
    base_w, _ = meta_blend(weights, returns, meta_cfg)
    base_w = base_w.reindex(data.forward_pnl.index).fillna(0.0)
    base_res = evaluate(base_w, data.forward_pnl)
    base_w.to_csv(args.output / "weights_v76.csv", index_label="trading_date")
    base_res.returns.to_csv(args.output / "returns_v76.csv", index_label="trading_date")

    add_field, _ = compute_add_lite_field(data.realized_pnl, ADDLiteV78Config(lam=0.6))
    v78_add_w = apply_asset_deformation(base_w, add_field, 0.6)
    v78_add_res = evaluate(v78_add_w, data.forward_pnl)
    v78_add_w.to_csv(args.output / "weights_v78_add.csv", index_label="trading_date")
    v78_add_res.returns.to_csv(args.output / "returns_v78_add.csv", index_label="trading_date")

    book_add = compute_book_add(base_w, add_field)
    d_rot, rot_detail = compute_rotation(book_add, RotationConfig())
    defensive_w = weights["defensive"].reindex(base_w.index).fillna(0.0)
    v79_w = apply_rotation(v78_add_w, defensive_w, d_rot)
    v79_res = evaluate(v79_w, data.forward_pnl)
    v79_w.to_csv(args.output / "weights_v79.csv", index_label="trading_date")
    v79_res.returns.to_csv(args.output / "returns_v79.csv", index_label="trading_date")

    # --- Candidate sleeves: evaluate two and let the registry decide -------
    # A rejected contrast (mean-reversion) and the V7.10 sleeve
    # (fixed-income crisis-trend) — the registry admits only what clears
    # every gate.
    gate_cfg = GateConfig(n_trials=args.n_trials)
    registry = SleeveRegistry()
    sleeve_panels: dict[str, pd.DataFrame] = {}
    sleeve_returns: dict[str, pd.Series] = {}

    # Contrast: short-horizon cross-sectional reversal — no edge here.
    mr_w = compute_weights(data, make_mean_reversion_signal(lookback=10), cfg)
    mr_net = cost_adjust(evaluate(mr_w, data.forward_pnl).returns, mr_w, cost_bps=5.0)
    sleeve_panels["xs_reversal_10d"] = mr_w
    sleeve_returns["xs_reversal_10d"] = mr_net
    mr_w.to_csv(args.output / "weights_mr_sleeve.csv", index_label="trading_date")
    mr_net.to_csv(args.output / "returns_mr_sleeve.csv", index_label="trading_date")
    registry.register(evaluate_sleeve(
        SleeveSpec(
            strategy_id="xs_reversal_10d", sleeve_type="mean_reversion",
            horizon="short",
            economic_mechanism="Short-horizon cross-sectional overreaction.",
            regime_affinity=["choppy / range-bound"],
            failure_modes=["strong persistent trends"],
            polyagora_block="D"),
        mr_net, v79_res.returns, gate_cfg))

    # V7.10 sleeve: fixed-income crisis-trend on the bond futures. 12-month
    # time-series trend on {TN, FGBL} — goes short bonds when bonds trend
    # down, so it earns in the 2022 rate shock. Low-turnover; a flat
    # zone-permission table — a crisis-alpha sleeve stays on under stress.
    bt_assets = ["TN", "FGBL"]
    bt_w = compute_weights(data, make_trend_sleeve_signal(bt_assets, 252, 21), cfg)
    bt_net = cost_adjust(evaluate(bt_w, data.forward_pnl).returns, bt_w, cost_bps=2.0)
    sleeve_panels["bond_trend"] = bt_w
    sleeve_returns["bond_trend"] = bt_net
    bt_w.to_csv(args.output / "weights_bond_trend.csv", index_label="trading_date")
    bt_net.to_csv(args.output / "returns_bond_trend.csv", index_label="trading_date")
    bt_spec = SleeveSpec(
        strategy_id="bond_trend_12m", sleeve_type="crisis_trend", horizon="slow",
        economic_mechanism=(
            "Time-series trend on government-bond futures (TN, FGBL). Long "
            "bonds in flight-to-quality rallies (2008, COVID), short bonds in "
            "persistent rate shocks (2022) — crisis alpha a long-only "
            "defensive manifold cannot capture."),
        regime_affinity=["rate shock / inflation", "flight-to-quality"],
        failure_modes=["whipsaw / rangebound rates"],
        polyagora_block="D",
        # Flat permission: a crisis-alpha sleeve must stay on in stress.
        zone_permission={"1-Stable": 1.0, "2-Transition": 1.0,
                         "3-Stress": 1.0, "4-Rupture": 1.0})
    registry.register(evaluate_sleeve(bt_spec, bt_net, v79_res.returns, gate_cfg))
    print()
    print(registry.report())

    # --- v7.10: fold in the best ADMITTED sleeve, else fall back to v79 -----
    admitted = sorted(registry.admitted,
                      key=lambda e: -e.contribution.get("blend_sharpe", 0))
    if admitted:
        best = admitted[0]
        s_t = zone_scaled_weight(best.base_weight,
                                 rot_detail["zone"],
                                 best.spec.zone_permission)
        v710_w = blend_sleeve(v79_w, sleeve_panels[
            "bond_trend" if best.spec.sleeve_type == "crisis_trend"
            else best.spec.strategy_id], s_t)
        sleeve_note = (f"sleeve {best.spec.strategy_id} ADMITTED — "
                       f"base_weight {best.base_weight:.3f}, "
                       f"zone-scaled mean {s_t.mean():.3f}")
    else:
        v710_w = v79_w.copy()
        s_t = pd.Series(0.0, index=v79_w.index)
        sleeve_note = ("no sleeve cleared the registry gates — "
                       "v7.10 falls back to v79")
    v710_res = evaluate(v710_w, data.forward_pnl)
    v710_w.to_csv(args.output / "weights_v710.csv", index_label="trading_date")
    v710_res.returns.to_csv(args.output / "returns_v710.csv", index_label="trading_date")
    print(f"\n[v7.10] {sleeve_note}")

    # --- References ---------------------------------------------------------
    ew_res = evaluate(compute_weights(data, equal_weight_signal, cfg), data.forward_pnl)
    sp = ROOT / "polyagora_v75_outputs" / "returns_sp500.csv"
    sp500 = (pd.read_csv(sp, parse_dates=["trading_date"]).set_index("trading_date").iloc[:, 0]
             if sp.exists() else None)

    series = [
        ("v76a (base)",  base_res.returns, base_res.equity),
        ("v78-ADD",      v78_add_res.returns, v78_add_res.equity),
        ("v79",          v79_res.returns, v79_res.equity),
        ("v7.10",        v710_res.returns, v710_res.equity),
        ("bond-trend",   bt_net, (1 + bt_net.fillna(0)).cumprod()),
        ("MR-sleeve",    mr_net, (1 + mr_net.fillna(0)).cumprod()),
        ("momentum_12_1", returns["momentum_12_1"], (1 + returns["momentum_12_1"]).cumprod()),
        ("defensive",    returns["defensive"], (1 + returns["defensive"]).cumprod()),
        ("equal_weight", ew_res.returns, ew_res.equity),
    ]
    if sp500 is not None:
        series.append(("sp500", sp500, (1 + sp500.fillna(0)).cumprod()))

    rows = [_summary(n, r, e) for n, r, e in series]
    cols = ["Series", "Total return", "CAGR", "Ann. vol",
            "Sharpe", "Sortino", "Calmar", "Max drawdown"]
    df = pd.DataFrame(rows)[cols]
    df.to_csv(args.output / "summary_v710_check.csv", index=False)
    print()
    print("=== Headline (full sample) ===")
    print(df.to_string(index=False,
                       formatters={c: "{:.4f}".format for c in cols if c != "Series"}))

    # --- Regime windows -----------------------------------------------------
    REG = [("GFC crash", "2008-04-01", "2009-03-31"),
           ("GFC recov", "2009-04-01", "2011-12-31"),
           ("QE bull",   "2012-01-01", "2019-12-31"),
           ("COVID",     "2020-02-15", "2020-12-31"),
           ("Reflation", "2021-01-01", "2021-12-31"),
           ("Rate 22",   "2022-01-01", "2022-12-31"),
           ("Recent",    "2023-01-01", "2026-04-29")]
    crows = []
    for n, r, e in series:
        for label, a, b in REG:
            crows.append({"series": n, **_crisis(r, label, a, b)})
    cdf = pd.DataFrame(crows)
    cdf.to_csv(args.output / "crisis_v710_check.csv", index=False)
    print()
    print("=== Regime-window Sharpe ===")
    piv = cdf.pivot(index="series", columns="window", values="sharpe")
    piv = piv.reindex([n for n, _, _ in series])[[r[0] for r in REG]]
    print(piv.to_string(float_format=lambda x: f"{x:.2f}"))

    # --- Correlation governance (multi-sleeve spec §10) ---------------------
    core = {"v76a": base_res.returns, "v78-ADD": v78_add_res.returns,
            "v79": v79_res.returns, "momentum": returns["momentum_12_1"],
            "defensive": returns["defensive"], "bond-trend": bt_net}
    cpanel = pd.DataFrame(core).dropna()
    cm = cpanel.corr()
    cm.to_csv(args.output / "corr_v710_check.csv")
    off = cm.where(~np.eye(len(cm), dtype=bool))
    avg_all = float(np.nanmean(off.values))
    off_nobt = cm.drop(index="bond-trend", columns="bond-trend")
    off_nobt = off_nobt.where(~np.eye(len(off_nobt), dtype=bool))
    avg_nobt = float(np.nanmean(off_nobt.values))
    print()
    print("=== Correlation governance (spec §10 — target avg < 0.35) ===")
    print(cm.to_string(float_format=lambda x: f"{x:.2f}"))
    print(f"  avg pairwise correlation: without bond-trend sleeve = {avg_nobt:.3f}  "
          f"with it = {avg_all:.3f}")
    print(f"  bond-trend correlation to the v79 book = {cm.loc['bond-trend', 'v79']:.3f}")


if __name__ == "__main__":
    main()
