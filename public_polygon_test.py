
"""
PolygonEye Public Test — Clean/Simple Pitch-First Version

Goal:
Compare PolyAgora V5.3, a static public benchmark, and the older simple
PolygonEye zone-driven portfolio using only observable public market data.

Data source:
Yahoo Finance via yfinance:
SPY  = S&P 500 ETF
GLD  = gold proxy
CPER = copper proxy
TLT  = long-duration Treasury proxy
HYG  = credit/carry stress proxy
VIX  = ^VIX

Install:
pip install yfinance pandas numpy matplotlib openpyxl

Run:
python public_polygon_test.py
python public_polygon_test.py --ref path_to_reference.csv
python public_polygon_test.py --tick 2024-01-31
"""

import argparse
import json
import numpy as np
import pandas as pd
import yfinance as yf
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
from matplotlib.ticker import PercentFormatter
from pathlib import Path

from polyagora_v53_engine import AGOR_STRATEGIES, backtest_polyagora_v53

START = "2011-11-15"  # First available CPER date in Yahoo Finance.
END = None

TICKERS = ["SPY", "GLD", "CPER", "TLT", "HYG", "^VIX"]
RETURN_TICKERS = ["SPY", "GLD", "CPER", "TLT", "HYG"]

OUT = Path("public_polygon_outputs")
OUT.mkdir(exist_ok=True)

MAIN_POLYGON_COLUMN = "PolyAgora"
LEGACY_POLYGON_COLUMN = "Polygon_Public_Clean"

POLYAGORA_AGUR_SOURCES = {
    "Backwardation Carry": "1. Backwardation Carry",
    "Low Volatility": "10. Low Volatility",
    "ORB Baseline": "11. ORB Baseline",
    "UK FTSE 350 HiLo Vol L/S": "12. UK FTSE 350 High Low Volatility Long Short",
    "VIX Roll Yield": "13. VIX Roll Yield",
    "Bloomberg Europe 600 LS Momentum": "2. Bloomberg Europe 600 Long Short Momentum",
    "Contango Roll Carry": "3. Contango Roll Carry",
    "Cross Sectional Trend Factor": "4. Cross Sectional Trend Factor",
    "FTW US Buyback LS Factor": "5. FTW US Share Buyback Long Short Factor",
    "G10 FX Carry": "6. G10 FX Carry",
    "Gold-Copper Ratio MR": "7. Gold Copper Ratio Mean Reversion",
    "Long-Short Momentum": "8. Long Short Momentum",
    "Long-Only Momentum": "9. Long-Only Momentum",
}

ZONE_COLORS = {
    1: "#009e73",  # stable
    2: "#0072b2",  # early stress
    3: "#e69f00",  # structural stress
    4: "#d55e00",  # break
}

ALLOCATION_PALETTE = [
    "#4e79a7",
    "#f28e2b",
    "#e15759",
    "#76b7b2",
    "#59a14f",
    "#edc948",
    "#b07aa1",
    "#ff9da7",
    "#9c755f",
    "#bab0ac",
    "#1f77b4",
    "#2ca02c",
    "#d62728",
    "#9467bd",
]
CASH_COLOR = "#9ca3af"

def add_zone_background(ax, zones: pd.Series, alpha: float = 0.18):
    zones = zones.dropna().astype(int).sort_index()
    if zones.empty:
        return []

    if len(zones) > 1:
        final_step = zones.index.to_series().diff().dropna().median()
        if pd.isna(final_step):
            final_step = pd.Timedelta(days=1)
    else:
        final_step = pd.Timedelta(days=1)

    span_start = zones.index[0]
    span_zone = int(zones.iloc[0])

    for date, zone in zones.iloc[1:].items():
        zone = int(zone)
        if zone != span_zone:
            ax.axvspan(
                span_start,
                date,
                facecolor=ZONE_COLORS.get(span_zone, "#d9d9d9"),
                alpha=alpha,
                linewidth=0,
                zorder=0,
            )
            span_start = date
            span_zone = zone

    ax.axvspan(
        span_start,
        zones.index[-1] + final_step,
        facecolor=ZONE_COLORS.get(span_zone, "#d9d9d9"),
        alpha=alpha,
        linewidth=0,
        zorder=0,
    )

    return [
        Patch(
            facecolor=ZONE_COLORS.get(zone, "#d9d9d9"),
            alpha=alpha,
            label=f"Zone {zone}",
        )
        for zone in sorted(zones.unique())
    ]

def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--ref",
        type=Path,
        default=None,
        help="Optional CSV or Excel file with date and index_value columns.",
    )
    parser.add_argument(
        "--agur",
        type=Path,
        default=Path("Agur"),
        help="Agur strategy data directory used by the HTML dashboard.",
    )
    parser.add_argument(
        "--no-dashboard",
        action="store_true",
        help="Skip writing the interactive HTML dashboard.",
    )
    parser.add_argument(
        "--tick",
        type=str,
        default=None,
        metavar="YYYY-MM-DD",
        help=(
            "Print the next-day PolyAgora value and actual executed "
            "allocation order for the supplied date, then exit."
        ),
    )
    return parser.parse_args()

def parse_index_dates(raw_dates: pd.Series) -> pd.Series:
    raw_dates = raw_dates.astype(str).str.strip()
    slash_parts = raw_dates.str.extract(r"^(\d{1,2})/(\d{1,2})/\d{4}")
    first_part = pd.to_numeric(slash_parts[0], errors="coerce")
    second_part = pd.to_numeric(slash_parts[1], errors="coerce")
    has_slash_dates = slash_parts.notna().any(axis=1).any()
    has_time = raw_dates.str.contains(":", regex=False).any()

    dayfirst = False
    if has_slash_dates:
        first_has_days = (first_part > 12).any()
        second_has_days = (second_part > 12).any()
        if first_has_days and not second_has_days:
            dayfirst = True
        elif not first_has_days and not second_has_days and has_time:
            # The Agur VIX Roll Yield file uses day/month/year timestamps.
            dayfirst = True

    try:
        dates = pd.to_datetime(
            raw_dates,
            errors="coerce",
            dayfirst=dayfirst,
            format="mixed",
        )
    except TypeError:
        dates = pd.to_datetime(raw_dates, errors="coerce", dayfirst=dayfirst)

    if getattr(dates.dt, "tz", None) is not None:
        dates = dates.dt.tz_localize(None)
    return dates.dt.normalize()

