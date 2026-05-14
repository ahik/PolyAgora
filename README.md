# PolyAgora Runtime

Research/runtime engines and benchmarking harnesses for the PolyAgora
allocation system. The active production line is **V7.6** — a two-level
meta-regime steering layer that allocates across four frozen strategy
manifolds. Prior versions (V6.3 → V7.5) remain in the tree as building
blocks and as on-dashboard reference baselines.

> **Partner data not included.** Every runner / validator / sweep script
> expects `Agur/baseline_pnl_partner_delivery.xlsx` (partner-proprietary
> realized + forward PnL for the 13-asset universe). The file is not
> redistributed with this repo. Place it at that path before running any
> backtest. Without it, the engines and design docs are still readable
> but no backtest can execute.

## Layout

```
polyagora_v63_partner_engine.py   data spine — partner xlsx loader, SignalFn protocol,
                                  compute_weights / evaluate, model-free baselines
polyagora_v62_engine.py           V6.2 regime block / zone classifier (used by V7.x)
polyagora_v73_engine.py           V7.3 — Driver Seat + Q polygons (VAIDM × ADD × Buffett)
polyagora_v74_engine.py           V7.4 — hard strategy-manifold engine
polyagora_v74b_engine.py          V7.4b/c — soft manifold (top-K block aggregation)
polyagora_v75_engine.py           V7.5α — momentum-as-polygon + the v74d_q winner
polyagora_v76_engine.py           V7.6 — meta-regime steering (active line)

run_polyagora_v74_partner.py      V7.3 → V7.5 registry / dashboard runner
run_v76_check.py                  V7.6 manifold + meta-blend backtest
run_v76_sweep.py                  V7.6 hyperparameter sensitivity sweep
sweep_v75.py / analyze_v75_sweep.py    V7.5 parameter sweep + analyzer
validate_v74c.py / validate_v75.py     version validation suites

build_polyagora.py                full V7.3 → V7.5 pipeline (data refresh + run + dashboards)
build_polyagora_v76.py            V7.6 dashboard composer (curated v76 lineup)
build_dashboard_nm.py             "no momentum" dashboard variant
build_algo_v74_pdf.py             Algo_V74.md → PDF
build_v74d_vs_momentum_pdf.py     V74d_vs_Momentum.md → PDF
build_v76_findings_pdf.py         V76_Findings.md → PDF

polyagora_dashboard.py            engine-agnostic dashboard layer (SignalRun → HTML)
dashboard_template.html           HTML template (charts, summary table, presets, tooltips)
```

## V7.6 — Meta-Regime Steering Layer

V7.6 is a two-level architecture per
`docs/PolyAgora_Meta_Regime_Steering_Layer_V0.1.pdf`:

**Level 1 — four frozen strategy manifolds**, each strong in a distinct
regime geometry:

| Manifold | Implementation | Strong regime (spec §3) |
| --- | --- | --- |
| **M1** v74d_q | `make_v75_q_signal(α_M=0, K=2, τ=2, λ=0.5)` + VAIDM × ADD | Transitions, fragmentation, boundary instability |
| **M2** momentum_12_1 | classic 12-1 momentum | Persistent trends, low-vol expansions |
| **M3** defensive | fixed 40% TN + 20% FGBL + 20% GC + 20% DX | Rupture, vol stress, collapse |
| **M4** cash | zero real-asset weights | Absorbing rest-state when nothing else works |

**Level 2 — meta-regime steering layer**, a slow softmax over the
manifolds. Four variants were tested:

| Variant | Composition | Role |
| --- | --- | --- |
| `v76α` | softmax of rolling Sharpe, 15% floor, EWM halflife 10d | **Recommended ship variant** — best Sharpe, smoothest transitions |
| `v76β` | + regime-conditioned admissibility A_i from v75 diagnostics | Higher CAGR, deeper drawdowns |
| `v76γ` | full MRTP composite α·S + β·F − γ·D, A_i = 1 | Negative result — F/D terms widen the recent-period gap |
| `v76γ-full` | full MRTP + regime A_i | Negative result — A_i on top of MRTP doesn't help |

Full empirical report — manifold definitions, comparison tables,
crisis-window analysis, temporal split, robustness sweep, honest
assessment, and forward recommendations — is in
**`V76_Findings.{md,pdf}`**.

### Run V7.6

```bash
# Backtest the four manifolds + four meta-variants + naive 1/4 + crisis windows
python run_v76_check.py

# Sensitivity sweep over (lookback, λ, halflife, floor)
python run_v76_sweep.py

# Build the v76 dashboard (curated lineup with prior-version + S&P 500 references)
python build_polyagora_v76.py
```

Outputs land in `polyagora_v76_outputs/`:

```
dashboard.html                    self-contained interactive dashboard
dashboard_data.json               sidecar payload — re-render without re-running
weights_<signal>.csv              emitted daily weights (per manifold + per meta-variant)
returns_<signal>.csv              daily forward-pnl-scored returns
manifold_alloc_v76*.csv           W_i(t) — manifold allocation over time
admissibility_v76b.csv            A_i(t) — regime-conditioned admissibility (v76β)
mrtp_v76g.csv                     MRTP_i(t) — composite meta-score (v76γ)
diagnostics_v74d_q.csv            v75 engine state shared by the meta-allocator
crisis_v76_check.csv              per-window summary across all series
summary_v76_check.csv             full-sample summary
sweep_v76.csv                     500-config sensitivity sweep results
```

