# Phase-II Deliverable B — Recoverability Geometry Formalization

**Companion to:** `PolyAgora_PhaseII_CTO_Response.md` (§2 is the summary; this is the full deliverable)
**Status:** Draft v0.1 — research proposal, 6–8 week horizon
**Scope:** formal estimators for the 5 geometry variables, tractable at weekly cadence
over the 13-asset universe, 2008–2026

---

## 1. Purpose

Recoverability Geometry (Layer 5) is the deepest layer and the primary mathematical
moat. The spec defines it conceptually; this deliverable makes it a **computable,
runtime-updateable estimator set**. The governing question is not "how risky is the
current position" but "**how many admissible futures does the current position preserve
access to**."

The layer produces four runtime variables — `C_t` (corridor width), `P_t` (ridge
pressure), `F_t` (fragmentation field), `R_t` (recoverability) — from five geometry
estimators. `R_t` is the composite of the two estimators not already exposed as C/P/F
(re-entry probability + admissibility persistence).

All estimators read realized data ≤ t−1 only (anti-hindsight).

## 2. The five geometry estimators

Notation: `S_ij` = Survival Matrix (Step 4); `p_b` = block membership scores from
`block_scores_from_x` (b ∈ {A,B,C,D}); `A` = 13×5 admissibility; `β_t` = β-Admissibility;
`r_t` = realized 13-asset return vector.

### 2.1 Corridor width `C_t`

*"Volume of admissible trajectory space available from the current state."* Wide when
multiple blocks are jointly admissible **and** admissibility is high.

```
N_eff(t)  = exp( −Σ_b p_b ln p_b )            effective # of admissible blocks ∈ [1,4]
depth(t)  = Σ_b max(p_b − θ_C, 0)             admissibility mass above floor θ_C
C_t       = tanh( κ_C · (N_eff(t)/4) · depth(t) · β_t )
```

`C_t ∈ [0,1]`. Falls when the regime collapses onto one block (low `N_eff`) or when
admissibility thins (`β_t` low). `θ_C ≈ 0.15`, `κ_C` calibrated so the 2009–2011 and
post-2020 expansions sit in the top tercile.

### 2.2 Ridge pressure `P_t`

*"Instability accumulation and contradiction density at the boundary of the corridor."*
Built from the **minimum pairwise survival** `W_min` — the spec's named cohesion metric.

```
W_min(t)  = min over admitted-block strategy pairs (i,j) of  S_ij(t)
level(t)  = 1 − W_min(t)                                     low cohesion = pressure
slope(t)  = max( 0, (W_min(t−k) − W_min(t)) / k )            cohesion eroding fast
P_t       = w_lvl · level(t) + w_slp · κ_P · slope(t)
```

`P_t ≥ 0`. Both terms non-negative; the slope term is the **early-warning** component
(pressure *building* before the ridge becomes an active barrier). `k ≈ 4` weeks,
`w_lvl = 0.5, w_slp = 0.5`.

### 2.3 Fragmentation field `F_t`

*"Block incoherence, regime divergence, structural instability across the universe."*

```
incoh(t)  = 1 − mean_offdiag( S_ij(t) )                      average pairwise incoherence
disp(t)   = z_clip( cross-sectional stdev of trailing r_t )  regime divergence
F_t       = 0.5 · incoh(t) + 0.5 · disp(t)
```

`F_t ∈ [0,1]`. Reuses the ADD-lite breadth/synchronization intuition but computes
directly from `S_ij` so it is consistent with the rest of Layer 5. `z_clip` = z-score
clipped to `[0,1]` via a logistic.

### 2.4 Re-entry probability

*"Probability of re-engaging an admissible trajectory after contraction."* Empirical
conditional frequency over a memory window `M`.

```
A contraction episode opens when Zone enters {LEAST_BAD, BOUNDARY} or β_t < θ_β.
A re-entry occurs if Zone returns to {LOCAL_STAR, TRANSITION} within horizon H weeks.

ReEntry_t = (# re-entries within H) / (# contraction episodes)   over trailing M
```

`M ≈ 252 weeks` (rolling), `H ≈ 12 weeks`, `θ_β ≈ 0.35`. v1 uses the empirical
frequency; a model-based form `σ(a + b·β_t + c·C_t − d·P_t)` is a v2 candidate once the
estimators are validated.

### 2.5 Admissibility persistence

*"Duration and stability of the current block's admissibility."*

```
streak(t) = consecutive weeks with β_t > θ_β
stab(t)   = 1 − rolling_stdev( β_t, w_p )
Persist_t = 0.5 · tanh( streak(t) / τ_p ) + 0.5 · clip(stab(t), 0, 1)
```

`τ_p ≈ 26 weeks`, `w_p ≈ 13 weeks`. Distinguishes a stable equilibrium from a transient
admissibility spike.

### 2.6 Composite recoverability `R_t`

