# PolyAgora Phase-II — Implementation Spec

**Document 2 of 2** · companion: `PolyAgora_PhaseII_General_Guideline.md`
**Status:** Consolidated buildable spec · Draft v1.1 — incorporates PolygonEye answers
(2026-05-19); **cleared for implementation**. Supersedes Deliverables A/B/C; adopts
PolygonEye's A–E renumbering; legacy indexes and matrices retained — §11.
**Audience:** Quant Engineering, Systems Architecture

> The *how*. Read the General Guideline (§0 destination capstone, doctrine) first.
> Every formula here serves `max(Recoverable Compounding) s.t. Maneuverability
> Preservation`.

---

## §0. Scope & Working Assumptions

Phase-II adds a governed convexity layer on the V7.10 baseline. All five assumptions
below were **confirmed by PolygonEye on 2026-05-19** (full answers — `Open_Questions.md`):

- **A1 — Universe.** Layer 1 operates on the **13 partner futures** (BTC, CL, DX, ES,
  FESX, FGBL, GC, HG, NKD, SI, TN, ZS, ZW). "13×5" = 13 futures × 5 blocks. *Confirmed.*
- **A2 — VAIDM.** Computed **in-house** — endogenous, not an external feed —
  `VAIDM = f(macro panel, cross-asset stress, realized PnL, fragmentation, transition
  dynamics)`; start from the macro panel, evolve toward richer topology. *Confirmed.*
- **A3 — Zones.** 5-mode classifier per §2 Step 6; definitions sharpened in §9.
  *Confirmed.*
- **A4 — Governance Core re-based on V6.2** (`polyagora_v62_engine.py`) — the spec-
  literal reading; execution Steps 2/4/5/6 describe V6.2 verbatim. *Confirmed.*
- **A5 — Leverage cap 1.25×** (§7) — not to be exceeded early; `θ_ERQ` is a
  *philosophical admissibility boundary*, calibrated by falsification (§5, §10),
  not a performance threshold. *Confirmed.*

### §0.1 Non-negotiable guardrails

Two invariants govern every implementation review. Violating either means the system is
no longer PolyAgora — it has degenerated into conventional hedge-fund optimization:

1. **The hierarchy never inverts:** `Recoverability > Convexity > Return`. Convexity must
   never dominate recoverability; return must never dominate admissibility.
2. **ERQ stays structural, not predictive.** ERQ scores maneuverability *structure*; it
   must never infer future returns — otherwise it becomes circular / hindsight-driven.

---

## §1. Layer Architecture

| Layer | Module (target) | Emits |
|---|---|---|
| 1. Governance Core | `governance/` (re-based V6.2) | `X_t`, `S_ij`, `A` (13×5), `β_t`, `Zone_t` |
| 2. Convexity Sleeves | `sleeves/` | `Π_t` sleeve weights, sleeve type activations |
| 3. MRTP Steering | `mrtp/` | `MRTP_i`, convexity decision |
| 4. Dynamic Kelly | `kelly/` | `f_t` leverage multiplier |
| 5. Recoverability Geometry | `recoverability/` | `R_t, C_t, F_t, P_t` (market-state) |
| **5A. Exposure Recoverability** | `recoverability/erq.py` | `ERQ_i` per exposure/sleeve |

Layer 5 = market-state geometry. Layer 5A = per-exposure geometry. Distinct objects;
both feed Layers 3 and 4.

---

## §2. Runtime Execution Graph (13 steps + 7A)

Legacy 13-step index retained (assumption: kept per CTO directive); **Step 7A inserted**
for ERQ. Cadence: **W** weekly · **E** event-driven · **P** persistent read.

