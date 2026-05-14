# PolyAgora V7.5 — Momentum-as-Polygon-Coordinate Specification

**Status:** Draft, awaiting CTO sign-off.
**Target:** V7.5α₁ — extend the Reference Polygon to 6D by promoting Momentum from an eigenfield in Φ to a polygon coordinate.
**Date:** 2026-05-12

<small>**Confidential & Proprietary.** This document is the confidential and proprietary specification of PolyAgora / PolygonEye. Do not reproduce, distribute, or disclose to any third party without prior written consent.</small>

---

## Source documents consolidated

| Source | Role |
| --- | --- |
| `docs/PolyAgora V8 – Momentum-as-Geometry Architecture.pdf` | Architectural impetus: momentum as polygon coordinate |
| `docs/The Better Architecture (Your Current Direction).pdf` | Layer-separation discipline: RP intrinsic, external polygons as deformers |
| `docs/V8 rough simulation .pdf` | Rough performance estimate (Sharpe 0.71–0.74, DD ~-9%) |
| `docs/PolyAgora_Strategy_Manifold_V1.pdf` | V7.4 strategy-eigenfield manifold (unchanged base) |
| `docs/PolyAgora_V7_4b_Soft_Manifold_Upgrade.pdf` | Soft top-K aggregation math (inherited) |
| `docs/Evaluation of V7.4b (1).pdf` | V7.4c four-point gate (re-applied to V7.5) |
| `Algo_V74.md` | Current production reference for V7.4c |

When the V8 PDF and `The Better Architecture` PDF disagree, **`The Better Architecture` supersedes** — its layer-separation discipline binds.

---

## 1. Architectural delta from V7.4c

V7.4c established three layers:

1. **Intrinsic geometry**: Reference Polygon `RP = (V, T, G, C, R)`.
2. **Soft Local-Star manifold**: top-K block aggregation over strategy eigenfields Φ.
3. **Runtime steering**: Driver Seat dials + zone gate.

V7.5α₁ makes a single targeted change at **Layer 1**: extend RP to 6D by promoting Momentum Persistence (M) as the 6th coordinate. Everything else (categories, blocks, soft aggregation, zone classifier, anti-hindsight invariants) is inherited from V7.4c without modification.

The deliberate scope discipline (per `The Better Architecture` §"Very Important Insight"): **do not** add Liquidity (L), Mission/Macro (Φ), or Recoverability (R_MRTP) axes at this stage. Those are reserved as **external polygons** (V7.5β, deferred). RP must remain *stable, universal, reusable, mathematically coherent*. Only signals with proven structural status migrate into RP. M earns inclusion because:

- It is **exogenous to category labels** — defined from the realized strategy panel, not from any single eigenfield's discretion.
- It is **bounded** — same tanh-squashing as the other five axes.
- It is **stable across regimes** — z-scored EMA spread is dimensionless and self-normalizing.
- It is **falsifiable** — Test 1 of the V7.4c validation pack establishes that V7.5α₁ reduces to V7.4c at `momentum_sensitivity = 0`. If that point doesn't exist, the migration is wrong.

## 2. Data and timing

Unchanged from V7.4c. Two streams per partner workbook:

- `r_real_i(t)` — realized panel, used for all signal computation
- `r_fwd_i(t)` — forward panel, used for evaluation only

**Strict timing**: all quantities at time `t` are computed from information available up to time `t−1` only. The new M coordinate is no exception — its anti-hindsight slice is `realized.iloc[:-1]` (§7).

Universe Φ = 13 partner futures + `MOM12_1` (kept in V7.5α₁ pending the A/B comparison in §9).

## 3. Reference Polygon — extended to 6D

The Reference Polygon becomes:

$$RP = (M, V, T, G, C, R) \in [-1, 1]^6$$

with the existing five axes preserved verbatim from V7.4c (see `Algo_V74.md` §A.4.1) and a new sixth axis:

| Symbol | Meaning | Source | Formula |
|---|---|---|---|
| **M** | **Momentum Persistence** | Cross-sectional median over realized strategy panel | `tanh(median_i z((EMA₆₃(r_i) - EMA₂₅₂(r_i)) / σ_i))` |
| V | Volatility / risk pressure | `VIX` | `tanh((VIX − 18) / 10)` |
| T | Trend / directional persistence | `SPY.pct_change(63)` | `tanh(5 · spy_63d)` |
| G | Gold-Copper / macro stress | `GLD / CPER` | `tanh(2 · (G/C − 4.5) / 4.5)` |
| C | Carry / credit | `HYG.pct_change(63)` | `tanh(10 · hyg_63d)` |
| R | Rates / duration | `TLT.pct_change(63)` | `−tanh(5 · tlt_63d)` |

