# PolyAgora V6.3 — Buffett-Doctrine Rollout

Persistent worklist for the partner-delivery v63 project. This file is the
durable source of truth across sessions; in-session `TaskCreate` lists are
session-scoped and should be re-seeded from this file at the start of a new
session.

## Context (current state)

- **Engine**: `polyagora_v63_partner_engine.py`. Loads
  `Agur/baseline_pnl_partner_delivery.xlsx`, builds weights respecting
  Type-1 (pre-inception → zero) / Type-2 (post-inception NaN → freeze) NaN
  rules, and enforces sum-to-1 over the live universe.
- **Runner**: `run_polyagora_v63_partner.py`. Produces five signals
  (`equal_weight`, `inverse_vol`, `momentum_12_1`, `polyagora`,
  `polyagora_gated`) plus a self-contained `dashboard.html` with brush-based
  range zoom.
- **No-lookahead guards**: `compute_weights` enforces history alignment,
  active-asset subset, and `forward_pnl` integrity hash. Adversarial probes
  trip both. `forward_pnl` is only ever read inside `evaluate()`.
- **Gated polyagora** uses v62 carry-core's β pattern adapted as a *blend*
  (no cash in the partner spec): `weights_t = β_t · regime_tilt + (1 − β_t) ·
  neutral_template`. β = vix_gate × spy_5d_gate × dd_gate × cooldown × EWM,
  shifted by 1.

### Latest summary (full window 2008-04-01 → 2026-04-29, regenerated 2026-05-05)

Under the new capital-budget envelope (cash slot enabled):

| Series          | CAGR  | Vol   | Sharpe | Max DD  |
|-----------------|-------|-------|--------|---------|
| equal_weight    | 1.86% | 4.46% | 0.44   | -10.6%  |
| inverse_vol     | 1.86% | 4.46% | 0.44   | -10.6%  |
| momentum_12_1   | 3.26% | 6.57% | 0.52   | -14.7%  |
| polyagora       | 1.90% | 4.20% | 0.47   | -10.6%  |
| polyagora_gated | 2.84% | 4.21% | **0.69** | **-9.7%** |

Head-to-head v63 vs v7 (partner-delivered structural baseline):

| Engine          | CAGR  | Vol   | Sharpe | Max DD   |
|-----------------|-------|-------|--------|----------|
| v63 polyagora_gated | 2.84% | 4.21% | 0.685 | **-9.67%**  |
| v7  polyagora_v7    | **3.99%** | 5.96% | 0.686 | -13.79% |

v7 wins ~110 bps CAGR; v63 wins ~410 bps max-DD. Sharpe is a tie. v7's
`Z3_DEFENSE` zone never fires (stress threshold too strict — fix forthcoming).

### Capital-budget envelope (landed 2026-05-05)

Per partner CTO direction, both engines now respect:
```
|w_real_i| ∈ [-1, 1]   per real asset
w_cash    ∈ [ 0, 1]   cash slot, never negative
sum(|w_real|) + w_cash = 1.0   capital budget
```

- Synthetic `CASH` pseudo-asset (zero return on realized & forward, always
  live, immune to inception/NaN) added inside both engines. Workbook is
  unchanged — cash is engine-internal and emerges in the weights panel.
- `polyagora_v63_partner_engine.py`: refactored `compute_weights` to
  gross-budget renorm; templates B and G squashed from gross 1.40/1.70 to
  gross 1.0 (long/short ratios preserved, net falls to 0.71/0.59);
  `momentum_signal` pre-normalizes to gross=1; runner invariant check
  updated to `abs().sum() == gross_cap`. The gated signal's
  `_renorm_to_gross` (was `_renorm_to_unit`) now divides by gross instead
  of net so the β-blend respects the envelope without the engine having to
  downscale (and CASH actually appears on stress days — mean 1.4%, max
  20%, fires on 22% of trading days).
- `docs/polyagora_v7_agor_baseline_engine.py`: `_cap_and_renormalize`
  emits cash residual; weights panel now has CASH column; legacy v7
  numbers are identical (cash fires only 5/4669 days during warmup).
- Verified: capital budget invariant holds exactly (1.000000) on every
  signal × every day.
- `evaluate()` only multiplies real-asset columns × `forward_pnl`, so cash
  is correctly priced at zero contribution.

## Buffett-doctrine threads to add (priority order)

Each item below maps a thread from `docs/The-Buffett-System.pdf` to a
concrete code change in v63. IDs in brackets match the in-session
`TaskCreate` IDs at the time this file was written; re-create those if
needed.

### [9] Patience — slower β smoothing halflife — done (2026-05-05)