| # | Step | Layer | Cadence | Phase-II change |
|---|---|---|---|---|
| 1 | Market Data Ingestion | Runtime | W | — |
| 2 | Polygon Projection → `(V,T,G,C,R)` | L1 | W | — |
| 3 | VAIDM Classification (6-axis) | L1 | E | new classifier (A2) |
| 4 | Survival Matrix Update `S_ij` | L1 | W | — |
| 5 | Admissibility Derivation (13×5) | L1 | W | `derive_admissibility_from_survival()` |
| 6 | Block / Zone Classification (5-mode) | L1 | W | 5-mode classifier |
| 7 | Recoverability Geometry Update | L5 | W/P | `R,C,F,P` (§4) |
| **7A** | **Exposure Recoverability Quality** | **L5A** | **W** | **`ERQ_i` per candidate (§5)** |
| 8 | ADD Filtering | L2 | W | — |
| 9 | MRTP Scoring | L3 | W | `+η·ERQ` term (§6) |
| 10 | Dynamic Kelly Sizing | L4 | W | ERQ-gated, asymmetric (§7) |
| 11 | Sleeve Allocation | L2 | W | Type-I/II governance (§8–§9) |
| 12 | Contraction Map (Banach `τ=0.60, λ=0.40`) | Runtime | W | — |
| 13 | Execution Output | Runtime | W | — |

**Conditional branches:** `VAIDM = RUPTURE` ⇒ Kelly FLOOR + sleeves restricted to
crisis types; `Zone = BUFFER` ⇒ freeze sleeve weights and leverage; `Zone = BOUNDARY`
⇒ disable irreversible convexity.

---

## §3. State Schema & Storage Contracts

| Symbol | Dim | Range | Producer | Consumers | Cadence | Persistence |
|---|---|---|---|---|---|---|
| `X_t` | 5 | `[-1,1]` | S2 | S5,S6 | W | recomputed |
| `VAIDM_class` / `_intensity` | enum / 1 | 4 modes / `[0,1]` | S3 | S7,S10 | E | recomputed |
| `S_ij` | 13×13 | `[0,1]` | S4 | S5,S6,S7 | W | rolling 126 |
| `A` | 13×5 | `[0,1]` | S5 | S6,S8,S11 | W | recomputed |
| `β_t` | 1 | `[0,1]` | S6 | S7,S9,S10 | W | EWM state |
| `Zone_t` | enum | 5 modes | S6 | S11 | W | transition buffer |
| `R_t,C_t,F_t,P_t` | 1 each | see §4 | S7 | S9,S10 | W | history window |
| `ERQ_i` | per exposure | `[0,1]` | S7A | S9,S10,S11 | W | recomputed |
| `MRTP_i` | n_traj | real | S9 | S11 | W | recomputed |
| `f_t` | 1 | `[0,1.25]` | S10 | S13 | W | Kelly hysteresis state |
| `Π_t` | n_sleeves | `[0,1]` | S11 | S12 | W | registry |
| `w_t` | 14 | envelope | S13 | — | W | logged |

**Persisted:** `S_ij` window, recoverability history, Kelly hysteresis state, registry,
zone-transition buffer, `β_t` EWM state. **Recomputed:** `X_t`, `A`, `ERQ_i`, MRTP
scores, final allocation.

---

## §4. Layer 5 — Recoverability Geometry (market-state)

Four runtime variables from five estimators; all read realized data ≤ t−1; all
`O(13²)`/bar. Notation: `S_ij` survival matrix; `p_b` block scores; `r_t` realized returns.

| Variable | Estimator | Range |
|---|---|---|
| Corridor width `C_t` | `tanh(κ_C · (N_eff/4) · depth · β_t)`, `N_eff = exp(−Σp_b ln p_b)`, `depth = Σ_b max(p_b−θ_C,0)` | `[0,1]` |
| Ridge pressure `P_t` | `w_lvl·(1−W_min) + w_slp·κ_P·max(0,(W_min,t−k−W_min,t)/k)`, `W_min` = min admitted-pair `S_ij` | `≥0` |
| Fragmentation `F_t` | `0.5·(1−mean_offdiag S_ij) + 0.5·z_clip(cross-sectional stdev r_t)` | `[0,1]` |
| Re-entry probability | empirical: re-entries within `H` / contraction episodes, trailing `M` | `[0,1]` |
| Admissibility persistence | `0.5·tanh(streak/τ_p) + 0.5·clip(1−rolling_std β,0,1)` | `[0,1]` |
| **Recoverability** `R_t` | vector `[ReEntry_t, Persist_t]` (v1) | `[0,1]` |