def read_reference_table(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        ref = pd.read_csv(path)
    elif suffix in {".xls", ".xlsx", ".xlsm", ".xlsb", ".ods"}:
        try:
            ref = pd.read_excel(path)
        except ImportError as exc:
            raise RuntimeError(
                "Reading Excel files requires an Excel engine. For .xlsx, install: "
                "pip install openpyxl"
            ) from exc
    else:
        raise ValueError(
            f"Unsupported reference file suffix '{path.suffix}'. "
            "Use .csv, .xls, .xlsx, .xlsm, .xlsb, or .ods."
        )

    columns_by_name = {str(col).strip().lower(): col for col in ref.columns}
    missing = {"date", "index_value"} - set(columns_by_name)
    if missing:
        missing_cols = ", ".join(sorted(missing))
        raise ValueError(f"Reference file is missing required column(s): {missing_cols}")

    ref = ref.rename(columns={
        columns_by_name["date"]: "date",
        columns_by_name["index_value"]: "index_value",
    })

    ref["date"] = parse_index_dates(ref["date"])
    ref["index_value"] = pd.to_numeric(ref["index_value"], errors="coerce")

    return (
        ref[["date", "index_value"]]
        .dropna()
        .sort_values("date")
        .groupby("date", as_index=True)
        .last()
    )

def normalize_index_series(series: pd.Series) -> pd.Series:
    series = series.dropna().sort_index()
    first_date = series.first_valid_index()
    if first_date is None:
        return series
    return series / series.loc[first_date]

def load_index_series(path: Path, name: str | None = None) -> pd.Series:
    ref = read_reference_table(path)
    label = name if name is not None else path.name
    return normalize_index_series(ref["index_value"]).rename(label)

def load_reference_equity(path: Path, target_index: pd.DatetimeIndex) -> pd.Series:
    ref = load_index_series(path, path.name)
    aligned = ref.reindex(target_index).ffill()
    first_date = aligned.first_valid_index()
    if first_date is None:
        raise ValueError("Reference file has no usable dates in the backtest range.")

    return (aligned / aligned.loc[first_date]).rename(path.name)

def series_to_points(series: pd.Series) -> list[dict]:
    points = []
    for date, value in series.dropna().sort_index().items():
        if np.isfinite(value):
            points.append({
                "date": pd.Timestamp(date).strftime("%Y-%m-%d"),
                "value": round(float(value), 8),
            })
    return points

def build_reference_payload(
    label: str,
    group: str,
    path: str,
    series: pd.Series,
    aggregate: bool = False,
) -> dict:
    return {
        "label": label,
        "group": group,
        "path": path,
        "aggregate": aggregate,
        "values": series_to_points(series),
    }

def nested_mean_series(series_list: list[pd.Series], label: str) -> pd.Series:
    frame = pd.concat(series_list, axis=1, sort=True).sort_index().ffill()
    mean_index = frame.mean(axis=1, skipna=True).dropna()
    return normalize_index_series(mean_index).rename(label)

def strategy_sort_key(path: Path) -> tuple:
    parts = str(path.name).split(" ", 1)[0].split(".")
    numeric_parts = []
    for part in parts:
        if part.isdigit():
            numeric_parts.append(int(part))
        else:
            break
    return tuple(numeric_parts), path.name

def load_agur_references(agur_root: Path) -> list[dict]:
    agur_root = agur_root.expanduser()
    if not agur_root.exists():
        return []

    single_references = []
    nested_references = []
    top_dirs = sorted(
        (path for path in agur_root.iterdir() if path.is_dir()),
        key=strategy_sort_key,
    )

    for top_dir in top_dirs:
        direct_files = sorted(
            (
                path for path in top_dir.glob("*.csv")
                if ":Zone.Identifier" not in path.name
            ),
            key=strategy_sort_key,
        )
        nested_files = sorted(
            (
                path for path in top_dir.rglob("*.csv")
                if path.parent != top_dir and ":Zone.Identifier" not in path.name
            ),
            key=strategy_sort_key,
        )

        if nested_files:
            child_series = []
            child_payloads = []
            for path in nested_files:
                label = path.parent.name
                series = load_index_series(path, label)
                child_series.append(series)
                child_payloads.append(build_reference_payload(
                    label=label,
                    group=top_dir.name,
                    path=str(path.relative_to(agur_root)),
                    series=series,
                ))

            if len(child_series) > 1:
                label = f"{top_dir.name} Mean"
                nested_references.append(build_reference_payload(
                    label=label,
                    group=top_dir.name,
                    path=str(top_dir.relative_to(agur_root)),
                    series=nested_mean_series(child_series, label),
                    aggregate=True,
                ))
            nested_references.extend(child_payloads)

        for path in direct_files:
            label = path.parent.name
            series = load_index_series(path, label)
            single_references.append(build_reference_payload(
                label=label,
                group="Single Strategy",
                path=str(path.relative_to(agur_root)),
                series=series,
            ))

    return single_references + nested_references

def load_strategy_directory_series(top_dir: Path, label: str) -> pd.Series | None:
    direct_files = sorted(
        (
            path for path in top_dir.glob("*.csv")
            if ":Zone.Identifier" not in path.name
        ),
        key=strategy_sort_key,
    )
    nested_files = sorted(
        (
            path for path in top_dir.rglob("*.csv")
            if path.parent != top_dir and ":Zone.Identifier" not in path.name
        ),
        key=strategy_sort_key,
    )

    source_files = nested_files if nested_files else direct_files
    if not source_files:
        return None

    series_list = [
        load_index_series(path, path.parent.name)
        for path in source_files
    ]
    if len(series_list) == 1:
        return series_list[0].rename(label)
    return nested_mean_series(series_list, label).rename(label)

def load_polyagora_strategy_indices(agur_root: Path) -> pd.DataFrame:
    agur_root = agur_root.expanduser()
    if not agur_root.exists():
        return pd.DataFrame()

    strategy_series = []
    missing_sources = []
    for strategy in AGOR_STRATEGIES:
        source_name = POLYAGORA_AGUR_SOURCES.get(strategy)
        if source_name is None:
            missing_sources.append(strategy)
            continue

        series = load_strategy_directory_series(agur_root / source_name, strategy)
        if series is None or series.dropna().empty:
            missing_sources.append(strategy)
            continue

        strategy_series.append(series.rename(strategy))

    if missing_sources:
        print(
            "PolyAgora skipped missing Agur source(s): "
            + ", ".join(missing_sources)
        )

    if not strategy_series:
        return pd.DataFrame()

    return pd.concat(strategy_series, axis=1, sort=True).sort_index()

def build_polyagora_market_history(signals: pd.DataFrame) -> pd.DataFrame:
    market_history = pd.DataFrame({
        "vix": signals["vix"],
        "spy_trend_63d": signals["spy_trend"],
        "gold_copper_ratio": signals["gold_copper_ratio"],
        "hyg_trend_63d": signals["credit_trend"],
        "tlt_trend_63d": signals["tlt_trend"],
    })
    return market_history.dropna()

def run_polyagora_backtest(
    agur_root: Path,
    market_history: pd.DataFrame,
) -> dict | None:
    strategy_indices = load_polyagora_strategy_indices(agur_root)
    if strategy_indices.empty:
        print("PolyAgora not built: no Agur strategy index data was found.")
        return None

    aligned_indices = strategy_indices.reindex(market_history.index).ffill()
    available_rows = aligned_indices.notna().any(axis=1)
    aligned_indices = aligned_indices.loc[available_rows]
    if aligned_indices.empty:
        print("PolyAgora not built: Agur data does not overlap public market data.")
        return None

    aligned_market = market_history.reindex(aligned_indices.index).dropna()
    aligned_indices = aligned_indices.reindex(aligned_market.index).ffill()
    strategy_returns = aligned_indices.pct_change().fillna(0.0)
    if len(strategy_returns) < 2:
        print("PolyAgora not built: not enough overlapping strategy return rows.")
        return None

    results = backtest_polyagora_v53(
        aligned_market,
        strategy_returns,
        rebalance_freq="W-FRI",
    )
    results["market_history"] = aligned_market
    results["strategy_indices"] = aligned_indices
    results["strategy_returns"] = strategy_returns
    return results

def build_polyagora_index(
    agur_root: Path,
    market_history: pd.DataFrame,
) -> tuple[pd.Series | None, pd.Series | None]:
    results = run_polyagora_backtest(agur_root, market_history)
    if results is None:
        return None, None

    return (
        results["returns"].rename(MAIN_POLYGON_COLUMN),
        results["equity"].rename(MAIN_POLYGON_COLUMN),
    )

def parse_cli_date(value: str) -> pd.Timestamp:
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        raise SystemExit(f"Could not parse --tick date: {value}")
    date = pd.Timestamp(parsed)
    if date.tzinfo is not None:
        date = date.tz_localize(None)
    return date.normalize()

def previous_available_date(index: pd.Index, requested: pd.Timestamp) -> pd.Timestamp:
    dates = pd.DatetimeIndex(index).sort_values()
    pos = dates.searchsorted(requested, side="right") - 1
    if pos < 0:
        raise SystemExit(
            f"--tick date {requested:%Y-%m-%d} is before the first available "
            f"PolyAgora date {dates[0]:%Y-%m-%d}."
        )
    return pd.Timestamp(dates[pos])

def next_available_date(index: pd.Index, current: pd.Timestamp) -> pd.Timestamp:
    dates = pd.DatetimeIndex(index).sort_values()
    pos = dates.searchsorted(current, side="right")
    if pos >= len(dates):
        raise SystemExit(
            f"No next trading day is available after {current:%Y-%m-%d}."
        )
    return pd.Timestamp(dates[pos])

def latest_decision_for_date(decisions: list, signal_date: pd.Timestamp):
    eligible = [
        decision for decision in decisions
        if pd.Timestamp(decision.timestamp) <= signal_date
    ]
    return eligible[-1] if eligible else None

def format_weight_lines(weights: pd.Series) -> list[str]:
    active = weights[weights.abs() > 1e-10].sort_values(ascending=False)
    if active.empty:
        return ["  CASH 100.00%"]
    return [
        f"  {name:<42s} {value:>8.2%}"
        for name, value in active.items()
    ]

def format_order_delta_lines(current_weights: pd.Series, next_weights: pd.Series) -> list[str]:
    deltas = (next_weights - current_weights)
    deltas = deltas[deltas.abs() > 1e-10].sort_values(
        key=lambda values: values.abs(),
        ascending=False,
    )
    if deltas.empty:
        return ["  No allocation change."]

    lines = []
    for name, delta in deltas.items():
        side = "BUY " if delta > 0 else "SELL"
        lines.append(f"  {side:<4s} {name:<42s} {delta:>+8.2%}")
    return lines

def actual_polyagora_allocations(results: dict | None) -> pd.DataFrame:
    if results is None:
        return pd.DataFrame()

    returns = results["returns"].sort_index()
    weights = results["weights"].reindex(returns.index).ffill().fillna(0.0)
    execution_weights = weights.shift(1).fillna(0.0)
    if "CASH" in execution_weights.columns:
        empty_rows = execution_weights.abs().sum(axis=1) < 1e-10
        execution_weights.loc[empty_rows, "CASH"] = 1.0
    return execution_weights

def polyagora_tick_report(tick_date: str, results: dict) -> str:
    requested = parse_cli_date(tick_date)
    returns = results["returns"].sort_index()
    equity = results["equity"].sort_index()
    execution_weights = actual_polyagora_allocations(results)

    signal_date = previous_available_date(returns.index, requested)
    execution_date = next_available_date(returns.index, signal_date)
    decision = latest_decision_for_date(results["decisions"], signal_date)

    current_weights = execution_weights.loc[signal_date]
    next_weights = execution_weights.loc[execution_date]
    next_return = float(returns.loc[execution_date])
    next_value = float(equity.loc[execution_date])

    lines = [
        "PolyAgora Tick",
        f"Requested date: {requested:%Y-%m-%d}",
    ]
    if signal_date != requested:
        lines.append(f"Signal date used: {signal_date:%Y-%m-%d}")
    else:
        lines.append(f"Signal date: {signal_date:%Y-%m-%d}")
    lines.extend([
        f"Execution date: {execution_date:%Y-%m-%d}",
        f"Next-day PolyAgora value: {next_value:.8f}",
        f"Next-day PolyAgora return: {next_return:.4%}",
    ])

    if decision is None:
        lines.append("Decision source: initial cash state")
    else:
        lines.extend([
            f"Decision source: {pd.Timestamp(decision.timestamp):%Y-%m-%d}",
            f"Selected block: {decision.selected_block} ({decision.selected_label})",
            f"Mode: {decision.mode}",
        ])

    lines.append("")
    lines.append("Target allocation executed on next day:")
    lines.extend(format_weight_lines(next_weights))
    lines.append("")
    lines.append("Actual execution order versus prior day:")
    lines.extend(format_order_delta_lines(current_weights, next_weights))
    return "\n".join(lines)

def active_allocation_columns(allocation: pd.DataFrame) -> list[str]:
    if allocation.empty:
        return []

    active = []
    for strategy in AGOR_STRATEGIES:
        if strategy in allocation.columns and allocation[strategy].abs().max() > 1e-10:
            active.append(strategy)
    if "CASH" in allocation.columns and allocation["CASH"].abs().max() > 1e-10:
        active.append("CASH")
    return active

def allocation_color(name: str, index: int) -> str:
    if name == "CASH":
        return CASH_COLOR
    return ALLOCATION_PALETTE[index % len(ALLOCATION_PALETTE)]

def build_allocation_payload(allocation: pd.DataFrame) -> tuple[list[str], list[dict]]:
    columns = active_allocation_columns(allocation)
    records = []
    if not columns:
        return columns, records

    for date, row in allocation[columns].sort_index().iterrows():
        weights = {
            column: round(float(row[column]), 8)
            for column in columns
            if np.isfinite(row[column]) and abs(float(row[column])) > 1e-10
        }
        records.append({
            "date": pd.Timestamp(date).strftime("%Y-%m-%d"),
            "weights": weights,
        })
    return columns, records

def build_dashboard_base(equity: pd.DataFrame, zones: pd.Series) -> list[dict]:
    main_column = (
        MAIN_POLYGON_COLUMN
        if MAIN_POLYGON_COLUMN in equity.columns
        else LEGACY_POLYGON_COLUMN
    )
    base = pd.DataFrame({
        "polygon": equity[main_column],
        "public_ew": equity["Static_Public_EW"],
        "zone": zones,
    })
    if LEGACY_POLYGON_COLUMN in equity.columns and main_column != LEGACY_POLYGON_COLUMN:
        base["legacy_polygon"] = equity[LEGACY_POLYGON_COLUMN]
    base = base.dropna(subset=["polygon", "public_ew", "zone"])

    records = []
    for date, row in base.sort_index().iterrows():
        record = {
            "date": pd.Timestamp(date).strftime("%Y-%m-%d"),
            "polygon": round(float(row["polygon"]), 8),
            "public_ew": round(float(row["public_ew"]), 8),
            "zone": int(row["zone"]),
        }
        if "legacy_polygon" in row and np.isfinite(row["legacy_polygon"]):
            record["legacy_polygon"] = round(float(row["legacy_polygon"]), 8)
        records.append(record)
    return records

def dashboard_html(data: dict) -> str:
    data_json = json.dumps(data, separators=(",", ":"), allow_nan=False)
    data_json = data_json.replace("</", "<\\/")
    return r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>PolygonEye Dashboard</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f7f8fa;
      --panel: #ffffff;
      --text: #1f2937;
      --muted: #6b7280;
      --border: #d7dce2;
      --grid: #e8ecf1;
      --polygon: #16a34a;
      --legacy: #7c3aed;
      --public: #2563eb;
      --reference: #d97706;
    }

    * {
      box-sizing: border-box;
    }

    body {
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }

    main {
      max-width: 1320px;
      margin: 0 auto;
      padding: 24px;
    }

    header {
      display: flex;
      justify-content: space-between;
      gap: 20px;
      align-items: flex-end;
      margin-bottom: 18px;
    }

    h1 {
      margin: 0;
      font-size: 24px;
      font-weight: 650;
      letter-spacing: 0;
    }

    .updated {
      color: var(--muted);
      font-size: 13px;
      white-space: nowrap;
    }

    .toolbar {
      display: grid;
      grid-template-columns: minmax(260px, 2fr) minmax(130px, 1fr) minmax(130px, 1fr) auto auto auto auto;
      gap: 12px;
      align-items: end;
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 14px;
      margin-bottom: 14px;
    }

    label {
      display: grid;
      gap: 6px;
      font-size: 12px;
      font-weight: 600;
      color: var(--muted);
    }

    select,
    input[type="date"],
    button {
      width: 100%;
      height: 36px;
      border: 1px solid var(--border);
      border-radius: 6px;
      background: #fff;
      color: var(--text);
      font: inherit;
      font-size: 14px;
      padding: 0 10px;
    }

    button {
      cursor: pointer;
      font-weight: 600;
    }

    .toggle {
      height: 36px;
      display: flex;
      gap: 8px;
      align-items: center;
      color: var(--text);
      font-size: 14px;
      font-weight: 500;
      padding: 0 4px;
    }

    .toggle input {
      width: 16px;
      height: 16px;
    }

    .panel {
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 14px;
      margin-bottom: 14px;
    }

    .chart-head {
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: center;
      margin-bottom: 8px;
    }

    h2 {
      margin: 0;
      font-size: 16px;
      font-weight: 650;
      letter-spacing: 0;
    }

    .legend {
      display: flex;
      flex-wrap: wrap;
      justify-content: flex-end;
      gap: 12px;
      color: var(--muted);
      font-size: 13px;
    }

    .legend span {
      display: inline-flex;
      gap: 6px;
      align-items: center;
    }

    .swatch {
      width: 22px;
      height: 3px;
      border-radius: 999px;
      background: var(--muted);
    }

    .chart {
      display: block;
      width: 100%;
      height: 430px;
    }

    .axis text {
      fill: var(--muted);
      font-size: 12px;
    }

    .axis line,
    .axis path {
      stroke: var(--border);
    }

    .grid line {
      stroke: var(--grid);
    }

    .empty {
      fill: var(--muted);
      font-size: 14px;
    }

    .stats {
      display: grid;
      grid-template-columns: repeat(4, minmax(120px, 1fr));
      gap: 12px;
      margin-bottom: 14px;
    }

    .stat {
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 12px;
    }

    .stat .label {
      color: var(--muted);
      font-size: 12px;
      font-weight: 600;
      margin-bottom: 4px;
    }

    .stat .value {
      font-size: 18px;
      font-weight: 650;
    }

    @media (max-width: 900px) {
      main {
        padding: 14px;
      }

      header,
      .chart-head {
        align-items: flex-start;
        flex-direction: column;
      }

      .toolbar {
        grid-template-columns: 1fr;
      }

      .stats {
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }
    }
  </style>