**Doctrine**: "Hold" step of Wait → Recognize → Act → Hold.
**Change**: exposed `--beta-halflife` CLI override on the runner; ran a sweep
over {3, 5, 7, 10, 15, 20}. Default kept at **3.0** — v62 carry-core's
finding did NOT transfer to the v63 partner-delivery universe.

Sweep results (polyagora_gated, full window):

| halflife | CAGR  | Vol   | Sharpe | Max DD |
|----------|-------|-------|--------|--------|
| **3**    | 2.85% | 4.35% | **0.668** | -9.71% |
| 5        | 2.83% | 4.36% | 0.662  | -9.77% |
| 7        | 2.83% | 4.38% | 0.659  | -9.77% |
| 10       | 2.82% | 4.40% | 0.655  | -9.75% |
| 15       | 2.80% | 4.42% | 0.648  | -9.70% |
| 20       | 2.78% | 4.44% | 0.641  | -9.67% |

Sharpe is monotonically decreasing in halflife. Max DD improves marginally
(~4 bps) above HL=10 but not enough to offset the Sharpe loss. v63's regime
tilt is faster-moving than v62 carry-core, so a slower β smoother just lags
opportunity.
**Files touched**: `polyagora_v63_partner_engine.py` (default unchanged at
3.0 after sweep), `run_polyagora_v63_partner.py` (added `--beta-halflife`).

### [10] Wait → Act — contrarian post-stress deployment — pending

**Doctrine**: "Cash accumulates during calm, deploys after fear" — the
genuinely differentiated edge. With the cash slot now landed, this becomes
a cleaner construction than the old "β > 1" overload.
**Change** (cash-aware): when β is low (stress regime), the gated signal
should opt for cash via `gross_real < 1`, not just blend toward NEUTRAL.
After `hard_kill` fires AND market is recovering (VIX 5d falling AND
SPY 5d > 0), drain that accumulated cash back into the regime tilt over a
10-20 day window. The contrarian edge is "deploy held cash after fear",
not "lever above 1".
**Files**: `polyagora_v63_partner_engine.py` — `_compute_beta_from_market`
and `make_polyagora_signal_gated._signal` (introduce a deployment-fraction
that returns `gross_real ≤ 1` and lets engine cash absorb the rest).
**Risk**: over-fitting to a small number of historical events
(COVID-March, Aug 2015, Q4 2018). Sensitivity sweep required.
**Blocked by**: nothing.

### [11] Survival — hard DD floor with N-day lockout — pending

**Doctrine**: "Risk = permanent impairment, not volatility."
**Change**: promote the soft `dd_gate` to a hard rule: when proxy portfolio
DD ≤ -10%, force β=0 and stay there for N days regardless of other gates.
Mirrors v62 engine's `hard_dd` / `hard_min_scale` pattern
(`polyagora_v62_engine.py:127-128`). Add `hard_dd_floor` and
`hard_dd_lockout` to `PolyagoraGateConfig`.
**File**: `polyagora_v63_partner_engine.py` — `_compute_beta_from_market`.
**Note**: less novel than #10 (essentially a v62 import) but aligned with
the doctrine and tail-protective.
**Blocked by**: [10].

### [12] Margin of Safety — 252d entry-quality filter — pending

**Doctrine**: "Buy only at substantial discount to intrinsic value."
**Change**: trailing-252d sanity filter. Before opening a *short* in any
template, require the asset's trailing 252d realized return ≤ 0; before a
*long*, require ≥ -20%. Apply by zeroing offending template entries on the
day, then renormalizing the live row.
**File**: `polyagora_v63_partner_engine.py` — inside the polyagora signal
closure or as a wrapper.
**Caveat**: may overlap with #10 (post-stress deployment already requires
SPY recovering) and may not be additive. Measure carefully.
**Blocked by**: [10].

### [13] Benchmark + dashboard refresh — pending

**What**: after each Buffett-doctrine add, run the runner and capture the
summary table in this file. Final pass: regenerate `dashboard.html`,
confirm all signals render, brush still works, no-lookahead adversarial
probes still trip.
**Files**: `run_polyagora_v63_partner.py`,
`polyagora_v63_partner_outputs/dashboard.html`.
**Blocked by**: [9], [10], [11], [12].

## How to resume in a new session

1. Read this file.
2. (Optional) Re-seed in-session tasks via `TaskCreate` matching the
   "pending" items here.
3. Pick up from the first pending, unblocked item.
4. Update *this file* (status: pending → in-progress → done; record any
   numbers from benchmark runs) as you go. Treat it as the source of truth.
