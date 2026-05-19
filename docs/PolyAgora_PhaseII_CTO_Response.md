# PolyAgora Phase-II — CTO Team Response

**To:** PolygonEye AI Lab — CTO / Quant Engineering / Systems Architecture
**Re:** Phase-II Engineering Specification v1.0 (May 2026), "Convexity Exploitation Under Governance"
**Status:** CTO counterproposal — Deliverables A, B, C + architectural challenge
**Baseline:** V7.10 Strategy Sleeve Registry

---

## 0. Executive Summary

This document responds to the Phase-II spec with the three requested deliverables
(A — Runtime State Diagram, B — Recoverability Geometry Formalization, C — Convexity
Participation Architecture) and an architectural counterproposal identifying the three
highest-risk assumptions.

The single most important engineering finding precedes all three deliverables:

> **The "Governance Core" the spec describes is not a layer in the running system.**
> Its machinery — Reference Polygon, Survival Matrix `S_ij`, block/star logic, zone
> classification — is fully implemented, but it is *scoped inside one of four manifolds*
> (`v74d_q`). The actual top-level allocator (`v76α meta_blend`) is a rolling-Sharpe
> softmax with no `β`, no zone, and no survival matrix. The spec's instruction "the
> Governance Core must not be modified" therefore cannot be satisfied literally — the
> object it names does not exist as a modifiable layer.

**CTO decision:** the Governance Core will be **re-based on the V6.2 engine**
(`polyagora_v62_engine.py`). This is the spec-literal reading: execution-graph Steps 2,
4, 5 and 6 describe V6.2 verbatim (the `(V,T,G,C,R)` coordinate, the 13×5
strategy×block admissibility, the survival matrix, the minimum-pairwise-`W` clustering).
V6.2 becomes Layer 1; the V7.x stack (polygon, meta-blend, ADD-lite, rotation, sleeve
registry) is re-wired to consume Layer 1's `β_t` / Zone / Governance-State outputs.

The re-base is the largest structural change in Phase-II and carries a regression risk
addressed directly in the counterproposal (§4, Risk 1).

**Document set.** §§1–3 below are summaries. Each deliverable has a full companion document:
- `PolyAgora_PhaseII_Deliverable_A_State_Diagram.md` — 13-step graph, state schema, contracts
- `PolyAgora_PhaseII_Deliverable_B_Recoverability_Geometry.md` — 5 estimators, formulas, falsification protocol
- `PolyAgora_PhaseII_Deliverable_C_Convexity_Architecture.md` — 6-gate API, typed catalog, new candidates

---

## 1. Deliverable A — Runtime State Diagram

### 1.1 Layer-1 reconciliation outcome

Layer 1 (Governance Core) is rebuilt from V6.2. It owns and emits, as **first-class
top-level outputs**:

| Output | V6.2 source | Definition |
|---|---|---|
| `X_t` — Reference Polygon coordinate | `compute_coordinate` | `(V,T,G,C,R) ∈ [-1,1]⁵` |
| `S_ij` — Survival Matrix | `rolling_survival_matrix` | continuous co-survival score `∈ [0,1]` |
| `A` — Admissibility matrix | Step 5 (see footnote 2) | 13×5 strategy × block |
| `β_t` — β-Admissibility | `compute_x_sm_alignment` → governor | scalar `∈ [0,1]` recoverable-admissibility signal |
| Zone | `classify_block` + `star_zone` | 5-mode classifier (see footnote 3) |

Every other Phase-II layer (Convexity Sleeves, MRTP, Dynamic Kelly, Recoverability
Geometry) operates strictly **downstream of, and conditional upon, these outputs**.

### 1.2 The 13-step runtime execution graph

Order is mandatory; each step's output feeds the next. Cadence: **W** = weekly,
**E** = event-driven, **P** = persistent-state read.

| # | Step | Target layer | Current code | Cadence |
|---|---|---|---|---|
| 1 | Market Data Ingestion | Runtime | `load_partner_xlsx` + market CSV | W |
| 2 | Polygon Projection → `(V,T,G,C,R)` | L1 Governance | `build_exogenous_x`, `compute_coordinate` (v62) | W |
| 3 | VAIDM Classification (6-axis → RUPTURE/HIGH_STRESS/ELEVATED/BENIGN) | L1 Governance | `Q_VAIDM` proxy only (v73) — see footnote 1 | E |
| 4 | Survival Matrix Update `S_ij` | L1 Governance | `rolling_survival_matrix` (v62) | W |
| 5 | Admissibility Derivation (13×5) | L1 Governance | none — see footnote 2 | W |
| 6 | Block / Zone Classification (5-mode) | L1 Governance | `classify_block`, `star_zone` (v62) — footnote 3 | W |
| 7 | Recoverability Geometry Update | L5 Recoverability | none (ADD-lite `R`-component partial) | W / P |
| 8 | ADD Filtering (per-strategy decay) | L2 Sleeves / filter | `compute_add_lite_field`, `apply_asset_deformation` (v78) | W |
| 9 | MRTP Scoring | L3 MRTP | `compute_mrtp_score` (v76, dormant) — footnote 4 | W |
| 10 | Dynamic Kelly Sizing `f_t` | L4 Kelly | v77 Kelly (haircut-only) — footnote 5 | W |
| 11 | Sleeve Allocation | L2 Sleeves | `blend_sleeve` + registry (v710) | W |
| 12 | Contraction Map (Banach, `τ=0.60, λ=0.40`) | Runtime | contraction in v73/v74b — footnote 6 | W |
| 13 | Execution Output (allocation + validation + log) | Runtime | `evaluate` + CSV logging | W |

