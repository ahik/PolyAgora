# Phase-II Deliverable C — Convexity Participation Architecture

**Companion to:** `PolyAgora_PhaseII_CTO_Response.md` (§3 is the summary; this is the full deliverable)
**Status:** Draft v0.1
**Scope:** the formal 6-gate sleeve admission pipeline, the typed sleeve catalog, two new
sleeve candidates, the decorrelation constraint matrix

---

## 1. Purpose

Convexity Sleeves (Layer 2) replace passive defensiveness with **governed convex
participation**. The Phase-II gap is bull/reflation under-participation; the sleeve
framework is the vehicle for closing it without destabilizing survivability. This
deliverable formalizes how a candidate sleeve is admitted, how large it may grow as a
function of governance state, and how sleeves are kept mutually decorrelated.

> **Data constraint.** The repo has only the 13-asset futures realized/forward PnL + the
> macro panel (VIX/SPY/HYG/TLT/GLD/CPER). Sleeves needing options, VIX term structure,
> or positioning data (Carry, Vol, Flow, Type-D tail) are **data-blocked** — flagged in
> §6, not fabricated.

## 2. The 6-gate admission pipeline

A candidate never enters the book on Sharpe alone. It clears an **ordered** gate
pipeline; failing any single gate ⇒ `REJECTED` with a documented reason. The current
registry (`polyagora_sleeve_registry.py`) implements gates 1–5; Phase-II adds gate 6.

### 2.1 Input schema

```
SleeveCandidate:
  spec            : SleeveSpec   # strategy_id, sleeve_type ∈ {A,B,C,D}, horizon,
                                 # economic_mechanism, regime_affinity, failure_modes,
                                 # polyagora_block, zone_permission
  sleeve_returns  : Series       # net of realistic transaction cost (cost_adjust)
  book_returns    : Series       # the current admitted book (v79 / v7.10)
  spy_returns     : Series       # for the SPY-correlation gate (new)
  weights_panel   : DataFrame    # for the Fragility Audit window slicing (new)
```

### 2.2 The gates

| # | Gate | Metric | Threshold | Rejection reason |
|---|---|---|---|---|
| 1 | Validation | standalone Sharpe, n_obs | Sharpe ≥ 0.20, n ≥ 252 | no real edge / too short |
| 2 | Deflated Sharpe | DSR p-value | `> dsr_floor` (0.50, noise floor — **not** the 0.95 AI-factory wall) | edge not separable from best-of-N luck |
| 3 | Correlation | `|corr|` to book **and** to SPY | book `< 0.70`; **SPY `< 0.15`** | re-expresses the book / carries equity beta |
| 4 | Walk-forward | OOS/IS Sharpe degradation | ratio ∈ `[0.3, 1.3]` ("healthy"/"suspicious") | fragile out-of-sample |
| 5 | Contribution | blended vs book Sharpe & Sortino | blend ≥ book on both | blending degrades the book |
| 6 | **Fragility Audit** (new) | per-window Sharpe + Max DD over 2008 / 2020 / 2022 | no rupture window worse than `−8%` DD contribution to the blended book | sleeve amplifies a known rupture |

### 2.3 Contribution scoring formula

The registry weight a sleeve earns is diversification-scaled; the contribution score
quantifies marginal benefit:

```
diversification = max(0, 1 − |corr_to_book|)
base_weight     = cap · diversification                 cap = 0.25 for a first sleeve
blend           = (1 − base_weight)·book + base_weight·sleeve
ContributionScore = (Sharpe(blend) − Sharpe(book)) / |Sharpe(book)|
                  + (Sortino(blend) − Sortino(book)) / |Sortino(book)|
```

Gate 5 passes iff `ContributionScore ≥ 0` on both terms. Among admitted sleeves the book
share is allocated in descending `ContributionScore`.

### 2.4 Output

```
SleeveEvaluation: spec, metrics, dsr, degradation, corr_to_book, corr_to_spy,
                  fragility_audit, contribution, gates{6 bools}, admitted, base_weight, notes
```

## 3. Typed sleeve catalog

The ad-hoc `SleeveSpec.sleeve_type` string is replaced by the spec's four formal types,
each with a regime target, a default zone-permission table, and an admission-cap profile.

| Type | Regime target | Instruments (this universe) | Status |
|---|---|---|---|
| **A — Crisis Trend** | panic persistence, flight-to-quality, rate shock | bond/USD time-series trend | **ADMITTED** (bond-trend, V7.10) |
| **B — Expansion Convexity** | persistent bull acceleration, stable reflation | cross-sectional / curve expansion | **candidate** (§4.1) |
| **C — Transition Convexity** | emerging regime transitions, early breakout | low-fragmentation cross-asset breakout | **candidate** (§4.2) |
| **D — Rupture Asymmetry** | non-linear breakdowns, correlation collapse | tail-option / long-vol structure | **data-blocked** (§6) |

## 4. New sleeve candidates

### 4.1 Type B — Cross-Sectional Expansion sleeve

The Phase-II priority. **Critically, it is *not* directional equity beta** — that is the
only construction that can also clear the SPY-correlation gate (CTO_Response §4, Risk 2).

- **Signal.** Rank the 13 futures by trailing 6–12 month risk-adjusted return; long the
  top quartile, short the bottom quartile; normalize to gross 1; long/short, so
  market-direction-neutral by construction.