Constants: `θ_C≈0.15`, `k≈4w`, `M≈252w`, `H≈12w`, `τ_p≈26w`, `θ_β≈0.35`. Smoothing:
EWM halflife 3–4w. `R_t` kept a **vector** in v1.

---

## §5. Layer 5A — Exposure Recoverability Quality (ERQ)  [Deliverable A]

ERQ scores a **position structure** (sleeve / candidate exposure) on whether it
preserves future maneuverability. `ERQ_i ∈ [0,1]`: 0 = recoverability-destructive,
1 = recoverability-preserving.

**Six components**, each a sub-score `∈ [0,1]`:

| # | Component | Question | Low ERQ ← → High ERQ |
|---|---|---|---|
| A | Forced Traversal Risk | does exit require future market cooperation? | naked short / margin unwind → no forced exit |
| B | Corridor Width Preservation | does it preserve multiple future trajectories? | narrow-path dependency → optional / bounded-risk |
| C | Liquidity Survivability | can it survive liquidity deformation? | illiquid / squeeze-prone → liquid, unwindable |
| D | Boundedness | is maximum damage structurally capped? | unbounded loss → premium-capped loss |
| E | Re-entry Flexibility | after failure, can the system re-enter efficiently? | locked-in → rotatable |
| F | Correlation-Rupture Robustness | does it survive transition-law deformation? | assumes stable cross-asset structure → robust |

**Score:** geometric mean of the six sub-scores —

```
ERQ_i = ( Π_{c∈{A..F}} erq_c )^(1/6)
```

Geometric mean so any single recoverability-destroying property (e.g. unbounded loss)
craters the score — consistent with the V7.7 Φ-field convention.

**Operational note (A1 data limit):** computed from **futures position structure** —
net-short exposure & buyback obligation (A), name concentration (B), turnover & ADV (C),
leverage & gross (D), block rotatability (E), pairwise-correlation stability (F).
Puts/calls are the conceptual benchmark, not inputs.

---

## §6. Layer 3 — MRTP Convexity Scoring  [Deliverable D]

MRTP evolves from crisis steering to **admissible convex trajectory governance**. The
operative formula (the `+η·ERQ` term is the Phase-II change):

```
MRTP_i = α·R_i + β·C_i − γ·F_i − δ·P_i + η·ERQ_i
```

| Term | Source | Sign | Role |
|---|---|---|---|
| `R_i` recoverability | L5 §4 | + | expansion qualifier |
| `C_i` corridor width | L5 §4 | + | expansion confidence |
| `F_i` fragmentation | L5 §4 | − | contraction trigger |
| `P_i` ridge pressure | L5 §4 | − | contraction trigger |
| `ERQ_i` exposure recoverability | L5A §5 | + | **admits recoverable, penalizes irreversible convexity** |

**Initial coefficient values (PolygonEye, 2026-05-19)** — these encode the Fixed-Star
hierarchy, not statistical weights; treat them as the *initial philosophical
configuration*, refined per regime later (Deliverable E):

| Coef | Value | Role |
|---|---|---|
| `α` recoverability priority | **1.00** | supreme invariant |
| `γ` fragmentation aversion | **0.90** | anti-chaos |
| `δ` ridge-pressure sensitivity | **0.75** | anticipatory contraction |
| `β` expansion confidence | **0.55** | subordinate to survivability |
| `η` recoverable-convexity preference | **0.45** | the "temptation dial" — evolve **last** |

The ordering `α, γ, δ > β, η` is mandatory early — it preserves the crisis moat. `η` is
raised only **after** the moat is proven intact (§12). Coefficients eventually become
regime-dependent (crisis: `α,γ,δ` dominate; reflation: `η` rises moderately; rupture:
`α` overwhelming). MRTP **modulates** sleeve activation within an L1-admitted block; it
may **not** override L1 block selection. Runtime cadence: weekly (event-driven re-score
on VAIDM change).

