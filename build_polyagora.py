"""
PolyAgora — canonical build command.

Re-runs the full V7.4 signal registry on the partner workbook and refreshes
the dashboard / CSV side-files under the output directory. Optionally pulls
the latest Yahoo market panel (`--refresh`) before running.

Usage
-----
    python build_polyagora.py                 # rebuild outputs (uses cached market CSV)
    python build_polyagora.py --refresh       # re-download Yahoo market data, then rebuild
    python build_polyagora.py --signal v74b_plateau --refresh
    python build_polyagora.py --output ./out_2026Q2

Inputs
------
    --input    Agur/baseline_pnl_partner_delivery.xlsx     (partner realized/forward PnL)
    --market   market_data/market_yahoo_vix_spy_hyg_tlt_gld_cper.csv
    --output   polyagora_v74_outputs/

Outputs (in `--output`)
-----------------------
    dashboard.html, dashboard_data.json, summary_v74.csv, run.log,
    weights_<signal>.csv, returns_<signal>.csv, equity_<signal>.csv,
    weights_<signal>_mom.csv, diagnostics_<signal>.csv
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
import yfinance as yf

from run_polyagora_v74_partner import (
    DEFAULT_INPUT,
    DEFAULT_MARKET,
    DEFAULT_OUTPUT,
    SP500_REFERENCE_CSV,
    run,
)


V75_OUTPUT_DIR = DEFAULT_OUTPUT.parent / "polyagora_v75_outputs"
V75_TITLE = "PolyAgora V7.5α₁ — Sweep findings (v74d = empirical winner)"
V75_DEFAULT_WEIGHTS_SIGNAL = "v74d"
V75_DEFAULT_VISIBLE = [
    "equal_weight",
    "v74b_plateau",
    "v74b_template",
    "v75",
    "v75_no_mom_eigen",
    "v74d",
    "v74d_q",
    "v75_short",
]
# sp500 omitted from default visible — its 6× total return flattens partner
# strategy curves on the linear Y-axis. Available in the legend; user toggles
# it on for direct-comparison views.


# Yahoo tickers powering the Reference Polygon coordinate (V, T, G, C, R).
TICKERS: dict[str, str] = {
    "VIX": "^VIX",
    "SPY": "SPY",
    "HYG": "HYG",
    "TLT": "TLT",
    "GLD": "GLD",
    "CPER": "CPER",
}
MARKET_START_DATE: str = "2013-01-01"


def refresh_market_data(market_csv: Path) -> pd.DataFrame:
    """Re-download the six Yahoo tickers and overwrite `market_csv`.

    Uses Adj Close where available, falls back to Close. Forward-fills gaps
    inside the series and drops leading rows where any ticker is still NaN.
    """
    print(f"[refresh] downloading {list(TICKERS.values())} from Yahoo since {MARKET_START_DATE}")
    raw = yf.download(
        list(TICKERS.values()),
        start=MARKET_START_DATE,
        auto_adjust=False,
        progress=False,
        group_by="ticker",
        threads=True,
    )
    if raw.empty:
        raise RuntimeError("Yahoo returned an empty dataset")

    cols: dict[str, pd.Series] = {}
    for name, ticker in TICKERS.items():
        if isinstance(raw.columns, pd.MultiIndex):
            if (ticker, "Adj Close") in raw.columns:
                cols[name] = raw[(ticker, "Adj Close")]
            elif (ticker, "Close") in raw.columns:
                cols[name] = raw[(ticker, "Close")]
            else:
                raise ValueError(f"No close column for {ticker}")
        else:
            raise ValueError("Unexpected Yahoo Finance output format")

    market = pd.DataFrame(cols)
    market.index = pd.to_datetime(market.index).tz_localize(None)
    market = market.dropna(how="all").ffill().dropna()

    market_csv.parent.mkdir(parents=True, exist_ok=True)
    market.to_csv(market_csv, index_label="date")
    last_row = market.index.max().date()
    print(f"[refresh] wrote {market_csv} — {len(market)} rows through {last_row}")
    return market


def refresh_sp500_reference(sp500_csv: Path, start: str = "2008-01-01") -> None:
    """Re-download SPY back to `start` and save as the S&P 500 reference.

    Separate from the V6.2 market panel because the partner forward-PnL
    starts in 2008, before the V6.2 panel's 2013-01-01 (HYG/CPER warmup).
    """
    print(f"[refresh] downloading SPY since {start} (S&P 500 reference)")
    raw = yf.download(
        ["SPY"], start=start, auto_adjust=False, progress=False,
        group_by="ticker", threads=True,
    )
    if raw.empty:
        raise RuntimeError("Yahoo returned empty SPY dataset")
    if isinstance(raw.columns, pd.MultiIndex):
        prices = (
            raw[("SPY", "Adj Close")] if ("SPY", "Adj Close") in raw.columns
            else raw[("SPY", "Close")]
        )
    else:
        prices = raw["Adj Close"] if "Adj Close" in raw.columns else raw["Close"]
    prices.index = pd.to_datetime(prices.index).tz_localize(None)
    prices = prices.dropna()
    sp500_csv.parent.mkdir(parents=True, exist_ok=True)
    prices.to_frame("SPY").to_csv(sp500_csv, index_label="date")
    print(f"[refresh] wrote {sp500_csv} — {len(prices)} rows through {prices.index.max().date()}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--refresh", action="store_true",
        help="Re-download the Yahoo market panel before running. Overwrites --market CSV.",
    )
    parser.add_argument(
        "--v75", action="store_true",
        help="V7.5α₁ dashboard skin: outputs to polyagora_v75_outputs/, "
             "title 'V7.5α₁ — Momentum-as-Polygon', default weights show v75.",
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT,
                        help="Partner xlsx workbook (default: %(default)s)")
    parser.add_argument("--market", type=Path, default=DEFAULT_MARKET,
                        help="Market CSV path (default: %(default)s)")
    parser.add_argument("--output", type=Path, default=None,
                        help="Output directory (default: polyagora_v74_outputs/, "
                             "or polyagora_v75_outputs/ if --v75 is set)")
    parser.add_argument("--signal", default="all",
                        help="Signal filter: 'all' or a single registry name (default: all)")
    args = parser.parse_args()

    if args.output is None:
        args.output = V75_OUTPUT_DIR if args.v75 else DEFAULT_OUTPUT

    if args.refresh:
        refresh_market_data(args.market)
        refresh_sp500_reference(SP500_REFERENCE_CSV)
    elif not args.market.exists():
        parser.error(
            f"market CSV not found: {args.market}\n"
            f"  → run with --refresh to download it from Yahoo, or pass --market <path>."
        )

    title = V75_TITLE if args.v75 else "PolyAgora V7.4c — Validated Strategy Manifold"
    default_weights = V75_DEFAULT_WEIGHTS_SIGNAL if args.v75 else "v74b_plateau"
    default_visible = V75_DEFAULT_VISIBLE if args.v75 else None

    try:
        run(
            input_path=args.input,
            output_dir=args.output,
            market_csv=args.market,
            signal_filter=args.signal,
            title=title,
            default_weights_signal=default_weights,
            default_visible_signals=default_visible,
        )
    except ValueError as e:
        parser.error(str(e))


if __name__ == "__main__":
    main()