- **Economic mechanism.** Persistent-expansion regimes show *cross-sectional dispersion*
  — the leaders keep leading. The sleeve harvests that dispersion convexity without
  taking the index.
- **Regime affinity.** `LOCAL_STAR`, persistent reflation, widening corridor (`C_t` high).
- **Failure modes.** Sharp cross-sectional reversals; correlation-collapse ruptures
  where all assets move together (dispersion vanishes).
- **Expected behavior.** Positive marginal Sharpe in 2009–2011 and post-2020; near-zero
  SPY correlation by the long/short construction; gate 3 SPY `< 0.15` should pass.
- **Admission risk.** Gate 6 Fragility Audit — must not amplify 2020; expected to need
  zone-permission `0` in `BOUNDARY`/`RUPTURE`.

### 4.2 Type C — Low-Fragmentation Breakout sleeve

- **Signal.** Cross-asset breakout entry (price clears an N-week range) **gated by
  Layer-5 `F_t`** — the sleeve only fires when fragmentation is low, i.e. the breakout
  is structurally coherent rather than a fragmented false move.
- **Economic mechanism.** Early-transition persistence: a breakout into a low-`F_t`
  regime tends to continue; into a high-`F_t` regime it whipsaws.
- **Regime affinity.** `TRANSITION` zone, rising `C_t`, low `F_t`.
- **Failure modes.** High-fragmentation false breakouts (suppressed by the `F_t` gate);
  rangebound chop.
- **Expected behavior.** Contributes in regime-transition windows; the `F_t` gate is
  itself the decorrelation mechanism vs. the Type-A crisis-trend sleeve.

## 5. Maximum admissible sleeve allocation by governance state

The sleeve cap is a function of `Zone_t` and sleeve type — convexity sleeves expand in
benign regimes and switch off in rupture; crisis sleeves do the opposite.

| Zone | Type A (Crisis) | Type B (Expansion) | Type C (Transition) | Type D (Rupture) |
|---|---|---|---|---|
| `LOCAL_STAR` | 0.10 | **0.25** | 0.10 | 0.00 |
| `TRANSITION` | 0.15 | 0.12 | **0.25** | 0.05 |
| `LEAST_BAD` | 0.20 | 0.05 | 0.10 | 0.10 |
| `BUFFER` | hold prior | hold prior | hold prior | hold prior |
| `BOUNDARY` / RUPTURE | **0.25** | 0.00 | 0.00 | **0.25** |

Caps are the *maximum* book share; the actual weight is `base_weight` (from §2.3) scaled
by the zone cap and further by MRTP's convexity decision. `BUFFER` freezes sleeve
weights at their prior value — the anti-whipsaw dwell state.

## 6. Dynamic intra-regime weight adjustment

Within an admitted zone, sleeve weights adjust with recoverability geometry, not just on
zone changes:

```
Π_sleeve(t) = base_weight · zone_cap(Zone_t, type)
            · g_type( C_t, R_t, F_t )
```

- **Type B:** `g_B` rises with `C_t` and `R_t` (wider corridor, higher recoverability ⇒
  more expansion convexity), falls with `F_t`.
- **Type C:** `g_C` peaks at intermediate `F_t` and rising `C_t`.
- **Type A:** `g_A` rises with `F_t` and `P_t` (crisis sleeve scales *into* stress).

This is the mechanism the spec's Open Problem B, Q4 asks for — sleeve weights track the
geometry continuously, not only at discrete zone transitions.

## 7. Decorrelation constraint matrix

Maximum allowed correlations, enforced at gate 3 per-sleeve and re-checked at book level
after each admission:

| Pair | Max `|corr|` |
|---|---|
| sleeve ↔ sleeve | 0.50 |
| sleeve ↔ main manifold (v79 book) | 0.70 |
| **sleeve ↔ SPY** | **0.15** (hard wall — the inviolable invariant) |
| book-aggregate ↔ SPY | 0.15 |

A candidate that would push the book-aggregate SPY correlation above 0.15 is rejected
even if it individually passes gate 3.

## 8. Expected Sharpe improvement & stress-test framing

Per the spec's Deliverable-C ask, each admitted sleeve ships with: (1) a quantified
marginal-Sharpe estimate from §2.3's `ContributionScore`; (2) the gate-6 Fragility Audit
table — per-window Sharpe and Max DD over 2008 / 2020 / 2022. The bond-trend (Type A)
reference: corr-to-book ≈ 0.28, flips the 2022 window from −0.84 to +0.44 Sharpe. The
Type B sleeve's target is the Phase-II acceptance criterion — **narrow the underexposure
gap vs. Momentum in post-2020 reflation by ≥30%** — not full beta capture.

## 9. Data-blocked sleeves (flagged, not built)

- **Type D — Rupture Asymmetry:** needs options / long-vol instruments — no data.
- **Carry:** needs futures term structure — no data.
- **Vol / Flow:** needs VIX term structure / dealer-gamma / CTA positioning — no data.

These remain registry placeholders with documented data requirements; they are not
fabricated from proxies.

## 10. Open items

- The Type B lookback (6 vs 12 months) and quartile width are calibration choices —
  resolved against the gate pipeline, not against returns.
- The `g_type` functional forms (§6) depend on Deliverable B's validated `C/R/F`
  estimators.
- Whether the V7.10 bond-trend sleeve's flat zone-permission table is retained or
  migrated to the §5 cap profile is a registry-migration decision for Deliverable A.

---
*Phase-II Deliverable C · CONFIDENTIAL · Draft v0.1*
