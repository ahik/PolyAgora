# PolyAgora Runtime

Research/runtime engines and benchmarking harnesses for the PolyAgora
allocation system. The active production line is **V7.10** — it pairs:

- **V7.9** — the winners-consolidated allocator: the V7.8 asset-level
  ADD-lite core plus a governed defensive rotation with convexity
  re-entry. Best risk-adjusted line to date (Sharpe 0.87).
- **V7.10** — the **Strategy Sleeve Registry**: a validation +
  admission gate (Deflated Sharpe, realistic cost, correlation-to-book)
  through which candidate alpha sleeves must pass before joining the
  V7.9 book.

The V7.6α meta-regime steering kernel remains the frozen governance
base under both. V7.7 / V7.8 are prior overlay cuts (portfolio-level
ADD-lite + μ/σ²·Φ Kelly; then asset-level ADD-lite + conditional Kelly).
Prior versions (V6.3 → V7.5) remain in the tree as building blocks and
as on-dashboard reference baselines. Full version history is in
`RELEASE_NOTES.md`; the cross-method analysis is in
`Allocation_Method_Study.md`.

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
polyagora_v76_engine.py           V7.6 — meta-regime steering (frozen base kernel)
polyagora_v77_engine.py           V7.7 — ADD-lite + Kelly overlays (prior overlay cut)
polyagora_v78_engine.py           V7.8 — asset-level ADD-lite + conditional Kelly
polyagora_v79_engine.py           V7.9 — governed defensive rotation / convexity re-entry
polyagora_validation.py           V7.10 — DSR gate, realistic cost, walk-forward metrics
polyagora_sleeve_registry.py      V7.10 — Strategy Sleeve Registry + admission gates
polyagora_v710_engine.py          V7.10 — mean-reversion sleeve + governed sleeve blend

run_polyagora_v74_partner.py      V7.3 → V7.5 registry / dashboard runner
run_v76_check.py                  V7.6 manifold + meta-blend backtest
run_v76_sweep.py                  V7.6 hyperparameter sensitivity sweep
run_v77_check.py                  V7.7 ADD-lite + Kelly overlay backtest
run_v78_check.py                  V7.8 asset-level ADD-lite + conditional Kelly backtest
run_v79_check.py                  V7.9 winners + governed defensive rotation backtest
run_v710_check.py                 V7.10 sleeve-registry gate + sleeve evaluation
sweep_v75.py / analyze_v75_sweep.py    V7.5 parameter sweep + analyzer
validate_v74c.py / validate_v75.py     version validation suites

build_polyagora.py                full V7.3 → V7.5 pipeline (data refresh + run + dashboards)
build_polyagora_v76.py            V7.6 dashboard composer (curated v76 lineup)
build_polyagora_v77.py            V7.7 dashboard composer (overlays + v76 base)
build_polyagora_v78.py            V7.8 dashboard composer (refined overlays + v76 base)
build_polyagora_v79.py            V7.9 dashboard composer (winners-only lineup)
build_polyagora_v710.py           V7.10 dashboard composer (winners + sleeve registry)
build_dashboard_nm.py             "no momentum" dashboard variant
build_algo_v74_pdf.py             Algo_V74.md → PDF
build_v74d_vs_momentum_pdf.py     V74d_vs_Momentum.md → PDF
build_v76_findings_pdf.py         V76_Findings.md → PDF

polyagora_dashboard.py            engine-agnostic dashboard layer (SignalRun → HTML)
dashboard_template.html           HTML template (charts, summary table, presets, tooltips)
```

## V7.10 — Strategy Sleeve Registry

V7.10 operationalizes the multi-sleeve architecture
(`docs/More Sleeves.pdf`, `docs/AI Quant System.pdf`): it builds the
governance machinery a candidate alpha strategy must pass before it can
join the V7.9 book.

**Validation layer** (`polyagora_validation.py`) — the **Deflated
Sharpe Ratio** (corrects a Sharpe for multiple-testing selection bias),
extended metrics (skew, excess kurtosis, profit factor), a
size/volatility/venue `realistic_cost_bps` model, and walk-forward
IS/OOS degradation.

**Strategy Sleeve Registry** (`polyagora_sleeve_registry.py`) — a
candidate enters the book only after clearing the ordered gate pipeline:

```
validation → DSR noise floor → correlation-to-book
            → walk-forward degradation → contribution