</head>
<body>
  <main>
    <header>
      <h1>PolygonEye Dashboard</h1>
      <div class="updated" id="updated"></div>
    </header>

    <section class="toolbar" aria-label="Dashboard controls">
      <label>
        Reference
        <select id="referenceSelect"></select>
      </label>
      <label>
        From
        <input id="fromDate" type="date">
      </label>
      <label>
        To
        <input id="toDate" type="date">
      </label>
      <label class="toggle">
        <input id="showZones" type="checkbox" checked>
        Zone background
      </label>
      <label class="toggle">
        <input id="showLegacyPolygon" type="checkbox">
        Legacy Polygon
      </label>
      <label class="toggle">
        <input id="showPublicEw" type="checkbox" checked>
        Public EW
      </label>
      <button id="resetRange" type="button">Reset</button>
    </section>

    <section class="stats" id="stats"></section>

    <section class="panel">
      <div class="chart-head">
        <h2>Equity Curves</h2>
        <div class="legend" id="equityLegend"></div>
      </div>
      <svg id="equityChart" class="chart" role="img" aria-label="Equity curves chart"></svg>
    </section>

    <section class="panel">
      <div class="chart-head">
        <h2>Drawdowns</h2>
        <div class="legend" id="drawdownLegend"></div>
      </div>
      <svg id="drawdownChart" class="chart" role="img" aria-label="Drawdown chart"></svg>
    </section>

    <section class="panel">
      <div class="chart-head">
        <h2>Actual Allocation</h2>
        <div class="legend" id="allocationLegend"></div>
      </div>
      <svg id="allocationChart" class="chart" role="img" aria-label="Actual allocation chart"></svg>
    </section>
  </main>

  <script id="dashboard-data" type="application/json">__DATA__</script>
  <script>
    const dashboard = JSON.parse(document.getElementById("dashboard-data").textContent);
    const zoneColors = dashboard.zoneColors;
    const colors = {
      polygon: "#16a34a",
      legacy_polygon: "#7c3aed",
      public_ew: "#2563eb",
      reference: "#d97706"
    };

    const refs = dashboard.references || [];
    const allocationNames = dashboard.allocationNames || [];
    const baseRows = dashboard.base.map((row) => ({
      date: row.date,
      t: Date.parse(row.date + "T00:00:00Z"),
      polygon: Number(row.polygon),
      legacy_polygon: Number(row.legacy_polygon),
      public_ew: Number(row.public_ew),
      zone: Number(row.zone)
    }));
    const allocationRows = (dashboard.allocations || []).map((row) => ({
      date: row.date,
      t: Date.parse(row.date + "T00:00:00Z"),
      weights: row.weights || {}
    }));
    const allocationPalette = [
      "#4e79a7", "#f28e2b", "#e15759", "#76b7b2", "#59a14f",
      "#edc948", "#b07aa1", "#ff9da7", "#9c755f", "#bab0ac",
      "#1f77b4", "#2ca02c", "#d62728", "#9467bd"
    ];

    const select = document.getElementById("referenceSelect");
    const fromInput = document.getElementById("fromDate");
    const toInput = document.getElementById("toDate");
    const showZonesInput = document.getElementById("showZones");
    const showLegacyPolygonInput = document.getElementById("showLegacyPolygon");
    const showPublicEwInput = document.getElementById("showPublicEw");
    const resetButton = document.getElementById("resetRange");

    function fillReferenceSelect() {
      select.innerHTML = "";
      if (!refs.length) {
        const option = document.createElement("option");
        option.value = "";
        option.textContent = "No Agur references found";
        select.appendChild(option);
        select.disabled = true;
        return;
      }

      const groups = new Map();
      refs.forEach((ref, index) => {
        const group = ref.group || "References";
        if (!groups.has(group)) {
          groups.set(group, []);
        }
        groups.get(group).push({ ref, index });
      });

      groups.forEach((items, group) => {
        const optgroup = document.createElement("optgroup");
        optgroup.label = group;
        items.forEach(({ ref, index }) => {
          const option = document.createElement("option");
          option.value = String(index);
          option.textContent = ref.aggregate ? `${ref.label} (mean)` : ref.label;
          optgroup.appendChild(option);
        });
        select.appendChild(optgroup);
      });

      const defaultIndex = refs.findIndex((ref) => ref.label === "1. Backwardation Carry Mean");
      select.value = String(defaultIndex >= 0 ? defaultIndex : 0);
    }

    function setDefaultRange() {
      const minDate = dashboard.minDate;
      const maxDate = dashboard.maxDate;
      fromInput.min = minDate;
      fromInput.max = maxDate;
      toInput.min = minDate;
      toInput.max = maxDate;
      fromInput.value = dashboard.defaultMinDate || minDate;
      toInput.value = dashboard.defaultMaxDate || maxDate;
    }

    function currentBounds() {
      let from = Date.parse(fromInput.value + "T00:00:00Z");
      let to = Date.parse(toInput.value + "T00:00:00Z");
      if (!Number.isFinite(from)) from = baseRows[0].t;
      if (!Number.isFinite(to)) to = baseRows[baseRows.length - 1].t;
      if (from > to) {
        const tmp = from;
        from = to;
        to = tmp;
      }
      return { from, to };
    }

    function baseSeries(field, label, color) {
      const { from, to } = currentBounds();
      const points = baseRows
        .filter((row) => row.t >= from && row.t <= to && Number.isFinite(row[field]))
        .map((row) => ({ t: row.t, value: row[field] }));
      return {
        label,
        color,
        points: rebase(points)
      };
    }

    function referenceSeries() {
      if (!refs.length || select.disabled) return null;
      const ref = refs[Number(select.value)];
      if (!ref) return null;
      const { from, to } = currentBounds();
      const points = ref.values
        .map((point) => ({
          t: Date.parse(point.date + "T00:00:00Z"),
          value: Number(point.value)
        }))
        .filter((point) => (
          point.t >= from &&
          point.t <= to &&
          Number.isFinite(point.value)
        ));
      return {
        label: ref.label,
        color: colors.reference,
        points: rebase(points)
      };
    }

    function rebase(points) {
      if (!points.length) return [];
      const first = points.find((point) => Number.isFinite(point.value));
      if (!first || first.value === 0) return [];
      return points.map((point) => ({
        t: point.t,
        value: point.value / first.value
      }));
    }

    function drawdown(points) {
      let peak = -Infinity;
      return points.map((point) => {
        peak = Math.max(peak, point.value);
        return {
          t: point.t,
          value: point.value / peak - 1
        };
      });
    }

    function visibleSeries() {
      const mainPolygonLabel = dashboard.mainPolygonLabel || "PolyAgora";
      const series = [
        baseSeries("polygon", mainPolygonLabel, colors.polygon)
      ];
      if (showLegacyPolygonInput.checked) {
        series.push(baseSeries("legacy_polygon", "Legacy Polygon", colors.legacy_polygon));
      }
      if (showPublicEwInput.checked) {
        series.push(baseSeries("public_ew", "Public EW", colors.public_ew));
      }
      const ref = referenceSeries();
      if (ref && ref.points.length) {
        series.push(ref);
      }
      return series;
    }

    function allocationColor(name, index) {
      if (name === "CASH") return "#9ca3af";
      return allocationPalette[index % allocationPalette.length];
    }

    function makePath(points, xScale, yScale) {
      return points
        .map((point, index) => `${index === 0 ? "M" : "L"}${xScale(point.t).toFixed(2)},${yScale(point.value).toFixed(2)}`)
        .join(" ");
    }

    function renderChart(svg, series, options) {
      const width = 1100;
      const height = 430;
      const margin = { top: 18, right: 24, bottom: 42, left: 64 };
      const plotWidth = width - margin.left - margin.right;
      const plotHeight = height - margin.top - margin.bottom;
      const { from, to } = currentBounds();

      svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
      svg.innerHTML = "";

      const values = series.flatMap((item) => item.points.map((point) => point.value));
      if (!values.length) {
        const text = document.createElementNS("http://www.w3.org/2000/svg", "text");
        text.setAttribute("x", width / 2);
        text.setAttribute("y", height / 2);
        text.setAttribute("text-anchor", "middle");
        text.setAttribute("class", "empty");
        text.textContent = "No data in selected range";
        svg.appendChild(text);
        return;
      }

      let yMin = Math.min(...values);
      let yMax = Math.max(...values);
      if (options.kind === "drawdown") {
        yMax = 0;
        yMin = Math.min(yMin, -0.01);
      } else {
        const padding = (yMax - yMin || yMax || 1) * 0.08;
        yMin = Math.max(0, yMin - padding);
        yMax = yMax + padding;
      }
      if (yMin === yMax) {
        yMin -= 1;
        yMax += 1;
      }

      const xScale = (t) => margin.left + ((t - from) / (to - from || 1)) * plotWidth;
      const yScale = (value) => margin.top + ((yMax - value) / (yMax - yMin)) * plotHeight;

      if (showZonesInput.checked) {
        drawZones(svg, xScale, margin, plotHeight, from, to);
      }

      drawAxes(svg, width, height, margin, plotWidth, plotHeight, from, to, yMin, yMax, yScale, options.kind);

      series.forEach((item) => {
        if (!item.points.length) return;
        const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
        path.setAttribute("d", makePath(item.points, xScale, yScale));
        path.setAttribute("fill", "none");
        path.setAttribute("stroke", item.color);
        path.setAttribute("stroke-width", item.label === (dashboard.mainPolygonLabel || "PolyAgora") ? "2.8" : "2");
        path.setAttribute("stroke-linejoin", "round");
        path.setAttribute("stroke-linecap", "round");
        svg.appendChild(path);
      });
    }

    function drawZones(svg, xScale, margin, plotHeight, from, to) {
      const inRange = baseRows.filter((row) => row.t >= from && row.t <= to);
      const previous = [...baseRows].reverse().find((row) => row.t < from);
      const rows = previous ? [{ ...previous, t: from }, ...inRange] : inRange;
      if (!rows.length) return;

      let spanStart = previous ? from : rows[0].t;
      let spanZone = rows[0].zone;

      for (let i = 1; i < rows.length; i += 1) {
        if (rows[i].zone !== spanZone) {
          appendZoneRect(svg, xScale, margin, plotHeight, spanStart, rows[i].t, spanZone);
          spanStart = rows[i].t;
          spanZone = rows[i].zone;
        }
      }
      appendZoneRect(svg, xScale, margin, plotHeight, spanStart, to, spanZone);
    }

    function appendZoneRect(svg, xScale, margin, plotHeight, start, end, zone) {
      if (end <= start) return;
      const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
      const x = xScale(start);
      rect.setAttribute("x", x.toFixed(2));
      rect.setAttribute("y", margin.top);
      rect.setAttribute("width", Math.max(0, xScale(end) - x).toFixed(2));
      rect.setAttribute("height", plotHeight);
      rect.setAttribute("fill", zoneColors[String(zone)] || "#d9d9d9");
      rect.setAttribute("opacity", "0.18");
      svg.appendChild(rect);
    }

    function drawAxes(svg, width, height, margin, plotWidth, plotHeight, from, to, yMin, yMax, yScale, kind) {
      const grid = document.createElementNS("http://www.w3.org/2000/svg", "g");
      grid.setAttribute("class", "grid");
      const axis = document.createElementNS("http://www.w3.org/2000/svg", "g");
      axis.setAttribute("class", "axis");

      yTicks(yMin, yMax, 5).forEach((value) => {
        const y = yScale(value);
        const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
        line.setAttribute("x1", margin.left);
        line.setAttribute("x2", width - margin.right);
        line.setAttribute("y1", y);
        line.setAttribute("y2", y);
        grid.appendChild(line);

        const text = document.createElementNS("http://www.w3.org/2000/svg", "text");
        text.setAttribute("x", margin.left - 10);
        text.setAttribute("y", y + 4);
        text.setAttribute("text-anchor", "end");
        text.textContent = kind === "drawdown" || kind === "allocation" ? percent(value) : value.toFixed(2);
        axis.appendChild(text);
      });

      xTicks(from, to, 6).forEach((value) => {
        const x = margin.left + ((value - from) / (to - from || 1)) * plotWidth;
        const text = document.createElementNS("http://www.w3.org/2000/svg", "text");
        text.setAttribute("x", x);
        text.setAttribute("y", height - 14);
        text.setAttribute("text-anchor", "middle");
        text.textContent = formatDate(value);
        axis.appendChild(text);
      });

      const xAxis = document.createElementNS("http://www.w3.org/2000/svg", "line");
      xAxis.setAttribute("x1", margin.left);
      xAxis.setAttribute("x2", width - margin.right);
      xAxis.setAttribute("y1", height - margin.bottom);
      xAxis.setAttribute("y2", height - margin.bottom);
      axis.appendChild(xAxis);

      const yAxis = document.createElementNS("http://www.w3.org/2000/svg", "line");
      yAxis.setAttribute("x1", margin.left);
      yAxis.setAttribute("x2", margin.left);
      yAxis.setAttribute("y1", margin.top);
      yAxis.setAttribute("y2", height - margin.bottom);
      axis.appendChild(yAxis);

      svg.appendChild(grid);
      svg.appendChild(axis);
    }

    function yTicks(min, max, count) {
      const ticks = [];
      for (let i = 0; i < count; i += 1) {
        ticks.push(min + ((max - min) * i) / (count - 1));
      }
      return ticks;
    }

    function xTicks(min, max, count) {
      const ticks = [];
      for (let i = 0; i < count; i += 1) {
        ticks.push(min + ((max - min) * i) / (count - 1));
      }
      return ticks;
    }

    function formatDate(ms) {
      return new Date(ms).toISOString().slice(0, 10);
    }

    function percent(value) {
      return `${(value * 100).toFixed(0)}%`;
    }

    function renderLegend(element, series) {
      const zoneItems = showZonesInput.checked
        ? Object.keys(zoneColors).map((zone) => ({
            label: `Zone ${zone}`,
            color: zoneColors[zone],
            zone: true
          }))
        : [];
      const items = [
        ...series.map((item) => ({ label: item.label, color: item.color })),
        ...zoneItems
      ];
      element.innerHTML = items.map((item) => (
        `<span><i class="swatch" style="background:${item.color};${item.zone ? "height:10px;opacity:.35" : ""}"></i>${item.label}</span>`
      )).join("");
    }

    function renderAllocationLegend(element, rows) {
      const activeNames = allocationNames.filter((name) => (
        rows.some((row) => Number(row.weights[name] || 0) > 0.0001)
      ));
      element.innerHTML = activeNames.map((name) => (
        `<span><i class="swatch" style="background:${allocationColor(name, allocationNames.indexOf(name))};height:10px"></i>${name}</span>`
      )).join("");
    }

    function renderAllocationChart(svg) {
      const width = 1100;
      const height = 430;
      const margin = { top: 18, right: 24, bottom: 42, left: 64 };
      const plotWidth = width - margin.left - margin.right;
      const plotHeight = height - margin.top - margin.bottom;
      const { from, to } = currentBounds();
      const rows = allocationRows.filter((row) => row.t >= from && row.t <= to);

      svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
      svg.innerHTML = "";
      renderAllocationLegend(document.getElementById("allocationLegend"), rows);

      if (!rows.length || !allocationNames.length) {
        const text = document.createElementNS("http://www.w3.org/2000/svg", "text");
        text.setAttribute("x", width / 2);
        text.setAttribute("y", height / 2);
        text.setAttribute("text-anchor", "middle");
        text.setAttribute("class", "empty");
        text.textContent = "No allocation data in selected range";
        svg.appendChild(text);
        return;
      }

      const xScale = (t) => margin.left + ((t - from) / (to - from || 1)) * plotWidth;
      const yScale = (value) => margin.top + ((1.0 - value) / 1.0) * plotHeight;

      const cumulative = new Array(rows.length).fill(0);
      allocationNames.forEach((name, index) => {
        const lower = cumulative.slice();
        const upper = rows.map((row, rowIndex) => {
          const next = lower[rowIndex] + Number(row.weights[name] || 0);
          cumulative[rowIndex] = next;
          return next;
        });
        if (!upper.some((value, rowIndex) => Math.abs(value - lower[rowIndex]) > 0.0001)) return;

        const topPath = rows
          .map((row, rowIndex) => `${rowIndex === 0 ? "M" : "L"}${xScale(row.t).toFixed(2)},${yScale(upper[rowIndex]).toFixed(2)}`)
          .join(" ");
        const bottomPath = rows
          .map((row, rowIndex) => `L${xScale(row.t).toFixed(2)},${yScale(lower[rowIndex]).toFixed(2)}`)
          .reverse()
          .join(" ");
        const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
        path.setAttribute("d", `${topPath} ${bottomPath} Z`);
        path.setAttribute("fill", allocationColor(name, index));
        path.setAttribute("stroke", "rgba(255,255,255,.55)");
        path.setAttribute("stroke-width", "0.5");
        svg.appendChild(path);
      });
      drawAxes(svg, width, height, margin, plotWidth, plotHeight, from, to, 0, 1, yScale, "allocation");
    }

    function endValue(points) {
      return points.length ? points[points.length - 1].value : NaN;
    }

    function maxDrawdown(points) {
      const drawdowns = drawdown(points).map((point) => point.value);
      return drawdowns.length ? Math.min(...drawdowns) : NaN;
    }

    function renderStats(series) {
      const stats = document.getElementById("stats");
      stats.innerHTML = series.map((item) => {
        const totalReturn = endValue(item.points) - 1;
        const dd = maxDrawdown(item.points);
        return `
          <div class="stat">
            <div class="label">${item.label}</div>
            <div class="value">${Number.isFinite(totalReturn) ? percent(totalReturn) : "n/a"}</div>
            <div class="label">Max DD ${Number.isFinite(dd) ? percent(dd) : "n/a"}</div>
          </div>
        `;
      }).join("");
    }

    function render() {
      const series = visibleSeries();
      renderStats(series);
      renderLegend(document.getElementById("equityLegend"), series);
      renderLegend(document.getElementById("drawdownLegend"), series);
      renderChart(document.getElementById("equityChart"), series, { kind: "equity" });
      renderChart(
        document.getElementById("drawdownChart"),
        series.map((item) => ({
          ...item,
          points: drawdown(item.points)
        })),
        { kind: "drawdown" }
      );
      renderAllocationChart(document.getElementById("allocationChart"));
    }

    fillReferenceSelect();
    setDefaultRange();
    document.getElementById("updated").textContent = `Generated ${dashboard.generatedAt}`;
    select.addEventListener("change", render);
    fromInput.addEventListener("change", render);
    toInput.addEventListener("change", render);
    showZonesInput.addEventListener("change", render);
    showLegacyPolygonInput.addEventListener("change", render);
    showPublicEwInput.addEventListener("change", render);
    resetButton.addEventListener("click", () => {
      setDefaultRange();
      render();
    });
    render();
  </script>
