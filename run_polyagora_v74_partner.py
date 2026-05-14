"""
Runner for PolyAgora V7.4 — Strategy Manifold V1.

Implements the engine described in
`docs/PolyAgora_Strategy_Manifold_V1.pdf`. Strategies are eigenfields
inside the Reference Polygon; allocation is admissibility × Local Star
× zone-gross × Driver Seat. The 14-stream universe is the 13 partner
assets + a synthetic Momentum 12-1 stream.

Reads `Agur/baseline_pnl_partner_delivery.xlsx`, builds weight panels
for V7.4 (with 5 driver presets) plus V6.3 / V7.3 baselines and
model-free baselines, scores each on `forward_pnl`, and writes outputs
to `polyagora_v74_outputs/` plus a self-contained `dashboard.html`.

This file is engine orchestration only. The engine itself lives in
`polyagora_v74_engine.py`; presentation lives in `polyagora_dashboard.py`.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

import polyagora_dashboard as dash
from polyagora_v63_partner_engine import (
    CASH,
    EngineConfig,
    PartnerData,
    PolyagoraGateConfig,
    UNIVERSE,
    compute_weights,
    equal_weight_signal,
    evaluate,
    inverse_vol_signal,
    load_partner_xlsx,
    make_polyagora_signal,
    make_polyagora_signal_gated,
    momentum_signal,
    summary_row,
)
from polyagora_v73_engine import (
    QPolygonConfig,
    V73DriverConfig,
    make_v73_signal,
)
from polyagora_v74_engine import (
    V74DriverConfig,
    make_v74_signal,
)
from polyagora_v74b_engine import (
    V74bDriverConfig,
    make_v74b_signal,
)
from polyagora_v75_engine import (
    V75DriverConfig,
    make_v75_q_signal,
    make_v75_short_signal,
    make_v75_signal,
)


# V7.4 / V7.4b Driver Seat presets — five named PM configurations of the
# manifold dials. Default reduces to the spec defaults (no deformation).
# V7.4b shares the same dials; soft-manifold params (K, τ, λ) are engine
# factory args, not driver dials.
DRIVER_PRESETS: dict[str, V74DriverConfig] = {
    "default":   V74DriverConfig(),
    "defensive": V74DriverConfig(boundary_sensitivity=1.5,
                                 defensive_preference=0.5),
    "carry":     V74DriverConfig(carry_preference=0.5),
    "convex":    V74DriverConfig(convexity_preference=0.5),
    "active":    V74DriverConfig(recovery_aggression=2.0),
}


ROOT = Path(__file__).resolve().parent
DEFAULT_INPUT = ROOT / "Agur" / "baseline_pnl_partner_delivery.xlsx"
DEFAULT_OUTPUT = ROOT / "polyagora_v74_outputs"
DEFAULT_MARKET = ROOT / "market_data" / "market_yahoo_vix_spy_hyg_tlt_gld_cper.csv"
SP500_REFERENCE_CSV = ROOT / "market_data" / "sp500_reference.csv"


SIGNAL_COLORS: dict[str, str] = {
    "v75_short":        "#7c3aed",  # V7.5 short-capable hybrid (v74d_q + v74b_template)
    "sp500":            "#111827",  # S&P 500 buy-and-hold reference (Yahoo SPY)
    "v74d_q":           "#065f46",  # V7.4d + VAIDM × ADD Q polygons
    "v74d":             "#0f766e",  # V7.4d — empirical sweep winner (Φ=13, K=2, τ=2, λ=0.5)
    "v75":              "#1e3a8a",  # V7.5α₁ — Momentum-as-Polygon-Coordinate
    "v75_no_mom_eigen": "#3b82f6",  # V7.5α₁ — MOM12_1 dropped from Φ
    "v74b_template": "#16a34a",   # V7.4c continuity anchor (v73-equivalent)
    "v74b_plateau":  "#0ea5e9",   # V7.4c production default (plateau center)
    "v74b":           "#b91c1c",
    "v74b_defensive": "#7c2d12",
    "v74b_carry":     "#0e7490",
    "v74b_convex":    "#7e22ce",
    "v74b_active":    "#9d174d",
    "v74b_graph":     "#a21caf",
    "v74b_static":    "#6d28d9",
    "v74":           "#dc2626",
    "v73":           "#f97316",
    "polyagora_gated": "#15803d",
    "polyagora":       "#10b981",
    "equal_weight":  "#2563eb",
    "inverse_vol":   "#d97706",
    "momentum_12_1": "#a16207",
}

SIGNAL_LABELS: dict[str, str] = {
    "v75_short":        "V7.5 · Short-capable hybrid (50% v74d_q + 50% v74b_template)",
    "sp500":            "S&P 500 · Buy-and-hold reference (Yahoo SPY)",
    "v74d_q":           "V7.4d · with VAIDM × ADD Q polygons",
    "v74d":             "V7.4d · Sweep winner (Φ = 13, K=2, τ=2, λ=0.5, α_M=0)",
    "v75":              "V7.5α₁ · Momentum-as-polygon (Φ = 14, MOM12_1 retained)",
    "v75_no_mom_eigen": "V7.5α₁ · Momentum-as-polygon (Φ = 13, MOM12_1 dropped)",
    "v74b_template": "V7.4c · Template (v73 recovery anchor)",
    "v74b_plateau":  "V7.4c · Plateau center (production default)",
    "v74b":           "V7.4b · Default (category, zone gate)",
    "v74b_defensive": "V7.4b · Defensive",
    "v74b_carry":     "V7.4b · Carry",
    "v74b_convex":    "V7.4b · Convex",
    "v74b_active":    "V7.4b · Active recovery",
    "v74b_graph":     "V7.4b · Graph blocks (spec §1.8)",
    "v74b_static":    "V7.4b · Static blocks",
    "v74":           "V7.4 · Hard mask",
    "v73":           "V7.3 · Default",
    "polyagora_gated": "V6.3 baseline (gated)",
    "polyagora":       "V6.3 baseline (raw)",
    "equal_weight":  "Equal-weight",
    "inverse_vol":   "Inverse-vol",
    "momentum_12_1": "Momentum 12-1",
}


def build_signal_registry(
    market_csv: Path,
    data: PartnerData,
    gate_cfg: PolyagoraGateConfig | None = None,
    q_cfg: QPolygonConfig | None = None,
) -> dict:
    """V7.4 registry: V7.4 (5 presets) + V7.3 default + V6.3 + model-free.

    V7.4 needs the V6.2 market CSV to construct X_t; if it's missing we fall
    back to V6.3 and model-free baselines only.
    """
    registry = {
        "equal_weight": equal_weight_signal,
        "inverse_vol":  inverse_vol_signal,
        "momentum_12_1": momentum_signal,
    }
    if not market_csv.exists():
        return registry

    market = pd.read_csv(market_csv, parse_dates=["date"]).set_index("date")
    registry["polyagora"] = make_polyagora_signal(market)
    registry["polyagora_gated"] = make_polyagora_signal_gated(
        market, data.realized_pnl, gate_cfg=gate_cfg
    )
    # V7.3 default for cross-version comparison on the dashboard.
    registry["v73"] = make_v73_signal(
        market, data.realized_pnl,
        drivers=V73DriverConfig(), q_cfg=q_cfg, gate_cfg=gate_cfg,
    )
    # V7.4 — kept as the "hard manifold" comparison baseline (default only).
    registry["v74"] = make_v74_signal(
        market, data.realized_pnl, drivers=V74DriverConfig(),
    )
    # V7.4b — soft manifold (the active line). Defaults: block_source="category",
    # K=2, τ=4, λ=0.6.
    for preset_name, drivers in DRIVER_PRESETS.items():
        sig_name = "v74b" if preset_name == "default" else f"v74b_{preset_name}"
        registry[sig_name] = make_v74b_signal(
            market, data.realized_pnl, drivers=drivers,
        )
    # Block-source sweeps: graph (spec §1.8) and static (v74-style) for comparison.
    registry["v74b_graph"] = make_v74b_signal(
        market, data.realized_pnl, drivers=V74bDriverConfig(),
        block_source="graph", theta_s=0.65,
    )
    registry["v74b_static"] = make_v74b_signal(
        market, data.realized_pnl, drivers=V74bDriverConfig(),
        block_source="static",
    )
    # V7.4c findings:
    #   - "plateau center" — Test 4 recommended production default
    #     (category K=2 τ=4 λ=0.5), chosen for parameter-surface robustness
    #     over peak Sharpe.
    #   - "template" — Test 1 continuity anchor recovering V7.3 within
    #     spec tolerance (template K=5 β +Q). Empirically Sharpe-equivalent
    #     to V7.3 in-sample, slightly better OOS (Test 6).
    registry["v74b_plateau"] = make_v74b_signal(
        market, data.realized_pnl, drivers=V74bDriverConfig(),
        block_source="category", top_k=2, tau=4.0, lam=0.5,
    )
    registry["v74b_template"] = make_v74b_signal(
        market, data.realized_pnl, drivers=V74bDriverConfig(),
        block_source="template", top_k=5,
        gate_mode="beta", q_cfg=q_cfg or QPolygonConfig(),
    )
    # V7.5α₁ — Momentum-as-Polygon-Coordinate. Two parallel variants per
    # `docs/PolyAgora_V7_5_Spec.md` §9 — the empirical winner becomes V7.5 default.
    registry["v75"] = make_v75_signal(
        market, data.realized_pnl, drivers=V75DriverConfig(),
        include_mom_eigen=True,
    )
    registry["v75_no_mom_eigen"] = make_v75_signal(
        market, data.realized_pnl, drivers=V75DriverConfig(),
        include_mom_eigen=False,
    )
    # V7.4d — empirical Test 4 sweep winner. V7.5α₁ contributed only the
    # *negative* finding (M in RP doesn't help, α_M=0 wins). The *positive*
    # finding is V7.4c machinery with MOM12_1 dropped from Φ and the softer
    # block-selection settings (K=2, τ=2, λ=0.5). Implemented via the V7.5
    # engine at α_M=0 since that path subsumes V7.4b with Φ=13.
    registry["v74d"] = make_v75_signal(
        market, data.realized_pnl,
        drivers=V75DriverConfig(momentum_sensitivity=0.0),
        include_mom_eigen=False,
        top_k=2, tau=2.0, lam=0.5,
    )
    # V7.4d + V7.3 Q polygons (VAIDM × ADD). Q polygons multiply the final
    # weight vector as a gross-exposure scalar — they don't alter asset
    # selection. VAIDM gates on cross-sectional dispersion; ADD on realized
    # equal-weight drawdown. Buffett stays disabled (no external feed).
    registry["v74d_q"] = make_v75_q_signal(
        market, data.realized_pnl,
        drivers=V75DriverConfig(momentum_sensitivity=0.0),
        q_cfg=q_cfg or QPolygonConfig(),
        include_mom_eigen=False,
        top_k=2, tau=2.0, lam=0.5,
    )
    # V7.5 short-capable hybrid — blends V7.4d_q (latest manifold long) with
    # V7.4b_template (V6.3 templates carrying shorts). Brings back negative
    # allocations while keeping VAIDM + ADD + V7.4d parameter tuning intact.
    registry["v75_short"] = make_v75_short_signal(
        market, data.realized_pnl,
        drivers=V75DriverConfig(momentum_sensitivity=0.0),
        q_cfg=q_cfg or QPolygonConfig(),
        alpha=0.5,
    )
    return registry


def run_signal(
    name: str,
    signal_fn,
    data: PartnerData,
    cfg: EngineConfig,
    output_dir: Path,
) -> dash.SignalRun:
    """Compute weights, evaluate, write CSV side-files, return a SignalRun."""
    weights = compute_weights(data, signal_fn, cfg)

    # Capital-budget invariant: sum(|w_real|) + w_cash == gross_cap.
    budget_used = weights.abs().sum(axis=1)
    breach = (budget_used.sub(cfg.gross_cap).abs() > 1e-6).sum()
    if breach:
        print(f"[warn] {name}: {breach} rows where capital budget != {cfg.gross_cap}")

    res = evaluate(weights, data.forward_pnl)
    weights.to_csv(output_dir / f"weights_{name}.csv", index_label="trading_date")
    res.returns.to_csv(output_dir / f"returns_{name}.csv", index_label="trading_date")
    res.equity.to_csv(output_dir / f"equity_{name}.csv", index_label="trading_date")
    print(f"[ok] {name}: wrote weights/returns/equity to {output_dir}")

    diagnostics = None
    weights_mom: pd.DataFrame | None = None
    if hasattr(signal_fn, "diagnostics_df"):
        diagnostics = signal_fn.diagnostics_df()
        if not diagnostics.empty:
            diagnostics.to_csv(output_dir / f"diagnostics_{name}.csv", index_label="trading_date")
            # Per-asset MOM contribution — present only for v74/v74b
            # strategy-eigenfield signals where MOM12-1 participates in Φ.
            mom_cols = [c for c in diagnostics.columns if c.startswith("mom_")]
            if mom_cols:
                weights_mom = diagnostics[mom_cols].rename(
                    columns={c: c[4:] for c in mom_cols}
                )
                # Align to the weights panel's index and fill missing.
                weights_mom = weights_mom.reindex(weights.index).fillna(0.0)
                weights_mom.to_csv(
                    output_dir / f"weights_{name}_mom.csv",
                    index_label="trading_date",
                )

    return dash.SignalRun(
        name=name,
        label=SIGNAL_LABELS.get(name, name),
        color=SIGNAL_COLORS.get(name),
        summary=summary_row(name, res.returns),
        returns=res.returns,
        equity=res.equity,
        weights=weights,
        diagnostics=diagnostics,
        weights_mom=weights_mom,
    )


def _build_sp500_reference_run(
    sp500_csv: Path,
    forward_index: pd.DatetimeIndex,
    output_dir: Path,
) -> dash.SignalRun | None:
    """Build an S&P 500 buy-and-hold reference SignalRun.

    Returns None if `sp500_csv` is missing — keeps `run()` callable in
    environments without the Yahoo-fetched reference series. The reference
    is aligned to `forward_index` (partner trading dates) and contributes
    only an equity / drawdown curve to the dashboard — weights are zero
    (the S&P 500 is not in the partner universe).
    """
    if not sp500_csv.exists():
        print(f"[info] S&P 500 reference missing at {sp500_csv} — skipping")
        return None
    prices = pd.read_csv(sp500_csv, parse_dates=["date"]).set_index("date").iloc[:, 0]
    prices = prices.reindex(forward_index, method="ffill").dropna()
    rets = prices.pct_change().fillna(0.0)
    equity = (1.0 + rets).cumprod()
    # Zero weights across the partner universe — SPY isn't in Φ. CASH = 1 so
    # `compute_weights`-style budget invariants still hold.
    universe_cols = [c for c in list(UNIVERSE) + [CASH]]
    weights = pd.DataFrame(0.0, index=forward_index, columns=universe_cols)
    weights[CASH] = 1.0
    rets.to_frame("portfolio_return").to_csv(output_dir / "returns_sp500.csv",
                                             index_label="trading_date")
    equity.to_frame("portfolio_equity").to_csv(output_dir / "equity_sp500.csv",
                                               index_label="trading_date")
    weights.to_csv(output_dir / "weights_sp500.csv", index_label="trading_date")
    print(f"[ok] sp500: aligned {len(prices)} rows to partner index, "
          f"{prices.index.min().date()} → {prices.index.max().date()}")
    return dash.SignalRun(
        name="sp500",
        label=SIGNAL_LABELS.get("sp500", "S&P 500"),
        color=SIGNAL_COLORS.get("sp500"),
        summary=summary_row("sp500", rets),
        returns=rets,
        equity=equity,
        weights=weights,
    )


def run(
    *,
    input_path: Path = DEFAULT_INPUT,
    output_dir: Path = DEFAULT_OUTPUT,
    market_csv: Path = DEFAULT_MARKET,
    signal_filter: str = "all",
    title: str = "PolyAgora V7.4c — Validated Strategy Manifold",
    default_weights_signal: str = "v74b_plateau",
    default_visible_signals: list[str] | None = None,
) -> pd.DataFrame:
    """Compute the full V7.4 signal registry, write CSVs + dashboard, return summary.

    Programmatic entry point shared by `main()` (CLI) and
    `build_polyagora.py` (which wraps this with --refresh / --v75).

    `title`, `default_weights_signal`, `default_visible_signals` let callers
    re-skin the dashboard (e.g. V7.5 mode) without touching the registry.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    data = load_partner_xlsx(input_path)
    cfg = EngineConfig()
    gate_cfg = PolyagoraGateConfig()

    signals = build_signal_registry(market_csv, data, gate_cfg=gate_cfg)
    valid_filters = {"all", "sp500", *signals.keys()}  # sp500 is an external reference
    if signal_filter not in valid_filters:
        raise ValueError(f"unknown signal {signal_filter!r}; have {sorted(valid_filters)}")

    if signal_filter == "all":
        selected = list(signals)
    elif signal_filter == "sp500":
        selected = []  # sp500 is added below; no internal signal to run
    else:
        selected = [signal_filter]
    runs = [run_signal(name, signals[name], data, cfg, output_dir) for name in selected]

    # External reference: S&P 500 buy-and-hold (Yahoo SPY), aligned to the
    # partner forward-PnL index. Skipped silently if the CSV isn't present.
    if signal_filter in {"all", "sp500"}:
        sp500_run = _build_sp500_reference_run(
            SP500_REFERENCE_CSV, data.forward_pnl.index, output_dir,
        )
        if sp500_run is not None:
            runs.append(sp500_run)

    summary_df = pd.DataFrame([r.summary for r in runs])
    summary_df.to_csv(output_dir / "summary_v74.csv", index=False)

    preset_table = []
    for preset_name, dr in DRIVER_PRESETS.items():
        sig_name = "v74b" if preset_name == "default" else f"v74b_{preset_name}"
        preset_table.append({
            "name": preset_name,
            "signal": sig_name,
            "label": SIGNAL_LABELS.get(sig_name, sig_name),
            "color": SIGNAL_COLORS.get(sig_name, "#000000"),
            "convexity_preference": dr.convexity_preference,
            "carry_preference": dr.carry_preference,
            "defensive_preference": dr.defensive_preference,
            "boundary_sensitivity": dr.boundary_sensitivity,
            "recovery_aggression": dr.recovery_aggression,
        })

    default_visible = default_visible_signals or [
        "equal_weight",
        "v74b_plateau",
        "v74b_template",
        "v75",
        "v75_no_mom_eigen",
        "v74d",
        "v74d_q",
        "v75_short",
    ]
    # sp500 stays available in the legend but off by default — its 6× total
    # return otherwise crushes the linear Y-axis of partner-strategy curves.

    html_path, _ = dash.write_dashboard(
        runs,
        universe=list(UNIVERSE) + [CASH],
        output_dir=output_dir,
        title=title,
        default_weights_signal=default_weights_signal,
        default_visible_signals=default_visible,
        driver_presets=preset_table,
    )
    print(f"[ok] dashboard: {html_path}")
    print()
    print(summary_df.to_string(index=False))
    return summary_df


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--market", type=Path, default=DEFAULT_MARKET)
    parser.add_argument(
        "--signal",
        default="all",
        help="Which signal(s) to run: equal_weight, inverse_vol, momentum_12_1, "
             "polyagora, polyagora_gated, v73, v74, v74_<preset>, or all.",
    )
    args = parser.parse_args()

    try:
        run(
            input_path=args.input,
            output_dir=args.output,
            market_csv=args.market,
            signal_filter=args.signal,
        )
    except ValueError as e:
        parser.error(str(e))


if __name__ == "__main__":
    main()