### V7.6 dashboard features

- **Equity, drawdown, and weight-stack charts** with drag-to-zoom and
  legend-toggle.
- **Summary table** with Total return / CAGR / Vol / Sharpe / Sortino /
  Calmar / Max DD — recomputed live on every range change.
- **Hover tooltips** on every signal label (summary rows + legend chips)
  with an extended description of each variant.
- **Time-range preset buttons** next to Reset — GFC, COVID, 2022 rates,
  Last 3y, First/Second half, Pre-COVID, COVID-on.

## Earlier versions

### V7.5 — momentum-as-polygon

`polyagora_v75_engine.py` lifts Momentum Persistence into the Reference
Polygon as a 6th coordinate. The empirical sweep (May 2026) found
**v74d_q** as the V7-line winner — V7.5α machinery at `α_M=0` with the
softer block-selection settings — and that result is what becomes V7.6's
M1. See `docs/PolyAgora_V7_5_Spec.md` and
`docs/PolyAgora_V7_5_PostMortem.md`.

```bash
python build_polyagora.py --v75       # full V7.3 → V7.5 pipeline + dashboard
python run_polyagora_v74_partner.py   # subset (registry only, no refresh)
```

### V7.3 / V7.4 / V7.4b/c

`polyagora_v73_engine.py` adds the Driver Seat dial + Q polygons (VAIDM,
ADD, Buffett) on top of V6.3. `polyagora_v74_engine.py` and
`polyagora_v74b_engine.py` are the hard / soft strategy-manifold engines
that V7.5 inherits. See `Algo_V74.{md,pdf}` and
`V74d_vs_Momentum.{md,pdf}` for the design and the cross-cycle
performance comparison.

### V6.3 — partner-delivery engine

`polyagora_v63_partner_engine.py` is the data spine for everything
above: loads the partner xlsx, defines the `SignalFn` contract,
implements `compute_weights` (with the capital-budget envelope) and
`evaluate`, and ships the three model-free baselines (`equal_weight`,
`inverse_vol`, `momentum_12_1`) plus the V6.3 `polyagora` /
`polyagora_gated` signals. Still imported by every higher version.

### V6.2

`polyagora_v62_engine.py` provides the regime block/zone classifier and
the market-data loader (`market_yahoo_vix_spy_hyg_tlt_gld_cper.csv`)
used by every V7-line signal for VIX / SPY / HYG / TLT / gold-copper
inputs.

## Universe & invariants (apply to all versions)

**Universe** — 13 single-asset futures, pre-scaled to 10% annual vol:

```
BTC  CL  DX  ES  FESX  FGBL  GC  HG  NKD  SI  TN  ZS  ZW
```

Plus a synthetic `CASH` slot — engine-internal residual capital, zero
return on both realized and forward.

**Capital-budget envelope** (per partner CTO 2026-05-05):

```
|w_real_i| ≤ 1   per asset
w_cash    ∈ [0, 1]
sum(|w_real|) + w_cash = 1.0
```

Enforced for every emitted weight row by `compute_weights`.

**Train/eval convention** (anti-hindsight):

```
weights.loc[T] is decided at close of T using realized_pnl ≤ T;
forward_pnl is never read inside the signal pipeline.
```

The V7.6 meta-allocator additionally reads each manifold's
`returns.shift(1)` so its score at row t uses only realized info ≤ t-1.

## Dependencies

```bash
pip install pandas numpy openpyxl markdown weasyprint
```

`weasyprint` is only needed for the `build_*_pdf.py` scripts.

## Re-render any dashboard without re-running

```bash
python -m polyagora_dashboard \
    --data polyagora_v76_outputs/dashboard_data.json \
    --template dashboard_template.html \
    --out polyagora_v76_outputs/dashboard.html
```

## Spec & background docs

```
docs/PolyAgora_Meta_Regime_Steering_Layer_V0.1.pdf   V7.6 spec (active)
docs/PolyAgora.pdf                                   V7.6 visual deck
docs/ChatGPT - PolyAgora - Fixed Star Fund - FSF.pdf V7.6 chat consolidation
docs/PolyAgora_Strategy_Manifold_V1.pdf              V7.4 manifold spec
docs/PolyAgora_V7_4b_Soft_Manifold_Upgrade.pdf       V7.4b soft manifold
docs/Evaluation of V7.4b (1).pdf                     V7.4b external evaluation
docs/PolyAgora_V7_5_Spec.md                          V7.5 spec
docs/PolyAgora_V7_5_PostMortem.md                    V7.5 post-mortem
docs/The Better Architecture (Your Current Direction).pdf
docs/PolyAgora V8 – Momentum-as-Geometry Architecture.pdf
docs/V8 rough simulation .pdf
```

Repo-root reports:

```
V76_Findings.{md,pdf}         V7.6 first-cut empirical findings (this version)
V74d_vs_Momentum.{md,pdf}     v74d vs Momentum 12-1 — when each wins
Algo_V74.{md,pdf}             V7.4 algorithm spec
TODO.md                       open follow-ups
```