M is placed *first* in the coordinate tuple to make it visually prominent in diagnostics, but the placement is arbitrary — admissibility is a dot product, order doesn't change semantics.

## 4. M_t — formal definition

For each strategy `i` in Φ (excluding `MOM12_1` itself, to avoid self-reference) and each date `t`:

1. **Short-term EMA** of realized returns:
   $$\text{EMA}^{\text{short}}_i(t) = \text{EWM}(r_i, \text{halflife}=\text{ln}(2) \cdot 63 / \text{ln}(2))$$
   (i.e. 63-day EWM with `adjust=False`).
2. **Long-term EMA**:
   $$\text{EMA}^{\text{long}}_i(t) = \text{EWM}(r_i, \text{halflife}=\text{ln}(2) \cdot 252 / \text{ln}(2))$$
3. **Vol normalization**:
   $$\sigma_i(t) = \text{std}(r_i, \text{rolling}=63)$$
4. **Per-strategy persistence quality**:
   $$m_i(t) = \frac{\text{EMA}^{\text{short}}_i(t) - \text{EMA}^{\text{long}}_i(t)}{\sigma_i(t) + \epsilon}$$
   with `ε = 1e-9` for numerical safety.
5. **Cross-sectional z-score** across the 13 strategies, then median, then tanh:
   $$M_t = \tanh\Big( \text{median}_i\big( \text{z}_\text{cs}(m_i(t)) \big) \Big)$$

`z_cs` is the cross-sectional z-score (subtract the per-day mean across i, divide by the per-day std across i). This makes `m` dimensionless and renders M independent of universe-wide return scale.

**Why median, not mean**: median is robust to one or two strategies in extreme breakout/breakdown — these would otherwise distort the polygon coordinate. The cross-sectional median naturally falls when persistence breaks down across the cross-section, even if 1–2 strategies are still trending.

**Why tanh**: bounds M to `[-1, 1]` and matches the other five axes' geometry. The argument is bounded in distribution but not in absolute magnitude; tanh provides saturation.

## 5. Admissibility coefficients (6 axes × 5 categories)

The full coefficient table for V7.5α₁ (Option B retune, 2026-05-12):

| Category | M | V | T | G | C | R |
|---|---:|---:|---:|---:|---:|---:|
| `persistence` | **+1.00** | -1.5 | +2.5 | -0.5 | +1.0 | -0.5 |
| `carry` | **+0.25** | -1.0 | +0.5 | -0.5 | +1.5 | -2.0 |
| `defensive` | **-0.50** | +1.0 | -0.5 | +0.5 | -0.5 | +1.0 |
| `convexity` | **-0.50** | +2.0 | -0.5 | +1.5 | -0.5 | +0.5 |
| `stress` | **-0.50** | +1.0 | -0.5 | +2.0 | -0.5 | +0.5 |

The V/T/G/C/R columns are unchanged from V7.4c (`polyagora_v74_engine.py:95–102`).

