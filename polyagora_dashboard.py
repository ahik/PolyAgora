"""
PolyAgora dashboard — presentation layer.

Engine-agnostic. Consumes a list of `SignalRun` records (one per backtest
signal) and emits a self-contained `dashboard.html` plus a sidecar
`dashboard_data.json`. The HTML template is a separate file
(`dashboard_template.html`) so it can be edited independently of any engine.

Typical wiring from a runner:

    import polyagora_dashboard as dash

    runs = []
    for name in selected:
        weights = compute_weights(...)
        res = evaluate(weights, data.forward_pnl)
        runs.append(dash.SignalRun(
            name=name,
            label=labels.get(name, name),
            color=colors.get(name),
            summary=summary_row(name, res.returns),
            returns=res.returns,
            equity=res.equity,
            weights=weights,
        ))

    dash.write_dashboard(
        runs,
        universe=list(UNIVERSE) + [CASH],
        output_dir=Path("outputs"),
        title="PolyAgora V6.3",
        asset_colors=ASSET_COLORS,
        default_weights_signal="polyagora",
    )

CLI re-render (no engine run needed):

    python -m polyagora_dashboard --data outputs/dashboard_data.json \\
        --template dashboard_template.html --out outputs/dashboard.html
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable

import pandas as pd


DEFAULT_TEMPLATE_PATH = Path(__file__).resolve().parent / "dashboard_template.html"

# Distinct asset palette for the weight stack. Engines may pass an override
# into `write_dashboard` / `build_payload`; this dict is the fallback.
DEFAULT_ASSET_COLORS: dict[str, str] = {
    "BTC":  "#f59e0b",
    "CL":   "#1f2937",
    "DX":   "#0ea5e9",
    "ES":   "#15803d",
    "FESX": "#22c55e",
    "FGBL": "#7c3aed",
    "GC":   "#eab308",
    "HG":   "#b45309",
    "NKD":  "#dc2626",
    "SI":   "#9ca3af",
    "TN":   "#6366f1",
    "ZS":   "#84cc16",
    "ZW":   "#a16207",
    "CASH": "#cbd5e1",
}

DEFAULT_FALLBACK_COLOR = "#475569"


@dataclass
class SignalRun:
    """One signal's results from a backtest. Engine-agnostic shape."""
    name: str
    summary: dict                    # output of summary_row(name, returns)
    returns: pd.Series               # daily portfolio returns
    equity: pd.Series                # cumulative equity curve
    weights: pd.DataFrame            # date x (real_assets + CASH)
    label: str | None = None         # display name; defaults to `name`
    color: str | None = None         # hex; defaults to a shared fallback


def _series_points(s: pd.Series, decimals: int = 6) -> list[dict]:
    """Compress a Series to [{d: ISO, v: float}, ...], dropping NaNs."""
    out = []
    for d, v in s.items():
        if pd.isna(v):
            continue
        out.append({"d": d.strftime("%Y-%m-%d"), "v": round(float(v), decimals)})
    return out


def _weights_payload(weights: pd.DataFrame, columns: list[str]) -> list[dict]:
    """Compress a weights DataFrame to per-row dicts over `columns`."""
    rows = []
    for d, row in weights.iterrows():
        entry: dict = {"d": d.strftime("%Y-%m-%d")}
        for asset in columns:
            entry[asset] = round(float(row[asset]), 6) if asset in weights.columns else 0.0
        rows.append(entry)
    return rows


