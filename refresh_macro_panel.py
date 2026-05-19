"""Extend the macro panel back to 2008 (Phase-3 fix — data gap).

The cached `market_yahoo_vix_spy_hyg_tlt_gld_cper.csv` covers only 2013-2026,
so the V6.2 polygon / VAIDM / Layer-5 recoverability geometry run on neutral
defaults for 2008-2013 (28% of the partner history, incl. the GFC).

This script PREPENDS 2007-10 -> 2013 from Yahoo Finance, keeping every
existing 2013+ row byte-identical (so V7.10 and the §12.2 reference are
untouched). Each prepended series is rescaled to splice continuously at the
2013-01-02 anchor. Pre-2011 CPER (the ETF's inception) is proxied by copper
futures HG=F, rescaled to CPER units.

    agora/bin/python refresh_macro_panel.py
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parent
PANEL = ROOT / "market_data" / "market_yahoo_vix_spy_hyg_tlt_gld_cper.csv"
TICKERS = {"VIX": "^VIX", "SPY": "SPY", "HYG": "HYG",
           "TLT": "TLT", "GLD": "GLD", "CPER": "CPER"}
COPPER_PROXY = "HG=F"          # copper futures — covers the pre-2011 CPER gap
FETCH_START = "2007-10-01"


def _close(ticker: str, start: str, end: str) -> pd.Series:
    df = yf.download(ticker, start=start, end=end, progress=False,
                     auto_adjust=True)
    if df.empty:
        return pd.Series(dtype=float)
    close = df["Close"]
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]
    return close.dropna()


def main() -> None:
    cached = pd.read_csv(PANEL, parse_dates=["date"]).set_index("date").sort_index()
    anchor = cached.index[0]
    end = (anchor + pd.Timedelta(days=15)).strftime("%Y-%m-%d")
    print(f"[refresh] cached panel: {anchor.date()} -> {cached.index[-1].date()} "
          f"({len(cached)} rows)")
    print(f"[refresh] fetching {FETCH_START} -> {end} (prepend region)")

    # --- fetch the six tickers + the copper proxy ---------------------------
    raw = {name: _close(tk, FETCH_START, end) for name, tk in TICKERS.items()}
    copper = _close(COPPER_PROXY, FETCH_START, end)
    for name, s in raw.items():
        fv = s.first_valid_index()
        print(f"[refresh]   {name:5} {len(s):5} rows  first={fv.date() if fv is not None else None}")
    print(f"[refresh]   HG=F  {len(copper):5} rows  first="
          f"{copper.first_valid_index().date()}")

    # --- build the copper series: CPER native, HG=F proxy before inception --
    cper = raw["CPER"]
    common = cper.index.intersection(copper.index)
    if common.empty:
        raise SystemExit("no overlap between CPER and HG=F — cannot splice copper")
    d0 = common[0]
    copper_scaled = copper * (cper.loc[d0] / copper.loc[d0])
    raw["CPER"] = cper.combine_first(copper_scaled).sort_index()
    print(f"[refresh] copper: CPER native from {cper.first_valid_index().date()}, "
          f"HG=F proxy before (spliced at {d0.date()})")

    # --- assemble the prepend block (business-day index, < anchor) ----------
    idx = pd.bdate_range(FETCH_START, anchor)
    prepend = pd.DataFrame(index=idx)
    for name in TICKERS:
        s = raw[name].reindex(idx).ffill()
        # rescale so the series is continuous with the cached panel at anchor
        if anchor in s.index and pd.notna(s.loc[anchor]) and s.loc[anchor] != 0:
            s = s * (cached[name].loc[anchor] / s.loc[anchor])
        prepend[name] = s
    prepend = prepend.loc[prepend.index < anchor].dropna()

    # --- concatenate: new 2008-2013 block + untouched cached 2013+ ----------
    extended = pd.concat([prepend[list(TICKERS)], cached[list(TICKERS)]])
    extended = extended[~extended.index.duplicated(keep="last")].sort_index()

    # --- verification -------------------------------------------------------
    tail_pre = prepend.iloc[-1]
    head_cached = cached.iloc[0]
    print("\n[refresh] splice continuity (last prepend row vs first cached row):")
    for name in TICKERS:
        jump = abs(tail_pre[name] - head_cached[name]) / abs(head_cached[name])
        print(f"  {name:5} {tail_pre[name]:12.4f} -> {head_cached[name]:12.4f}  "
              f"rel-gap {jump:.4%}")
    assert not extended.isna().any().any(), "extended panel has NaNs"
    cached_back = extended.loc[extended.index >= anchor]
    assert cached_back.equals(cached[list(TICKERS)]), "2013+ rows were altered!"

    # --- back up and write --------------------------------------------------
    backup = PANEL.with_suffix(".csv.bak")
    if not backup.exists():
        cached.to_csv(backup, index_label="date")
        print(f"\n[refresh] backed up original -> {backup.name}")
    extended.to_csv(PANEL, index_label="date")
    print(f"[refresh] wrote {PANEL.name}: {extended.index[0].date()} -> "
          f"{extended.index[-1].date()}  ({len(extended)} rows)")
    print("[refresh] 2013+ rows verified byte-identical to the original.")


if __name__ == "__main__":
    main()
