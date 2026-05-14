"""
V7.6α minimum-viable check.

Runs the three manifolds (V7 = v74d_q, Momentum = momentum_12_1,
Defensive = polyagora_v76_engine.defensive_signal), constructs the meta
blend, and prints a summary comparing:

    - static M1 (v74d_q)
    - static M2 (momentum_12_1)
    - static M3 (defensive)
    - v76 meta-steered blend
    - equal-weight (sanity baseline)

This is intentionally NOT wired into the main runner — we want to know
"does meta-steering produce a real improvement" before investing in the
dashboard / MRTP / admissibility overlays.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from polyagora_v63_partner_engine import (
    CASH,
    EngineConfig,
    UNIVERSE,
    compute_weights,
    equal_weight_signal,
    evaluate,
    load_partner_xlsx,
    momentum_signal,
    summary_row,
)
from polyagora_v73_engine import QPolygonConfig
from polyagora_v75_engine import V75DriverConfig, make_v75_q_signal
from polyagora_v76_engine import (
    AdmissibilityConfig,
    MetaConfig,
    MrtpConfig,
    cash_signal,
    compute_mrtp_score,
    compute_regime_admissibility,
    defensive_signal,
    meta_blend,
    meta_blend_gamma,
    meta_blend_mrtp,
)


ROOT = Path(__file__).resolve().parent
DEFAULT_INPUT = ROOT / "Agur" / "baseline_pnl_partner_delivery.xlsx"
DEFAULT_MARKET = ROOT / "market_data" / "market_yahoo_vix_spy_hyg_tlt_gld_cper.csv"
DEFAULT_OUTPUT = ROOT / "polyagora_v76_outputs"


def _summary(name: str, rets: pd.Series, equity: pd.Series) -> dict:
    r = summary_row(name, rets)
    dd = equity / equity.cummax() - 1.0
    down = rets[rets < 0]
    sortino = (
        (rets.mean() * 252) / (down.std() * np.sqrt(252))
        if len(down) and down.std() > 0
        else float("nan")
    )
    cagr = r.get("CAGR", float("nan"))
    max_dd = abs(r.get("Max drawdown", float("nan")))
    calmar = cagr / max_dd if max_dd > 1e-9 else float("nan")
    r["Sortino"] = sortino
    r["Calmar"] = calmar
    return r


def _crisis_window(returns: pd.Series, label: str, start: str, end: str) -> dict:
    sl = returns.loc[start:end]
    if sl.empty:
        return {"window": label, "n": 0}
    eq = (1 + sl).cumprod()
    dd = (eq / eq.cummax() - 1.0).min()
    return {
        "window": label,
        "n": len(sl),
        "return": float(eq.iloc[-1] - 1.0),
        "vol_ann": float(sl.std() * np.sqrt(252)),
        "sharpe": float((sl.mean() * 252) / (sl.std() * np.sqrt(252))) if sl.std() > 0 else float("nan"),
        "max_dd": float(dd),
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    p.add_argument("--market", type=Path, default=DEFAULT_MARKET)
    p.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    p.add_argument("--lookback", type=int, default=63)
    p.add_argument("--lam", type=float, default=2.0)
    p.add_argument("--halflife", type=float, default=10.0)
    p.add_argument("--floor", type=float, default=0.15)
    p.add_argument("--no-cash", dest="with_cash", action="store_false",
                   help="Drop the CASH manifold (3-manifold v76α₁ behavior)")
    p.set_defaults(with_cash=True)
    args = p.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)
    data = load_partner_xlsx(args.input)
    cfg = EngineConfig()
    market = pd.read_csv(args.market, parse_dates=["date"]).set_index("date")

    # --- Build the three manifolds (frozen, no further tuning) ---------------
    m1_sig = make_v75_q_signal(
        market, data.realized_pnl,
        drivers=V75DriverConfig(momentum_sensitivity=0.0),
        q_cfg=QPolygonConfig(),
        include_mom_eigen=False,
        top_k=2, tau=2.0, lam=0.5,
    )
    manifolds: dict[str, object] = {
        "v74d_q":        m1_sig,
        "momentum_12_1": momentum_signal,
        "defensive":     defensive_signal,
    }
    if args.with_cash:
        manifolds["cash"] = cash_signal

    print(f"[run] data: {data.realized_pnl.index.min().date()} → "
          f"{data.realized_pnl.index.max().date()}  ({len(data.realized_pnl)} rows)")
    print(f"[run] meta cfg: lookback={args.lookback}  lam={args.lam}  "
          f"halflife={args.halflife}  floor={args.floor}")

    weights: dict[str, pd.DataFrame] = {}
    returns: dict[str, pd.Series] = {}
    equities: dict[str, pd.Series] = {}
    v74d_q_diag: pd.DataFrame | None = None
    for name, sig in manifolds.items():
        w = compute_weights(data, sig, cfg)
        res = evaluate(w, data.forward_pnl)
        weights[name] = w
        returns[name] = res.returns
        equities[name] = res.equity
        w.to_csv(args.output / f"weights_{name}.csv", index_label="trading_date")
        res.returns.to_csv(args.output / f"returns_{name}.csv", index_label="trading_date")
        if name == "v74d_q" and hasattr(sig, "diagnostics_df"):
            v74d_q_diag = sig.diagnostics_df()
            v74d_q_diag.to_csv(args.output / "diagnostics_v74d_q.csv", index_label="trading_date")
        print(f"  [ok] {name}: gross_mean={float(w[list(UNIVERSE)].abs().sum(axis=1).mean()):.3f}  "
              f"cash_mean={float(w[CASH].mean()):.3f}")

    # --- Equal-weight reference ---------------------------------------------
    ew_w = compute_weights(data, equal_weight_signal, cfg)
    ew_res = evaluate(ew_w, data.forward_pnl)

    # --- v76α: rolling-Sharpe-only meta blend --------------------------------
    meta_cfg = MetaConfig(
        lookback=args.lookback, lam=args.lam,
        ewm_halflife=args.halflife, min_floor=args.floor,
    )
    v76_w, alloc = meta_blend(weights, returns, meta_cfg)
    v76_w = v76_w.reindex(data.forward_pnl.index).fillna(0.0)
    v76_res = evaluate(v76_w, data.forward_pnl)
    v76_w.to_csv(args.output / "weights_v76.csv", index_label="trading_date")
    v76_res.returns.to_csv(args.output / "returns_v76.csv", index_label="trading_date")
    alloc.to_csv(args.output / "manifold_alloc_v76.csv", index_label="trading_date")

    # --- v76β: MRTP-lite blend (admissibility from v75 regime coords) --------
    v76b_res = None
    alloc_b = None
    v76g_res = None
    alloc_g = None
    v76g_full_res = None
    alloc_g_full = None
    if v74d_q_diag is not None:
        # Floor on W to 0 since A_i provides the natural floor.
        meta_cfg_b = MetaConfig(
            lookback=args.lookback, lam=args.lam,
            ewm_halflife=args.halflife, min_floor=0.0,
        )
        A = compute_regime_admissibility(v74d_q_diag, returns, meta_cfg_b)
        v76b_w, alloc_b = meta_blend_mrtp(weights, returns, A, meta_cfg_b)
        v76b_w = v76b_w.reindex(data.forward_pnl.index).fillna(0.0)
        v76b_res = evaluate(v76b_w, data.forward_pnl)
        v76b_w.to_csv(args.output / "weights_v76b.csv", index_label="trading_date")
        v76b_res.returns.to_csv(args.output / "returns_v76b.csv", index_label="trading_date")
        alloc_b.to_csv(args.output / "manifold_alloc_v76b.csv", index_label="trading_date")
        A.to_csv(args.output / "admissibility_v76b.csv", index_label="trading_date")
        print(f"  [ok] v76β (MRTP-lite): diag rows={len(v74d_q_diag)} adm rows={len(A)}")

        # --- v76γ: full MRTP composite (S + F − D), uniform A_i = 1 ---------
        mrtp_cfg = MrtpConfig()
        MRTP = compute_mrtp_score(v74d_q_diag, returns, mrtp_cfg)
        MRTP.to_csv(args.output / "mrtp_v76g.csv", index_label="trading_date")
        A_uniform = pd.DataFrame(1.0, index=MRTP.index, columns=MRTP.columns)
        meta_cfg_g = MetaConfig(
            lookback=args.lookback, lam=args.lam,
            ewm_halflife=args.halflife, min_floor=0.05,
        )
        v76g_w, alloc_g = meta_blend_gamma(weights, returns, A_uniform, MRTP, meta_cfg_g)
        v76g_w = v76g_w.reindex(data.forward_pnl.index).fillna(0.0)
        v76g_res = evaluate(v76g_w, data.forward_pnl)
        v76g_w.to_csv(args.output / "weights_v76g.csv", index_label="trading_date")
        v76g_res.returns.to_csv(args.output / "returns_v76g.csv", index_label="trading_date")
        alloc_g.to_csv(args.output / "manifold_alloc_v76g.csv", index_label="trading_date")
        print(f"  [ok] v76γ (MRTP S+F-D, uniform A): MRTP rows={len(MRTP)}")

        # --- v76γ-full: MRTP composite + regime A_i ------------------------
        v76gf_w, alloc_g_full = meta_blend_gamma(weights, returns, A, MRTP, meta_cfg_g)
        v76gf_w = v76gf_w.reindex(data.forward_pnl.index).fillna(0.0)
        v76g_full_res = evaluate(v76gf_w, data.forward_pnl)
        v76gf_w.to_csv(args.output / "weights_v76g_full.csv", index_label="trading_date")
        v76g_full_res.returns.to_csv(args.output / "returns_v76g_full.csv", index_label="trading_date")
        alloc_g_full.to_csv(args.output / "manifold_alloc_v76g_full.csv", index_label="trading_date")
        print(f"  [ok] v76γ-full (MRTP S+F-D + regime A)")
    else:
        print("  [warn] v76β/γ skipped — no diagnostics from v74d_q")

    # --- Headline summary ----------------------------------------------------
    rows = []
    for name in list(manifolds):
        rows.append(_summary(name, returns[name], equities[name]))
    rows.append(_summary("equal_weight", ew_res.returns, ew_res.equity))

    # Naive 1/N fixed blend of the manifolds — diversification-only baseline.
    cols_union = sorted(set().union(*[w.columns for w in weights.values()]))
    w_naive = sum(w.reindex(columns=cols_union).fillna(0.0) for w in weights.values()) / len(weights)
    w_naive = w_naive.reindex(data.forward_pnl.index).fillna(0.0)
    naive_res = evaluate(w_naive, data.forward_pnl)
    rows.append(_summary(f"naive_1_over_{len(weights)}", naive_res.returns, naive_res.equity))

    rows.append(_summary("v76α (Sharpe-only)", v76_res.returns, v76_res.equity))
    if v76b_res is not None:
        rows.append(_summary("v76β (MRTP-lite)", v76b_res.returns, v76b_res.equity))
    if v76g_res is not None:
        rows.append(_summary("v76γ (S+F-D, A=1)", v76g_res.returns, v76g_res.equity))
    if v76g_full_res is not None:
        rows.append(_summary("v76γ-full (S+F-D + A)", v76g_full_res.returns, v76g_full_res.equity))

    cols = ["Series", "Total return", "CAGR", "Ann. vol",
            "Sharpe", "Sortino", "Calmar", "Max drawdown"]
    df = pd.DataFrame(rows)[cols]
    df.to_csv(args.output / "summary_v76_check.csv", index=False)
    print()
    print("=== Headline (full sample) ===")
    print(df.to_string(index=False,
                       formatters={c: "{:.4f}".format for c in cols if c != "Series"}))

    # --- Crisis windows ------------------------------------------------------
    windows = [
        ("2008 GFC",        "2008-04-01", "2009-06-30"),
        ("COVID",           "2020-02-15", "2020-12-31"),
        ("2022 rates",      "2022-01-01", "2022-12-31"),
        ("Last 3 years",    "2023-01-01", "2026-04-29"),
    ]
    print()
    print("=== Crisis & recent windows ===")
    crisis_rows = []
    crisis_series = [(n, returns[n]) for n in manifolds] + [
        (f"naive_1_over_{len(weights)}", naive_res.returns),
        ("v76α (Sharpe-only)", v76_res.returns),
    ]
    if v76b_res is not None:
        crisis_series.append(("v76β (MRTP-lite)", v76b_res.returns))
    if v76g_res is not None:
        crisis_series.append(("v76γ (S+F-D, A=1)", v76g_res.returns))
    if v76g_full_res is not None:
        crisis_series.append(("v76γ-full", v76g_full_res.returns))
    for name, rets in crisis_series:
        for w in windows:
            row = {"series": name, **_crisis_window(rets, *w)}
            crisis_rows.append(row)
    cdf = pd.DataFrame(crisis_rows)
    cdf.to_csv(args.output / "crisis_v76_check.csv", index=False)
    print(cdf.to_string(index=False))

    # --- Manifold allocation stats ------------------------------------------
    def _alloc_summary(name: str, A: pd.DataFrame) -> None:
        print()
        print(f"=== W_i (time-averages) — {name} ===")
        print(A.mean().to_frame("mean").join(
            A.std().to_frame("std")).join(
            A.min().to_frame("min")).join(
            A.max().to_frame("max")
        ).to_string(formatters={c: "{:.3f}".format for c in ["mean", "std", "min", "max"]}))
        big_moves = (A.diff().abs() > 0.05).sum()
        print(f"  days with |ΔW_i|>5pp:  {dict(big_moves)}")

    _alloc_summary("v76α (Sharpe-only)", alloc)
    if alloc_b is not None:
        _alloc_summary("v76β (MRTP-lite)", alloc_b)
    if alloc_g is not None:
        _alloc_summary("v76γ (S+F-D, A=1)", alloc_g)
    if alloc_g_full is not None:
        _alloc_summary("v76γ-full", alloc_g_full)

    # Temporal split — does the steering advantage hold in both halves?
    print()
    print("=== Temporal split: Sharpe in each window ===")
    splits = [
        ("2008-04 → 2016-12 (first half)",  "2008-04-01", "2016-12-31"),
        ("2017-01 → 2026-04 (second half)", "2017-01-01", "2026-04-29"),
        ("2008-04 → 2019-12 (pre-COVID)",   "2008-04-01", "2019-12-31"),
        ("2020-01 → 2026-04 (COVID-on)",    "2020-01-01", "2026-04-29"),
    ]
    series_for_split = [
        ("naive_1_over_4", naive_res.returns),
        ("v76α", v76_res.returns),
    ]
    if v76b_res is not None:
        series_for_split.append(("v76β", v76b_res.returns))
    if v76g_res is not None:
        series_for_split.append(("v76γ", v76g_res.returns))
    if v76g_full_res is not None:
        series_for_split.append(("v76γf", v76g_full_res.returns))
    split_rows = []
    for lbl, a, b in splits:
        row = {"window": lbl}
        for nm, r in series_for_split:
            sl = r.loc[a:b]
            if len(sl) and sl.std() > 0:
                sh = float((sl.mean() * 252) / (sl.std() * np.sqrt(252)))
            else:
                sh = float("nan")
            eq = (1 + sl).cumprod()
            dd = float((eq / eq.cummax() - 1.0).min()) if len(sl) else 0.0
            row[f"{nm}_sharpe"] = sh
            row[f"{nm}_maxdd"] = dd
        split_rows.append(row)
    sdf = pd.DataFrame(split_rows)
    print(sdf.to_string(index=False,
        formatters={c: "{:.3f}".format for c in sdf.columns if c != "window"}))


if __name__ == "__main__":
    main()
