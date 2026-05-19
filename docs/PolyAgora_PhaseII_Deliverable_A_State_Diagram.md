# Phase-II Deliverable A — Runtime State Diagram

**Companion to:** `PolyAgora_PhaseII_CTO_Response.md` (§1 is the summary; this is the full deliverable)
**Status:** Draft v0.1 — the single source of truth for implementation sequencing
**Scope:** the 13-step execution graph, state schema, storage contracts, layer contracts

> **Working assumptions** (flagged; pending PolygonEye confirmation — CTO_Response §6):
> - **A1 — Universe.** The rebased Layer 1 operates on the **13 partner futures**
>   (BTC, CL, DX, ES, FESX, FGBL, GC, HG, NKD, SI, TN, ZS, ZW). V6.2's native AGUR-strategy
>   universe is treated as the historical lineage; `v74` already re-targeted the block
>   structure onto the futures. "13×5" = 13 futures × 5 blocks.
> - **A2 — VAIDM.** No external VAIDM feed exists. The six-axis VAIDM vector is
>   **computed** from the macro panel (VIX/SPY/HYG/TLT/GLD/CPER) + realized PnL,
>   generalizing the existing `Q_VAIDM` proxy.
> - **A3 — Zones.** The 5-mode classifier is defined in §3, Step 6.

---

## 1. Purpose

Deliverable A fixes the runtime execution sequence, the state schema, and the storage
contracts. Per the spec, it "must be agreed before any module is built." No layer may be
implemented or modified independently of this document.

## 2. Layer-1 reconciliation (recap)

The Governance Core is **re-based on `polyagora_v62_engine.py`**. V6.2 becomes Layer 1
and emits, as first-class top-level outputs, the Reference Polygon `X_t`, the Survival
Matrix `S_ij`, the 13×5 admissibility matrix `A`, the scalar β-Admissibility `β_t`, and
the 5-mode Zone. Layers 2–5 operate strictly downstream.

## 3. The 13-step execution graph

Cadence key: **W** weekly · **E** event-driven · **P** persistent-state read.

### Step 1 — Market Data Ingestion · Runtime · W
- **In:** partner XLSX (`realized_pnl`, `forward_pnl`), macro panel CSV.
- **Compute:** load, align to weekly index, normalize, compute returns + factor proxies.
- **Out:** `realized_pnl`, `forward_pnl`, macro panel `market`.
- **Code:** `load_partner_xlsx`, market CSV read. **No change.**

### Step 2 — Polygon Projection · L1 Governance · W
- **In:** macro panel.
- **Compute:** `build_exogenous_x` → 5 raw features; `compute_coordinate` →
  `X_t = (V,T,G,C,R) ∈ [-1,1]⁵`. Feature lag = 1 (anti-hindsight).
- **Out:** `X_t`.
- **Code:** `build_exogenous_x`, `compute_coordinate` (v62). **No change.**

### Step 3 — VAIDM Classification · L1 Governance · E
- **In:** macro panel + realized PnL (assumption A2).
- **Compute:** six-axis VAIDM vector; classify `RUPTURE / HIGH_STRESS / ELEVATED /
  BENIGN`; compute intensity multiplier `∈ [0,1]`.
- **Out:** `VAIDM_class`, `VAIDM_intensity`.
- **Code:** **new** — generalize `Q_VAIDM` (v73) into a six-axis classifier. *Footnote 1.*
- **Branch:** `RUPTURE` short-circuits Step 10 to Kelly FLOOR.

### Step 4 — Survival Matrix Update · L1 Governance · W
- **In:** realized PnL over the trailing window (126).
- **Compute:** `S_ij = 0.40·corr_score + 0.40·(1−joint_bad) + 0.20·co_pos`, clipped
  `[0,1]`, unit diagonal.
- **Out:** `S_ij` (13×13).
- **Code:** `rolling_survival_matrix` (v62). **No change.**

### Step 5 — Admissibility Derivation · L1 Governance · W
- **In:** `S_ij`, `X_t`, block geometry.
- **Compute:** the 13×5 admissibility matrix `A`. *Footnote 2* — `derive_admissibility_from_survival()`
  does not exist; current admissibility is `σ(coef·X_t)` (polygon-derived). Phase-II
  builds Step 5 as: `A_polygon = σ(coef·X_t)` is retained as the **prior**; the survival
  matrix supplies a **cohesion modulation** `A_ij = A_polygon · g(block-internal S)`.
- **Out:** `A` (13×5).
- **Code:** **new** — `derive_admissibility_from_survival()`; reuses `_admissibility_v75`
  coefficients + `_block_internal_survival`.