```
R_t = 0.5 · ReEntry_t + 0.5 · Persist_t           (v1 scalar)
R_t = [ ReEntry_t , Persist_t ]                   (v1 vector — preferred, see §4)
```

## 3. Normalization, smoothing, memory windows

| Estimator | Output range | Memory window | Smoothing |
|---|---|---|---|
| `C_t` | `[0,1]` | none (instantaneous) | EWM halflife 4w |
| `P_t` | `≥0` (clip 0–1 for MRTP) | 4w slope window | EWM halflife 3w |
| `F_t` | `[0,1]` | trailing 13w for `disp` | EWM halflife 4w |
| ReEntry | `[0,1]` | 252w rolling | none (already an average) |
| Persist | `[0,1]` | 13–26w | none |

Smoothing halflives are deliberately short (3–4w) — Layer 5 is faster than the
Governance Core but slower than execution, preserving the spec's layer-separation
principle.

## 4. Scalar vs. vector

`R_t` is kept a **vector** `[ReEntry_t, Persist_t]` in v1, per the spec's Open Problem A,
question 6. Re-entry probability and admissibility persistence answer different
questions (can I get back vs. is the current state stable) and may diverge — e.g. a long
stable streak with low historical re-entry frequency. Collapsing to a scalar is deferred
until the §5 falsification test shows the two move together; if they do not, the vector
form is retained and MRTP/Kelly consume both components.

## 5. Falsification protocol — the key methodological commitment

Every estimator must pass a falsification test **before it is wired into MRTP (Step 9)
or Kelly (Step 10)**. An estimator that does not respond to the known episodes is
rejected, not tuned.

**Required behavior over 2008–2026:**

| Episode | Window | `C_t` | `P_t` | `F_t` | `R_t` |
|---|---|---|---|---|---|
| GFC rupture | 2008-04 → 2009-03 | ↓ low | ↑ high | ↑ high | ↓ low |
| GFC recovery | 2009-04 → 2011-12 | ↑ rising | ↓ falling | ↓ falling | ↑ rising |
| QE bull | 2012 → 2019 | high, stable | low | low | high |
| COVID rupture | 2020-02 → 2020-12 | ↓ sharp | ↑ sharp | ↑ sharp | ↓ sharp |
| Post-2020 reflation | 2021 | ↑ rising | ↓ | ↓ | ↑ |
| 2022 rate shock | 2022 | ↓ moderate | ↑ moderate | ↑ moderate | ↓ moderate |

**Pass criterion:** the estimator's episode-mean must sit in the correct tercile (top /
mid / bottom) for ≥5 of the 6 episodes, and the COVID + GFC ruptures must both register
as bottom-tercile `C_t`/`R_t` and top-tercile `P_t`/`F_t`. An estimator failing this is
returned to formalization, not calibrated to pass.

**`VAIDM` coupling (spec Open Problem A, Q5):** under `VAIDM_class = RUPTURE`,
recoverability must degrade — operationalized as a hard check that `R_t` mean over
RUPTURE-classified bars < `R_t` mean over BENIGN bars by a margin (target ≥ 0.3).

## 6. Computational tractability

At weekly cadence over 13 assets, 2008–2026 ≈ 940 weekly bars:
- `S_ij` is 13×13 — all estimators are `O(13²)` per bar, trivially tractable.
- `N_eff`, `W_min`, `incoh` are single passes over `S_ij` / `p_b`.
- Re-entry probability is a rolling count — `O(M)` per bar, `M ≈ 252`.
- No optimization, no matrix inversion, no iterative solver. Full-history backtest runs
  in seconds. Tractability is **not** a constraint at this universe size.

## 7. Integration points

| Estimator | Feeds | Role |
|---|---|---|
| `C_t` corridor width | MRTP (`+β·C`), Kelly | expansion confidence |
| `P_t` ridge pressure | MRTP (`−δ·P`) | contraction trigger |
| `F_t` fragmentation | MRTP (`−γ·F`), Kelly | contraction trigger |
| `R_t` recoverability | MRTP (`+α·R`), Kelly | primary expansion qualifier |

## 8. Deliverable artifact

The completed Deliverable B ships: (1) the five estimator implementations; (2) the
`R_t` vector backtested over 2008–2026 with the §5 episode annotations; (3) the
falsification-test result per estimator (pass/fail + episode terciles); (4) calibrated
constants (`κ_C, θ_C, k, τ_p, M, H, θ_β`). Treated as a 6–8 week research track running
parallel to Deliverables A and C.

## 9. Open items

- Calibration of `κ_C` and the MRTP/Kelly coefficient weights is empirical — depends on
  Deliverable A's universe decision (assumption A1).
- The model-based re-entry form (§2.4 v2) is deferred pending v1 validation.
- Whether `F_t` and `P_t` are sufficiently independent to both feed MRTP, or whether one
  is redundant, is itself a §5 output.

---
*Phase-II Deliverable B · CONFIDENTIAL · Draft v0.1*
