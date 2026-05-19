"""
Build the V7.9 dashboard — winners-consolidated lineup.

The cross-method study (`Allocation_Method_Study.md`) found the
V6.3→V7.8 tree mostly redundant. V7.9's dashboard shows only the
non-dominated winners — no v74b·* / v75·* / v76β/γ / v77·* clutter:

  - v79:        v78-ADD + governed defensive rotation (the candidate)
  - v78-ADD:    V7.8 asset-level ADD-lite core
  - v76α:       frozen meta-steered governance base
  - manifolds:  v74d_q, momentum_12_1, defensive, cash
  - references: v73 (carries the β-band diagnostics), equal_weight, S&P 500

A pure re-render from cached CSVs. V7.9 variants + manifolds are read
from `polyagora_v79_outputs/`; the references from `polyagora_v75_outputs/`.

Run `python run_v79_check.py` and `python build_polyagora.py --v75` first.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

import polyagora_dashboard as dash
from polyagora_v63_partner_engine import CASH, UNIVERSE, summary_row


ROOT = Path(__file__).resolve().parent
DEFAULT_V79_OUT = ROOT / "polyagora_v79_outputs"
DEFAULT_V75_OUT = ROOT / "polyagora_v75_outputs"


LINEUP: list[tuple[str, str, str, str, str]] = [
    ("v79",        "v79", "#be123c",
     "V7.9 · v78-ADD + governed defensive rotation",
     "The winners-consolidated line: the V7.8 asset-level ADD-lite core with a governed defensive rotation — w = (1−d)·v78-ADD + d·defensive — where d rises with ADD-lite book fragility (multi-sleeve spec §13–§14, convexity re-entry / runtime zones). Lifts Sharpe (0.83→0.87), Sortino and Calmar over v78-ADD at ~0.6pp extra drawdown; rotation is inert ~78% of the time."),
    ("v78_add",    "v79", "#e11d48",
     "V7.8-ADD · Asset-level ADD-lite core",
     "v76α with the V7.8 per-asset ADD-lite continuous deformation (w'_i = w_i·(1−λ·ADD_i)). The V7.8 production core and the base v7.9 rotates. Best standalone Calmar/drawdown of the pre-v7.9 line."),
    ("v76",        "v79", "#7c3aed",
     "V7.6α · Meta-steered governance base",
     "The frozen V7.6α meta-steering kernel — softmax-of-rolling-Sharpe over the four manifolds, 15% floor, 10-day EWM. The governance base every later overlay sits on; strongest full-return line."),
    ("v74d_q",     "v79", "#065f46",
     "M1: V7.4d_q · V7 manifold (transitions / fragmentation)",
     "Manifold 1 — make_v75_q_signal at α_M=0, K=2, τ=2, λ=0.5 with VAIDM × ADD Q polygons. Strong in transitions and regime deformation. Frozen."),
    ("momentum_12_1","v79", "#a16207",
     "M2: Momentum 12-1 · Persistent-trend manifold",
     "Manifold 2 — classic 12-1 momentum, long-only on positive-trend assets. Owns the recent (2023-26) trend era; crashes in transitions. Frozen."),
    ("defensive",  "v79", "#0f766e",
     "M3: Defensive · Rupture / collapse manifold",
     "Manifold 3 — frozen 40% TN + 20% FGBL + 20% GC + 20% DX. Wins the deflationary crash (GFC +1.62 Sharpe) and is the worst method in the 2022 rate shock — a regime-specific hedge, not all-weather. Frozen."),
    ("cash",       "v79", "#9ca3af",
     "M4: Cash · Absorbing rest-state",
     "Manifold 4 — zero real-asset weights. Receives meta-allocation only when every other manifold has negative recent Sharpe."),
    ("v73",        "v75", "#f97316",
     "V7.3 · Reference (β-gate + Q polygons)",
     "V7.3 default — kept as a historical reference; carries the β′ₜ diagnostics that shade the zone bands on the equity / drawdown charts."),
    ("equal_weight","v75", "#2563eb",
     "Equal-weight · 1/N over 13 assets",
     "Naive 1/N over the 13 partner assets — lower bound for any reasonable strategy."),
    ("sp500",      "v75", "#111827",
     "S&P 500 · Buy-and-hold reference (Yahoo SPY)",
     "S&P 500 buy-and-hold via Yahoo SPY. Market-beta reference; hidden by default since its full-sample 6× crushes the linear y-axis."),
]

DEFAULT_VISIBLE = ["v79", "v78_add", "v76", "v74d_q",
                   "momentum_12_1", "defensive", "cash"]

TIME_RANGE_PRESETS = [
    {"label": "GFC",         "from": "2008-04-01", "to": "2009-06-30"},
    {"label": "COVID",       "from": "2020-02-15", "to": "2020-12-31"},
    {"label": "2022 rates",  "from": "2022-01-01", "to": "2022-12-31"},
    {"label": "Last 3y",     "from": "2023-01-01", "to": "2099-12-31"},
    {"label": "First half",  "from": "2008-04-01", "to": "2016-12-31"},
    {"label": "Second half", "from": "2017-01-01", "to": "2099-12-31"},
    {"label": "Pre-COVID",   "from": "2008-04-01", "to": "2019-12-31"},
    {"label": "COVID-on",    "from": "2020-01-01", "to": "2099-12-31"},
]


def _load_returns(name, out):
    p = out / f"returns_{name}.csv"
    if not p.exists():
        return None
    return pd.read_csv(p, parse_dates=["trading_date"]).set_index("trading_date").iloc[:, 0]


def _load_weights(name, out):
    p = out / f"weights_{name}.csv"
    if not p.exists():
        return None
    return pd.read_csv(p, parse_dates=["trading_date"]).set_index("trading_date")


def _load_equity(name, out):
    r = _load_returns(name, out)
    return (1.0 + r.fillna(0.0)).cumprod() if r is not None else None


def _load_diagnostics(name, out):
    p = out / f"diagnostics_{name}.csv"
    if not p.exists():
        return None
    return pd.read_csv(p, parse_dates=["trading_date"]).set_index("trading_date")


def _build_run(name, label, color, info, out):
    weights = _load_weights(name, out)
    returns = _load_returns(name, out)
    equity = _load_equity(name, out)
    if weights is None or returns is None or equity is None:
        print(f"[v79] !! skipping {name} — missing files in {out}")
        return None
    return dash.SignalRun(
        name=name, label=label, color=color, info=info,
        summary=summary_row(name, returns),
        returns=returns, equity=equity, weights=weights,
        diagnostics=_load_diagnostics(name, out),
    )


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--v79-output", type=Path, default=DEFAULT_V79_OUT)
    p.add_argument("--v75-output", type=Path, default=DEFAULT_V75_OUT)
    p.add_argument("--title", default="PolyAgora V7.9 — Winners + Governed Defensive Rotation")
    p.add_argument("--weights-signal", default="v79")
    args = p.parse_args()

    for label, path in [("v79", args.v79_output), ("v75", args.v75_output)]:
        if not path.exists():
            p.error(f"{label} output dir {path} does not exist — run the upstream step first")

    srcs = {"v79": args.v79_output, "v75": args.v75_output}
    runs = []
    for name, src, color, label, info in LINEUP:
        r = _build_run(name, label, color, info, srcs[src])
        if r is not None:
            runs.append(r)
    if not runs:
        p.error("no runs assembled — check that the output dirs contain CSVs")

    print(f"[v79] composed {len(runs)} runs: {[r.name for r in runs]}")
    html_path, json_path = dash.write_dashboard(
        runs, universe=list(UNIVERSE) + [CASH], output_dir=args.v79_output,
        title=args.title, default_weights_signal=args.weights_signal,
        default_visible_signals=DEFAULT_VISIBLE,
        time_range_presets=TIME_RANGE_PRESETS, filename_stem="dashboard")
    print(f"[ok] {html_path}")
    print(f"[ok] {json_path}")


if __name__ == "__main__":
    main()