---

## §7. Layer 4 — Recoverability-Aware Kelly  [Deliverable C]

```
f_t = f(β_t, R_t, F_t, C_t, ERQ_t)        leverage permitted only when maneuverability survives
```

**Kelly EXPANSION permitted iff all hold:** `ERQ > θ_ERQ` **and** `C_t ↑` **and**
`F_t ↓` **and** `P_t ↓` **and** `β_t` stable. States: EXPANSION / CONTRACTION / FLOOR /
RE-ENGAGEMENT.

**Asymmetric dynamics (Risk-3 mitigation):** slow expansion, **instant contraction** —
no hysteresis on the down-leg. Hard cap **1.25×** (A5). A non-negotiable cash / crisis-
sleeve floor survives even maximum expansion. `VAIDM = RUPTURE` ⇒ FLOOR regardless of
other inputs. Stress-tested against a synthetic instant-rupture-from-peak-leverage path.

---

## §8. Layer 2 — Convexity Sleeve Architecture  [Deliverable B]

### 8.1 Recoverable vs. Irreversible sleeve classification

Every sleeve carries a class tag, set at registry intake from its ERQ score:

| Class | Definition | Examples | Policy |
|---|---|---|---|
| **Type-I — Irreversible** | `ERQ ≤ θ_ERQ`; forced-traversal, leverage/path-fragile | directional leverage, concentrated beta, naked shorts, liquidity-fragile momentum | capped, heavily governed, disabled in TRANSITION & BOUNDARY |
| **Type-II — Recoverable** | `ERQ > θ_ERQ`; optionality-preserving, bounded | dispersion, bounded asymmetry, low-fragmentation breakout, optionality-preserving structures | admissible, scalable, favored in expansion corridors |

### 8.2 The 6-gate admission pipeline (legacy matrix retained)

| # | Gate | Metric | Threshold |
|---|---|---|---|
| 1 | Validation | standalone Sharpe, n_obs | Sharpe ≥ 0.20, n ≥ 252 |
| 2 | Deflated Sharpe | DSR p-value | `> dsr_floor` (0.50) |
| 3 | Correlation | `|corr|` to book **and SPY** | book `< 0.70`; SPY `< 0.15` |
| 4 | Walk-forward | OOS/IS degradation | ratio ∈ `[0.3, 1.3]` |
| 5 | Contribution | blended vs book Sharpe & Sortino | blend ≥ book on both |
| 6 | Fragility Audit | per-window Sharpe + Max DD 2008/2020/2022 | no rupture window worse than −8% DD contribution |

Contribution score: `ContributionScore = ΔSharpe/|Sharpe_book| + ΔSortino/|Sortino_book|`,
gate 5 passes iff `≥ 0` on both. ERQ class (8.1) is a registry tag; the ERQ threshold
governs caps (§9), not a 7th gate.

### 8.3 Typed sleeve catalog (legacy matrix retained)

| Type | Regime target | Instruments (13-futures) | ERQ class | Status |
|---|---|---|---|---|
| A — Crisis Trend | flight-to-quality, rate shock | bond/USD time-series trend | Type-I/II — short leg ERQ-checked | ADMITTED (bond-trend) |
| B — Expansion Convexity | persistent bull, stable reflation | cross-sectional long/short expansion | Type-II | candidate |
| C — Transition Convexity | emerging transitions, early breakout | `F_t`-gated cross-asset breakout | Type-II | candidate |
| D — Rupture Asymmetry | non-linear breakdown, corr collapse | tail-option / long-vol | Type-II | data-blocked |

### 8.4 Decorrelation constraint matrix (legacy matrix retained)

| Pair | Max `|corr|` |
|---|---|
| sleeve ↔ sleeve | 0.50 |
| sleeve ↔ main manifold | 0.70 |
| sleeve ↔ SPY | **0.15** (hard wall) |
| book-aggregate ↔ SPY | 0.15 |