def build_payload(
    runs: Iterable[SignalRun],
    universe: list[str],
    *,
    asset_colors: dict[str, str] | None = None,
    default_weights_signal: str | None = None,
) -> dict:
    """Build the JSON payload consumed by `dashboard_template.html`.

    Parameters
    ----------
    runs : iterable of SignalRun
        One per signal. Order is preserved in summary table & legends.
    universe : list[str]
        Full column order for the weights stack (real assets + CASH).
    asset_colors : dict, optional
        Per-asset hex colors. Defaults merged with module DEFAULT_ASSET_COLORS.
    default_weights_signal : str, optional
        Which signal the weights chart selects on first render. If None or
        not present in `runs`, the dashboard falls back to the first signal.
    """
    runs = list(runs)
    colors = {**DEFAULT_ASSET_COLORS, **(asset_colors or {})}

    curves: list[dict] = []
    drawdowns: list[dict] = []
    weights_panels: dict[str, list[dict]] = {}
    formatted_summary: list[dict] = []

    for r in runs:
        label = r.label or r.name
        color = r.color or DEFAULT_FALLBACK_COLOR

        curves.append({
            "name": r.name, "label": label, "color": color,
            "points": _series_points(r.equity, decimals=5),
        })
        dd = r.equity / r.equity.cummax() - 1.0
        drawdowns.append({
            "name": r.name, "label": label, "color": color,
            "points": _series_points(dd, decimals=5),
        })
        weights_panels[r.name] = _weights_payload(r.weights, universe)

        s = r.summary
        formatted_summary.append({
            "name": s.get("Series", r.name),
            "label": label,
            "color": color,
            "totalReturn": s.get("Total return"),
            "cagr": s.get("CAGR"),
            "vol": s.get("Ann. vol"),
            "sharpe": s.get("Sharpe"),
            "maxDrawdown": s.get("Max drawdown"),
        })

    # Date window union across equity curves.
    all_dates: list = []
    for r in runs:
        all_dates.extend(r.equity.index)
    if all_dates:
        min_date = min(all_dates).strftime("%Y-%m-%d")
        max_date = max(all_dates).strftime("%Y-%m-%d")
    else:
        min_date = max_date = ""

    return {
        "generatedAt": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "minDate": min_date,
        "maxDate": max_date,
        "universe": list(universe),
        "assetColors": colors,
        "defaultWeightsSignal": default_weights_signal,
        "summary": formatted_summary,
        "curves": curves,
        "drawdowns": drawdowns,
        "weights": weights_panels,
    }


def render_html(
    payload: dict,
    *,
    title: str = "PolyAgora",
    template_path: Path | None = None,
) -> str:
    """Substitute payload + title into the HTML template."""
    template_path = Path(template_path) if template_path else DEFAULT_TEMPLATE_PATH
    template = template_path.read_text()
    html = template.replace("__TITLE__", title)
    html = html.replace("__DATA__", json.dumps(payload, separators=(",", ":")))
    return html


def write_dashboard(
    runs: Iterable[SignalRun],
    universe: list[str],
    output_dir: Path | str,
    *,
    title: str = "PolyAgora",
    asset_colors: dict[str, str] | None = None,
    default_weights_signal: str | None = None,
    template_path: Path | None = None,
) -> tuple[Path, Path]:
    """Write `dashboard.html` + `dashboard_data.json` into `output_dir`.

    Returns (html_path, json_path).
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    payload = build_payload(
        runs, universe,
        asset_colors=asset_colors,
        default_weights_signal=default_weights_signal,
    )
    json_path = output_dir / "dashboard_data.json"
    html_path = output_dir / "dashboard.html"
    json_path.write_text(json.dumps(payload, separators=(",", ":")))
    html_path.write_text(render_html(payload, title=title, template_path=template_path))
    return html_path, json_path


def _cli() -> None:
    """Re-render an HTML dashboard from an existing JSON payload.

    Useful when iterating on the template or colors without re-running
    the engine: regenerate `dashboard.html` from a saved `dashboard_data.json`.
    """
    p = argparse.ArgumentParser(description=_cli.__doc__)
    p.add_argument("--data", type=Path, required=True, help="Path to dashboard_data.json")
    p.add_argument("--out", type=Path, required=True, help="Output dashboard.html path")
    p.add_argument("--template", type=Path, default=None,
                   help="Override template path (default: dashboard_template.html next to this module)")
    p.add_argument("--title", default="PolyAgora", help="Dashboard title")
    args = p.parse_args()

    payload = json.loads(args.data.read_text())
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render_html(payload, title=args.title, template_path=args.template))
    print(f"[ok] re-rendered {args.out}")


if __name__ == "__main__":
    _cli()
