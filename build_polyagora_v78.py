"""
Build the V7.8 dashboard.

Composes the V7.8 lineup into `polyagora_v78_outputs/dashboard.html`:
  - V7.8:            v78 (ADD+Kelly), v78-ADD (asset-level ADD-lite)
  - V7.7 reference:  v77-ADD (portfolio-level ADD-lite — the serious V7.7 line)
  - V7.6 base:       v76α (the frozen meta-steered governance base)
  - V7.6 manifolds:  v74d_q, momentum_12_1, defensive, cash
  - Prior-version references: v74d, v74b_template, v73
  - Model-free baselines: equal_weight, inverse_vol
  - External reference: S&P 500 buy-and-hold

No engine code runs here — a pure re-render from cached CSVs. V7.8
variants + the v76α base + v77-ADD are read from `polyagora_v78_outputs/`;
the four manifolds from `polyagora_v76_outputs/`; everything else from
`polyagora_v75_outputs/`.

Run `python run_v78_check.py`, `python run_v76_check.py` and
`python build_polyagora.py --v75` first.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

import polyagora_dashboard as dash
from polyagora_v63_partner_engine import CASH, UNIVERSE, summary_row


ROOT = Path(__file__).resolve().parent
DEFAULT_V78_OUT = ROOT / "polyagora_v78_outputs"
DEFAULT_V76_OUT = ROOT / "polyagora_v76_outputs"
DEFAULT_V75_OUT = ROOT / "polyagora_v75_outputs"


# (signal name, source dir key, color, label, info)
LINEUP: list[tuple[str, str, str, str, str]] = [
    ("v78",        "v78", "#be123c",
     "V7.8 · Asset-level ADD-lite + conditional Kelly",
     "Full V7.8: the v76α meta-steered base with the two refined overlays — per-asset ADD-lite continuous deformation (w'_i = w_i·(1−λ·ADD_i), spec §9) followed by the conditional soft-Kelly gate (K = max(0, 1−γ·(ADD_book−baseline)+), spec §12). Kelly is near-inert by design — a quiet convexity-preserving gate, not the V7.7 μ/σ²·Φ brake."),
    ("v78_add",    "v78", "#e11d48",
     "V7.8-ADD · Asset-level ADD-lite (continuous deformation)",
     "v76α with asset-level ADD-lite only. Unlike V7.7's single portfolio scalar, ADD is a per-asset field — a fragile asset is trimmed without flattening the convex winners. Beats both v76α and v77-ADD on Sharpe, Sortino and Calmar at lower drawdown: the spec §9 'preserve convex winners' property realized."),
    ("v77_add",    "v78", "#fb7185",
     "V7.7-ADD · Portfolio-level ADD-lite (reference)",
     "v76α scaled by the V7.7 portfolio-level ADD-lite scalar — the serious V7.7 candidate, kept here as the reference the V7.8 asset-level redesign is measured against. Roughly risk-neutral vs v76α; the asset-level field improves on it."),
    ("v76",        "v78", "#7c3aed",
     "V7.6α · Meta-steered governance base (no overlay)",
     "The frozen V7.6α meta-steering kernel — softmax-of-rolling-Sharpe over four manifolds, 15% floor, 10-day EWM. The governance base the V7.8 overlays deform; still the strongest full-return line."),
    ("v74d_q",       "v76", "#065f46",
     "M1: V7.4d_q · V7 manifold (transitions / fragmentation)",
     "Manifold 1 — make_v75_q_signal at α_M=0, K=2, τ=2, λ=0.5 with VAIDM × ADD Q polygons. Strong in transitions and regime deformation. Frozen."),
    ("momentum_12_1","v76", "#a16207",
     "M2: Momentum 12-1 · Persistent-trend manifold",
     "Manifold 2 — classic 12-1 momentum, long-only on positive-trend assets. Strong in persistent trends. Frozen."),
    ("defensive",    "v76", "#0f766e",
     "M3: Defensive · Rupture / collapse manifold",
     "Manifold 3 — frozen mix 40% TN + 20% FGBL + 20% GC + 20% DX. Strong under rupture and vol stress. Frozen."),
    ("cash",         "v76", "#9ca3af",
     "M4: Cash · Absorbing rest-state",
     "Manifold 4 — zero real-asset weights. Receives meta-allocation only when every other manifold has negative recent Sharpe."),
    ("v74d",         "v75", "#0f766e",
     "V7.4d · Sweep winner (Φ=13, α_M=0, K=2, τ=2, λ=0.5)",
     "V7.4d — the empirical V7.4/V7.5 sweep winner. Reference for the V7 line without meta-steering."),
    ("v74b_template","v75", "#16a34a",
     "V7.4b template · V7.3 continuity anchor (β-gate + Q)",
     "V7.4b in template-block mode with β-gate and VAIDM × ADD Q polygons — the V6.3 → V7.3 → V7.4b lineage anchor."),
    ("v73",          "v75", "#f97316",
     "V7.3 · Default (β-gate + Q polygons)",
     "V7.3 default — V6.3 templates × β-gate × VAIDM × ADD Q polygons. Carries the β′ₜ diagnostics that shade the zone bands."),
    ("equal_weight", "v75", "#2563eb",
     "Equal-weight · 1/N over 13 assets",
     "Naive 1/N over the 13 partner assets — lower bound for any reasonable strategy."),
    ("inverse_vol",  "v75", "#d97706",
     "Inverse-vol · 1/σ over 63-day window",
     "Inverse-volatility weighting, σ over 63 days — risk-parity-flavored model-free baseline."),
    ("sp500",        "v75", "#111827",
     "S&P 500 · Buy-and-hold reference (Yahoo SPY)",
     "S&P 500 buy-and-hold via Yahoo SPY, aligned to the partner forward-pnl index. Market-beta reference; hidden by default since its full-sample 6× crushes the linear y-axis."),
]


DEFAULT_VISIBLE = [
    "v78", "v78_add", "v77_add", "v76",
    "v74d_q", "momentum_12_1", "defensive", "cash",
]


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


def _load_returns(name: str, out: Path) -> pd.Series | None:
    p = out / f"returns_{name}.csv"
    if not p.exists():
        return None
    return pd.read_csv(p, parse_dates=["trading_date"]).set_index("trading_date").iloc[:, 0]


def _load_weights(name: str, out: Path) -> pd.DataFrame | None:
    p = out / f"weights_{name}.csv"
    if not p.exists():
        return None
    return pd.read_csv(p, parse_dates=["trading_date"]).set_index("trading_date")


def _load_equity(name: str, out: Path) -> pd.Series | None:
    p = out / f"equity_{name}.csv"
    if p.exists():
        return pd.read_csv(p, parse_dates=["trading_date"]).set_index("trading_date").iloc[:, 0]
    r = _load_returns(name, out)
    if r is None:
        return None
    return (1.0 + r.fillna(0.0)).cumprod()


def _load_diagnostics(name: str, out: Path) -> pd.DataFrame | None:
    p = out / f"diagnostics_{name}.csv"
    if not p.exists():
        return None
    return pd.read_csv(p, parse_dates=["trading_date"]).set_index("trading_date")


def _build_run(
    name: str, label: str, color: str, info: str, out: Path
) -> dash.SignalRun | None:
    weights = _load_weights(name, out)
    returns = _load_returns(name, out)
    equity = _load_equity(name, out)
    if weights is None or returns is None or equity is None:
        print(f"[v78] !! skipping {name} — missing files in {out}")
        return None
    return dash.SignalRun(
        name=name, label=label, color=color, info=info,
        summary=summary_row(name, returns),
        returns=returns, equity=equity, weights=weights,
        diagnostics=_load_diagnostics(name, out),
    )


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--v78-output", type=Path, default=DEFAULT_V78_OUT)
    p.add_argument("--v76-output", type=Path, default=DEFAULT_V76_OUT)
    p.add_argument("--v75-output", type=Path, default=DEFAULT_V75_OUT)
    p.add_argument("--title", default="PolyAgora V7.8 — Asset-level ADD-lite + Conditional Kelly")
    p.add_argument("--weights-signal", default="v78",
                   help="Which signal to render in the weights stack by default")
    args = p.parse_args()

    for label, path in [("v78", args.v78_output), ("v76", args.v76_output),
                        ("v75", args.v75_output)]:
        if not path.exists():
            p.error(f"{label} output dir {path} does not exist — "
                    f"run the upstream step first")

    srcs = {"v78": args.v78_output, "v76": args.v76_output, "v75": args.v75_output}
    runs: list[dash.SignalRun] = []
    for name, src, color, label, info in LINEUP:
        r = _build_run(name, label, color, info, srcs[src])
        if r is not None:
            runs.append(r)

    if not runs:
        p.error("no runs assembled — check that the output dirs contain CSVs")

    print(f"[v78] composed {len(runs)} runs: {[r.name for r in runs]}")

    html_path, json_path = dash.write_dashboard(
        runs,
        universe=list(UNIVERSE) + [CASH],
        output_dir=args.v78_output,
        title=args.title,
        default_weights_signal=args.weights_signal,
        default_visible_signals=DEFAULT_VISIBLE,
        time_range_presets=TIME_RANGE_PRESETS,
        filename_stem="dashboard",
    )
    print(f"[ok] {html_path}")
    print(f"[ok] {json_path}")


if __name__ == "__main__":
    main()
