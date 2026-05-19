"""
Build the V7.10 dashboard.

V7.10 adds the Strategy Sleeve Registry. The dashboard shows the V7.9
winners plus the candidate mean-reversion sleeve that the registry
evaluated — kept visible (hidden by default) so the rejected candidate
is inspectable:

  - v7.10:     v79 + any admitted sleeve (this run: no sleeve cleared
               the gates, so v7.10 ≡ v79)
  - v79:       v78-ADD + governed defensive rotation
  - v78-ADD:   asset-level ADD-lite core
  - v76α:      meta-steered governance base
  - manifolds: v74d_q, momentum_12_1, defensive, cash
  - MR-sleeve: the cross-sectional reversal candidate (registry-REJECTED,
               net of cost) — hidden by default
  - references: v73 (β-band diagnostics), equal_weight, S&P 500

A pure re-render from cached CSVs. Run `python run_v710_check.py` and
`python build_polyagora.py --v75` first.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

import polyagora_dashboard as dash
from polyagora_v63_partner_engine import CASH, UNIVERSE, summary_row


ROOT = Path(__file__).resolve().parent
DEFAULT_V710_OUT = ROOT / "polyagora_v710_outputs"
DEFAULT_V75_OUT = ROOT / "polyagora_v75_outputs"


LINEUP: list[tuple[str, str, str, str, str]] = [
    ("v710",       "v710", "#9d174d",
     "V7.10 · Strategy Sleeve Registry",
     "The active production line. V7.10 adds the Strategy Sleeve Registry — candidate alpha sleeves clear validation → DSR noise floor → correlation-to-book → walk-forward → contribution before joining the book. Built on the V7.9 governance book with the registry's first admitted sleeve (the fixed-income crisis-trend sleeve, ~18%); reaches Sharpe 0.91 / Sortino 1.23 / Calmar 0.49 at −6.5% drawdown and — for the first time — a positive 2022 rate-shock Sharpe (+0.44 vs v79's −0.84)."),
    ("v79",        "v710", "#be123c",
     "V7.9 · v78-ADD + governed defensive rotation",
     "The V7.9 book: v78-ADD with a governed defensive rotation driven by the ADD-lite fragility field. Best risk-adjusted line of the consolidated winners (Sharpe 0.87, Sortino 1.16, Calmar 0.33)."),
    ("v78_add",    "v710", "#e11d48",
     "V7.8-ADD · Asset-level ADD-lite core",
     "v76α with the V7.8 per-asset ADD-lite continuous deformation. The V7.8 production core."),
    ("v76",        "v710", "#7c3aed",
     "V7.6α · Meta-steered governance base",
     "The frozen V7.6α meta-steering kernel — softmax-of-rolling-Sharpe over the four manifolds. The governance base every overlay sits on."),
    ("v74d_q",     "v710", "#065f46",
     "M1: V7.4d_q · V7 manifold (transitions / fragmentation)",
     "Manifold 1 — strong in transitions and regime deformation. Frozen."),
    ("momentum_12_1","v710", "#a16207",
     "M2: Momentum 12-1 · Persistent-trend manifold",
     "Manifold 2 — classic 12-1 momentum. Owns the recent trend era. Frozen."),
    ("defensive",  "v710", "#0f766e",
     "M3: Defensive · Rupture / collapse manifold",
     "Manifold 3 — frozen bond/gold/USD mix. Wins the deflationary crash, loses the 2022 rate shock. Frozen."),
    ("cash",       "v710", "#9ca3af",
     "M4: Cash · Absorbing rest-state",
     "Manifold 4 — zero real-asset weights."),
    ("bond_trend", "v710", "#0891b2",
     "Bond-trend sleeve · Fixed-income crisis-trend (registry-ADMITTED)",
     "The first admitted alpha sleeve — a 12-month time-series trend on the bond futures (TN, FGBL). It goes long bonds in flight-to-quality rallies and short bonds in persistent rate shocks, so it earns +1.8 Sharpe in the 2022 rate shock — the regime every other component loses. Genuinely uncorrelated to the book (corr 0.28). v7.10 holds it at ~18% via the registry. Shown standalone, net of cost; hidden by default."),
    ("mr_sleeve",  "v710", "#dc2626",
     "MR-sleeve · Mean-reversion candidate (registry-REJECTED)",
     "Candidate cross-sectional reversal sleeve, net of cost. The registry REJECTED it on validation, DSR and contribution: short-horizon reversal has no gross edge on the momentum-prone partner universe and realistic cost annihilates what little exists (net Sharpe −1.4). Kept as the rejected-candidate contrast. Hidden by default."),
    ("v73",        "v75", "#f97316",
     "V7.3 · Reference (β-gate + Q polygons)",
     "V7.3 default — kept as a reference; carries the β′ₜ diagnostics that shade the zone bands."),
    ("equal_weight","v75", "#2563eb",
     "Equal-weight · 1/N over 13 assets",
     "Naive 1/N over the 13 partner assets — lower bound for any reasonable strategy."),
    ("sp500",      "v75", "#111827",
     "S&P 500 · Buy-and-hold reference (Yahoo SPY)",
     "S&P 500 buy-and-hold via Yahoo SPY. Market-beta reference; hidden by default."),
]

DEFAULT_VISIBLE = ["v710", "v79", "v78_add", "v76",
                   "v74d_q", "momentum_12_1", "defensive", "cash"]

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
        print(f"[v710] !! skipping {name} — missing files in {out}")
        return None
    return dash.SignalRun(
        name=name, label=label, color=color, info=info,
        summary=summary_row(name, returns),
        returns=returns, equity=equity, weights=weights,
        diagnostics=_load_diagnostics(name, out),
    )


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--v710-output", type=Path, default=DEFAULT_V710_OUT)
    p.add_argument("--v75-output", type=Path, default=DEFAULT_V75_OUT)
    p.add_argument("--title", default="PolyAgora V7.10 — Strategy Sleeve Registry")
    p.add_argument("--weights-signal", default="v710")
    args = p.parse_args()

    for label, path in [("v710", args.v710_output), ("v75", args.v75_output)]:
        if not path.exists():
            p.error(f"{label} output dir {path} does not exist — run the upstream step first")

    srcs = {"v710": args.v710_output, "v75": args.v75_output}
    runs = []
    for name, src, color, label, info in LINEUP:
        r = _build_run(name, label, color, info, srcs[src])
        if r is not None:
            runs.append(r)
    if not runs:
        p.error("no runs assembled — check that the output dirs contain CSVs")

    print(f"[v710] composed {len(runs)} runs: {[r.name for r in runs]}")
    html_path, json_path = dash.write_dashboard(
        runs, universe=list(UNIVERSE) + [CASH], output_dir=args.v710_output,
        title=args.title, default_weights_signal=args.weights_signal,
        default_visible_signals=DEFAULT_VISIBLE,
        time_range_presets=TIME_RANGE_PRESETS, filename_stem="dashboard")
    print(f"[ok] {html_path}")
    print(f"[ok] {json_path}")


if __name__ == "__main__":
    main()