---

## §9. Per-Zone Runtime Governance Logic

**The 5 zone modes** (definitions sharpened by PolygonEye, 2026-05-19):

| Zone | Definition | Posture |
|---|---|---|
| `LOCAL_STAR` | strong, stable local star | recoverable convexity expansion + controlled Kelly increase |
| `TRANSITION` | regime transition in progress | prefer Type-C; disable Type-I; avoid beta escalation |
| `LEAST_BAD` | *degraded admissibility without full rupture* — no attractive corridor, one still survivable; **constrained continuity, not bearishness** | minimal deployment; preserve continuity, avoid collapse, maintain re-entry |
| `BUFFER` | *corridor-ambiguity state* — no stable local star yet, transition law still deforming; *"do not collapse possibility space too early"* | freeze leverage + aggressive convexity; preserve optionality |
| `BOUNDARY` / RUPTURE | boundary block active / confirmed rupture | disable irreversible convexity; crisis sleeves + re-entry only |

Sleeve caps by `Zone_t` and type (legacy cap matrix, extended with Type-I/II rules):

| Zone | Type A | Type B | Type C | Type D | Convexity rule |
|---|---|---|---|---|---|
| `LOCAL_STAR` | 0.10 | **0.25** | 0.10 | 0.00 | permit recoverable convexity + controlled Kelly increase; suppress irreversible leverage |
| `TRANSITION` | 0.15 | 0.12 | **0.25** | 0.05 | prefer Type-C / low-frag breakout; **disable Type-I**; avoid directional beta escalation |
| `LEAST_BAD` | 0.20 | 0.05 | 0.10 | 0.10 | minimal deployment |
| `BUFFER` | hold | hold | hold | hold | **freeze sleeve weights and leverage expansion** |
| `BOUNDARY` / RUPTURE | **0.25** | 0.00 | 0.00 | **0.25** | **disable irreversible convexity**; preserve optionality + crisis sleeves + re-entry |

Within a zone, weights adjust continuously: `Π_sleeve(t) = base_weight ·
zone_cap(Zone,type) · g_type(C_t,R_t,F_t,ERQ_t)` — `g_B`↑ with `C,R,ERQ`; `g_A`↑ with
`F,P`.

---

## §10. Backtest & Validation Plan  [Deliverable E]

Backtest windows: GFC, COVID, 2022, post-2020 reflation; momentum comparison; SPY-
correlation preservation. **Success criterion:** improve admissible convex participation
*without materially degrading the drawdown moat.*

**Falsification protocol (Layer 5 / 5A):** every estimator (`R,C,F,P,ERQ`) must, before
feeding MRTP or Kelly, land in the correct tercile for ≥5 of 6 episodes — 2008 & 2020
ruptures bottom-tercile `C,R,ERQ` / top-tercile `P,F`; QE bull & post-2020 top-tercile
`C,R,ERQ`. An estimator that does not respond is rejected, not calibrated.

| Episode | Window | `C/R/ERQ` | `P/F` |
|---|---|---|---|
| GFC rupture | 2008-04→2009-03 | low | high |
| GFC recovery | 2009-04→2011-12 | rising | falling |
| QE bull | 2012→2019 | high | low |
| COVID rupture | 2020-02→2020-12 | sharp low | sharp high |
| Post-2020 reflation | 2021 | rising | falling |
| 2022 rate shock | 2022 | moderate low | moderate high |

---

## §11. Deliverable Crosswalk (PolygonEye A–E ↔ legacy A/B/C)

Both index systems are retained. PolygonEye's A–E is the **Phase-II convexity
workstream**; the legacy A/B/C are the **foundational infrastructure** they build on.