### 1.3 State schema

| Variable | Dim | Range | Update | Persistence | Normalization / smoothing |
|---|---|---|---|---|---|
| `X_t` | 5 | `[-1,1]` | weekly | recomputed | `tanh` per axis |
| `S_ij` | 13×13 | `[0,1]` | weekly | rolling window (126) | rolling corr + co-survival blend |
| `A` | 13×5 | `[0,1]` | weekly | recomputed | sigmoid |
| `β_t` | 1 | `[0,1]` | weekly | EWM-smoothed across steps | governor + alignment |
| Zone | categorical | 5 modes | weekly | hysteresis on transitions | discrete |
| `R_t` | vector (v1) | `[0,1]` | weekly | history window | see Deliverable B |
| `C_t` corridor width | 1 | `[0,1]` | weekly | history window | see Deliverable B |
| `P_t` ridge pressure | 1 | `≥0` | weekly | history window | see Deliverable B |
| `F_t` fragmentation | 1 | `[0,1]` | weekly | history window | see Deliverable B |
| `f_t` Kelly multiplier | 1 | `[0, cap]` | weekly | hysteresis state persisted | see Deliverable C / §4 |
| `Π_t` sleeve weights | n_sleeves | `[0,1]` | weekly | registry-persisted | zone-scaled |

### 1.4 Storage contracts

- **Persisted across time steps:** `S_ij` rolling window, Recoverability history
  (Step 7), Kelly hysteresis state (Step 10), the Sleeve Registry, Zone-transition
  hysteresis buffer.
- **Recomputed fresh each bar:** `X_t`, `A`, `β_t`, MRTP scores, the final allocation
  vector.

### Deliverable-A footnotes (spec/code reconciliation items)

1. **VAIDM is not implemented as a six-axis classifier.** Step 3 says "Load VAIDM
   report." In code, VAIDM exists only as `Q_VAIDM`, a single gross-exposure multiplier
   in `v73`. Deliverable A must pin VAIDM's provenance — external feed vs. computed from
   the macro panel — before Step 3 is buildable. *Open.*
2. **`derive_admissibility_from_survival()` does not exist.** Step 5 says the 13×5
   admissibility is derived *from the survival matrix*. In code, admissibility is
   `σ(coef · polygon_coord)` — derived from the Reference Polygon, not `S_ij`. `S_ij`
   feeds block cohesion on a separate path. The rebased Layer 1 will implement Step 5 as
   specified; the polygon-derived path is retained as the admissibility *prior*.
3. **Zone classifier is 3-mode, spec wants 5.** V6.2 `star_zone` emits
   `zone1_star / zone2_transition / zone3_defensive`; `v75` emits 4 integer modes. The
   spec's 5 modes (`LOCAL_STAR / TRANSITION / LEAST_BAD / BUFFER / BOUNDARY`) require
   defining `LEAST_BAD` and `BUFFER`. There are also **three uncoordinated zone systems**
   today (v75 gross-gate zones, v79 rotation zones, v710 sleeve-permission zones); Phase-II
   collapses these into the single Layer-1 5-mode classifier.
4. **MRTP formula differs.** `v76.compute_mrtp_score` implements `α·S + β·F − γ·D`; the
   spec's Step 9 / §3.3 wants `α·R + β·C − γ·F − δ·P`. The dormant code is a starting
   point, not the target — see Deliverable B for the `R/C/F/P` inputs.
5. **Kelly is inverted.** v77 Kelly is `f_t = mode_mult · f* · Φ` with `Φ ∈ [0,1]` and
   `kelly_cap = 1.0` — it can only *haircut* exposure. The spec's Dynamic Kelly must
   *expand* (see §4 Risk 3).
6. **Banach params differ.** Step 12 specifies `TAU_BUFFER=0.60, LAMBDA=0.40`; the
   contraction maps in `v73`/`v74b` use different values — to be standardized.