```

The DSR is a *noise floor* here, not a hard 0.95 wall — that bar is the
upstream AI-factory gate; doc-2's registry admits on regime fit,
correlation and **contribution** (blending the sleeve must not degrade
the book). Each sleeve is stored with metadata (id, type, regime
affinity, failure modes, block, per-runtime-zone permission).

**Sleeves evaluated — one rejected, one admitted.** The mean-reversion
sleeve the cross-method study had named the next diversifier was
**rejected** — short-horizon reversal has no gross edge on the
momentum-prone universe and realistic cost annihilates it. The
**bond-trend sleeve** — a 12-month time-series trend on the bond
futures (TN, FGBL) — was **admitted**: it goes short bonds in
persistent rate shocks, so it earns +1.8 Sharpe in the 2022 rate
shock, is genuinely uncorrelated to the book (corr 0.28), and is
low-turnover. The registry holds it at ~18%.

v7.10 = v79 + the bond-trend sleeve reaches **Sharpe 0.91 / Sortino
1.23 / Calmar 0.49** at −6.5% drawdown, and — for the first time —
a **positive 2022 rate-shock Sharpe (+0.44** vs v79's −0.84): the
long-standing inflationary blind spot is finally addressed.

`docs/Terminal class and Banach points.pdf` is a theoretical
refinement of the Fixed Star ontology (semantic equivalence class +
Banach zero-tension representative) — conceptual grounding, no code.

### Run V7.10

```bash
# build the v79 book, evaluate the sleeves through the registry
python run_v710_check.py

# build the v7.10 dashboard (run run_v76_check.py + build_polyagora.py --v75 first)
python build_polyagora_v710.py
```

## V7.9 — Winners + Governed Defensive Rotation

V7.9 consolidates the V6.3→V7.8 tree down to the validated winners (the
cross-method study `Allocation_Method_Study.md` found the meta family
internally 0.98–1.00 correlated) and adds one improvement: a **governed
defensive rotation with convexity re-entry**
(`docs/PolyAgora Multi-Sleeve Alpha Architecture.pdf` §13–§14).

```
w_v79 = (1 − dₜ)·w_v78-ADD + dₜ·w_defensive
```

The rotation weight `dₜ` is driven by the ADD-lite book-fragility field
— the internal governed signal, not a lagged price trend — so re-entry
is prompt as conditions heal. `dₜ` is inert ~78% of the time (Zone 1)
and escalates only in genuine stress. Balanced default
`rot_gain = 1.0, d_max = 0.6`.

v79 reaches Sharpe **0.873** / Sortino 1.157 / Calmar 0.331 — the best
risk-adjusted line to date, beating v78-ADD on all three and preserving
the COVID-regime call. The runner/dashboard render only the
non-dominated winner set; the v74b·*, v75·*, v76β/γ and v77·* variants
are retired from the candidate lineup.

### Run V7.9

```bash
python run_v79_check.py        # headline + Dov panel + runtime zones + correlation governance
python build_polyagora_v79.py  # winners-only dashboard
```

## V7.8 — Asset-level ADD-lite + Conditional Kelly

V7.8 keeps the frozen V7.6α governance base and refines both V7.7
overlays per `docs/PolyAgora V7.8 Absolute Return Mode.pdf` and
`docs/Keep V7.7-ADD.pdf`. The V7.7 evaluation validated ADD-lite but
found Kelly "too blunt" — the μ/σ²·Φ sizer was a permanent brake that
moved too much capital to `CASH` and killed compounding.

**Asset-level ADD-lite (spec §9)** — V7.7 ADD-lite was a single
portfolio-level scalar scaling the whole book. V7.8 makes it a per-asset
field:

```
ADD_{i,t} ∈ [0,1]        w'_{i,t} = w_{i,t} · (1 − λ · ADD_{i,t})
```

so a fragile asset is trimmed without flattening the assets that are
still convex. Five segments, all derived from the 13-asset realized PnL
(ADD-lite stays external to the endogenous geometry): per-asset crowding,
recoverability loss, momentum saturation, volatility asymmetry, plus a
shared breadth-degeneration term.

**Conditional Kelly (spec §11–§12)** — V7.7's `f = mode_mult·(μ/σ²)·Φ`
is removed (§11 flags classical μ/σ² as "unstable under noisy
estimates"). V7.8 Kelly is the §12 gate:

```
K_t = max(0, 1 − γ · (ADD_book,t − baseline_t)_+ )      γ ∈ [0.2, 0.5]
w''_{i,t} = K_t · w'_{i,t}
```

`baseline` is `ADD_book`'s own trailing median, so Kelly is **inert
(K = 1) at or below normal book fragility** and trims only gently above
it — conditional, not a continuous brake.

Empirically (full sample 2008–2026) **v78-ADD beats both v76α and
v77-ADD on Sharpe, Sortino and Calmar at lower drawdown** — the spec §9
"preserve convex winners" property realized. Conditional Kelly is
near-inert by design (it barely moves the book in this sample); it is a
quiet safety gate, not an alpha source. Per `docs/Dov Benchmarks .pdf`,
this focused increment is a governance/risk refinement — clearing the
Dov bar (Sharpe / Sortino / Calmar > 1.5) needs the Phase-2 alpha
sleeves, not this version.

### Run V7.8

```bash
# v76α base + v77-ADD ref + v78-ADD + v78, with the Dov benchmark panel
python run_v78_check.py

