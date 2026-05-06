"""
Runner for PolyAgora V6.3 — Partner-Delivery Allocation.

Reads `Agur/baseline_pnl_partner_delivery.xlsx`, builds weight panels for a
set of baseline signals, scores each on `forward_pnl`, and writes outputs to
`polyagora_v63_partner_outputs/` plus a self-contained `dashboard.html`.

This file is **engine orchestration only**. Presentation lives in
`polyagora_dashboard.py` + `dashboard_template.html` and is engine-agnostic.
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


ROOT = Path(__file__).resolve().parent
DEFAULT_INPUT = ROOT / "Agur" / "baseline_pnl_partner_delivery.xlsx"
DEFAULT_OUTPUT = ROOT / "polyagora_v63_partner_outputs"
DEFAULT_MARKET = ROOT / "polyagora_v62_yahoo_outputs" / "market_yahoo_vix_spy_hyg_tlt_gld_cper.csv"


# Per-signal display config — purely cosmetic, lives with the runner since
# the runner is what knows which signals it builds.
SIGNAL_COLORS = {
    "polyagora_gated": "#15803d",
    "polyagora": "#10b981",
    "equal_weight": "#2563eb",
    "inverse_vol": "#d97706",
    "momentum_12_1": "#9333ea",
}

SIGNAL_LABELS = {
    "polyagora_gated": "PolyAgora V6.3 gated",
    "polyagora": "PolyAgora V6.3 raw",
    "equal_weight": "Equal-weight",
    "inverse_vol": "Inverse-vol",
    "momentum_12_1": "Momentum 12-1",
}


def build_signal_registry(
    market_csv: Path,
    data: PartnerData,
    gate_cfg: PolyagoraGateConfig | None = None,
) -> dict:
    registry = {
        "equal_weight": equal_weight_signal,
        "inverse_vol": inverse_vol_signal,
        "momentum_12_1": momentum_signal,
    }
    if market_csv.exists():
        market = pd.read_csv(market_csv, parse_dates=["date"]).set_index("date")
        registry["polyagora"] = make_polyagora_signal(market)
        registry["polyagora_gated"] = make_polyagora_signal_gated(
            market, data.realized_pnl, gate_cfg=gate_cfg
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

    return dash.SignalRun(
        name=name,
        label=SIGNAL_LABELS.get(name, name),
        color=SIGNAL_COLORS.get(name),
        summary=summary_row(name, res.returns),
        returns=res.returns,
        equity=res.equity,
        weights=weights,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--market", type=Path, default=DEFAULT_MARKET)
    parser.add_argument(
        "--signal",
        default="all",
        help="Which signal(s) to run: equal_weight, inverse_vol, momentum_12_1, polyagora, or all.",
    )
    parser.add_argument(
        "--beta-halflife",
        type=float,
        default=None,
        help="Override PolyagoraGateConfig.beta_smoothing_halflife (default: 3.0).",
    )
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)
    data = load_partner_xlsx(args.input)
    cfg = EngineConfig()

    gate_cfg = PolyagoraGateConfig()
    if args.beta_halflife is not None:
        gate_cfg.beta_smoothing_halflife = args.beta_halflife

    signals = build_signal_registry(args.market, data, gate_cfg=gate_cfg)
    if args.signal not in {"all", *signals.keys()}:
        parser.error(f"unknown signal {args.signal!r}; have {sorted(signals)}")

    selected = list(signals) if args.signal == "all" else [args.signal]

    runs = [run_signal(name, signals[name], data, cfg, args.output) for name in selected]

    summary_df = pd.DataFrame([r.summary for r in runs])
    summary_df.to_csv(args.output / "summary_v63_partner.csv", index=False)

    html_path, _ = dash.write_dashboard(
        runs,
        universe=list(UNIVERSE) + [CASH],
        output_dir=args.output,
        title="PolyAgora V6.3 — Partner Delivery",
        default_weights_signal="polyagora",
    )
    print(f"[ok] dashboard: {html_path}")

    print()
    print(summary_df.to_string(index=False))


if __name__ == "__main__":
    main()