**Sign rationale**:
- **Persistence (+1.00 on M)**: trend-following strategies are admissible when cross-sectional persistence is high; strongest positive but reduced from +1.5 to avoid crushing top-K diversification in trend regimes.
- **Carry (+0.25 on M)**: mild positive — empirically, carry strategies (TN, FGBL) benefit modestly in coherent persistence regimes (yield-momentum coexistence in "everything rally" periods).
- **Defensive (-0.50 on M)**: defensive admissibility falls when persistence is strong, but softer than the first-pass -1.0 — defensive demand persists even in trends (tail risk doesn't vanish).
- **Convexity (-0.50 on M)**: convexity strategies (SI, BTC) want dislocation / regime fracture, mildly penalized in coherent trends.
- **Stress (-0.50 on M)**: stress / commodity-rupture strategies want chop and dislocation, mildly penalized when momentum is coherent.

**First-pass history**: the original §5 table (persistence=+1.5, carry=0, defensive=-1.0) was rejected on 2026-05-12 after the first end-to-end run showed Sharpe falling below the V7.4c plateau, traced to top-K aggregation collapsing onto persistence in trend regimes. The current table tightens the M-column range from `[-1.0, +1.5]` to `[-0.5, +1.0]` and adds a mild carry positive — preserving the persistence lead while restoring multi-block diversification.

These coefficients are **operational defaults**. The Test 4 parameter frontier sweep refines them further; if no plateau exists, the table is rejected and V7.5 falls back to V7.5α₂ (per-asset multiplicative deformer, RP stays 5D).

## 6. Driver Seat extension

New dial:

| Dial | Default | Range | Effect |
|---|---:|---|---|
| `momentum_sensitivity` (α_M) | 1.0 | `[0.0, 2.0]` | Multiplies the M column of `ADMISSIBILITY_COEFS` across all categories. `0.0` ⇒ M has no admissibility effect (V7.5 reduces to V7.4c). `2.0` ⇒ M sensitivity doubled. |

The existing five dials (`convexity_preference`, `carry_preference`, `defensive_preference`, `boundary_sensitivity`, `recovery_aggression`) are preserved without change.

**Continuity anchor**: with `momentum_sensitivity = 0`, the M column is zeroed out, the admissibility function ignores M, and V7.5α₁ becomes computationally identical to V7.4c (modulo a one-row-shorter realized panel needed to compute M, which is itself zero-effect). Test 1 verifies this mechanically.

## 7. Anti-hindsight invariants

V7.5α₁ adds two invariants on top of V7.4c's eight (`Algo_V74.md` §B.11):

9. **M_t reads `realized.iloc[:-1]`**: the per-strategy EMA spreads and rolling vols are computed on rows ≤ `t-1` only. The `M_t` value used at row `t` is measurable strictly before `t`.
10. **MOM12_1 is excluded from the cross-section that builds M**: prevents circularity (`MOM12_1`'s synthetic PnL is itself a momentum portfolio).

Test 5 (mechanical + statistical) is extended to verify both invariants.

## 8. Block selection, soft manifold, zones — unchanged

- Block sources, top-K aggregation, softmax weighting, M_i(t) soft membership: inherited verbatim from V7.4b (`polyagora_v74b_engine.py:174–225`).
- Zone classifier: inherited verbatim from V7.4c's hardened `_classify_zone` (`polyagora_v74_engine.py:284–330`). The V/G saturation cut still uses *only* `|V|` and `|G|` — M does not enter zone logic at this stage.
- MOM12_1 decomposition: inherited from V7.4 (`_synth_mom_pnl`, `_momentum_portfolio`).

If V7.5α₁ exposes a need to incorporate M into zone classification (e.g. M near ±1 should attenuate gross exposure), that becomes a V7.5γ task.

## 9. MOM12_1 fate — parallel A/B

Per CTO instruction (2026-05-12): decide MOM12_1's fate empirically.

Ship two V7.5α₁ variants in the signal registry:

| Signal name | Φ universe | M lives in | Role |
|---|---|---|---|
| `v75` | 14 (13 partner + `MOM12_1`) | RP | "Belt and braces" — momentum represented at both layers |
| `v75_no_mom_eigen` | 13 (partner only) | RP | Clean architecture — momentum lives only in RP |

Decision criterion (post-validation): the variant that achieves **higher Sharpe under Test 4's identified plateau** and **smaller Sharpe drop in Test 6 OOS holdout** becomes the V7.5 default. The losing variant stays in the registry as a comparison baseline.

The double-counting concern: if `v75` consistently outperforms `v75_no_mom_eigen`, it suggests M and `MOM12_1` capture genuinely orthogonal signal (cross-sectional persistence at the polygon level vs single-strategy participation at the eigenfield level). If `v75_no_mom_eigen` wins, the redundancy is real and `MOM12_1` should be dropped.

## 10. Code layout

New files:

- `polyagora_v75_engine.py` — engine factory `make_v75_signal(...)`. Imports `polyagora_v74b_engine` and overrides:
  - `_coordinate_from_x_v75(x_row, m_value) → np.ndarray[6]`
  - `ADMISSIBILITY_COEFS_V75` (6-column dict)
  - `_admissibility_v75(coord_6d, drivers) → dict[strategy, float]` — multiplies M column by `drivers.momentum_sensitivity`
  - `build_polygon_with_m(market, realized, cfg) → (X_5d, M_series)` — joins V7.4c's `build_exogenous_x` with the new `M_t` series.

- `validate_v75.py` — extends `validate_v74c.py` to register `v75` and `v75_no_mom_eigen` and re-run the six tests, plus the new MOM12_1 A/B comparison.

Modified files:

- `run_polyagora_v74_partner.py` — register `v75` and `v75_no_mom_eigen` in `build_signal_registry`. Add them to `SIGNAL_COLORS`, `SIGNAL_LABELS`, and `default_visible_signals` so they appear on the dashboard.

Unchanged files:

- `polyagora_v74_engine.py`, `polyagora_v74b_engine.py`, `polyagora_v73_engine.py`, `polyagora_v63_partner_engine.py`, `polyagora_v62_engine.py`, `polyagora_dashboard.py`. **V7.4c remains the immutable production baseline.**

## 11. Validation plan — the six tests

Re-run `validate_v75.py` against the V7.4c six-test pack.

| Test | V7.4c pass criterion | V7.5α₁ pass criterion |
|---|---|---|
| 1. Continuity | `v74b_template` ≈ V7.3 within Sharpe ±0.02 | `v75` with `momentum_sensitivity=0` ≈ V7.4c within Sharpe ±0.02 |
| 2. Zone audit | Z=3/Z=4 fires in ≥ 4/5 stress quarters | Unchanged threshold |
| 3. Jaccard stability | Category blocks median Jaccard ≥ 0.70 | Unchanged (blocks not affected by M) |
| 4. Parameter frontier | Plateau ≥ 30% of cells in ≥ 1 slice | Plateau ≥ 30% in (`block_source`, `K`, `τ`, `λ`, **`α_M`**) sweep |
| 5. No-look-ahead | 7/7 mechanical + 3/3 statistical | 9/9 mechanical (incl. new M invariants) + 4/4 statistical (incl. M_t perturbation) |
| 6. OOS holdout | Δ Sharpe > -0.20 vs IS | Unchanged threshold, applied to `v75` and `v75_no_mom_eigen` |

Plus the **A/B**: `v75` vs `v75_no_mom_eigen` head-to-head on Sharpe / DD / Test 4 plateau width / Test 6 OOS Sharpe.

A V7.5α₁ that fails any test reverts to V7.5α₂ (per-asset multiplicative deformer, RP stays 5D) — see §13.

## 12. Out-of-scope for V7.5α₁

Reserved for later increments:

| Item | Reason | Future increment |
|---|---|---|
| Per-asset M_i as admissibility deformer | Smaller-step alternative if α₁ fails Test 4 | V7.5α₂ (fallback) |
| External polygons as deformers (VAIDM/ADD/Buffett deforming A_i or Γ_m, not just β) | Layer 2 work; orthogonal to RP change | V7.5β |
| Continuous zone gate `g(coh) = sigmoid(...)` instead of 4-bucket | Smoother zones, but V7.4c plateau-tested | V7.5γ |
| Liquidity axis (L), Mission/Macro axis (Φ) | Not yet defined operationally on this universe | Deferred indefinitely |
| MRTP recoverability as polygon axis | Conceptually appealing, no operational definition yet | Deferred until MRTP framework is concrete |

## 13. Fallback path — V7.5α₂

If Test 4 finds no plateau for V7.5α₁, fall back without rewriting:

- Keep RP 5D (V7.4c geometry).
- Apply M as a *per-asset multiplicative deformer*: `A_i'(t) = A_i(t) · (1 + α_M · M_i(t))` where `M_i(t)` is the same per-strategy persistence quality from §4 step 4 (no cross-sectional aggregation).
- Same Driver Seat dial `momentum_sensitivity` controls intensity.
- Continuity anchor: `α_M = 0` reduces to V7.4c.

V7.5α₂ is structurally smaller — it leaves admissibility coefficients untouched and just modulates per-asset values. It's the safety net.

## 14. Open questions before sign-off

1. **EMA halflife pair** — is the spec's 63/252 EMA combination right, or should we test alternatives (e.g. 21/126 short-medium for faster regime response)?
2. **Cross-sectional reducer** — median vs mean vs trimmed mean for the cross-section. Median is the conservative default; mean would be more reactive.
3. **`MOM12_1` exclusion from M's cross-section** — currently §4 excludes it (it's a derived stream, not an independent strategy). Confirm.
4. **M_t at engine warmup** — for the first ~252 days, `EMA_long` is undefined. Spec assumes M_t falls back to 0 (neutral) during warmup. Confirm vs alternative (skip those dates entirely, push the engine start forward).
5. **Driver Seat preset for V7.5** — do we ship a `v75_plateau` analogue to `v74b_plateau` (chosen for robustness) once Test 4 identifies it?

## 15. Deliverables for V7.5α₁ sign-off

A short V7.5 Validation Note (~5 pages, matching `V7.4c_Validation_Note.md`) containing:

- Six-test results vs V7.4c.
- `v75` vs `v75_no_mom_eigen` head-to-head.
- The identified parameter plateau (including `α_M`).
- The recommended V7.5 production configuration.
- The MOM12_1 decision (kept or dropped).
- Algo_V74.md → Algo_V75.md doc update (or §A.11 addendum to the existing doc).
