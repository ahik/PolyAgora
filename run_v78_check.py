"""
V7.8 check — asset-level ADD-lite + conditional soft Kelly.

Builds the frozen V7.6α blend as the governance base, then compares the
V7.7 and V7.8 overlay treatments side-by-side:

    v76α            frozen meta-steered base (no overlay)
    v77-ADD         V7.7 portfolio-level ADD-lite  (the serious V7.7 candidate)
    v78-ADD         V7.8 asset-level ADD-lite      (spec §9 continuous deformation)
    v78             V7.8 asset-level ADD-lite + conditional soft Kelly (§12)
    naive 1/4       diversification-only reference

Also reports the Dov benchmark panel (`docs/Dov Benchmarks .pdf`):
Sharpe / Sortino / Calmar / MaxDD plus correlation to SPY / TLT / HYG,
flagged against the "first CTO test" targets (Sharpe > 1.2, Sortino >
1.5, Calmar > 1.0, MaxDD < 8%, Corr-to-SPY < 0.35). The focused V7.8
increment is a governance/risk refinement — the Dov bar (all three
ratios > 1.5) needs the Phase-2 alpha sleeves, not this version.

Outputs land in `polyagora_v78_outputs/`:
    weights_/returns_ {v76, v77_add, v78_add, v78}
    add_field_v78.csv       — asset-level ADD-lite field
    kelly_v78.csv           — book_add, baseline, K_t
    summary_v78_check.csv / crisis_v78_check.csv / dov_v78_check.csv
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
from polyagora_v77_engine import ADDLiteConfig, add_lite_scale, apply_gross_scale, compute_add_lite
from polyagora_v78_engine import (
    ADDLiteV78Config,
    KellyV78Config,
    apply_asset_deformation,
    apply_kelly_gate,
    compute_add_lite_field,
    compute_book_add,
    compute_conditional_kelly,
)


ROOT = Path(__file__).resolve().parent
DEFAULT_INPUT = ROOT / "Agur" / "baseline_pnl_partner_delivery.xlsx"
DEFAULT_MARKET = ROOT / "market_data" / "market_yahoo_vix_spy_hyg_tlt_gld_cper.csv"
DEFAULT_OUTPUT = ROOT / "polyagora_v78_outputs"


def _summary(name: str, rets: pd.Series, equity: pd.Series) -> dict:
    r = summary_row(name, rets)
    down = rets[rets < 0]
    sortino = (
        (rets.mean() * 252) / (down.std() * np.sqrt(252))
        if len(down) and down.std() > 0 else float("nan")
    )
    cagr = r.get("CAGR", float("nan"))
    max_dd = abs(r.get("Max drawdown", float("nan")))
    r["Sortino"] = sortino
    r["Calmar"] = cagr / max_dd if max_dd > 1e-9 else float("nan")
    return r


def _crisis_window(returns: pd.Series, label: str, start: str, end: str) -> dict:
    sl = returns.loc[start:end]
    if sl.empty:
        return {"window": label, "n": 0}
    eq = (1 + sl).cumprod()
    return {
        "window": label, "n": len(sl),
        "return": float(eq.iloc[-1] - 1.0),
        "vol_ann": float(sl.std() * np.sqrt(252)),
        "sharpe": float((sl.mean() * 252) / (sl.std() * np.sqrt(252)))
        if sl.std() > 0 else float("nan"),
        "max_dd": float((eq / eq.cummax() - 1.0).min()),
    }


def _corr_to(rets: pd.Series, bench_ret: pd.Series) -> float:
    j = pd.concat([rets, bench_ret], axis=1, join="inner").dropna()
    if len(j) < 30:
        return float("nan")
    return float(j.iloc[:, 0].corr(j.iloc[:, 1]))


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    p.add_argument("--market", type=Path, default=DEFAULT_MARKET)
    p.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    p.add_argument("--lookback", type=int, default=63)
    p.add_argument("--lam", type=float, default=2.0)
    p.add_argument("--halflife", type=float, default=10.0)
    p.add_argument("--floor", type=float, default=0.15)
    p.add_argument("--add-lam", type=float, default=0.6,
                   help="λ in the asset-level deformation w' = w·(1-λ·ADD_i)")
    p.add_argument("--kelly-gamma", type=float, default=0.35,
                   help="γ in the conditional Kelly gate (spec band 0.2-0.5)")
    args = p.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)
    data = load_partner_xlsx(args.input)
    cfg = EngineConfig()
    market = pd.read_csv(args.market, parse_dates=["date"]).set_index("date")

    # --- Four V7.6 manifolds (frozen) ---------------------------------------
    m1_sig = make_v75_q_signal(
        market, data.realized_pnl,
        drivers=V75DriverConfig(momentum_sensitivity=0.0),
        q_cfg=QPolygonConfig(),
        include_mom_eigen=False, top_k=2, tau=2.0, lam=0.5,
    )
    manifolds = {
        "v74d_q": m1_sig, "momentum_12_1": momentum_signal,
        "defensive": defensive_signal, "cash": cash_signal,
    }
    print(f"[run] data: {data.realized_pnl.index.min().date()} → "
          f"{data.realized_pnl.index.max().date()}  ({len(data.realized_pnl)} rows)")

    weights, returns = {}, {}
    for name, sig in manifolds.items():
        w = compute_weights(data, sig, cfg)
        weights[name] = w
        returns[name] = evaluate(w, data.forward_pnl).returns

    # --- V7.6α governance base ----------------------------------------------
    meta_cfg = MetaConfig(lookback=args.lookback, lam=args.lam,
                          ewm_halflife=args.halflife, min_floor=args.floor)
    base_w, _ = meta_blend(weights, returns, meta_cfg)
    base_w = base_w.reindex(data.forward_pnl.index).fillna(0.0)
    base_res = evaluate(base_w, data.forward_pnl)
    base_w.to_csv(args.output / "weights_v76.csv", index_label="trading_date")
    base_res.returns.to_csv(args.output / "returns_v76.csv", index_label="trading_date")

    # --- V7.7 portfolio-level ADD-lite (reference, the serious V7.7 line) ----
    v77_add_cfg = ADDLiteConfig(add_sensitivity=args.add_lam)
    add_lite_v77, _ = compute_add_lite(data.realized_pnl, v77_add_cfg)
    v77_add_w = apply_gross_scale(base_w, add_lite_scale(add_lite_v77, v77_add_cfg))
    v77_add_res = evaluate(v77_add_w, data.forward_pnl)
    v77_add_w.to_csv(args.output / "weights_v77_add.csv", index_label="trading_date")
    v77_add_res.returns.to_csv(args.output / "returns_v77_add.csv", index_label="trading_date")

    # --- V7.8 asset-level ADD-lite (spec §9) --------------------------------
    add_cfg = ADDLiteV78Config(lam=args.add_lam)
    add_field, _segments = compute_add_lite_field(data.realized_pnl, add_cfg)
    add_field.to_csv(args.output / "add_field_v78.csv", index_label="trading_date")
    v78_add_w = apply_asset_deformation(base_w, add_field, add_cfg.lam)
    v78_add_res = evaluate(v78_add_w, data.forward_pnl)
    v78_add_w.to_csv(args.output / "weights_v78_add.csv", index_label="trading_date")
    v78_add_res.returns.to_csv(args.output / "returns_v78_add.csv", index_label="trading_date")

    # --- V7.8 conditional soft Kelly (spec §12) -----------------------------
    kelly_cfg = KellyV78Config(gamma=args.kelly_gamma)
    book_add = compute_book_add(base_w, add_field)
    K, kelly_detail = compute_conditional_kelly(book_add, kelly_cfg)
    kelly_detail.to_csv(args.output / "kelly_v78.csv", index_label="trading_date")
    v78_w = apply_kelly_gate(v78_add_w, K)
    v78_res = evaluate(v78_w, data.forward_pnl)
    v78_w.to_csv(args.output / "weights_v78.csv", index_label="trading_date")
    v78_res.returns.to_csv(args.output / "returns_v78.csv", index_label="trading_date")

    # --- Naive 1/4 reference -------------------------------------------------
    cols_union = sorted(set().union(*[w.columns for w in weights.values()]))
    w_naive = sum(w.reindex(columns=cols_union).fillna(0.0)
                  for w in weights.values()) / len(weights)
    naive_res = evaluate(w_naive.reindex(data.forward_pnl.index).fillna(0.0),
                         data.forward_pnl)

    # --- Overlay-field diagnostics ------------------------------------------
    print()
    print("=== ADD-lite asset-level field ===")
    print(f"  field mean={add_field.values.mean():.4f}  "
          f"per-asset means: " + ", ".join(
              f"{a}={add_field[a].mean():.2f}" for a in UNIVERSE[:7]) + " …")
    print(f"  book_add: mean={book_add.mean():.4f}  "
          f"p50={book_add.median():.4f}  p95={book_add.quantile(0.95):.4f}")
    print("=== Conditional Kelly gate K_t ===")
    print(f"  K: mean={K.mean():.4f}  p05={K.quantile(0.05):.4f}  "
          f"p50={K.median():.4f}  min={K.min():.4f}  "
          f"(share inert K=1: {float((K >= 0.999).mean()):.1%})")
    base_gross = base_w[list(UNIVERSE)].abs().sum(axis=1)
    v78_gross = v78_w[list(UNIVERSE)].abs().sum(axis=1)
    print(f"  mean real gross: v76α={base_gross.mean():.3f}  v78={v78_gross.mean():.3f}")

    series = [
        ("v76α (base)", base_res),
        ("v77-ADD",     v77_add_res),
        ("v78-ADD",     v78_add_res),
        ("v78 (ADD+Kelly)", v78_res),
        ("naive_1_over_4", naive_res),
        ("equal_weight", evaluate(compute_weights(data, equal_weight_signal, cfg),
                                  data.forward_pnl)),
    ]

    # --- Headline summary ----------------------------------------------------
    rows = [_summary(n, res.returns, res.equity) for n, res in series]
    cols = ["Series", "Total return", "CAGR", "Ann. vol",
            "Sharpe", "Sortino", "Calmar", "Max drawdown"]
    df = pd.DataFrame(rows)[cols]
    df.to_csv(args.output / "summary_v78_check.csv", index=False)
    print()
    print("=== Headline (full sample) ===")
    print(df.to_string(index=False,
                       formatters={c: "{:.4f}".format for c in cols if c != "Series"}))

    # --- Dov benchmark panel -------------------------------------------------
    spy = market["SPY"].pct_change()
    tlt = market["TLT"].pct_change()
    hyg = market["HYG"].pct_change()
    dov_rows = []
    for name, res in series:
        s = _summary(name, res.returns, res.equity)
        dov_rows.append({
            "Series": name,
            "Sharpe": s.get("Sharpe", float("nan")),
            "Sortino": s.get("Sortino", float("nan")),
            "Calmar": s.get("Calmar", float("nan")),
            "MaxDD": s.get("Max drawdown", float("nan")),
            "Corr_SPY": _corr_to(res.returns, spy),
            "Corr_TLT": _corr_to(res.returns, tlt),
            "Corr_HYG": _corr_to(res.returns, hyg),
        })
    dov = pd.DataFrame(dov_rows)
    dov.to_csv(args.output / "dov_v78_check.csv", index=False)
    print()
    print("=== Dov benchmark panel  (first-test targets: "
          "Sharpe>1.2 Sortino>1.5 Calmar>1.0 MaxDD<8% Corr_SPY<0.35) ===")
    print(dov.to_string(index=False, formatters={
        c: "{:.3f}".format for c in dov.columns if c != "Series"}))

    # --- Crisis windows ------------------------------------------------------
    windows = [
        ("2008 GFC",     "2008-04-01", "2009-06-30"),
        ("COVID",        "2020-02-15", "2020-12-31"),
        ("2022 rates",   "2022-01-01", "2022-12-31"),
        ("Last 3 years", "2023-01-01", "2026-04-29"),
    ]
    crisis_rows = []
    for name, res in series:
        for w in windows:
            crisis_rows.append({"series": name, **_crisis_window(res.returns, *w)})
    cdf = pd.DataFrame(crisis_rows)
    cdf.to_csv(args.output / "crisis_v78_check.csv", index=False)
    print()
    print("=== Crisis & recent windows ===")
    print(cdf.to_string(index=False))


if __name__ == "__main__":
    main()
