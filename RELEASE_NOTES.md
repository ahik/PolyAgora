# Release Notes

## Phase-II (v8.0) — 2026-05-19

Base: V7.10. Phase-II implements the six-layer "Convexity Exploitation
Under Governance" runtime from the PolygonEye Phase-II CTO spec and the
2026-05-19 response notes. **Status: draft / RC — the architecture is
built and the V7.10 crisis moat is preserved; the convexity gap is not
yet closed (see Findings).**

### What shipped — the `polyagora/` package

A new layered package (departing from the `polyagora_vXX` convention):

- `governance/moat.py` — Layer 1+2 base: the proven V7.10 stack,
  consumed as the Phase-II base allocation.
- `mrtp.py` — Layer 3 MRTP convexity scoring,
  `MRTP = aR + bC - cF - dP + eERQ` (coefficients 1.00 / 0.55 / 0.90 /
  0.75 / 0.45).
- `kelly.py` — Layer 4 Dynamic Kelly: asymmetric, ERQ-gated, 1.25x cap,
  post-stress cooldown; only ever adds recoverable leverage on top of
  the moat.
- `recoverability.py` — Layer 5 recoverability geometry (C/P/F/R) and
  Layer 5A Exposure Recoverability Quality (six-component ERQ).
- `runtime/graph.py` — the mandatory 13-step (+7A) execution graph.
- `regression.py` — the §12.2 moat-regression gate.
- `governance/core.py` — the V6.2 re-base (retained as reference only,
  see Key Decisions).

Runners `run_phase1..4`, `run_phase56_validation`, `run_sleeve_research`,
`refresh_macro_panel`, `build_phase2_dashboard`. Specs:
`docs/PolyAgora_PhaseII_General_Guideline.md`,
`_Implementation_Spec.md`, `_Open_Questions.md`.

### Key decisions

- **The v62 re-base of the Governance Core failed the §12.2 moat gate**
  (Sharpe 0.42 vs 0.91) — exactly as CTO_Response Risk 1 predicted: the
  moat rests on the v75->v76->v78->v79 stack, not v62. Resolution
  (Option B): the proven V7.10 stack *is* the Phase-II base; the new
  layers govern on top. The moat is reproduced bit-exact.
- Dynamic Kelly kept moat-respecting — leverage is added only in
  pristine, post-cooldown regimes and never cuts below the moat base.

### Validation

- **§12.2 moat gate: PASS 10/10** (Sharpe / Max DD / Corr SPY / GFC /
  COVID / 2022 / recovery-latency — crisis windows zero degradation).
- Recoverability falsification (directional, rupture vs bull): 12/15;
  the GFC is detected on all five estimators.
- First-test acceptance scorecard: 2/5 — Max DD and Corr SPY pass;
  Sharpe / Sortino / Calmar remain ≈ V7.10.

### Findings

- **Convexity sleeve research — 0/9 candidates admitted.** Type-C
  breakout has no edge; Type-B cross-sectional expansion is marginal
  (fails DSR); the strongest candidate (haven-trend) fails the
  contribution gate — it is redundant with the bond-trend sleeve
  already in the moat. Core finding: on the 13-futures universe with
  only realized PnL + a macro panel there is no un-harvested,
  cost-survivable, decorrelated convexity sleeve. The constructions
  that decorrelate have no edge; the ones with edge are already
  captured. (Confirms counterproposal Risk 2.)
- **Kelly leverage scales the moat — it does not create convexity.**
  Real convex participation requires admitted sleeves; none cleared.
- **Macro-data gap fixed.** The panel covered only 2013+; extended back
  to 2007-10 (`refresh_macro_panel.py` — Yahoo prepend, HG=F copper
  proxy for pre-2011 CPER, splice-rescaled; 2013+ rows byte-identical).
- The `R_t` estimator was re-formalized (the original streak/`tanh`
  form saturated and did not respond across regimes).

### Recommendations

