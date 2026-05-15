"""
V7.7 check — ADD-lite + Kelly overlays on the V7.6α meta-steered blend.

Builds the frozen V7.6α blend as the base, then applies the two V7.7
overlays — separately and combined — and prints a side-by-side
comparison against the v76α baseline (the `Lite-ADD in Flow` §17
"forward shadow deployment" protocol: run baseline vs baseline+overlay
side-by-side, track steering stability / crisis handling / false alarms).

Series compared
    v76α            frozen meta-steered base (no overlay)
    v77-ADD         v76α × ADD-lite topology deformation
    v77-Kelly       v76α × Kelly capital-intensity sizing
    v77             v76α × ADD-lite × Kelly (full V7.7)
    naive 1/4       diversification-only reference

Outputs land in `polyagora_v77_outputs/`:
    weights_/returns_ {v76, v77_add, v77_kelly, v77}
    add_lite_v77.csv        — 6 components + raw/smoothed composite
    governance_phi_v77.csv  — 5 φ sub-gates + Φ
    kelly_v77.csv           — μ, σ², f*, Φ, f_kelly
    summary_v77_check.csv / crisis_v77_check.csv
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
from polyagora_v76_engine import MetaConfig, cash_signal, defensive_signal, meta_blend
from polyagora_v77_engine import (
    ADDLiteConfig,
    KellyConfig,
    add_lite_scale,
    apply_gross_scale,
    compute_add_lite,
    compute_governance_phi,
    compute_kelly_fraction,
)


ROOT = Path(__file__).resolve().parent
DEFAULT_INPUT = ROOT / "Agur" / "baseline_pnl_partner_delivery.xlsx"
DEFAULT_MARKET = ROOT / "market_data" / "market_yahoo_vix_spy_hyg_tlt_gld_cper.csv"
DEFAULT_OUTPUT = ROOT / "polyagora_v77_outputs"


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
    dd = (eq / eq.cummax() - 1.0).min()
    return {
        "window": label,
        "n": len(sl),
        "return": float(eq.iloc[-1] - 1.0),
        "vol_ann": float(sl.std() * np.sqrt(252)),
        "sharpe": float((sl.mean() * 252) / (sl.std() * np.sqrt(252)))
        if sl.std() > 0 else float("nan"),
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
    p.add_argument("--add-sensitivity", type=float, default=0.6,
                   help="k in ADD-lite gross scale = 1 - k·ADD_lite")
    p.add_argument("--kelly-gain", type=float, default=1.0,
                   help="λ-equivalent scaling on the Kelly μ/σ² term")
    p.add_argument("--kelly-mode-mult", type=float, default=0.25,
                   help="fractional-Kelly multiplier (0.25 = Mode A Conservative)")
    args = p.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)
    data = load_partner_xlsx(args.input)
    cfg = EngineConfig()
    market = pd.read_csv(args.market, parse_dates=["date"]).set_index("date")

    # --- Build the four V7.6 manifolds (frozen) ------------------------------
    m1_sig = make_v75_q_signal(
        market, data.realized_pnl,
        drivers=V75DriverConfig(momentum_sensitivity=0.0),
        q_cfg=QPolygonConfig(),
        include_mom_eigen=False,
        top_k=2, tau=2.0, lam=0.5,
    )
    manifolds = {
        "v74d_q": m1_sig,
        "momentum_12_1": momentum_signal,
        "defensive": defensive_signal,
        "cash": cash_signal,
    }

    print(f"[run] data: {data.realized_pnl.index.min().date()} → "
          f"{data.realized_pnl.index.max().date()}  ({len(data.realized_pnl)} rows)")

    weights: dict[str, pd.DataFrame] = {}
    returns: dict[str, pd.Series] = {}
    v74d_q_diag: pd.DataFrame | None = None
    for name, sig in manifolds.items():
        w = compute_weights(data, sig, cfg)
        res = evaluate(w, data.forward_pnl)
        weights[name] = w
        returns[name] = res.returns
        if name == "v74d_q" and hasattr(sig, "diagnostics_df"):
            v74d_q_diag = sig.diagnostics_df()
    if v74d_q_diag is not None:
        print(f"[run] v74d_q diagnostics: {len(v74d_q_diag)} rows, "
              f"cols={sorted(v74d_q_diag.columns)[:8]}…")
    else:
        print("[run] !! no v74d_q diagnostics — Φ geometry gates fall back to 0.9")

    # --- V7.6α base blend ----------------------------------------------------
    meta_cfg = MetaConfig(lookback=args.lookback, lam=args.lam,
                          ewm_halflife=args.halflife, min_floor=args.floor)
    base_w, _alloc = meta_blend(weights, returns, meta_cfg)
    base_w = base_w.reindex(data.forward_pnl.index).fillna(0.0)
    base_res = evaluate(base_w, data.forward_pnl)
    base_w.to_csv(args.output / "weights_v76.csv", index_label="trading_date")
    base_res.returns.to_csv(args.output / "returns_v76.csv", index_label="trading_date")

    # --- Feature 1: ADD-lite topology deformation ---------------------------
    add_cfg = ADDLiteConfig(add_sensitivity=args.add_sensitivity)
    add_lite, add_panel = compute_add_lite(data.realized_pnl, add_cfg)
    add_panel.to_csv(args.output / "add_lite_v77.csv", index_label="trading_date")
    add_scale = add_lite_scale(add_lite, add_cfg)

    v77_add_w = apply_gross_scale(base_w, add_scale)
    v77_add_res = evaluate(v77_add_w, data.forward_pnl)
    v77_add_w.to_csv(args.output / "weights_v77_add.csv", index_label="trading_date")
    v77_add_res.returns.to_csv(args.output / "returns_v77_add.csv", index_label="trading_date")

    # --- Feature 2: Kelly capital-intensity sizing --------------------------
    kelly_cfg = KellyConfig(kelly_gain=args.kelly_gain,
                            mode_mult=args.kelly_mode_mult)
    phi = compute_governance_phi(base_res.returns, v74d_q_diag, add_panel, kelly_cfg)
    phi.to_csv(args.output / "governance_phi_v77.csv", index_label="trading_date")
    f_kelly, kelly_detail = compute_kelly_fraction(base_res.returns, phi["Phi"], kelly_cfg)
    kelly_detail.to_csv(args.output / "kelly_v77.csv", index_label="trading_date")

    v77_kelly_w = apply_gross_scale(base_w, f_kelly)
    v77_kelly_res = evaluate(v77_kelly_w, data.forward_pnl)
    v77_kelly_w.to_csv(args.output / "weights_v77_kelly.csv", index_label="trading_date")
    v77_kelly_res.returns.to_csv(args.output / "returns_v77_kelly.csv", index_label="trading_date")

    # --- Full V7.7: both overlays stacked -----------------------------------
    combined_scale = (add_scale.reindex(base_w.index).fillna(1.0)
                      * f_kelly.reindex(base_w.index).fillna(0.0))
    v77_w = apply_gross_scale(base_w, combined_scale)
    v77_res = evaluate(v77_w, data.forward_pnl)
    v77_w.to_csv(args.output / "weights_v77.csv", index_label="trading_date")
    v77_res.returns.to_csv(args.output / "returns_v77.csv", index_label="trading_date")

    # --- Naive 1/4 reference -------------------------------------------------
    cols_union = sorted(set().union(*[w.columns for w in weights.values()]))
    w_naive = sum(w.reindex(columns=cols_union).fillna(0.0)
                  for w in weights.values()) / len(weights)
    w_naive = w_naive.reindex(data.forward_pnl.index).fillna(0.0)
    naive_res = evaluate(w_naive, data.forward_pnl)

    # --- Overlay-field diagnostics ------------------------------------------
    print()
    print("=== ADD-lite field (composite, applied) ===")
    print(add_lite.describe()[["mean", "std", "min", "25%", "50%", "75%", "max"]]
          .to_string(float_format="{:.4f}".format))
    print("  component means: " + ", ".join(
        f"{c}={add_panel[c].mean():.3f}" for c in ["C", "S", "B", "R", "P", "F"]))
    print()
    print("=== Kelly fraction f_t (applied) & Φ ===")
    print(f_kelly.describe()[["mean", "std", "min", "25%", "50%", "75%", "max"]]
          .to_string(float_format="{:.4f}".format))
    print("  φ-gate means: " + ", ".join(
        f"{c}={phi[c].mean():.3f}" for c in
        ["phi_Z", "phi_R", "phi_B", "phi_V", "phi_M", "Phi"]))
    base_gross = base_w[list(UNIVERSE)].abs().sum(axis=1)
    v77_gross = v77_w[list(UNIVERSE)].abs().sum(axis=1)
    print(f"  mean real gross: v76α={base_gross.mean():.3f}  v77={v77_gross.mean():.3f}")

    # --- Headline summary ----------------------------------------------------
    series = [
        ("v76α (base)",   base_res),
        ("v77-ADD",       v77_add_res),
        ("v77-Kelly",     v77_kelly_res),
        ("v77 (ADD+Kelly)", v77_res),
        ("naive_1_over_4", naive_res),
        ("equal_weight",  evaluate(compute_weights(data, equal_weight_signal, cfg),
                                   data.forward_pnl)),
    ]
    rows = [_summary(n, res.returns, res.equity) for n, res in series]
    cols = ["Series", "Total return", "CAGR", "Ann. vol",
            "Sharpe", "Sortino", "Calmar", "Max drawdown"]
    df = pd.DataFrame(rows)[cols]
    df.to_csv(args.output / "summary_v77_check.csv", index=False)
    print()
    print("=== Headline (full sample) ===")
    print(df.to_string(index=False,
                       formatters={c: "{:.4f}".format for c in cols if c != "Series"}))

    # --- Crisis & recent windows --------------------------------------------
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
    cdf.to_csv(args.output / "crisis_v77_check.csv", index=False)
    print()
    print("=== Crisis & recent windows ===")
    print(cdf.to_string(index=False))

    # --- Temporal split ------------------------------------------------------
    splits = [
        ("2008-04 → 2016-12 (first half)",  "2008-04-01", "2016-12-31"),
        ("2017-01 → 2026-04 (second half)", "2017-01-01", "2026-04-29"),
        ("2008-04 → 2019-12 (pre-COVID)",   "2008-04-01", "2019-12-31"),
        ("2020-01 → 2026-04 (COVID-on)",    "2020-01-01", "2026-04-29"),
    ]
    split_rows = []
    for lbl, a, b in splits:
        row = {"window": lbl}
        for nm, res in series[:4]:
            sl = res.returns.loc[a:b]
            sh = (float((sl.mean() * 252) / (sl.std() * np.sqrt(252)))
                  if len(sl) and sl.std() > 0 else float("nan"))
            eq = (1 + sl).cumprod()
            row[f"{nm}_sharpe"] = sh
            row[f"{nm}_maxdd"] = float((eq / eq.cummax() - 1.0).min()) if len(sl) else 0.0
        split_rows.append(row)
    sdf = pd.DataFrame(split_rows)
    print()
    print("=== Temporal split: Sharpe / MaxDD ===")
    print(sdf.to_string(index=False,
        formatters={c: "{:.3f}".format for c in sdf.columns if c != "window"}))


if __name__ == "__main__":
    main()