# tuning knobs
python run_v78_check.py --add-lam 0.6 --kelly-gamma 0.35

# build the v78 dashboard (run run_v76_check.py + build_polyagora.py --v75 first)
python build_polyagora_v78.py
```

Outputs land in `polyagora_v78_outputs/`:

```
dashboard.html / dashboard_data.json   self-contained interactive dashboard
weights_/returns_ {v76, v77_add, v78_add, v78}
add_field_v78.csv                      asset-level ADD-lite field
kelly_v78.csv                          book_add, baseline, K_t
summary_v78_check.csv / crisis_v78_check.csv / dov_v78_check.csv
```

## V7.7 — ADD-lite + Kelly Overlays

V7.7 freezes the V7.6α steering kernel and adds two **downstream
overlays**. Neither touches regime / block / star / manifold
construction — both act only on the already-blended weight panel,
after the meta-allocator and before final allocation, and both deform
*capital intensity* (scaling real gross toward `CASH`) never direction.

**ADD-lite** — a low-frequency topology-deformation field per
`docs/Classical ADD to Lite-ADD.pdf` and `docs/Lite-ADD in Flow .pdf`:

```
ADD_lite = w_C·C + w_S·S + w_B·B + w_R·R + w_P·P + w_F·F   ∈ [0, 1]
```

over six interpretable segments — Corridor compression, Synchronization
stress, Breadth degeneration, Recoverability degradation,
Path-dependence, Fragility asymmetry. Component weights are frozen and
equal (never optimized against forward returns). ADD-lite is **external**
to the endogenous geometry: every segment is derived from market data
only (the 13-asset partner realized PnL). Rising ADD-lite scales gross
exposure down (`scale = 1 − k·ADD_lite`).

**Kelly** — capital-intensity sizing downstream of governance per
`docs/Kelly Integration Spec for PolyAgora CTO Team.pdf` (theory:
`docs/kelly_56.pdf`):

```
f_t = mode_mult · f*_t · Φ_t       f*_t = kelly_gain · μ_t / σ²_t
Φ_t = geomean(φ_Z, φ_R, φ_B, φ_V, φ_M)
```

`f_t` is the fraction of the capital budget deployed into real assets;
the rest parks in `CASH`. Conservative Mode A (`mode_mult = 0.25`) is the
default. Φ ∈ [0,1] is the governance gate — unlike ADD-lite it reads the
**internal** geometry (v75/v76 diagnostics + base-portfolio trajectory).
Each φ gate self-calibrates against a trailing window of its own stress
driver; Φ is their geometric mean (the spec writes a raw product, but a
product of five sub-unity gates would sit near 0.1 even in calm regimes
— the geometric mean places Φ on the spec §11 operational scale).

Empirically (full sample 2008–2026): ADD-lite is roughly risk-neutral
versus v76α (similar Sharpe, lower vol and drawdown, marginally higher
Calmar); Kelly is a conservative drawdown governor — it gives up the
strong first-half trend run but improves second-half / COVID-on
stability. The proxy choices for the six ADD + five Φ components are
provisional pending a dedicated "ADD-lite Runtime Integration Spec".

### Run V7.7

```bash
# v76α base + ADD-lite / Kelly / both, side-by-side vs the v76α baseline
python run_v77_check.py

# tuning knobs
python run_v77_check.py --add-sensitivity 0.6 --kelly-gain 1.0 --kelly-mode-mult 0.25

# build the v77 dashboard (run run_v76_check.py + build_polyagora.py --v75 first)
python build_polyagora_v77.py
```

Outputs land in `polyagora_v77_outputs/`:

```
dashboard.html / dashboard_data.json   self-contained interactive dashboard
weights_/returns_ {v76, v77_add, v77_kelly, v77}
add_lite_v77.csv                       6 components + raw/smoothed composite
governance_phi_v77.csv                 5 φ sub-gates + Φ
kelly_v77.csv                          μ, σ², f*, Φ, f_kelly
summary_v77_check.csv / crisis_v77_check.csv
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