1. **Source new data — the real unlock.** The convexity gap cannot be
   closed from realized-PnL + macro. Options data -> Type-D long-vol /
   rupture-asymmetry; futures term structure -> carry.
2. Re-test the 1.2 Sharpe first-test target with PolygonEye — the
   evidence suggests it may be unreachable on this universe while the
   moat stays sacred.
3. θ_ERQ and coefficient regime-dependence remain Phase-5 research
   items — iterate, do not block on them.

### Dashboard

`build_phase2_dashboard.py` -> a self-contained interactive HTML
dashboard: equity chart (full strategy family, log scale, re-based to
the window start, per-curve toggle + colour), sortable comparison
table that follows the chart toggles, mouse brush-zoom + manual date
pickers, zone colour bands, asset-allocation panel, index explorer,
the Layer 3/4/5/5A panels, crisis-window marks.

---

## V7.10 — 2026-05-17

Base: V7.9 book (v76α → v78-ADD → v79 governed rotation).

V7.10 operationalizes the multi-sleeve architecture: it builds the
Strategy Sleeve Registry, and admits the first alpha sleeve through it.
It collaborates `docs/AI Quant System.pdf` (the validation engine) and
`docs/More Sleeves.pdf` (the CTO instruction: "build a Strategy Sleeve
Registry"). `docs/Terminal class and Banach points.pdf` is a
theoretical refinement of the Fixed Star ontology — design notes only.

### Validation layer — `polyagora_validation.py`

The doc-1 evaluation pieces PolyAgora was missing, scipy-free: the
**Deflated Sharpe Ratio**, extended `performance_metrics` (skew, excess
kurtosis, hit rate, profit factor), a `realistic_cost_bps` model, and
`walk_forward_degradation`.

A **DSR bug was found and fixed**: the expected-maximum-null term was
scaled by `√annualization` (252) instead of `√n_observations`,
inflating the null bar ~4× — the gate rejected every real strategy,
including v79 itself. With the correct standard-error scaling the DSR
is functional (v79 now scores 0.96).

### Strategy Sleeve Registry — `polyagora_sleeve_registry.py`

A candidate enters the book only after clearing the ordered gate
pipeline — validation → DSR noise floor → correlation-to-book →
walk-forward degradation → **contribution** — and is stored with the
doc-2 metadata schema (id, type, regime affinity, failure modes, block,
per-runtime-zone permission).

The DSR's role was corrected: doc-1's hard `DSR > 0.95` is the *AI
strategy-factory* gate (kills best-of-1000 data-mined survivors). doc-2
— the PolyAgora *registry* — never sets that bar; it stores the DSR as
a metric and admits on regime fit, correlation and governance.
Accordingly the registry uses the DSR as a **noise floor** (the edge
must be more-likely-than-not real) and adds doc-2's governing
criterion as the **contribution gate**: blending the sleeve into the
book at its registry weight must not degrade risk-adjusted return.

### Sleeves evaluated — one rejected, one admitted

| Candidate | Net Sharpe | DSR | Corr-to-book | Verdict |
|-----------|-----------:|----:|-------------:|---------|
| xs_reversal_10d (mean-reversion) | −1.38 | 0.00 | −0.09 | REJECTED |
| **bond_trend_12m (crisis-trend)** | **0.51** | **0.58** | **0.28** | **ADMITTED** |

Mean-reversion has no gross edge on the momentum-prone universe and
realistic cost annihilates it — correctly rejected (validation, DSR,
contribution all fail). The **bond-trend sleeve** — a 12-month
time-series trend on the bond futures (TN, FGBL) — clears every gate:
it goes long bonds in flight-to-quality rallies and *short* bonds in
persistent rate shocks, so it earns a **+1.8 Sharpe in the 2022 rate
shock**, the regime every other component loses. It is genuinely
uncorrelated to the book (corr 0.28) and a low-turnover signal that
survives realistic cost. The registry admits it at ~18%.

### Result

v7.10 = v79 + the bond-trend sleeve. Dov first-test targets as before.

| Series | Sharpe | Sortino | Calmar | Max DD | Rate-22 Sharpe |
|--------|-------:|--------:|-------:|-------:|---------------:|
| v79 | 0.873 | 1.157 | 0.331 | −8.57% | −0.84 |
| **v7.10** | **0.914** | **1.234** | **0.491** | **−6.45%** | **+0.44** |

v7.10 beats v79 on Sharpe, Sortino, Calmar and drawdown — and **for the
first time posts a positive 2022 rate-shock Sharpe**. The bond-trend
sleeve gives back some upside in the 2021 reflation (its named failure
mode, choppy rates), but the net is a clear improvement and the long-
standing 2022 blind spot is finally addressed. Correlation governance
improves (winner-set avg correlation 0.72 → 0.56), though still above
the 0.35 target.

### Tooling

- `run_v710_check.py` builds the v79 book, evaluates the sleeves
  through the registry, and reports gate verdicts + correlation
  governance; `build_polyagora_v710.py` composes the dashboard (the
  admitted bond-trend and rejected MR sleeves both visible, hidden by
  default).

## V7.9 — 2026-05-16

Base: frozen V7.6α governance kernel; V7.8 asset-level ADD-lite core.

V7.9 consolidates the line down to the validated winners and adds the
single improvement identified by the cross-method study
(`Allocation_Method_Study.md`). It collaborates the insights of
`docs/PolyAgora Multi-Sleeve Alpha Architecture.pdf` — §13 convexity
re-entry, §14 runtime zones, §10 correlation governance.

### Winners-consolidated lineup

A cross-method study compared all 33 return series across the full
2008→2026 timeline and seven regime windows. It found the V6.3→V7.8
tree is mostly redundant — the V7.6/7.7/7.8 meta family is internally
0.98–1.00 correlated. V7.9's runner and dashboard carry only the
non-dominated set (v76α, v78-ADD, v79, the four manifolds, references —
10 methods, down from 14). The v74b·*, v75·*, v76β/γ and v77·* variants
are retired from the candidate lineup and survive only as importable
building blocks.

### Governed defensive rotation with convexity re-entry

`w_v79 = (1 − dₜ)·w_v78-ADD + dₜ·w_defensive`. The rotation weight dₜ is
driven by the ADD-lite **book-fragility field** — the internal governed
signal, not a lagged price trend — so re-entry is prompt as conditions
heal (the spec §13 "re-enters too slowly" fix). dₜ is inert ~78% of the
time (Zone 1) and escalates only in genuine stress (Zones 3–4).
Balanced default `rot_gain = 1.0, d_max = 0.6`, set by parameter sweep.

### Results vs. base — and the Dov first-test targets

Dov "first CTO test" targets: Sharpe > 1.2, Sortino > 1.5, Calmar > 1.0,
MaxDD < 8%, Corr-SPY < 0.35. ✓ = meets target, ✗ = misses.

| Series             | Sharpe       | Sortino      | Calmar       | Max DD        | Corr-SPY     |
|--------------------|--------------|--------------|--------------|---------------|--------------|
| v76α (base)        | 0.821 ✗      | 1.078 ✗      | 0.315 ✗      | −10.25% ✗     | 0.026 ✓      |
| v78-ADD            | 0.827 ✗      | 1.081 ✗      | 0.324 ✗      | −7.99% ✓      | 0.023 ✓      |
| **v79 (rotation)** | **0.873 ✗**  | **1.157 ✗**  | **0.331 ✗**  | **−8.57% ✗**  | **0.024 ✓**  |

v79 beats v78-ADD on Sharpe, Sortino *and* Calmar, and preserves the
COVID-regime call (Sharpe 1.30) where a trend-driven tilt lagged. The
gain costs ~0.6pp of drawdown — v79 slips just back over the 8% line
that v78-ADD cleared. The three ratio targets remain unmet; that bar
needs the Phase-2 alpha sleeves, not this governance increment.

### Honest limitations

- **Correlation governance fails.** Average pairwise correlation of the
  winner set is 0.64 vs the spec §10 target of 0.35 — the winners are
  still one return stream. The next genuine diversifier is a
  mean-reversion sleeve.
- **2022 is still unsolved.** v79 posts a negative 2022 Sharpe (−0.84);
  it rotates into `defensive`, itself the rate-shock victim. Rotation
  raises the deflationary-crash edge; it cannot fix the inflationary
  blind spot.

### Tooling & docs

- `run_v79_check.py` reports the headline, Dov panel, regime windows,
  the §14 runtime-zone distribution and the §10 correlation-governance
  check; `build_polyagora_v79.py` composes the winners-only dashboard.
- New analysis report `Allocation_Method_Study.md` — the full
  cross-method, multi-timeline comparison behind this release.
- Ships `docs/PolyAgora Multi-Sleeve Alpha Architecture.pdf`.

## V7.8 — 2026-05-16

Base: frozen V7.6α governance kernel.

V7.8 refines the two V7.7 overlays based on the V7.7 evaluation, which
validated ADD-lite but found Kelly too blunt — a permanent μ/σ² brake that
over-allocated to CASH and suppressed compounding.

### ADD-lite → per-asset deformation field

ADD-lite is now a continuous per-asset deformation `w'ᵢ = wᵢ·(1 − λ·ADDᵢ)`
(spec §9), built from five segments derived from the 13-asset realized PnL:
per-asset crowding, recoverability loss, momentum saturation, volatility
asymmetry, and a shared breadth term. Trimming a fragile asset no longer
flattens the convex winners.

### Kelly → conditional gate

Kelly drops the μ/σ²·Φ machinery and becomes the spec §12 conditional gate
`K = max(0, 1 − γ·(ADD_book − baseline)₊)`: inert at or below normal book
fragility, gently trimming only above it. Near-inert by design.

### Results vs. base — and the Dov first-test targets

Dov "first CTO test" targets: Sharpe > 1.2, Sortino > 1.5, Calmar > 1.0,
MaxDD < 8%, Corr-SPY < 0.35. ✓ = meets target, ✗ = misses.

| Series          | Sharpe        | Sortino       | Calmar        | Max DD         | Corr-SPY      |
|-----------------|---------------|---------------|---------------|----------------|---------------|
| v76α (base)     | 0.821 ✗       | 1.078 ✗       | 0.315 ✗       | −10.25% ✗      | 0.026 ✓       |
| v77-ADD         | 0.802 ✗       | 1.035 ✗       | 0.319 ✗       | −8.61% ✗       | 0.026 ✓       |
| **v78-ADD**     | **0.827 ✗**   | **1.081 ✗**   | **0.324 ✗**   | **−7.99% ✓**   | **0.023 ✓**   |
| v78 (ADD+Kelly) | 0.827 ✗       | 1.080 ✗       | 0.323 ✗       | −7.97% ✓       | 0.023 ✓       |

v78-ADD beats both v76α and v77-ADD on Sharpe, Sortino, and Calmar at lower
drawdown. It clears the two structural Dov targets (MaxDD, Corr-SPY) — v78 is
the first line under 8% drawdown — but the three ratio targets remain unmet:
that bar (all three ratios > 1.5) needs the Phase-2 alpha sleeves, not this
governance/risk increment.

### Tooling & dashboard

- `run_v78_check.py` reports the Dov benchmark panel; `build_polyagora_v78.py`
  composes the dashboard.
- Summary table gains a **Corr-SPY** column and shades Sharpe / Sortino /
  Calmar / Max DD / Corr-SPY cells green/red for pass/fail against the Dov
  first-test targets, recomputed live per selected time window.
- Ships the three V7.8 spec docs.
