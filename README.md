# PolyAgora Runtime

Research/runtime engines and benchmarking harnesses for the PolyAgora
allocation system. The current canonical engine is V6.3 — the
partner-delivery adapter that targets the basis-portfolio benchmark in
`Agur/baseline_pnl_partner_delivery.xlsx`.

> **Partner data not included.** Every runner / validator / sweep script
> expects `Agur/baseline_pnl_partner_delivery.xlsx` (partner-proprietary
> realized + forward PnL for the 13-asset universe). The file is not
> redistributed with this repo. Place it at that path before running any
> backtest. Without it, the engines and design docs are still readable
> but no backtest can execute.

## Layout

```
polyagora_v63_partner_engine.py   canonical engine (V6.3)
run_polyagora_v73_partner.py      runner / orchestration
polyagora_dashboard.py            engine-agnostic dashboard layer
dashboard_template.html           HTML template consumed by the dashboard
polyagora_carry_core.py           shared β-throttle / carry-core helpers
sweep_carry_core.py               parameter-sweep utility for carry-core
public_polygon_test.py            legacy V5.3 public-data harness
```

V6.3 is **engine + runner + presentation**, split across three files:

- `polyagora_v63_partner_engine.py` — pure compute. Loads the partner
  workbook, defines the signal contract, computes weights, evaluates them
  on `forward_pnl`. No I/O, no plotting.
- `run_polyagora_v73_partner.py` — orchestration. Builds the signal
  registry, runs each signal, writes per-signal CSVs, calls the dashboard
  layer.
- `polyagora_dashboard.py` + `dashboard_template.html` — presentation,
  fully engine-agnostic. Consumes a list of `SignalRun` records and emits
  a self-contained `dashboard.html` plus a sidecar `dashboard_data.json`
  that can be re-rendered without re-running the engine.

## V6.3 — Partner-Delivery Engine

### Universe

13 single-asset futures, each pre-scaled to 10% annual vol:

```
BTC  CL  DX  ES  FESX  FGBL  GC  HG  NKD  SI  TN  ZS  ZW
```

Plus a synthetic `CASH` slot — engine-internal residual capital, zero
return on both realized and forward (no risk-free assumed).

### Spec envelope

Per partner CTO (2026-05-05):

```
|w_real_i| ≤ 1   per asset
w_cash    ∈ [0, 1]
sum(|w_real|) + w_cash = 1.0      (capital budget)
```

Enforced for every emitted weight row.

### Train/eval convention

```
weights.loc[T] is decided at close of T using realized_pnl rows
with index ≤ T, and scored by forward_pnl.loc[T].
forward_pnl is never read inside the signal pipeline.
```

### Built-in signals

| Name | Description |
| --- | --- |
| `equal_weight` | Uniform across live assets. |
| `inverse_vol` | 1/σ over a 63-day lookback. |
| `momentum_12_1` | 12-1 long-only, pre-normalized to gross = 1. |
| `polyagora` | V6.3 raw — convex combination of five regime templates (A/B/C/D/G) weighted by V6.2 block probabilities. |
| `polyagora_gated` | `polyagora` blended toward a defensive `NEUTRAL_TEMPLATE` by a β throttle. β is the v62 carry-core series: VIX / SPY / drawdown soft gates × hard-kill (VIX shock or SPY 1d ≤ −3%) × cooldown × EWM × shift(1). |

The two PolyAgora signals require the V6.2 market CSV
(`polyagora_v62_yahoo_outputs/market_yahoo_vix_spy_hyg_tlt_gld_cper.csv`)
for VIX/SPY inputs to the regime classifier and β throttle. Without it,
the runner falls back to the three model-free baselines.

### Regime templates

The PolyAgora signal maps V6.2 regime blocks to the 13-asset universe.
Each template is a unit-gross vector; the gross-1.0 envelope is enforced
at module load.

| Block | Intuition | Net |
| --- | --- | --- |
| A | Vol-Carry — calm, low VIX, healthy credit. Long-only, diversified. | 1.00 |
| B | Commodity Stress — high VIX, GC > HG, equities/credit weak. Long commods + DX, short risk/bonds/HG. | ~0.71 |
| C | Momentum — strong SPY uptrend. Long equities + procyclical, no bonds. | 1.00 |
| D | Low-Vol — long bonds + equities + DX, lighter commods. | 1.00 |
| G | Boundary — VIX spike, flight to safety. Long FGBL/TN/GC/DX, short risk. | ~0.59 |

`B` and `G` were originally gross > 1; both were squashed to gross = 1.0
to fit the capital-budget envelope. Long/short ratios are preserved.

## Run V6.3

Install dependencies:

```bash
pip install pandas numpy openpyxl
```

Full backtest — runs every signal, writes CSVs, builds the dashboard:

```bash
python run_polyagora_v73_partner.py
```

Single signal:

```bash
python run_polyagora_v73_partner.py --signal polyagora_gated
```

Override the β-throttle smoothing half-life:

```bash
python run_polyagora_v73_partner.py --beta-halflife 5.0
```

Outputs land in `polyagora_v73_outputs/`:

```
dashboard.html               self-contained interactive dashboard
dashboard_data.json          sidecar — re-render without re-running
summary_v73.csv      per-signal summary table
weights_<signal>.csv         emitted daily weights
returns_<signal>.csv         daily forward-pnl-scored returns
equity_<signal>.csv          cumulative equity
```

### Re-render the dashboard without re-running

Useful when iterating on the HTML template:

```bash
python -m polyagora_dashboard \
    --data polyagora_v73_outputs/dashboard_data.json \
    --template dashboard_template.html \
    --out polyagora_v73_outputs/dashboard.html
```

## Tests

```bash
python -m unittest discover -p 'test_polyagora_*_engine.py'
```

The test files cover the older engines (`v4`, `v5.3`, `v6.2`). There is
no dedicated V6.3 test suite yet — the gross-budget invariant is checked
at runtime by the runner, which warns on any row where
`sum(|w_real|) + w_cash ≠ gross_cap`.

## Legacy V6.2

`polyagora_v62_engine.py` + `run_polyagora_v62_real_yahoo.py` remain in
the tree as the source of regime block/zone classification and the
market-data loader feeding V6.3's PolyAgora signals. V6.2 ran a single
PolyAgora curve against AGUR strategies on Yahoo data with five driver
presets (Default / Conservative / Aggressive / Alignment off / No convex
tilt); see git history for its standalone dashboard.

## Legacy public report

`public_polygon_test.py` is a V5.3 public-data harness that compares
PolyAgora V5.3, a static equal-weight basket, and an older four-zone
PolygonEye allocation. Outputs land in `public_polygon_outputs/`.

```bash
python public_polygon_test.py
python public_polygon_test.py --tick 2024-01-31
```

## Spec & background

```
docs/PolyAgora Engine – CTO Specification (V7).pdf
docs/PolyAgora — A Geometric Runtime Allocation System.pdf
docs/PolyAgora - white paper .pdf
docs/V62/polyagora_v6_2_production.pdf      V6.2 canonical spec
docs/PolyAgora_V62_Carry_Core_Implementation.md
```
