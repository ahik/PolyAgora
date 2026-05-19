# PolyAgora Phase-II — Open Questions Register

**Companion to:** `PolyAgora_PhaseII_Implementation_Spec.md` (§13) and
`PolyAgora_PhaseII_General_Guideline.md`
**Status:** **ALL 7 RESOLVED** — answered by PolygonEye 2026-05-19 · Draft v2.0
**Purpose:** the questions that had to be answered before Phase-II became code. All are
now closed; outcomes are folded into the Implementation Spec.

| # | Question | Resolution | Folded into |
|---|---|---|---|
| 1 | VAIDM provenance | **Computed in-house** (endogenous) | Impl Spec §0 A2 |
| 2 | Universe | **13 partner futures** | Impl Spec §0 A1 |
| 3 | `LEAST_BAD` / `BUFFER` definitions | **Sharpened** (see Q3) | Impl Spec §9 |
| 4 | Leverage cap | **1.25×** — do not exceed early | Impl Spec §0 A5, §7 |
| 5 | Regression tolerance band | **Defined** (see Q5) | Impl Spec §12.2 |
| 6 | `θ_ERQ` calibration | **Philosophical admissibility boundary**, by falsification | Impl Spec §5, §10 |
| 7 | MRTP coefficients | **Initial values set** (see Q7) | Impl Spec §6 |

---

## Q1 — VAIDM provenance · RESOLVED: computed in-house

VAIDM remains **endogenous** to PolygonEye/PolyAgora — not an external feed. It is not
merely a macro indicator; it is a semantic deformation operator, a corridor-pressure
estimator, a topology modifier. Outsourcing it would fragment the ontology.

`VAIDM_t = f(macro panel, cross-asset stress, realized PnL, fragmentation, transition
dynamics)`. Start from the macro panel; evolve later toward richer topology. Our working
assumption A2 was correct.

## Q2 — Universe · RESOLVED: 13 partner futures

Layer 1 is **futures-native**. Futures are liquid, with observable corridor behavior,
measurable recoverability, and clearer transition geometry. AGUR strategies are already-
transformed, partially opaque, downstream abstractions — PolyAgora must govern *primary
geometry first*. Strategies may later be *mapped onto* the futures manifold, but
foundational Layer 1 stays futures-native. Working assumption A1 was correct.

## Q3 — `LEAST_BAD` / `BUFFER` · RESOLVED: definitions sharpened

- **BUFFER** — a *corridor-ambiguity state*: no stable local star yet, fragmentation
  unresolved, transition law still deforming, premature commitment dangerous. Action:
  freeze leverage, freeze aggressive convexity, preserve optionality. In one line:
  *"do not collapse possibility space too early."* Deeply MRTP.
- **LEAST_BAD** — *degraded admissibility without full rupture*: no attractive corridor,
  but one corridor still survivable. **Not an opportunity state and not bearishness — a
  constrained-continuity state.** Action: minimal deployment, preserve continuity, avoid
  collapse, maintain re-entry.

## Q4 — Leverage cap · RESOLVED: keep 1.25×

Keep **1.25×**; do **not** exceed it early. The moat comes from recoverability and low
forced-deleveraging risk; too much Kelly expansion destroys the ontology and the crisis
edge, turning the system into a leveraged momentum allocator. You need *asymmetry, not
leverage*. A dynamic regime-sensitive cap may come later — not now.

## Q5 — Regression tolerance band · RESOLVED

"Without this, Phase-II can silently destroy V7.10." The crisis moat is **sacred**:

| Metric | Allowed degradation |
|---|---|
| Sharpe | max −0.07 |
| Max DD | max +1.5 pp |
| Corr SPY | max +0.03 |
| Crisis windows (GFC / COVID / 2022) | **NO degradation allowed** |
| Recovery latency | max +15% |

If GFC / COVID / 2022 materially degrade, the architecture **fails — even if CAGR rises.**

## Q6 — `θ_ERQ` calibration · RESOLVED: a philosophical boundary, not a metric

`θ_ERQ` is **not a performance threshold — it is a philosophical admissibility
boundary.** Too low → the system admits irreversible convexity and the moat dies; too
high → the system reproduces V7.10 under-participation. Method: do **not** begin from
return optimization — begin from **recoverability falsification**: identify structures
that historically destroyed maneuverability, ensure ERQ rejects those *first*, then
gradually widen admissibility. Calibrated in Phase 5; method fixed now.

## Q7 — MRTP coefficients · RESOLVED: initial values set

The coefficients are not statistical weights — they are *the ethical geometry of the
system*: what it protects, what it sacrifices, what it deems irreversible. Optimizing
them directly for Sharpe/CAGR would collapse the architecture into conventional
optimization. Initial **philosophical configuration** (not final):

| Coef | Value | Meaning |
|---|---|---|
| `α` recoverability priority | **1.00** | supreme invariant |
| `γ` fragmentation aversion | **0.90** | anti-chaos |
| `δ` ridge-pressure sensitivity | **0.75** | anticipatory contraction |
| `β` expansion confidence | **0.55** | subordinate to survivability |
| `η` recoverable-convexity preference | **0.45** | the "temptation dial" — evolve LAST |

Hierarchy `α, γ, δ > β, η` early. Raise `η` only after the crisis moat is proven intact;
raising it prematurely makes the system convexity-seeking. Coefficients eventually become
regime-dependent (crisis: `α,γ,δ` dominate; reflation: `η` rises moderately; rupture:
`α` overwhelming).

---

## Outcome

PolygonEye's verdict (`GO CTO Team — Final touches`, 2026-05-19): the ontology,
runtime architecture and implementation decomposition are all coherent — *"this is
enough to start coding."* No question remains a blocker. `θ_ERQ` and final coefficient
calibration are **Phase-5 research outputs**, not pre-conditions — implementation
proceeds per the mandated 6-phase sequence (Impl Spec §12.1).

---
*PolyAgora Phase-II Open Questions Register · CONFIDENTIAL · Draft v2.0 — all resolved*
