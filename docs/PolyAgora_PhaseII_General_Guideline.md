# PolyAgora Phase-II — General Guideline

**Document 1 of 2** · companion: `PolyAgora_PhaseII_Implementation_Spec.md`
**Status:** Consolidated doctrine · Draft v1.0 (supersedes `CTO_Response` §0 and the
narrative sections of Deliverables A/B/C)
**Audience:** CTO, Quant Engineering, Systems Architecture, PolygonEye AI Lab
**Sources compiled:** Phase-II CTO Spec v1.0 + 6 PolygonEye/FSF response notes (May 2026)

> This document is the *why*. The companion Implementation Spec is the *how* —
> formulas, schemas, matrices, deliverables. Read this first.

---

## §0. Capstone — The Destination

PolyAgora is not a return-maximizing system. Its destination — the invariant every
layer is built to serve — is:

> **Survivable admissibility under changing reality.**

Traditional finance optimizes `Goal = max(Return)`; risk, liquidity, optionality and
drawdown are treated as secondary constraints. PolyAgora inverts this:

> **`Goal = max(Recoverable Compounding)` subject to `Future Maneuverability Preservation`.**

`max(Return)` is **not a true Fixed Star** — it is unstable across regimes, not
invariant, corridor-dependent, and frequently self-destructive (LTCM, Archegos, levered
momentum collapses, volatility-selling blowups). It behaves like a transient local
attractor. The true invariant is closer to **`max(Survivable Maneuverability)`** —
*preserve the ability to continue navigating under changing regime geometry.*

**Consequences that bind the whole architecture:**

1. **Returns are demoted to local manifestations** — admissible realizations,
   corridor-dependent opportunities — *inside* a larger invariant: recoverable
   continuity. Returns are an output, never the target.
2. **The Fixed Star is not a point, payoff, or terminal reward.** It is the invariant
   that preserves coherent navigation under regime transformation.
3. **There is no single universal star — there are local stars per block.** The
   Governance Core navigates *among* local stars while preserving higher-order
   recoverability:

   | Block / regime | Local star |
   |---|---|
   | Crisis | survivability |
   | Stable reflation | controlled expansion |
   | Inflation rupture | correlation independence |
   | Transition | optionality preservation |

The profound inversion: a hedge fund asks *"How do we maximize return?"*; PolyAgora asks
*"What forms of growth preserve future admissibility?"* — a different ontology. Phase-II
makes this distinction **operational and measurable** (see Implementation Spec — Layer 5
geometry and the ERQ score are the measuring instruments).

---

## §1. Core Diagnosis

PolyAgora V7.10 already excels at: contraction, admissibility gating, crisis steering,
recoverability preservation, avoiding corridor collapse — hence its strong GFC / COVID /
2022 behavior, low drawdown, near-zero SPY correlation.

The *same machinery* contracts early, reduces irreversible exposure, avoids forced
traversal, and keeps optionality high — so the system **structurally under-participates
in convex bull expansions**. This is **not a bug**. It is recoverability preference
correctly dominating convex exploitation. The system today optimizes
`Recoverability ≫ Convex Exploitation`. Phase-II rebalances this relationship — *without
sacrificing the crisis moat.*

---

## §2. The New Principle

> **Convexity must itself be recoverability-compatible.**

The system currently governs allocations, blocks, regimes and sleeves — but not
**exposure topology itself**. That is the next layer.

The doctrine sharpens what MRTP is:

> **MRTP is not anti-convexity. MRTP is anti-*irreversible*-convexity.**

The objective is not "maximize upside" but **"maximize upside without destroying future
maneuverability."**

---

## §3. Two Classes of Convexity

Convexity is decomposed into two first-class, runtime-governed classes:

| Class | Definition | Examples | Policy |
|---|---|---|---|
| **Irreversible convexity** | path-fragile, leverage-fragile, forced-traversal-dependent; narrows future admissible corridors | naked leverage, concentrated beta, naked shorts, correlation-collapse bets, liquidity-fragile momentum | suppressed / capped / disabled in transition & rupture |
| **Recoverable convexity** | optionality-preserving, bounded-risk, corridor-compatible; preserves or widens future corridors | cross-sectional dispersion, bounded asymmetry, low-fragmentation breakout, long-vol, recoverability-aware momentum | admissible, scalable, favored in expansion corridors |

`Convexity = Recoverable Convexity + Irreversible Convexity`. This decomposition becomes
a **first-class runtime governance object** — measured by the ERQ score (Implementation
Spec §5).

---

## §4. The Exposure-Topology Lens — Short / Long / Put / Call

Recoverability is a property of **position structure**, not direction. The governing
question is not *"bullish or bearish?"* but *"what future maneuverability does the
exposure preserve?"* — equivalently, *"what kind of convexity is admissible under the
current corridor geometry?"*

| Structure | MRTP reading | Recoverability |
|---|---|---|
| **Short** | assumes *"future re-entry into ownership stays admissible"* — needs future liquidity, an open buyback corridor, bounded squeeze risk. **Forced future traversal.** | **Low** — structurally; worst under fragmentation / squeeze / liquidity rupture |
| **Long** | assumes *"the current corridor stays survivable"* — but you already own it: **no forced traversal**. Usually more recoverable than the mirror short… | **Medium** — *collapses to low* when levered / concentrated / illiquid → "corridor-fragile" |
| **Long Put** | bounded downside, optionality retained, no forced traversal | **High** |
| **Call** | *"I preserve the right to participate if the corridor survives"* — convex upside, loss bounded to premium, no forced liquidation | **High** — "profoundly MRTP-compatible" |

