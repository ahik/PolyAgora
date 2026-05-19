"""
V7.9 check — winners-consolidated line + governed defensive rotation.

The cross-method study (`Allocation_Method_Study.md`) showed the
V6.3→V7.8 tree is mostly redundant: only the V7.6α governance base, the
four frozen manifolds and the V7.8 asset-level ADD-lite core are
non-dominated. V7.9 keeps **only those winners** and adds one
improvement — a governed defensive rotation with convexity re-entry
(multi-sleeve spec §13–§14):

    v76α        frozen meta-steered governance base
    v78-ADD     asset-level ADD-lite core            (V7.8 production core)
    v79         v78-ADD + governed defensive rotation (the new candidate)
    TILT-ref    trend-driven defensive tilt          (study's validated TILT)
    + manifolds v74d_q / momentum / defensive / cash, naive 1/4, EW, SPY

Reporting incorporates the multi-sleeve doc's two named gaps:
  - §10 correlation governance — average pairwise correlation of the
    winner set (target < 0.35); expected to FAIL, which is the finding
    that motivates a future mean-reversion sleeve.
  - §14 runtime zones — the time-in-zone distribution of v79.

Outputs land in `polyagora_v79_outputs/`.
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


ROOT = Path(__file__).resolve().parent
DEFAULT_INPUT = ROOT / "Agur" / "baseline_pnl_partner_delivery.xlsx"
DEFAULT_MARKET = ROOT / "market_data" / "market_yahoo_vix_spy_hyg_tlt_gld_cper.csv"
DEFAULT_OUTPUT = ROOT / "polyagora_v79_outputs"


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
            "ret": float(eq.iloc[-1] - 1.0),
            "max_dd": float((eq / eq.cummax() - 1.0).min())}


def _corr(a: pd.Series, b: pd.Series) -> float:
    j = pd.concat([a, b], axis=1, join="inner").dropna()
    return float(j.iloc[:, 0].corr(j.iloc[:, 1])) if len(j) > 30 else float("nan")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    p.add_argument("--market", type=Path, default=DEFAULT_MARKET)
    p.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    p.add_argument("--lookback", type=int, default=63)
    p.add_argument("--lam", type=float, default=2.0)
    p.add_argument("--halflife", type=float, default=10.0)
    p.add_argument("--floor", type=float, default=0.15)
    p.add_argument("--add-lam", type=float, default=0.6)
    p.add_argument("--rot-gain", type=float, default=1.0,
                   help="rotation gain — above-baseline fragility -> defensive weight")
    p.add_argument("--d-max", type=float, default=0.60,
                   help="cap on the defensive rotation weight")
    args = p.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)
    data = load_partner_xlsx(args.input)
    cfg = EngineConfig()
    market = pd.read_csv(args.market, parse_dates=["date"]).set_index("date")

    # --- Four frozen manifolds (the level-1 winners) ------------------------
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

    # --- v76α governance base -----------------------------------------------
    meta_cfg = MetaConfig(lookback=args.lookback, lam=args.lam,
                          ewm_halflife=args.halflife, min_floor=args.floor)
    base_w, _ = meta_blend(weights, returns, meta_cfg)
    base_w = base_w.reindex(data.forward_pnl.index).fillna(0.0)
    base_res = evaluate(base_w, data.forward_pnl)
    base_w.to_csv(args.output / "weights_v76.csv", index_label="trading_date")
    base_res.returns.to_csv(args.output / "returns_v76.csv", index_label="trading_date")

    # --- v78-ADD core (asset-level ADD-lite) --------------------------------
    add_cfg = ADDLiteV78Config(lam=args.add_lam)
    add_field, _ = compute_add_lite_field(data.realized_pnl, add_cfg)
    v78_add_w = apply_asset_deformation(base_w, add_field, add_cfg.lam)
    v78_add_res = evaluate(v78_add_w, data.forward_pnl)
    v78_add_w.to_csv(args.output / "weights_v78_add.csv", index_label="trading_date")
    v78_add_res.returns.to_csv(args.output / "returns_v78_add.csv", index_label="trading_date")

    # --- v79: governed defensive rotation -----------------------------------
    book_add = compute_book_add(base_w, add_field)
    rot_cfg = RotationConfig(rot_gain=args.rot_gain, d_max=args.d_max)
    d_rot, rot_detail = compute_rotation(book_add, rot_cfg)
    rot_detail.to_csv(args.output / "rotation_v79.csv", index_label="trading_date")
    defensive_w = weights["defensive"].reindex(base_w.index).fillna(0.0)
    v79_w = apply_rotation(v78_add_w, defensive_w, d_rot)
    v79_res = evaluate(v79_w, data.forward_pnl)
    v79_w.to_csv(args.output / "weights_v79.csv", index_label="trading_date")
    v79_res.returns.to_csv(args.output / "returns_v79.csv", index_label="trading_date")

    # --- TILT-ref: the study's validated trend-driven defensive tilt --------
    base_eq = (1 + base_res.returns.fillna(0.0)).cumprod()
    trend = (base_eq / base_eq.shift(63) - 1.0).shift(1).fillna(0.0)
    d_trend = (0.6 / (1.0 + np.exp(40.0 * trend))).clip(0.0, 0.6)
    tilt_w = apply_rotation(v78_add_w, defensive_w, d_trend)
    tilt_res = evaluate(tilt_w, data.forward_pnl)

    # --- naive 1/4 + equal-weight references --------------------------------
    cols_u = sorted(set().union(*[w.columns for w in weights.values()]))
    w_naive = sum(w.reindex(columns=cols_u).fillna(0.0)
                  for w in weights.values()) / len(weights)
    naive_res = evaluate(w_naive.reindex(data.forward_pnl.index).fillna(0.0),
                         data.forward_pnl)
    ew_res = evaluate(compute_weights(data, equal_weight_signal, cfg), data.forward_pnl)

    # SPY reference from the V7.5 outputs if present.
    sp = ROOT / "polyagora_v75_outputs" / "returns_sp500.csv"
    sp500 = (pd.read_csv(sp, parse_dates=["trading_date"]).set_index("trading_date").iloc[:, 0]
             if sp.exists() else None)

    series = [
        ("v76a (base)", base_res.returns, base_res.equity),
        ("v78-ADD",     v78_add_res.returns, v78_add_res.equity),
        ("v79 (rotation)", v79_res.returns, v79_res.equity),
        ("TILT-ref (trend)", tilt_res.returns, tilt_res.equity),
        ("v74d_q",      returns["v74d_q"], (1 + returns["v74d_q"]).cumprod()),
        ("momentum_12_1", returns["momentum_12_1"], (1 + returns["momentum_12_1"]).cumprod()),
        ("defensive",   returns["defensive"], (1 + returns["defensive"]).cumprod()),
        ("naive_1_4",   naive_res.returns, naive_res.equity),
        ("equal_weight", ew_res.returns, ew_res.equity),
    ]
    if sp500 is not None:
        series.append(("sp500", sp500, (1 + sp500.fillna(0)).cumprod()))

    # --- Rotation / runtime-zone diagnostics --------------------------------
    print()
    print("=== v79 governed rotation — runtime zones (spec §14) ===")
    zc = rot_detail["zone"].value_counts(normalize=True).sort_index()
    print("  time-in-zone: " + "  ".join(f"{z}={p:.1%}" for z, p in zc.items()))
    print(f"  d_rotation: mean={d_rot.mean():.3f}  p50={d_rot.median():.3f}  "
          f"p95={d_rot.quantile(0.95):.3f}  max={d_rot.max():.3f}")
    base_g = base_w[list(UNIVERSE)].abs().sum(axis=1)
    v79_g = v79_w[list(UNIVERSE)].abs().sum(axis=1)
    print(f"  mean real gross: v76a={base_g.mean():.3f}  v79={v79_g.mean():.3f}")

    # --- Headline summary ---------------------------------------------------
    rows = [_summary(n, r, e) for n, r, e in series]
    cols = ["Series", "Total return", "CAGR", "Ann. vol",
            "Sharpe", "Sortino", "Calmar", "Max drawdown"]
    df = pd.DataFrame(rows)[cols]
    df.to_csv(args.output / "summary_v79_check.csv", index=False)
    print()
    print("=== Headline (full sample, winners only) ===")
    print(df.to_string(index=False,
                       formatters={c: "{:.4f}".format for c in cols if c != "Series"}))

    # --- Dov benchmark panel ------------------------------------------------
    if sp500 is not None:
        spy_r, tlt_r, hyg_r = (market[c].pct_change() for c in ("SPY", "TLT", "HYG"))
        dov = []
        for n, r, e in series:
            s = _summary(n, r, e)
            dov.append({"Series": n, "Sharpe": s["Sharpe"], "Sortino": s["Sortino"],
                        "Calmar": s["Calmar"], "MaxDD": s["Max drawdown"],
                        "Corr_SPY": _corr(r, spy_r), "Corr_TLT": _corr(r, tlt_r),
                        "Corr_HYG": _corr(r, hyg_r)})
        ddf = pd.DataFrame(dov)
        ddf.to_csv(args.output / "dov_v79_check.csv", index=False)
        print()
        print("=== Dov benchmark panel (targets: Sharpe>1.2 Sortino>1.5 "
              "Calmar>1.0 MaxDD<8% Corr_SPY<0.35) ===")
        print(ddf.to_string(index=False, formatters={
            c: "{:.3f}".format for c in ddf.columns if c != "Series"}))

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
    cdf.to_csv(args.output / "crisis_v79_check.csv", index=False)
    print()
    print("=== Regime-window Sharpe ===")
    piv = cdf.pivot(index="series", columns="window", values="sharpe")
    piv = piv.reindex([n for n, _, _ in series])[[r[0] for r in REG]]
    print(piv.to_string(float_format=lambda x: f"{x:.2f}"))

    # --- Correlation governance (multi-sleeve spec §10) ---------------------
    core = ["v76a (base)", "v78-ADD", "v79 (rotation)", "v74d_q",
            "momentum_12_1", "defensive"]
    rmap = {n: r for n, r, _ in series}
    cpanel = pd.DataFrame({n: rmap[n] for n in core}).dropna()
    cm = cpanel.corr()
    off = cm.where(~np.eye(len(cm), dtype=bool))
    avg_corr = float(np.nanmean(off.values))
    cm.to_csv(args.output / "corr_v79_check.csv")
    print()
    print("=== Correlation governance (spec §10 — target avg < 0.35) ===")
    print(cm.to_string(float_format=lambda x: f"{x:.2f}"))
    verdict = "PASS" if avg_corr < 0.35 else "FAIL"
    print(f"  average pairwise correlation = {avg_corr:.3f}  [{verdict} vs 0.35]")
    if verdict == "FAIL":
        print("  -> winners share one return stream; an uncorrelated sleeve "
              "(mean-reversion) is the next genuine diversifier.")


if __name__ == "__main__":
    main()