### Step 6 — Block / Zone Classification · L1 Governance · W
- **In:** `X_t`, `A`, `S_ij`.
- **Compute:** `classify_block` → active block; `star_zone` → strength + delta;
  micro-block clustering → minimum pairwise `W_t` per cluster. Map to the **5-mode**
  classifier (assumption A3):

  | Mode | Condition | Lineage |
  |---|---|---|
  | `LOCAL_STAR` | block strength ≥ z1 threshold, delta ≥ −0.08 | v62 `zone1_star` |
  | `TRANSITION` | strength ≥ z2 threshold, below z1 | v62 `zone2_transition` |
  | `LEAST_BAD` | no block strong; one block least-bad (min `W_t` still ≥ floor) | **new** — minimal deployment, not rupture |
  | `BUFFER` | zone-transition cooldown / hysteresis holding state | **new** — anti-whipsaw dwell |
  | `BOUNDARY` | VIX ≥ `boundary_vix` (35) — boundary block G active | v62 boundary |

- **Out:** `Zone_t`, `block_t`, `β_t` (β-Admissibility, scalar — from X-SM alignment +
  governor).
- **Code:** `classify_block`, `star_zone` (v62) + **new** 5-mode mapping + `BUFFER`
  hysteresis. *Footnote 3.*

### Step 7 — Recoverability Geometry Update · L5 · W/P
- **In:** `S_ij`, `A`, block geometry, `β_t` history, ADD-lite field.
- **Compute:** corridor width `C_t`, ridge pressure `P_t`, fragmentation `F_t`,
  recoverability `R_t` (re-entry probability + admissibility persistence). See
  **Deliverable B**.
- **Out:** `C_t, P_t, F_t, R_t`.
- **Code:** **new** — Layer 5.

### Step 8 — ADD Filtering · L2 / governance filter · W
- **In:** base allocation, realized PnL.
- **Compute:** per-strategy Adaptive Decay Detector; redistribute weight among survivors
  within the admitted block.
- **Out:** decay-filtered allocation.
- **Code:** `compute_add_lite_field`, `apply_asset_deformation` (v78). **No change.**

### Step 9 — MRTP Scoring · L3 · W
- **In:** `R_t, C_t, F_t, P_t` (Step 7), candidate trajectories.
- **Compute:** `MRTP_Score_i = α·R_i + β·C_i − γ·F_i − δ·P_i`; rank trajectories;
  decide expansion vs. contraction.
- **Out:** `MRTP_rank`, `convexity_decision`.
- **Code:** **new** — Layer 3. *Footnote 4* — `compute_mrtp_score` (v76) uses the old
  `α·S+β·F−γ·D` form; it is a starting point, not the target.

### Step 10 — Dynamic Kelly Sizing · L4 · W
- **In:** `β_t, R_t, F_t, C_t`, `VAIDM_class`, prior Kelly state.
- **Compute:** `f_t = f(β_t, R_t, F_t, C_t)` with contraction hysteresis + anti-whipsaw;
  state ∈ {EXPANSION, CONTRACTION, FLOOR, RE-ENGAGEMENT}.
- **Out:** `f_t` (leverage multiplier, capped — assumption: 1.25×).
- **Code:** **new** — Layer 4, inverts v77 Kelly. *Footnote 5.*
- **Branch:** `VAIDM_class = RUPTURE` ⇒ Kelly FLOOR regardless of other inputs.

### Step 11 — Sleeve Allocation · L2 · W
- **In:** `Zone_t`, `MRTP` output, admitted Sleeve Registry.
- **Compute:** sleeve type activations; zone-scaled weights within admission caps. See
  **Deliverable C**.
- **Out:** `Π_t` (sleeve weight vector).
- **Code:** `blend_sleeve`, `SleeveRegistry` (v710) — extended.

### Step 12 — Contraction Map · Runtime · W
- **In:** prior allocation, target allocation.
- **Compute:** Banach contraction blend for block transitions, `τ_buffer=0.60,
  λ=0.40`. *Footnote 6* — standardize params vs v73/v74b.
- **Out:** smoothed allocation.
- **Code:** contraction maps in v73/v74b — standardized.

### Step 13 — Execution Output · Runtime · W
- **In:** smoothed allocation × `f_t`.
- **Compute:** final allocation vector; validate vs envelope/constraints; log governance
  state, VAIDM reading, recoverability metrics.
- **Out:** `w_t`, run logs.
- **Code:** `evaluate` + CSV logging.

## 4. Data-flow diagram

```
 [1 Ingest]
      │ realized/forward PnL, macro panel
      ▼
 [2 Polygon] ──X_t──┐
      │             │
 [3 VAIDM] ─────────┤  (E: RUPTURE branch ─────────────────┐
      │             │                                      │
 [4 Survival S_ij]──┤                                       │
      │             │                                       │
 [5 Admissibility A]┤                                       │
      │             │                                       │
 [6 Block/Zone] ──β_t, Zone──┐                               │
      │                      │                               │
 [7 Recoverability] ──R,C,F,P─┼───────────┐                   │
      │                      │            │                   │
 [8 ADD Filter]              │            │                   │
      │                      ▼            ▼                   │
 [9 MRTP Score] ◄────R,C,F,P──┘   [10 Kelly f_t] ◄─β,R,F,C─────┤
      │ convexity_decision               │ (FLOOR if RUPTURE)◄─┘
      ▼                                   │
 [11 Sleeve Alloc Π_t] ◄──Zone, MRTP──────┘
      │
 [12 Contraction Map]  (τ=0.60, λ=0.40)
      │
 [13 Execution Output]  w_t = contracted_alloc × f_t
```