**Key asymmetries:**

- A **short** carries an *inherent* forced-traversal penalty — it must be bought back,
  so it depends on a future liquidity corridor existing. It is structurally lower-
  recoverability than the mirror long.
- A **long is not automatically safe.** A *levered / concentrated* long is irreversible
  convexity — under rupture it forces deleveraging and collapses re-entry. An *unlevered
  / dispersed* long is recoverable.
- `LONG` says *"I commit to the corridor."* `CALL` says *"I preserve the right to
  participate if the corridor survives."* The call is the recoverability-compatible way
  to be bullish.

**Data note.** Puts and calls are the *clean conceptual benchmark*. PolyAgora's tradable
universe is the 13 futures (no options data). Operationally, the recoverability lens is
applied to **futures position structure** — leverage, concentration, net-short exposure,
forced-traversal, liquidity — scored by ERQ. Puts/calls remain the reference ideal, not
buildable sleeves.

---

## §5. Architecture at a Glance

Six layers. Layers 1–5 are the Phase-II spec's; **Layer 5A is the new addition.**

| Layer | Responsibility |
|---|---|
| **1. Governance Core** | admissibility, regime qualification, survival matrix, 5-mode zone — *re-based on V6.2* |
| **2. Convexity Sleeves** | governed convex participation; typed sleeve catalog; admission pipeline |
| **3. MRTP Steering** | runtime trajectory choice — *anti-irreversible-convexity* |
| **4. Dynamic Kelly** | recoverability-governed leverage; asymmetric, ERQ-gated |
| **5. Recoverability Geometry** | market-state topology: corridor width, ridge pressure, fragmentation, recoverability |
| **5A. Exposure Recoverability Geometry** | **per-exposure** topology — the ERQ score |

Layer 5 measures the *market's* geometry (`R, C, F, P`). Layer 5A measures a *position
structure's* geometry (`ERQ`). They are different objects and both feed MRTP and Kelly.

---

## §6. Governing Equations (conceptual)

```
Objective    Goal = max(Recoverable Compounding)  s.t.  Future Maneuverability Preservation
MRTP score   MRTP_i = α·R_i + β·C_i − γ·F_i − δ·P_i + η·ERQ_i
Kelly        f_t = f(β_t, R_t, F_t, C_t, ERQ_t)        leverage only when maneuverability survives
ERQ          ERQ_i ∈ [0,1]      0 = recoverability-destructive · 1 = recoverability-preserving
Allocation   w_t = f(Zone, Survival Matrix, Corridor, ERQ)
```

The `+η·ERQ` term is the operative change from the original Phase-II spec: MRTP no
longer rewards convexity uniformly — it rewards *recoverable* convexity.

---

## §7. What Phase-II Is / Is Not

**Is:** a governed convexity layer that distinguishes recoverable from irreversible
exposure and permits only the former to expand; preservation of the V7.10 crisis moat.

**Is NOT:** a momentum engine, a CTA blend, a portfolio optimizer, a prediction system,
"more signals," "more leverage," "more beta." Maximizing CAGR / Sharpe / beta is
explicitly *not* the destination (§0).

### §7.1 Non-negotiable guardrails

PolygonEye's GO review (2026-05-19) fixed two invariants every implementation review
must enforce. Violating either means the architecture has stopped being PolyAgora and
has degenerated into conventional hedge-fund optimization:

1. **The hierarchy never inverts:** `Recoverability > Convexity > Return`. Convexity must
   never dominate recoverability; return must never dominate admissibility. The
   coefficient ordering `α, γ, δ > β, η` is the runtime expression of this hierarchy.
2. **ERQ stays structural, not predictive.** ERQ measures maneuverability *structure* —
   forced traversal, boundedness, liquidity, corridor preservation. It must never infer
   future returns, or it becomes circular and hindsight-driven.

**Sequencing corollary:** preserve the crisis moat *first* — prove GFC / COVID / 2022
intact before widening admissible convexity (raising `η`). The moat is not a side
effect; it is the manifestation of the invariant itself.

---

## §8. Acceptance Philosophy

The Phase-II spec's first-test targets (Sharpe > 1.2, Sortino > 1.5, Calmar > 1.0,
Max DD < 8%, Corr SPY < 0.15) are **necessary local admissibility checks** — evidence
that a corridor was realized well. They are **not the invariant**.

The **primary** acceptance question is: *did the system improve admissible convex
participation while preserving recoverable compounding and future maneuverability?* —
measured by corridor width, re-entry capacity, ERQ, and forced-deleveraging risk across
the rupture and expansion episodes. Return ratios sit *underneath* that, as the
per-regime local-star scorecard. See Implementation Spec §10 and §12.

---

## §9. Glossary

- **Recoverability** — ability to re-engage admissible trajectories from the current state.
- **Corridor** — the space of admissible trajectories available from the current state.
- **Forced traversal** — a future action the position *must* take (e.g. short buyback),
  dependent on a future liquidity corridor existing.
- **ERQ** — Exposure Recoverability Quality; `[0,1]` score of a position structure.
- **Local star** — the per-block invariant the system orients to within a regime.
- **Irreversible / recoverable convexity** — see §3.

---
*PolyAgora Phase-II General Guideline · CONFIDENTIAL · Draft v1.0*
