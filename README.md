# PolyAgora Runtime

This workspace contains the PolyAgora research/runtime engines and public-data
test harnesses.

## Primary Engine

The current canonical engine is:

```bash
polyagora_v62_engine.py
```

V6.2 implements the production form from `docs/V62/polyagora_v6_2_production.pdf`:

- exogenous market geometry `X_{t-1}` built from `VIX`, `SPY`, `HYG`, `TLT`, `GLD`, `CPER` only — no AGUR returns enter `X`
- Reference Polygon block classification (A / B / C / D / G) + star zone (1 / 2 / 3 / boundary)
- payoff-adjusted convex overlay blended with an inverse-vol RP core
- survival-matrix micro-block clustering inside the active block
- X-SM alignment amplifier with floor + boost + nonlinear suppression
- governor: drawdown / realized-vol / composite market-stress / boundary
- driver controls: alpha dial (α), risk dial, alignment dimmer (γ)
- hard no-leverage invariant: `sum(strategy weights) ≤ 1`, `CASH ≥ 0`, enforced after the Risk Dial

The docs package copy, `docs/V62/polyagora_v62_full.py`, is kept aligned with
the root engine except for its header text.

## Run V6.2

Install dependencies if needed:

```bash
pip install yfinance pandas numpy matplotlib
```

### Full backtest

Runs the V6.2 engine over the full Yahoo + AGUR dataset and regenerates the
interactive dashboard:

```bash
python run_polyagora_v62_real_yahoo.py
```

The runner:

- Loads cached market data from `polyagora_v62_yahoo_outputs/market_yahoo_vix_spy_hyg_tlt_gld_cper.csv`
  when it covers the requested range; otherwise re-downloads from Yahoo.
- Loads AGUR strategy returns from either `Agur Capital Sample Strategies 2.zip`
  or the extracted `Agur/` folder.
- Runs the backtest **once per driver preset** (5 presets — see *Driver presets*
  below). The headline CSV / PNG / dashboard log files reflect the *Default*
  preset; per-preset results are bundled into `dashboard.html` and switchable
  from the UI.
- Writes everything to `polyagora_v62_yahoo_outputs/`:
  - `dashboard.html` (interactive — see below)
  - `summary_v62_yahoo.csv`
  - `weights_v62_yahoo.csv`
  - `agur_benchmark_v62_yahoo.csv`
  - `dashboard_log_v62_yahoo.json`
  - `deployment_matters_v62_real_yahoo.png`
  - `market_yahoo_vix_spy_hyg_tlt_gld_cper.csv`

Pass `--refresh` to force a re-download of the Yahoo CSV even when the cached
file would otherwise be reused.

### Single-day prediction (`--tick` / `--asof`)

Predicts the engine's allocation for a specific date and exits. Runs the
backtest truncated to the target date so the governor's running drawdown state
is honest.

```bash
python run_polyagora_v62_real_yahoo.py --tick today
python run_polyagora_v62_real_yahoo.py --asof 2024-01-15
python run_polyagora_v62_real_yahoo.py --tick week+1     # 2 weeks ago
```

`--asof` is an alias of `--tick`. Both accept the same token forms:

| Token | Meaning |
| --- | --- |
| `2024-01-15` | exact ISO date |
| `today`, `now` | today (use today's data, prediction is for the next trading day) |
| `day` | 1 day ago |
| `week`, `month`, `year` | 1 unit ago |
| `day+1`, `week+1`, `month+2`, `year+3` | `(N+1)` units ago — `+` reads "step further back" |
| `day-1`, `week-1`, … | accepted alias for `+` (legacy form, same meaning) |

The runner snaps any token to the last trading day with available data
on or before the resolved target. For tokens that fall on weekends or
holidays the engine reports the nearest preceding trading day.

The console output for a tick prints: target date, snapped date, block, zone,
star strength, overlay α, gross, cash, X-SM alignment, alignment multiplier,
governor scale + sub-components (`dd_scale`, `vol_scale`, `market_risk_scale`),
the executed top weights, and the plain-English driver instruction.

`--tick` / `--asof` always runs at the **Default** preset (α = risk = γ = 1.0).
To inspect alternate presets, use the dashboard's preset switcher (below) or
edit `PRESETS` at the top of `run_polyagora_v62_real_yahoo.py` and re-run the
full backtest.

### Driver presets

Each full run produces five backtests, one per driver-dial preset. They are
bundled into `dashboard.html` and selectable at runtime via a dropdown in the
toolbar or by clicking a row in the **Driver Presets** table just below it.

| Preset | α | risk | γ | Diagnostic |
| --- | --- | --- | --- | --- |
| **Default (production)** | 1.0 | 1.0 | 1.0 | Production-tuned baseline. |
| **Conservative** | 0.7 | 0.8 | 1.0 | Reduced convex tilt and reduced gross — lower-vol path. |
| **Aggressive** | 1.3 | 1.2 | 1.0 | More convex, more gross. Often saturates at the 100% cap. |
| **Alignment off** | 1.0 | 1.0 | 0.0 | γ = 0 collapses the alignment multiplier to 1 — isolates the alignment layer's contribution. |
| **No convex tilt** | 0.0 | 1.0 | 1.0 | α = 0 strips the overlay — pure RP core, isolates the convex layer's contribution. |

Selecting a preset swaps the PolyAgora equity curve, the executed allocation
stack, the Decision State panel's lines, the Latest State block, and the
PolyAgora row of the summary table. The AGUR benchmarks and Yahoo Ticker Mean
remain fixed (they're dial-independent). The active preset's row in the table
is highlighted; the summary table relabels its PolyAgora row as
*"PolyAgora — \<preset name\>"* so the active preset is unambiguous.

The preset list is defined as a `PRESETS` constant at the top of
`run_polyagora_v62_real_yahoo.py`. Add a new entry there and re-run the full
backtest to extend the set; the dropdown and table auto-populate.

### Dashboard interactivity

`dashboard.html` ships with four panels in this order:

1. **Equity Curves** — PolyAgora V6.2 vs AGUR equal-weight, AGUR inverse-vol, Yahoo Ticker Mean. Faint zone-color background bands.
2. **Executed Allocation** — daily strategy-by-strategy stack with CASH (gray) on top. Pinned colors: VIX Roll Yield = red, ORB Baseline = green, CASH = gray.
3. **Decision State** — pastel block band background (A / B / C / D / G), zone stripe across the top (zone1 / zone2 / zone3 / boundary), and five lines: gross, star strength, X-SM alignment, overlay α, governor scale. Dashed reference lines at 0.34 (zone-2 entry), 0.55 (alignment min-to-amplify), 0.58 (zone-1 entry).
4. **Drawdowns** — same zone-color background bands as Equity.

All panels share these interactions:

- **Drag-to-zoom** — click and drag horizontally on any panel to set the From / To window. All four panels update in lock-step.
- **Hover tooltip** — date + value on the line charts; strategy name + weight at that date on the allocation; on Decision State, date, block, zone, plus a plain-English summary (e.g. *"Strong vol-carry regime — engine has high conviction. Invested 95% — 35% inverse-vol core, 65% convex overlay. Alignment 0.82 amplifying; governor not binding."*).
- **Clickable legend** — left-click a legend pill to toggle the corresponding line on/off; the embedded swatch is an HTML5 color picker for the line.

Controls above the charts: AGUR reference dropdown, From / To date inputs,
Market mean / All tickers checkboxes, and a Reset button that snaps back to the
default 2015-01-01 → 2025-12-31 window.

## Legacy Public Report

`public_polygon_test.py` remains a V5.3 public proxy report. It compares:

- PolyAgora V5.3
- static public equal-weight proxy basket
- older four-zone PolygonEye proxy allocation

Run it with:

```bash
python public_polygon_test.py
python public_polygon_test.py --tick 2024-01-31
```

Outputs land in `public_polygon_outputs/`.

## Tests

```bash
python -m unittest discover -p 'test_polyagora_*_engine.py'
```

`test_polyagora_v53_engine.py` and `test_polyagora_v4_engine.py` cover the
older engines. There is no dedicated V6.2 test suite yet.

## Spec & background

Canonical specification:

```text
docs/V62/polyagora_v6_2_production.pdf
```

Background papers:

```text
docs/PolyAgora — A Geometric Runtime Allocation System.pdf
docs/PolyAgora - white paper .pdf
```

## Recent changes

- **Driver presets in the dashboard.** Each full run now produces five backtests (Default, Conservative, Aggressive, Alignment off, No convex tilt), bundled into `dashboard.html`. Switch between them via dropdown or a clickable Driver Presets table; the PolyAgora curve / allocation / decision state / summary row swap instantly. Wall time grows ~5× because all five backtests run in sequence, but the in-browser switch is free.
- **No-leverage cap fix.** Earlier revisions allowed `gross` up to `1.10` in `zone1_star`, silently producing ~10% leverage when CASH clipped to 0. Both `polyagora_v62_full.py` and `polyagora_v62_engine.py` now cap zone1's gross at `1.00` and re-clamp after the Risk Dial (`gross = min(gross, 1.0)`). The Risk Dial can still scale exposure down below zone caps; it cannot push the portfolio above 100%.
- **`--tick` / `--asof` CLI** added to `run_polyagora_v62_real_yahoo.py` for single-date predictions, with relative tokens (`today`, `day`, `week`, `month`, `year`, `unit+N`).
- **Dashboard interactivity** rewritten: clickable legend with color picker, drag-to-zoom on every panel, hover tooltips with plain-English summaries, zone-color backgrounds, new Decision State panel.
- **Default display window** for the dashboard set to 2015-01-01 → 2025-12-31; data download still starts at 2013 so users can pan back.