## 5. State schema

| Symbol | Dim | Range | Producer | Consumers | Cadence | Norm / smoothing | Persistence |
|---|---|---|---|---|---|---|---|
| `X_t` | 5 | `[-1,1]` | S2 | S5, S6 | W | `tanh` per axis | recomputed |
| `VAIDM_class` | enum | 4 modes | S3 | S10 | E | — | recomputed |
| `VAIDM_intensity` | 1 | `[0,1]` | S3 | S7, S10 | E | — | recomputed |
| `S_ij` | 13×13 | `[0,1]` | S4 | S5, S6, S7 | W | corr+co-survival blend | rolling 126 |
| `A` | 13×5 | `[0,1]` | S5 | S6, S8, S11 | W | sigmoid | recomputed |
| `β_t` | 1 | `[0,1]` | S6 | S7, S9, S10 | W | EWM (halflife ~10) | EWM state |
| `Zone_t` | enum | 5 modes | S6 | S11 | W | `BUFFER` hysteresis | transition buffer |
| `C_t` corridor width | 1 | `[0,1]` | S7 | S9, S10 | W | see Deliverable B | history window |
| `P_t` ridge pressure | 1 | `≥0` | S7 | S9 | W | see Deliverable B | history window |
| `F_t` fragmentation | 1 | `[0,1]` | S7 | S9, S10 | W | see Deliverable B | history window |
| `R_t` recoverability | vector (v1) | `[0,1]` | S7 | S9, S10 | W | see Deliverable B | history window |
| `MRTP_rank` | n_traj | ordinal | S9 | S11 | W | — | recomputed |
| `f_t` Kelly mult | 1 | `[0, 1.25]` | S10 | S13 | W | hysteresis (asym.) | Kelly state |
| `Π_t` sleeve weights | n_sleeves | `[0,1]` | S11 | S12 | W | zone-scaled | registry |
| `w_t` final alloc | 14 | envelope | S13 | — | W | contraction map | logged |

## 6. Storage contracts

**Persisted across time steps** (carry state forward):
- `S_ij` rolling window — 126-bar realized-PnL buffer.
- Recoverability history (Step 7) — memory windows for re-entry probability and
  admissibility persistence.
- Kelly hysteresis state (Step 10) — current Kelly mode + dwell counters.
- Sleeve Registry — admitted set + per-sleeve metadata.
- Zone-transition hysteresis buffer (Step 6) — drives the `BUFFER` mode.
- `β_t` EWM smoothing state.

**Recomputed fresh each bar** (no carried state):
- `X_t`, `A`, MRTP scores, the final allocation vector.

## 7. Layer interaction contracts

- **L1 → all:** L1 promises `β_t ∈ [0,1]`, a valid 5-mode `Zone_t`, and `A` every bar.
  Downstream layers may **read** but never **write** L1 state.
- **L1 → L5:** L5 consumes `S_ij`, `A`, `β_t` history; L5 never feeds back into L1.
- **L5 → L3, L4:** `R/C/F/P` are inputs to MRTP and Kelly; they are the *only* path by
  which geometry reaches sizing.
- **L3 → L2:** MRTP may **modulate** sleeve activation within an admitted block; it may
  **not** override an L1 block selection (resolves spec Open Problem C, Q3).
- **L4 → Runtime:** Kelly produces a scalar `f_t`; it sizes, it does not select assets.
- **Rupture override:** `VAIDM_class = RUPTURE` forces Kelly FLOOR and caps sleeve
  activation to Type-A/D crisis sleeves only — a hard branch, not a soft modulation.

## 8. Footnotes (spec/code reconciliation — resolved within this deliverable)

1. **VAIDM** — built per assumption A2; six-axis classifier generalizing `Q_VAIDM`.
2. **`derive_admissibility_from_survival()`** — does not exist; built in Step 5 as
   polygon prior × survival-cohesion modulation.
3. **5-mode zones** — `LEAST_BAD` and `BUFFER` newly defined in Step 6; the three
   legacy zone systems (v75 gross-gate, v79 rotation, v710 sleeve-permission) collapse
   into this single Layer-1 classifier.
4. **MRTP formula** — `v76.compute_mrtp_score` uses `α·S+β·F−γ·D`; superseded by
   `α·R+β·C−γ·F−δ·P`.
5. **Kelly** — v77 Kelly is haircut-only (`cap=1.0`); Layer 4 rebuilds it to expand.
6. **Banach params** — Step 12 standardizes on `τ_buffer=0.60, λ=0.40`.
7. **Universe** — per assumption A1, the 13 partner futures.

---
*Phase-II Deliverable A · CONFIDENTIAL · Draft v0.1*
