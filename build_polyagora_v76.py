"""
Build the V7.6 dashboard.

Composes a curated set of signals into `polyagora_v76_outputs/dashboard.html`:
  - V7.6 meta-steered variants: v76α, v76β, v76γ, v76γ-full
  - Naive 1/N baseline (diversification-only, no steering)
  - The four V7.6 manifolds: v74d_q, momentum_12_1, defensive, cash
  - Prior-version references: v74d, v75_no_mom_eigen, v74b_template, v73
  - Model-free baselines: equal_weight, inverse_vol
  - External reference: S&P 500 buy-and-hold (Yahoo SPY)

No engine code runs here — purely a re-render from cached CSVs in
`polyagora_v76_outputs/` (v76 manifolds + meta) and `polyagora_v75_outputs/`
(prior-version baselines + sp500). Equity curves missing on disk are
computed from returns. The 4 V7.6 manifolds are loaded from v76_outputs;
everything else from v75_outputs.

Adds:
  - Sortino / Calmar columns to the summary table
  - Hover tooltips with extended descriptions on every signal label
  - Preset time-range buttons in the toolbar matching the windows used
    in `V76_Findings.md` (GFC, COVID, 2022 rates, Last 3 years, etc.)
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

import polyagora_dashboard as dash
from polyagora_v63_partner_engine import CASH, UNIVERSE, summary_row


ROOT = Path(__file__).resolve().parent
DEFAULT_V76_OUT = ROOT / "polyagora_v76_outputs"
DEFAULT_V75_OUT = ROOT / "polyagora_v75_outputs"


# -----------------------------------------------------------------------------
# Curated signal lineup. Display order = top-to-bottom order in the summary
# table when sort is in registry mode. The lineup is intentionally short —
# every prior-version reference is here as historical context, not as a
# product candidate. The product candidates are v76α (default) and v76β.
# -----------------------------------------------------------------------------

# (signal name, source directory key, color, label, info)
LINEUP: list[tuple[str, str, str, str, str]] = [
    # V7.6 meta-steered
    ("v76",          "v76", "#7c3aed",
     "V7.6α · Meta-steered (rolling-Sharpe gate)",
     "Production-default v76 variant. Softmax-of-rolling-Sharpe over 4 manifolds (V7=v74d_q, Momentum, Defensive, Cash) with 15% allocation floor and 10-day EWM smoothing on manifold weights W_i(t). Spec §9 with A_i=1. Best Sharpe (0.82 full-sample). Crisis defense: GFC Sharpe +0.55, COVID +1.37."),
    ("v76b",         "v76", "#a855f7",
     "V7.6β · MRTP-lite (regime-conditioned admissibility)",
     "v76β: same softmax as v76α but A_i is computed from v75 regime coords (T, V, d_RP, dQ) — sharper regime calls, more concentrated. Higher CAGR (3.85% vs 3.23%) at the cost of larger drawdowns (-12.4% vs -10.3%). Best GFC Sharpe of the lineup (+0.94)."),
    ("v76g",         "v76", "#c084fc",
     "V7.6γ · Full MRTP (S + F − D, A=1)",
     "v76γ: full MRTP composite per spec §8 = α·S + β·F − γ·D, where F is lag-21 autocorrelation of regime coords and D is regime-bin-mismatch CVaR. Negative result: underperforms v76α in 2017–2026 (Sharpe 0.52 vs 0.65). The F/D terms are forward-looking in interpretation only — their information content remains lagged."),
    ("v76g_full",    "v76", "#d8b4fe",
     "V7.6γ-full · Full MRTP + regime A_i",
     "v76γ + regime-conditioned A_i from v76β stacked on top. Comparable to v76γ; adding A_i on top of full MRTP barely moves the needle (Sharpe 0.53 vs 0.52). Documents that the structural bottleneck is the score composition, not the admissibility gate."),
    # Diversification-only baseline (computed below)
    ("naive_1_over_4", "synthetic", "#374151",
     "Naive 1/4 · Equal-weight 4-manifold blend",
     "Fixed equal-weight blend of the 4 v76 manifolds, no regime steering. Diversification-only baseline. Sharpe 0.74, MaxDD -6.6%. Beats every v76 variant in the 2017–2026 window — the reference line v76 must clear to justify the steering layer."),
    # V7.6 manifolds (frozen, level-1 of the two-level architecture)
    ("v74d_q",       "v76", "#065f46",
     "M1: V7.4d_q · V7 manifold (transitions / fragmentation)",
     "Manifold 1 (V7) — make_v75_q_signal at α_M=0, include_mom_eigen=False, K=2, τ=2, λ=0.5, with VAIDM × ADD Q polygons. The empirical V7-line sweep winner; identified by spec §3.2 as strong in transitions, boundary instability, regime deformation. Frozen during v76 validation per spec §12.A."),
    ("momentum_12_1","v76", "#a16207",
     "M2: Momentum 12-1 · Persistent-trend manifold",
     "Manifold 2 (Momentum) — classic 12-1 momentum baseline, long-only on assets with positive cumulative return. Spec §3.1: strong in persistent trends and coherent low-vol expansions; weak in violent reversals, fragmentation, transition shocks. Frozen."),
    ("defensive",    "v76", "#0f766e",
     "M3: Defensive · Rupture / collapse manifold",
     "Manifold 3 (Defensive / CHASH) — frozen mix: 40% TN + 20% FGBL + 20% GC + 20% DX. Spec §3.3: strong under rupture, inadmissibility, collapse geometry. Single asset set, no parameters. -19% MaxDD in 2022 rates regime is the system's worst single-manifold blind spot."),
    ("cash",         "v76", "#9ca3af",
     "M4: Cash · Absorbing rest-state",
     "Manifold 4 (Cash) — zero real-asset weights, all CASH. Rolling Sharpe ≡ 0 by construction, so receives meta-allocation only when every other manifold has negative recent Sharpe. The architectural floor for when no admissible geometry exists."),
    # Prior-version references
    ("v74d",         "v75", "#0f766e",
     "V7.4d · Sweep winner (Φ=13, α_M=0, K=2, τ=2, λ=0.5)",
     "V7.4d — the empirical V7.4/V7.5 sweep winner before V7.6. Φ=13 (MOM12_1 dropped), block selection at K=2, τ=2, λ=0.5, momentum_sensitivity=0. Equivalent to v74d_q without Q polygons. Reference for what V7-line could do without meta-steering."),
    ("v74b_template","v75", "#16a34a",
     "V7.4b template · V7.3 continuity anchor (β-gate + Q)",
     "V7.4b in template-block mode with β-gate and VAIDM × ADD Q polygons. The V6.3 → V7.3 → V7.4b lineage anchor. Carries V6.3 short positions through V7.3's β-throttle, so it shorts during commodity-stress regimes — unique vs the long-only v76 lineup."),
    ("v75_no_mom_eigen", "v75", "#3b82f6",
     "V7.5α₁ · Momentum-as-polygon (Φ=13, MOM12_1 dropped)",
     "V7.5α₁ — Momentum lifted out of Φ into the Reference Polygon as a 6th coordinate M. MOM12_1 dropped from Φ (Φ=13). Validated parallel of v74d_q at the time of V7.5 spec; v74d_q later won on the parameter-stability test."),
    ("v73",          "v75", "#f97316",
     "V7.3 · Default (β-gate + Q polygons)",
     "V7.3 default — V6.3 templates × β-gate × VAIDM × ADD Q polygons. The V7-line's first compositional pass; everything from V7.4 onward refines this."),
    # Model-free baselines
    ("equal_weight", "v75", "#2563eb",
     "Equal-weight · 1/N over 13 assets",
     "Naive 1/N over the 13 partner assets, no engine logic, no regime awareness. Lower bound for any reasonable strategy in the partner universe."),
    ("inverse_vol",  "v75", "#d97706",
     "Inverse-vol · 1/σ over 63-day window",
     "Inverse-volatility weighting, σ over 63 days, no engine logic. Risk-parity-flavored model-free baseline."),
    # External reference
    ("sp500",        "v75", "#111827",
     "S&P 500 · Buy-and-hold reference (Yahoo SPY)",
     "S&P 500 buy-and-hold via Yahoo SPY, aligned to the partner forward-pnl index. Not part of the partner universe — included as a market-beta reference for absolute-return context. Hidden from the chart by default since SPY's full-sample 6× crushes the linear y-axis."),
]


# Default visible on the equity chart (everything else stays toggleable).
# We turn on:
#   - the two v76 product candidates
#   - naive 1/4 (the bar v76 must clear)
#   - the four manifolds (so the layering is visible)
#   - equal_weight (lower bound)
# We turn off by default:
#   - v76γ / v76γ-full (negative-result variants, available for inspection)
#   - prior-version references (history, not product)
#   - sp500 (would dominate the y-axis)
DEFAULT_VISIBLE = [
    "v76", "v76b",
    "naive_1_over_4",
    "v74d_q", "momentum_12_1", "defensive", "cash",
    "equal_weight",
]


# Preset time ranges — match the windows used in V76_Findings.md.
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
    """Prefer cached equity; fall back to (1 + returns).cumprod() if absent."""
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
        print(f"[v76] !! skipping {name} — missing files in {out}")
        return None
    return dash.SignalRun(
        name=name, label=label, color=color, info=info,
        summary=summary_row(name, returns),
        returns=returns, equity=equity, weights=weights,
        diagnostics=_load_diagnostics(name, out),
    )


def _build_naive_run(
    manifold_runs: dict[str, dash.SignalRun], info: str,
) -> dash.SignalRun:
    """Naive 1/N blend over the 4 v76 manifolds. Same shape as a SignalRun."""
    columns: set = set()
    for r in manifold_runs.values():
        columns.update(r.weights.columns)
    columns = sorted(columns)

    aligned: list[pd.DataFrame] = []
    common_idx = None
    for r in manifold_runs.values():
        df = r.weights.reindex(columns=columns).fillna(0.0)
        aligned.append(df)
        common_idx = df.index if common_idx is None else common_idx.union(df.index)
    common_idx = common_idx.sort_values()

    n = len(aligned)
    blend = sum(df.reindex(common_idx).fillna(0.0) for df in aligned) / n

    # naive returns = sum of (1/N · manifold returns) — equivalent to applying
    # the naive weights to forward_pnl, since the underlying manifold returns
    # already encode that mapping.
    naive_ret = sum(r.returns.reindex(common_idx).fillna(0.0)
                    for r in manifold_runs.values()) / n
    naive_eq = (1.0 + naive_ret).cumprod()

    return dash.SignalRun(
        name="naive_1_over_4",
        label="Naive 1/4 · Equal-weight 4-manifold blend",
        color="#374151",
        info=info,
        summary=summary_row("naive_1_over_4", naive_ret),
        returns=naive_ret, equity=naive_eq, weights=blend,
    )


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--v76-output", type=Path, default=DEFAULT_V76_OUT)
    p.add_argument("--v75-output", type=Path, default=DEFAULT_V75_OUT)
    p.add_argument("--title", default="PolyAgora V7.6 — Meta-Regime Steering Layer")
    p.add_argument("--weights-signal", default="v76",
                   help="Which signal to render in the weights stack by default")
    args = p.parse_args()

    if not args.v76_output.exists():
        p.error(f"v76 output dir {args.v76_output} does not exist — run `python run_v76_check.py` first")
    if not args.v75_output.exists():
        p.error(f"v75 output dir {args.v75_output} does not exist — run `python build_polyagora.py --v75` first")

    naive_info = next((info for n, _, _, _, info in LINEUP if n == "naive_1_over_4"), "")
    naive_color = next((color for n, _, color, _, _ in LINEUP if n == "naive_1_over_4"), "#374151")
    naive_label = next((label for n, _, _, label, _ in LINEUP if n == "naive_1_over_4"), "Naive 1/4")
    manifold_runs: dict[str, dash.SignalRun] = {}
    runs: list[dash.SignalRun] = []

    for name, src, color, label, info in LINEUP:
        if name == "naive_1_over_4":
            continue  # built after manifolds are loaded
        out = args.v76_output if src == "v76" else args.v75_output
        r = _build_run(name, label, color, info, out)
        if r is None:
            continue
        runs.append(r)
        if name in ("v74d_q", "momentum_12_1", "defensive", "cash"):
            manifold_runs[name] = r

    # Synthetic naive 1/4 run, inserted right after the v76γ variants per
    # LINEUP's display order.
    if len(manifold_runs) == 4:
        naive_run = _build_naive_run(manifold_runs, naive_info)
        # Splice naive into the LINEUP-order position
        naive_pos = next(i for i, e in enumerate(LINEUP) if e[0] == "naive_1_over_4")
        # Count how many earlier-in-LINEUP entries actually made it into runs
        earlier_names = {e[0] for e in LINEUP[:naive_pos]}
        insert_at = sum(1 for r in runs if r.name in earlier_names)
        runs.insert(insert_at, naive_run)
    else:
        print(f"[v76] !! naive_1_over_4 skipped — manifolds present: {sorted(manifold_runs)}")

    if not runs:
        p.error("no runs assembled — check that v76 and v75 output dirs contain CSVs")

    print(f"[v76] composed {len(runs)} runs: {[r.name for r in runs]}")

    html_path, json_path = dash.write_dashboard(
        runs,
        universe=list(UNIVERSE) + [CASH],
        output_dir=args.v76_output,
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
