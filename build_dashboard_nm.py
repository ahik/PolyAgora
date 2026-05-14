"""
Build a 'no momentum' dashboard variant — `dashboard_nm.html`.

Loads the existing per-signal CSVs from `polyagora_v75_outputs/`,
reconstructs `SignalRun` objects, drops `momentum_12_1` from the displayed
set (it remains computed and on disk — only hidden from this variant), and
emits `dashboard_nm.html` + `dashboard_nm_data.json` alongside the main
dashboard.

Re-runs no engine code — purely a re-render of artifacts already generated
by `build_polyagora.py`. Run `build_polyagora.py --v75` first if the
underlying CSVs are stale.

Usage:
    python build_dashboard_nm.py
    python build_dashboard_nm.py --output polyagora_v74_outputs   # V7.4 layout
    python build_dashboard_nm.py --hide momentum_12_1,v74b_graph  # custom filter
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

import polyagora_dashboard as dash
from polyagora_v63_partner_engine import CASH, UNIVERSE, summary_row
from run_polyagora_v74_partner import (
    DRIVER_PRESETS,
    SIGNAL_COLORS,
    SIGNAL_LABELS,
)


ROOT = Path(__file__).resolve().parent
DEFAULT_OUT = ROOT / "polyagora_v75_outputs"
DEFAULT_HIDE = "momentum_12_1"


def _load_run(name: str, out: Path) -> dash.SignalRun | None:
    weights_p = out / f"weights_{name}.csv"
    returns_p = out / f"returns_{name}.csv"
    equity_p = out / f"equity_{name}.csv"
    if not (weights_p.exists() and returns_p.exists() and equity_p.exists()):
        return None
    weights = pd.read_csv(weights_p, parse_dates=["trading_date"]).set_index("trading_date")
    returns = (
        pd.read_csv(returns_p, parse_dates=["trading_date"]).set_index("trading_date").iloc[:, 0]
    )
    equity = (
        pd.read_csv(equity_p, parse_dates=["trading_date"]).set_index("trading_date").iloc[:, 0]
    )
    diag = None
    diag_p = out / f"diagnostics_{name}.csv"
    if diag_p.exists():
        diag = pd.read_csv(diag_p, parse_dates=["trading_date"]).set_index("trading_date")
    weights_mom = None
    mom_p = out / f"weights_{name}_mom.csv"
    if mom_p.exists():
        weights_mom = pd.read_csv(mom_p, parse_dates=["trading_date"]).set_index("trading_date")
    return dash.SignalRun(
        name=name,
        label=SIGNAL_LABELS.get(name, name),
        color=SIGNAL_COLORS.get(name),
        summary=summary_row(name, returns),
        returns=returns,
        equity=equity,
        weights=weights,
        diagnostics=diag,
        weights_mom=weights_mom,
    )


def _all_signal_names(out: Path) -> list[str]:
    """Discover signals present on disk by scanning `weights_*.csv` (excluding _mom variants)."""
    names: set[str] = set()
    for p in out.glob("weights_*.csv"):
        stem = p.stem  # 'weights_<name>'
        if stem.endswith("_mom"):
            continue
        names.add(stem[len("weights_") :])
    return sorted(names)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUT,
                        help="Directory containing existing CSVs (default: %(default)s)")
    parser.add_argument("--hide", default=DEFAULT_HIDE,
                        help="Comma-separated signals to omit from display "
                             "(default: %(default)s)")
    parser.add_argument("--filename", default="dashboard_nm",
                        help="Output stem; emits <stem>.html + <stem>_data.json "
                             "(default: %(default)s)")
    parser.add_argument("--title", default="PolyAgora V7.5α₁ — Sweep findings (no momentum_12_1 display)",
                        help="Dashboard title")
    parser.add_argument("--weights-signal", default="v74d",
                        help="Which signal's weights to render on first load (default: %(default)s)")
    args = parser.parse_args()

    out = args.output
    if not out.exists():
        parser.error(f"output dir {out} does not exist — run `python build_polyagora.py --v75` first")

    hide = {s.strip() for s in args.hide.split(",") if s.strip()}
    all_names = _all_signal_names(out)
    displayed = [n for n in all_names if n not in hide]
    if not displayed:
        parser.error(f"no signals left to display after hiding {sorted(hide)}")

    print(f"[nm] found {len(all_names)} signals on disk: {all_names}")
    print(f"[nm] hiding from display: {sorted(hide)}")
    print(f"[nm] displaying {len(displayed)} signals: {displayed}")

    runs = []
    for name in displayed:
        r = _load_run(name, out)
        if r is None:
            print(f"[nm]   ! skipping {name} — missing CSV files")
            continue
        runs.append(r)

    # Driver-Seat preset table — match the regular dashboard.
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

    default_visible = [
        "equal_weight",
        "v74b_plateau",
        "v74b_template",
        "v75",
        "v75_no_mom_eigen",
        "v74d",
    ]
    default_visible = [s for s in default_visible if s not in hide]

    # Pick a sensible default-weights signal if the user's choice was hidden.
    weights_signal = args.weights_signal
    if weights_signal in hide:
        weights_signal = next((s for s in displayed if s in default_visible), displayed[0])

    html_path, json_path = dash.write_dashboard(
        runs,
        universe=list(UNIVERSE) + [CASH],
        output_dir=out,
        title=args.title,
        default_weights_signal=weights_signal,
        default_visible_signals=default_visible,
        driver_presets=preset_table,
        filename_stem=args.filename,
    )
    print(f"[ok] {html_path}")
    print(f"[ok] {json_path}")


if __name__ == "__main__":
    main()