</body>
</html>
""".replace("__DATA__", data_json)

def write_dashboard(
    output_path: Path,
    equity: pd.DataFrame,
    zones: pd.Series,
    allocation: pd.DataFrame,
    references: list[dict],
) -> None:
    base = build_dashboard_base(equity, zones)
    if not base:
        return
    allocation_names, allocation_records = build_allocation_payload(allocation)

    dashboard_dates = [row["date"] for row in base]
    dashboard_dates.extend(row["date"] for row in allocation_records)
    for reference in references:
        dashboard_dates.extend(point["date"] for point in reference["values"])
    dashboard_dates = sorted(set(dashboard_dates))

    data = {
        "generatedAt": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"),
        "mainPolygonLabel": (
            MAIN_POLYGON_COLUMN
            if MAIN_POLYGON_COLUMN in equity.columns
            else "Legacy Polygon"
        ),
        "minDate": dashboard_dates[0],
        "maxDate": dashboard_dates[-1],
        "defaultMinDate": base[0]["date"],
        "defaultMaxDate": base[-1]["date"],
        "zoneColors": ZONE_COLORS,
        "base": base,
        "allocationNames": allocation_names,
        "allocations": allocation_records,
        "references": references,
    }
    output_path.write_text(dashboard_html(data), encoding="utf-8")

def extract_close_prices(raw: pd.DataFrame, tickers: list[str]) -> pd.DataFrame:
    if raw.empty:
        return pd.DataFrame()

    if isinstance(raw.columns, pd.MultiIndex):
        price_fields = raw.columns.get_level_values(0)
        if "Close" in price_fields:
            return raw.xs("Close", axis=1, level=0).copy()
        if "Adj Close" in price_fields:
            return raw.xs("Adj Close", axis=1, level=0).copy()
        raise SystemExit("Yahoo Finance response did not include Close prices.")

    close_column = "Close" if "Close" in raw.columns else "Adj Close"
    if close_column in raw.columns and len(tickers) == 1:
        return raw[[close_column]].rename(columns={close_column: tickers[0]})

    raise SystemExit("Unexpected yfinance response format.")

def download_public_prices() -> pd.DataFrame:
    raw = yf.download(
        TICKERS,
        start=START,
        end=END,
        auto_adjust=True,
        progress=False,
        threads=False,
    )
    px = extract_close_prices(raw, TICKERS)

    missing = [
        ticker for ticker in TICKERS
        if ticker not in px.columns or px[ticker].dropna().empty
    ]

    if missing:
        print(f"Retrying missing ticker(s) individually: {', '.join(missing)}")
        for ticker in missing:
            retry_raw = yf.download(
                ticker,
                start=START,
                end=END,
                auto_adjust=True,
                progress=False,
                threads=False,
            )
            retry_px = extract_close_prices(retry_raw, [ticker])
            if ticker in retry_px.columns and not retry_px[ticker].dropna().empty:
                px[ticker] = retry_px[ticker]

    missing = [
        ticker for ticker in TICKERS
        if ticker not in px.columns or px[ticker].dropna().empty
    ]
    if missing:
        raise SystemExit(
            "Yahoo Finance returned no usable prices for: "
            f"{', '.join(missing)}.\n"
            "The Polygon/Public EW plots require all public tickers. "
            "Try rerunning; if it persists, check network/yfinance access "
            "or adjust START/END."
        )

    px = px[TICKERS].sort_index().dropna(how="all").ffill().dropna()
    if px.empty:
        raise SystemExit(
            "No overlapping complete price history remained after aligning "
            "the public tickers."
        )

    return px.rename(columns={"^VIX": "VIX"})

def max_drawdown(equity: pd.Series) -> float:
    peak = equity.cummax()
    dd = equity / peak - 1
    return float(dd.min())

def cagr(equity: pd.Series) -> float:
    years = (equity.index[-1] - equity.index[0]).days / 365.25
    return float(equity.iloc[-1] ** (1 / years) - 1)

def sharpe(returns: pd.Series) -> float:
    return float(np.sqrt(252) * returns.mean() / returns.std())

def metrics(name: str, r: pd.Series) -> dict:
    eq = (1 + r.fillna(0)).cumprod()
    return {
        "portfolio": name,
        "CAGR": cagr(eq),
        "Volatility": float(r.std() * np.sqrt(252)),
        "Sharpe": sharpe(r),
        "MaxDD": max_drawdown(eq),
        "Worst_Day": float(r.min()),
        "Positive_Days": float((r > 0).mean())
    }

args = parse_args()

# Download public data
px = download_public_prices()

# Daily returns
ret = px[RETURN_TICKERS].pct_change()

# Signals — all lagged to avoid lookahead
spy_trend = px["SPY"].pct_change(63).shift(1)       # 3-month trend
vix = px["VIX"].shift(1)
gc_ratio = (px["GLD"] / px["CPER"]).shift(1)
gc_trend = gc_ratio.pct_change(63).shift(1)         # rising = stress
credit_trend = px["HYG"].pct_change(63).shift(1)    # falling = stress
tlt_trend = px["TLT"].pct_change(63).shift(1)       # rising TLT = rates relief

# Clean/simple zone rules
def detect_zone(row):
    if row["vix"] > 40:
        return 4
    if row["vix"] > 30 and row["spy_trend"] < 0:
        return 3
    if row["vix"] > 20 or (row["spy_trend"] < 0 and row["gc_trend"] > 0):
        return 2
    return 1

signals = pd.DataFrame({
    "vix": vix,
    "spy_trend": spy_trend,
    "gold_copper_ratio": gc_ratio,
    "gc_trend": gc_trend,
    "credit_trend": credit_trend,
    "tlt_trend": tlt_trend,
}).dropna()

signals["zone"] = signals.apply(detect_zone, axis=1)

# Align returns to next day after signal
r = ret.loc[signals.index].copy()
if r.empty:
    raise SystemExit(
        "No return rows remained after building signals. "
        "Check public ticker downloads and START/END."
    )

# Static benchmark: equal-weight public proxy basket
static = r[RETURN_TICKERS].mean(axis=1)

# Polygon allocations
# Zone 1: Stable trend -> SPY
# Zone 2: Early stress -> reduced SPY + Gold/Copper tilt + cash
# Zone 3: Structural stress -> GLD + TLT + cash
# Zone 4: Break -> cash/TLT defensive, no naked VIX ETF in v1
polygon = pd.Series(index=r.index, dtype=float)
weights_by_zone = {}

for date in r.index:
    z = int(signals.loc[date, "zone"])
    if z == 1:
        weights = {"SPY": 1.00}
    elif z == 2:
        weights = {"SPY": 0.35, "GLD": 0.35, "CPER": -0.15, "TLT": 0.15}
    elif z == 3:
        weights = {"GLD": 0.45, "TLT": 0.45}
    else:
        weights = {"TLT": 0.70}  # remaining 30% cash

    val = 0.0
    for k, w in weights.items():
        val += w * r.loc[date, k]
    polygon.loc[date] = val
    weights_by_zone[date] = z

polyagora_results = run_polyagora_backtest(
    args.agur,
    build_polyagora_market_history(signals),
)
if polyagora_results is None:
    polyagora_return = None
    polyagora_equity = None
else:
    polyagora_return = polyagora_results["returns"].rename(MAIN_POLYGON_COLUMN)
    polyagora_equity = polyagora_results["equity"].rename(MAIN_POLYGON_COLUMN)

if args.tick is not None:
    if polyagora_results is None:
        raise SystemExit("Cannot run --tick because PolyAgora was not built.")
    print(polyagora_tick_report(args.tick, polyagora_results))
    raise SystemExit(0)

actual_allocation = actual_polyagora_allocations(polyagora_results)

# Save outputs
equity = pd.DataFrame(index=r.index)
if polyagora_equity is not None:
    equity[MAIN_POLYGON_COLUMN] = polyagora_equity.reindex(r.index).ffill()
equity["Static_Public_EW"] = (1 + static.fillna(0)).cumprod()
equity[LEGACY_POLYGON_COLUMN] = (1 + polygon.fillna(0)).cumprod()

reference_equity = None
reference_return = None
if args.ref is not None:
    reference_equity = load_reference_equity(args.ref.expanduser(), equity.index)
    reference_return = reference_equity.pct_change()
    equity[reference_equity.name] = reference_equity

dd = equity / equity.cummax() - 1

metrics_rows = [
    *(
        [metrics(MAIN_POLYGON_COLUMN, polyagora_return.dropna())]
        if polyagora_return is not None
        else []
    ),
    metrics("Static_Public_EW", static),
    metrics(LEGACY_POLYGON_COLUMN, polygon),
]
if reference_return is not None:
    reference_metrics_return = reference_return.dropna()
    if len(reference_metrics_return) >= 2:
        metrics_rows.append(metrics(reference_equity.name, reference_metrics_return))
metrics_df = pd.DataFrame(metrics_rows)
metrics_df.to_csv(OUT / "public_polygon_metrics.csv", index=False)

timeseries = pd.DataFrame({
    "static_return": static,
    "polygon_return": polygon,
    "zone": signals.loc[r.index, "zone"],
    "vix": signals.loc[r.index, "vix"],
    "spy_trend_63d": signals.loc[r.index, "spy_trend"],
    "gold_copper_ratio": signals.loc[r.index, "gold_copper_ratio"],
    "gold_copper_trend_63d": signals.loc[r.index, "gc_trend"],
    "hyg_trend_63d": signals.loc[r.index, "credit_trend"],
    "tlt_trend_63d": signals.loc[r.index, "tlt_trend"],
})
if polyagora_return is not None:
    timeseries["polyagora_return"] = polyagora_return.reindex(r.index)
if polyagora_equity is not None:
    timeseries["polyagora_equity"] = polyagora_equity.reindex(r.index).ffill()
if reference_equity is not None:
    timeseries["reference_equity"] = reference_equity
    timeseries["reference_return"] = reference_return
timeseries.to_csv(OUT / "public_polygon_timeseries.csv")
if not actual_allocation.empty:
    actual_allocation.to_csv(OUT / "public_polygon_allocations.csv")

zone_series = signals.loc[equity.index, "zone"]

fig, ax = plt.subplots(figsize=(11, 6))
zone_handles = add_zone_background(ax, zone_series)
for c in equity.columns:
    ax.plot(
        equity.index,
        equity[c],
        label=c,
        linewidth=2.6 if c == MAIN_POLYGON_COLUMN else 1.7,
        zorder=3 if c == MAIN_POLYGON_COLUMN else 2,
    )
line_handles, _ = ax.get_legend_handles_labels()
ax.set_title("Public PolygonEye Test — PolyAgora Equity Curves")
ax.set_ylabel("Growth of $1")
ax.set_xlim(equity.index[0], equity.index[-1])
ax.legend(handles=line_handles + zone_handles, ncols=2)
fig.tight_layout()
fig.savefig(OUT / "public_polygon_equity_curves.png", dpi=180)
plt.close(fig)

fig, ax = plt.subplots(figsize=(11, 6))
zone_handles = add_zone_background(ax, zone_series)
for c in dd.columns:
    ax.plot(
        dd.index,
        dd[c],
        label=c,
        linewidth=2.6 if c == MAIN_POLYGON_COLUMN else 1.7,
        zorder=3 if c == MAIN_POLYGON_COLUMN else 2,
    )
line_handles, _ = ax.get_legend_handles_labels()
ax.set_title("Public PolygonEye Test — PolyAgora Drawdowns")
ax.set_ylabel("Drawdown")
ax.set_xlim(dd.index[0], dd.index[-1])
ax.legend(handles=line_handles + zone_handles, ncols=2)
fig.tight_layout()
fig.savefig(OUT / "public_polygon_drawdowns.png", dpi=180)
plt.close(fig)

allocation_columns = active_allocation_columns(actual_allocation)
if allocation_columns:
    plot_allocation = actual_allocation.reindex(equity.index).ffill().fillna(0.0)
    fig, ax = plt.subplots(figsize=(11, 6))
    ax.stackplot(
        plot_allocation.index,
        *[
            plot_allocation[column].clip(lower=0.0).to_numpy()
            for column in allocation_columns
        ],
        labels=allocation_columns,
        colors=[
            allocation_color(column, index)
            for index, column in enumerate(allocation_columns)
        ],
        linewidth=0.2,
        edgecolor="white",
    )
    ax.set_title("Public PolygonEye Test — Actual PolyAgora Allocation")
    ax.set_ylabel("Executed weight")
    ax.set_ylim(0, 1)
    ax.set_xlim(plot_allocation.index[0], plot_allocation.index[-1])
    ax.yaxis.set_major_formatter(PercentFormatter(xmax=1.0))
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.12), ncols=2, fontsize=7)
    fig.tight_layout()
    fig.savefig(OUT / "public_polygon_allocations.png", dpi=180)
    plt.close(fig)

plt.figure(figsize=(11, 3))
plt.plot(signals.index, signals["zone"], linewidth=1)
plt.yticks([1,2,3,4])
plt.title("Public PolygonEye Test — Zone Calendar")
plt.ylabel("Zone")
plt.tight_layout()
plt.savefig(OUT / "public_polygon_zone_calendar.png", dpi=180)
plt.close()

dashboard_path = None
if not args.no_dashboard:
    dashboard_references = load_agur_references(args.agur)
    if reference_equity is not None:
        dashboard_references.insert(0, build_reference_payload(
            label=reference_equity.name,
            group="External reference",
            path=str(args.ref.expanduser()),
            series=reference_equity,
        ))
    dashboard_path = OUT / "dashboard.html"
    write_dashboard(dashboard_path, equity, zone_series, actual_allocation, dashboard_references)

print(metrics_df.to_string(index=False))
print(f"\nSaved outputs to: {OUT.resolve()}")
if dashboard_path is not None:
    print(f"Dashboard: {dashboard_path.resolve()}")