7. **Universe ambiguity.** V6.2's native universe is the 13 AGUR *strategies*; the V7.10
   baseline metrics are on the 13 partner *futures*. The spec's "13×5" and "13-strategy
   universe" language matches V6.2. Deliverable A must pin which universe the rebased
   Layer 1 operates on, and the mapping between them.

---

## 2. Deliverable B — Recoverability Geometry Formalization

The deepest layer and the primary mathematical moat. Currently conceptual; Phase-II
makes it a computable, runtime-updateable estimator set, tractable at weekly cadence
over the 13-strategy universe across 2008–2026.

### 2.1 Candidate v1 estimators

Built from signals that already exist, to keep v1 falsifiable rather than speculative:

| Geometry variable | v1 proxy estimator | Source |
|---|---|---|
| Corridor width `C_t` | count / dispersion of admissible blocks; spread of block membership scores | v62 `block_scores_from_x`, `A` |
| Ridge pressure `P_t` | rate-of-change of minimum pairwise `W_t`; contradiction-density buildup | v62 `rolling_survival_matrix` |
| Fragmentation field `F_t` | ADD-lite breadth (`B`) + synchronization (`S`) sub-components | v77/v78 ADD-lite field |
| Re-entry probability | conditional recovery frequency in a memory window after contraction | backtest-derived |
| Admissibility persistence | duration / stability of the current block's `β_t` above threshold | Layer-1 `β_t` series |

### 2.2 Falsification protocol (the key methodological commitment)

Every estimator must, **before it is allowed to feed Kelly or MRTP**, pass a
falsification test: it must measurably degrade through the 2008 and 2020 ruptures and
recover through the post-2020 reflation. An estimator that does not move in the known
episodes is rejected. This prevents "primary mathematical moat" from becoming
unfalsifiable narrative.

### 2.3 Scalar vs. vector

`R_t` is kept a **vector** in v1 (per the spec's own Open Problem A, question 6).
Collapse to a scalar only if a defensible aggregation survives §2.2.

### 2.4 Deliverable artifact

Backtested `R_t` (vector) over 2008–2026, annotated against known rupture (2008, 2020,
2022) and expansion (2009–2011, post-2020) episodes, with the §2.2 falsification result
per estimator. Treated as a 6–8 week research track.

---

## 3. Deliverable C — Convexity Participation Architecture

### 3.1 Formal sleeve admission pipeline — 6 gates

The current registry has 5 gates. Phase-II adds the sixth (Fragility Audit).

| # | Gate | Metric | Status |
|---|---|---|---|
| 1 | Validation | finite standalone edge, ≥252 obs | exists |
| 2 | Deflated Sharpe | DSR noise floor (not the hard 0.95 AI-factory wall) | exists |
| 3 | Correlation | max corr to book **and to SPY** (hard ceiling `< 0.15`) | exists for book; **add SPY ceiling** |
| 4 | Walk-forward | OOS/IS degradation across ≥2 regimes | exists |
| 5 | Contribution | marginal Sharpe/Sortino — blending must not degrade the book | exists |
| 6 | **Fragility Audit** | stress test vs 2008 / 2020 / 2022 rupture windows | **new** |

API: `evaluate_sleeve(spec, sleeve_returns, book_returns, cfg) → SleeveEvaluation`,
extended with the SPY-correlation input and the Fragility Audit gate.

### 3.2 Typed sleeve catalog

Replace ad-hoc `SleeveSpec` strings with the spec's four types:

- **A — Crisis Trend.** Bond/USD/long-vol trend. *Status: bond-trend ADMITTED in V7.10.*
- **B — Expansion Convexity.** The Phase-II priority — the bull-market gap.
  *Status: no sleeve. New candidate required.*
- **C — Transition Convexity.** Cross-asset breakout, early momentum, low fragmentation.
  *Status: no sleeve. New candidate required.*
- **D — Rupture Asymmetry.** Tail-option / long-vol structure. *Status: data-blocked
  (no options/VIX-term-structure data) — flagged, not fabricated.*

### 3.3 New candidates within current data limits

The repo has only the 13-asset futures realized/forward PnL + a macro panel
(VIX/SPY/HYG/TLT/GLD/CPER). Carry, Vol and Flow sleeves remain data-blocked.

- **Type B candidate — cross-sectional / relative-value expansion.** Long the strongest
  vs. short the weakest futures within the universe — captures persistent-expansion
  convexity *without* taking directional equity beta, the only way to also clear the
  Corr-SPY `< 0.15` gate (see §4 Risk 2).
- **Type C candidate — low-fragmentation cross-asset breakout.** Early-momentum entry
  gated by Layer-5 `F_t` so it only fires when fragmentation is low.

### 3.4 Decorrelation constraint matrix

A maximum-correlation matrix between every pair of admitted sleeves and between each
sleeve and the main manifold, with the **SPY column as a hard wall** (`< 0.15`).
Enforced both per-sleeve (gate 3) and at book level after each admission.

---

## 4. Architectural Counterproposal — Three Highest-Risk Assumptions

The spec requests a structured challenge, not implementation agreement. The three
highest-risk assumptions, with engineering mitigations:

### Risk 1 — "The V7.10 baseline rests on a Governance Core that can be frozen."

The spec freezes the Governance Core and treats the V7.10 baseline (Sharpe 0.91, Max DD
-6.46%) as resting on it. It does not. The baseline is produced by the **entire v75 → v76
→ v78 → v79 stack**; the spec-described Core (V6.2) is not what runs, and V6.2 *alone*
never produced those metrics. Re-basing Layer 1 onto V6.2 for spec-compliance therefore
endangers the very baseline the spec wants protected.

**Mitigation.** Treat the re-base as a **behavior-bounded migration, not a rewrite**:
(a) Deliverable A is the agreed contract before any module is built; (b) the rebased
Layer 1 must reproduce the V7.10 baseline within a pre-agreed tolerance band as a hard
acceptance gate — if it regresses, the re-base is rejected and we fall back to
documenting the v75/v76 stack *as* the Core; (c) keep the current V7.10 stack runnable
in parallel as the regression reference throughout Phase-II.

### Risk 2 — "Expansion convexity can be captured while holding Corr SPY < 0.15."

The entire Phase-II thesis is harvesting persistent-bull / reflation upside. But Type B
instruments (equity-trend acceleration, growth exposure) *are* equity beta. Capturing
reflation convexity and holding near-zero SPY correlation pull in opposite directions —
one of the Sharpe target or the correlation invariant will fail.

**Mitigation.** Define Type B as **cross-sectional / relative-value** expansion (long
strong vs short weak within the futures universe) or commodity-curve expansion — not
directional equity beta. Treat the acceptance criterion "narrow the gap vs Momentum by
≥30%" as the binding target, *not* full beta capture. Enforce SPY correlation as a hard
registry gate both per-sleeve and at book level (§3.4).

### Risk 3 — "Kelly leverage expansion is compatible with Max DD < 8%, given hysteresis."

Dynamic Kelly must *expand* gross toward (and possibly past) 1.0× during "stable
expansion." But stable expansion is exactly the state preceding fast ruptures (2020
followed a calm bull). Hysteresis protects against transient ridge-pressure spikes — but
it makes the system *slower to de-lever* into a genuine rupture from a high-leverage
state. Leverage expansion and the drawdown floor are in direct tension.