| PolygonEye Deliverable | This spec | Legacy deliverable | Legacy index retained as |
|---|---|---|---|
| **A** — ERQ formalization | §5 | (new — sibling of legacy B) | Layer 5A |
| **B** — Recoverable/irreversible sleeve classification | §8 | legacy C — Convexity Participation Architecture | §8.2–8.4 matrices |
| **C** — Recoverability-aware Kelly | §7 | legacy A — Open Problem D / Step 10 | — |
| **D** — MRTP convexity scoring | §6 | legacy A — Step 9 + legacy B inputs | — |
| **E** — Backtest | §10 | legacy B — falsification protocol | §10 episode matrix |
| *Foundational* — Runtime State Diagram | §2, §3 | legacy A — Runtime State Diagram | 13-step graph + 7A; state schema |
| *Foundational* — Recoverability Geometry | §4 | legacy B — Recoverability Geometry | 5-estimator matrix |

All legacy matrices preserved: 13-step graph (§2), state schema (§3), 5-estimator table
(§4), 6-gate pipeline (§8.2), typed catalog (§8.3), decorrelation matrix (§8.4),
zone-cap matrix (§9), falsification episode matrix (§10).

---

## §12. Phasing & Acceptance Gates

### §12.1 Mandated build sequence (PolygonEye, 2026-05-19)

Implementation begins now — the architecture is sufficiently specified. Do **not** wait
for perfect coefficients / `θ_ERQ` / ERQ / Kelly calibration; those are iterative
research outputs that evolve afterward. **Preserve the moat first.**

| Phase | Goal |
|---|---|
| 1 | Implement the runtime architecture (13-step graph, state schema, L1 re-base) |
| 2 | **Reproduce the V7.10 crisis moat** — hard gate before anything convex |
| 3 | Integrate ERQ (Layer 5A) |
| 4 | Integrate recoverable convexity (sleeves, MRTP `η` term) |
| 5 | Calibrate coefficients (`α,β,γ,δ,η`, `θ_ERQ`) |
| 6 | Validate moat preservation across GFC / COVID / 2022 |

`η` is raised only in Phases 5–6, after the moat is confirmed to survive. Improving
reflation participation before proving GFC/COVID/2022 intact is explicitly forbidden.

### §12.2 Regression tolerance band (the re-base / moat gate)

The re-based Layer 1 and every Phase-II increment must hold the V7.10 baseline within:

| Metric | Allowed degradation |
|---|---|
| Sharpe | max −0.07 |
| Max DD | max +1.5 pp |
| Corr SPY | max +0.03 |
| Crisis windows (GFC / COVID / 2022) | **zero degradation — sacred** |
| Recovery latency | max +15% |

If the crisis windows materially degrade, the increment **fails** — even if CAGR rises.

### §12.3 Acceptance

The first-test ratios (Sharpe > 1.2, Sortino > 1.5, Calmar > 1.0, Max DD < 8%,
Corr SPY < 0.15) are local checks. The **primary** gate is recoverable compounding with
preserved maneuverability — improved convex participation **and** preserved corridor
width / re-entry capacity / ERQ / low forced-deleveraging risk across rupture and
expansion episodes — **plus** the §12.2 band satisfied.

---

## §13. Resolved Questions & Footnotes

**All 7 open questions were answered by PolygonEye on 2026-05-19** — full answers in
`PolyAgora_PhaseII_Open_Questions.md` (all marked RESOLVED). Outcomes folded into this
spec: §0 (A1/A2/A4/A5 confirmed + guardrails), §6 (coefficient values), §9 (zone
definitions), §12 (leverage cap, build sequence, regression band). `θ_ERQ` remains a
Phase-5 calibration output, with the falsification method fixed (§5, §10).

**Footnotes:** `derive_admissibility_from_survival()` and the VAIDM six-axis classifier
are net-new; v77 Kelly is haircut-only and must be rebuilt to expand; the three legacy
zone systems (v75/v79/v710) collapse into the single L1 5-mode classifier; Banach params
standardized to `τ=0.60, λ=0.40`; Type-D / Carry / Vol / Flow remain data-blocked.

---
*PolyAgora Phase-II Implementation Spec · CONFIDENTIAL · Draft v1.0*