**Mitigation.** Asymmetric Kelly dynamics: **slow expansion, instant contraction** — no
hysteresis on the down-leg. Hard leverage cap (recommend **1.25×**, not uncapped). A
non-negotiable cash / crisis-sleeve floor that survives even maximum Kelly expansion.
Stress-test every Kelly schedule against a **synthetic instant-rupture-from-peak-leverage**
scenario, not only the historical 2008/2020 paths.

*Noted research risk (already flagged by the spec, not counted in the top three):*
Recoverability Geometry may not be cleanly computable from 13 return streams — mitigated
by the falsification protocol in Deliverable B §2.2.

---

## 5. Proposed Phasing

| Track | Weeks | Scope |
|---|---|---|
| Deliverable A — state diagram + V6.2 re-base contract | 1–2 | gates everything |
| Deliverable C — 6-gate API + Type B/C candidate design | 1–4 | parallel to A |
| Deliverable B — recoverability estimators + 2008–2026 backtest | 1–8 | research track |
| Layer-1 re-base + regression gate (Risk 1 mitigation) | 3–6 | behavior-bounded |
| Layers 5 → 3 → 4 build (Recoverability → MRTP → Kelly) | 6–12 | dependent on B |
| Integration + stress test + CTO-target validation | 10–14 | acceptance |

**Acceptance:** Sharpe > 1.2, Sortino > 1.5, Calmar > 1.0, Max DD < 8%, Corr SPY < 0.15,
walk-forward OOS — *and* the Risk-1 regression gate (rebased Layer 1 reproduces the
V7.10 baseline within tolerance).

## 6. Open Questions Returned to PolygonEye

1. VAIDM provenance — external six-axis feed, or computed from the macro panel?
2. Universe — does the rebased Layer 1 operate on the 13 AGUR strategies or the 13
   partner futures? (Footnote 7.)
3. Definitions of the 5th and intermediate zone modes (`LEAST_BAD`, `BUFFER`).
4. Leverage cap — confirm 1.25× as the maximum admissible expansion.
5. Regression tolerance band for the Risk-1 acceptance gate.

---

*PolyAgora Phase-II — CTO Team Response · CONFIDENTIAL · Draft v0.1*
