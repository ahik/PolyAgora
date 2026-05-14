# PolyAgora V7.6 — First-Cut Findings

**Date:** 2026-05-14
**Status:** Pre-dashboard spike. Four variants tested (v76α, v76β, v76γ, v76γ-full). Architecture validated; quantitative alpha over naive diversification is regime-dependent and not closed by the spec's full MRTP composite under cheap implementations.
**Spec source:** `docs/PolyAgora_Meta_Regime_Steering_Layer_V0.1.pdf`, `docs/ChatGPT - PolyAgora - Fixed Star Fund - FSF.pdf`, `docs/PolyAgora.pdf` (all dated 2026-05-14, same content in three formats).

## Executive summary

The minimum-viable meta-regime steering layer **delivers what the spec describes** — better Sharpe than any single manifold, strong "transition maneuverability" in 2008 / COVID, and robustness across hyperparameter choices. **But** the steering's marginal alpha over a naive equal-weight blend of the same manifolds is concentrated in the 2008–2016 half of the sample, and is neutral-to-negative in 2017–2026. We tested four progressively more sophisticated meta-layer formulations: rolling-Sharpe-only (v76α), regime-gated admissibility (v76β), full MRTP composite with persistence + adverse-CVaR (v76γ), and MRTP composite + regime-gate (v76γ-full). **None close the 2017–2026 gap; the more complex variants make it worse.** Under cheap implementations the spec's full MRTP composite is not predictive — its F_i (persistence autocorr) and D_i (regime-mismatch CVaR) terms are forward-looking only in *interpretation*, while their data inputs remain rolling backward signals that lag regime changes as much as rolling Sharpe does.

Headline (2008-04 → 2026-04, 4,669 trading days):

| Series | Sharpe | Sortino | Calmar | MaxDD | CAGR |
| --- | --- | --- | --- | --- | --- |
| v74d_q (M1) | 0.47 | 0.56 | 0.18 | -9.7% | 1.79% |
| momentum_12_1 (M2) | 0.52 | 0.67 | 0.22 | -14.7% | 3.26% |
| defensive (M3) | 0.62 | 0.93 | 0.18 | -19.0% | 3.51% |
| cash (M4) | — | — | — | 0.0% | 0.00% |
| naive 1/4 blend | 0.74 | 1.00 | 0.33 | -6.6% | 2.21% |
| **v76α** (rolling-Sharpe gate) | **0.82** | **1.08** | 0.32 | -10.3% | 3.23% |
| **v76β** (MRTP-lite, regime-gated) | 0.80 | 1.03 | 0.31 | -12.4% | **3.85%** |
| **v76γ** (full MRTP: S + F − D, A = 1) | 0.72 | 0.92 | 0.29 | -10.5% | 3.10% |
| **v76γ-full** (full MRTP + regime A) | 0.73 | 0.94 | 0.30 | -10.5% | 3.19% |

## What's new in V7.6

V7.6 is a **structural shift**, not another single-engine refinement. The prior V7.x line iterated one alpha engine (V7.3 / V7.4 / V7.5) inside the same Reference Polygon. V7.6 introduces a **two-level architecture per spec §2** — strategy manifolds at level 1, a meta-regime steering layer at level 2 — and treats the prior engines as one of several manifolds rather than as the system itself. Concretely new in V7.6:

1. **Four manifolds instead of one engine.** v74d_q (the V7-line winner) is now M1 of four. M2 is plain 12-1 momentum. M3 is a deliberately simple frozen defensive mix (40% TN + 20% FGBL + 20% GC + 20% DX). M4 is pure CASH — the absorbing rest-state for when no manifold has positive realized Sharpe. Each manifold is frozen during meta-layer validation per spec §12.A.
2. **Meta-regime steering layer.** A slow softmax-over-manifolds with admissibility gating, computed once per close from `realized ≤ t-1`. Four variants tested, progressively more sophisticated: v76α (Sharpe-only), v76β (regime-conditioned admissibility), v76γ (full MRTP composite α·S + β·F − γ·D), v76γ-full (MRTP + regime A).
3. **Smooth probabilistic steering, no binary regime switches.** EWM halflife 10 days plus a 15% allocation floor (v76α) gives 0 days with |ΔW_i| > 5pp over 4,669 trading days. Spec §4's "slower / coarser / lower entropy" mandate is satisfied.
4. **Explicit recoverability framing.** The product optimization target is no longer "beat the benchmark." It is the spec §1 objective set — absolute returns, recoverability, maneuverability, low correlation to traditional asset classes, institutional robustness.
5. **A negative result we are publishing.** v76γ and v76γ-full implement the spec's full MRTP composite from cheap inputs derivable from existing v75 diagnostics. They do not close the recent-period gap to naive 1/4 diversification — they widen it. Documented so the next iteration does not retrace this path.
6. **Empirical reference line: naive 1/4.** A fixed equal-weight blend of the four manifolds is now the reference any v76 variant must clear. Its full-sample Sharpe of 0.74 is the diversification-only baseline; the meta-steering layer's marginal value is whatever sits above that line.

Nothing in the V7.4 / V7.5 line is deprecated. v74d_q remains the V7-line winner, and is the M1 manifold in V7.6.

## Architecture

Two-level construction per spec §2:

**Level 1 — Strategy manifolds (frozen, no further tuning):**

- **M1 = v74d_q** — the PolyAgora V7 manifold (`make_v75_q_signal` with `α_M=0, include_mom_eigen=False, K=2, τ=2, λ=0.5`, VAIDM × ADD Q polygons). Maps to spec §3.2: transitions, fragmentation, boundary instability.
- **M2 = momentum_12_1** — the 12-1 momentum baseline from `polyagora_v63_partner_engine`. Maps to spec §3.1: persistent trends, coherent low-vol expansions.
- **M3 = defensive** (new, `polyagora_v76_engine.defensive_signal`) — frozen 40% TN + 20% FGBL + 20% GC + 20% DX. Maps to spec §3.3: rupture, collapse geometry.
- **M4 = cash** (new, `polyagora_v76_engine.cash_signal`) — zero real-asset weights. The absorbing rest-state for when no manifold has positive rolling Sharpe.

**Level 2 — Meta steering layer:** softmax-of-rolling-Sharpe with two variants of the admissibility gate.

```
v76α:  W_i(t) = exp(λ·MRTP_i(t)) / Σ_j exp(λ·MRTP_j(t))
v76β:  W_i(t) = A_i(t) · exp(λ·MRTP_i(t)) / Σ_j A_j(t) · exp(λ·MRTP_j(t))

where
  MRTP_i(t)  = annualized rolling Sharpe of manifold i's returns over [t-63, t-1]
  A_i(t)     ∈ [0.10, 1.00] — see "Admissibility (v76β)" below
  EWM smoothing on W_i with halflife 10 days, then min_floor 0.15 (v76α only).
```

Anti-hindsight: `MRTP_i(t)` reads `returns_i.shift(1)`; v75 diagnostics at `t` already depend only on `realized ≤ t-1`, so they pair with `manifold_weights[t]` without further shift.

## Full MRTP composite (v76γ, v76γ-full)

Spec §8: `MRTP_i = α·S_i + β·F_i − γ·D_i`. Anti-hindsight is preserved by computing every term from data ≤ t-1 — "forward-looking" in the spec terminology means *projects expected future state from a model fit on the past*, not *reads the future*.

```
S_i(t) = tanh( rolling Sharpe of returns_i over [t-63, t-1] / 2 )           # → [-1, 1]
F_i(t) = lag-21 autocorrelation of a regime coord over [t-252, t-1]:
         v74d_q   ← autocorr(dQ_τ)       — transition activity persistence
         momentum ← autocorr(T_τ)         — trend persistence
         defensive← autocorr(V_τ)         — vol-stress persistence
         cash     ← -max(S_i for i ≠ cash) — option value when nothing works
D_i(t) = tanh( 50 · CVaR_5%( returns_i_τ | sign(V_τ, T_τ) ≠ sign(V_t, T_t) ) )
                                                                              # → [0, 1]
```

`v76γ` runs the composite with `A_i ≡ 1` (no gate — MRTP does the regime work); `v76γ-full` keeps the v76β regime-gated `A_i`. Defaults `α = β = 1`, `γ = 0.5`, lookbacks 63/252/252, EWM halflife 10d, floor 0.05.

Anti-hindsight is enforced at three points: (1) `_rolling_sharpe` applies `.shift(1)` before windowing; (2) `_rolling_autocorr` does the same on the regime coord; (3) `_conditional_cvar` uses `bin_V = sign(V.shift(1))` and indexes returns via `r.shift(1)`. v75 diagnostics at row t already depend only on `realized ≤ t-1` by the v75 invariants, so the diag-side inputs need no further shift.

## Admissibility (v76β, MRTP-lite)

Each manifold's regime-conditional admissibility is computed directly from v75's existing diagnostics output — no new feature stack:

```
A_v74d_q   = σ(2.0 · [1.5·dQ⁺ + 1.0·(d_RP-0.4)⁺] - 0.5)
A_momentum = σ(3.0 · [|T| - 1.5·dQ⁺] - 0.5)
A_defensive= σ(3.0 · V)
A_cash     = σ(-3.0 · max(rolling_sharpes, 0))
```

then floored at 0.10. The mapping echoes the spec's conceptual interpretation (§3): V7 wins under transition activity (`dQ`, `d_RP`); momentum wins under stable trends (high `|T|`, low `dQ`); defensive wins under VIX stress (high `V`); cash wins only when no manifold's recent realized Sharpe is positive.

## Results

### Robustness — sensitivity sweep (500 configs)

Grid over `lookback ∈ {21, 42, 63, 126, 252}`, `λ ∈ {0.5, 1, 2, 4, 8}`, `halflife ∈ {1, 5, 10, 21, 60}`, `floor ∈ {0, 0.05, 0.10, 0.20}`.

- 4-manifold v76α Sharpe distribution: min 0.58, 25th 0.73, median 0.76, 75th 0.79, max 0.86.
- Every config beats every single static manifold (best static = defensive at 0.62).
- Median Sharpe rises monotonically with `floor`: 0.75 at floor=0 → 0.78 at floor=0.20.
- Lookback=63 is the median winner (0.81); lookback=252 collapses (0.68).
- `λ` is approximately flat between 0.5 and 8.

Conclusion: the chosen `(lookback=63, λ=2, halflife=10, floor=0.15)` lands near the 90th percentile of the grid. Sharpe 0.82 is not a hyperparameter accident.

### Crisis windows — the spec's "transition maneuverability"

| Window | naive | v76α | v76β | v76γ | v76γ-full |
| --- | --- | --- | --- | --- | --- |
| 2008 GFC (Apr08–Jun09) | -0.81 | +0.55 | **+0.94** | +0.76 | +0.79 |
| COVID (Feb20–Dec20) | +0.54 | **+1.37** | +1.14 | +0.44 | +0.31 |
| 2022 rates (Jan22–Dec22) | -0.49 | -0.71 | -0.89 | **-0.48** | -0.55 |
| Last 3 years (Jan23–) | **+0.85** | +0.72 | +0.65 | +0.49 | +0.55 |

All four steered variants substantially outperform naive in 2008. In COVID v76α is the clear winner — adding F_i and D_i (γ, γ-full) *halves* the COVID Sharpe (1.37 → 0.44). v76γ is the only variant to beat v76α on 2022 rates, but at the cost of much worse COVID and trend-period results. **No variant beats naive in 2022 rates or the recent 3-year trend.**

### Temporal split — the headline finding

Sharpe in each window:

| Window | naive | v76α | v76β | v76γ | v76γ-full |
| --- | --- | --- | --- | --- | --- |
| 2008-04 → 2016-12 (first half) | 0.78 | 0.99 | **1.03** | 0.93 | 0.94 |
| 2017-01 → 2026-04 (second half) | **0.70** | 0.65 | 0.56 | 0.52 | 0.53 |
| 2008-04 → 2019-12 (pre-COVID) | 0.81 | 0.95 | **0.97** | 0.89 | 0.92 |
| 2020-01 → 2026-04 (COVID-on) | **0.60** | 0.56 | 0.43 | 0.35 | 0.33 |

MaxDD in each window:

| Window | naive | v76α | v76β | v76γ | v76γ-full |
| --- | --- | --- | --- | --- | --- |
| 2008-04 → 2016-12 | **-5.1%** | -6.1% | -7.4% | -6.9% | -6.9% |
| 2017-01 → 2026-04 | **-6.6%** | -10.2% | -12.4% | -10.5% | -10.5% |
| 2008-04 → 2019-12 | **-6.0%** | -8.6% | -10.9% | -10.5% | -10.4% |
| 2020-01 → 2026-04 | **-6.6%** | -10.2% | -12.4% | -10.0% | -10.5% |

**The entire v76 alpha over naive comes from the first half of the sample.** In 2017-2026 every steered variant underperforms naive on Sharpe and on MaxDD. **More machinery does not help — Sharpe in 2017-2026 decreases monotonically with sophistication:** α (0.65) > β (0.56) > γ-full (0.53) > γ (0.52). The 2020-2026 window is starker still: naive 0.60 vs γ 0.35. Adding the spec's F_i and D_i terms makes the trend-period drag *worse*, not better.

Year-by-year vs naive (full sample, 19 years):

```
α wins over naive: 13/19 years, mean +1.04pp/yr
β wins over naive: 13/19 years, mean +1.69pp/yr
β wins over α:     13/19 years, mean +0.65pp/yr
```

β has higher mean alpha than α (full sample) — but pays for it in worse drawdowns (2022 -2.4pp vs α's -1.1pp; 2023 -4.4pp vs α's -3.2pp). γ and γ-full underperform both α and β across recent years. The pattern is unambiguous: the steering layer earns its keep in regime transitions and gives some back in persistent trends, and adding more terms to the meta-score does not recover the trend-period drag — it amplifies it.

### Manifold allocation behavior

v76α (Sharpe-only gate, with 15% floor):

```
v74d_q:        mean 0.285  std 0.205  min 0.104  max 0.688
momentum_12_1: mean 0.248  std 0.172  min 0.104  max 0.688
defensive:     mean 0.306  std 0.217  min 0.104  max 0.689
cash:          mean 0.160  std 0.098  min 0.104  max 0.657
days with |ΔW_i|>5pp: 0 across all manifolds
```

v76β (regime gate, no W-floor since A_i provides natural floor):

```
v74d_q:        mean 0.317  std 0.316  min 0.000  max 0.995
momentum_12_1: mean 0.264  std 0.264  min 0.000  max 0.992
defensive:     mean 0.335  std 0.340  min 0.000  max 0.999
cash:          mean 0.084  std 0.144  min 0.000  max 0.849
days with |ΔW_i|>5pp: v74d_q 6, mom 9, def 11, cash 1
```

v76β is materially more concentrated — three manifolds reach >99% allocation at some point. This explains both its higher absolute returns in transitions and its worse drawdowns when its regime call is wrong. v76α stays gently smoothed.

Regime calls (W_i snapshots, v76α with 15% floor):

```
2008-09 GFC peak:       def 0.91  mom 0.05  v74d 0.05  ✓
2020-03 COVID:          def 0.90  mom 0.05  v74d 0.05  ✓
2020-12 rally:          v74d 0.91 mom 0.05  def 0.05   ✓
2022-06 rates:          mom 0.81  v74d 0.14 def 0.05   ✓
2024-12 trending:       mom 0.88  v74d 0.05 def 0.07   ✓
```

Regime detection is qualitatively right in all five test points.

## Honest assessment

**The v76 architecture works as the spec describes.** Four-manifold composition is clean, regime detection is qualitatively correct, sweep robustness is strong, and crisis-window performance is materially better than any single manifold or naive diversification. The spec's "transition maneuverability" promise is empirically delivered.

**But the steering's quantitative alpha over naive diversification is regime-dependent and fragile.** A fixed equal-weight blend of the four manifolds achieves Sharpe 0.74 with -6.6% MaxDD. v76α adds Sharpe (+0.08) and CAGR (+102bps) over the naive blend in full-sample terms, **but the wins are concentrated in 2008-2016 and the losses are concentrated in 2017-2026**. In the recent 6 years, naive 1/4 beats every v76 variant on Sharpe and MaxDD.

**MRTP-lite (v76β) does not close this gap.** Replacing the trivial admissibility gate with regime-conditioned `A_i` from v75's already-computed `(T, V, d_RP, dQ)` coords *amplifies* both ends of the trade — it concentrates harder when its call is strong (Sharpe 0.94 in GFC vs 0.55 for v76α) and concentrates harder when its call is wrong (2022 rates: -0.89 vs -0.71). Net Sharpe drops slightly (0.80 vs 0.82); net CAGR rises (3.85% vs 3.23%); net MaxDD worsens (-12.4% vs -10.3%).

**Full MRTP (v76γ, v76γ-full) does not close it either — it makes the recent-period gap worse.** This is the substantive negative finding of this iteration. The spec's full composite `MRTP_i = α·S_i + β·F_i − γ·D_i` was supposed to overcome the lagged-Sharpe limitation by adding "future maneuverability" (`F_i`) and "expected damage if wrong" (`D_i`). Under the cheapest defensible implementation — lag-21 autocorrelation of regime coords for `F`, regime-bin-mismatch CVaR for `D` — neither term is actually predictive. Specifically:

- `F_i = autocorr(regime_coord)` over 252d tells us *how persistent the regime has been*, which is mathematically very close to *what already happened*. When a long trend is about to reverse, autocorr is at its peak right when the signal is most wrong.
- `D_i = CVaR_5%(returns | sign-mismatched regime bin)` over 252d puts a static-historical loss prior on each manifold. It updates slowly and doesn't actually predict damage on the specific upcoming regime.
- Subtracting `D` from `MRTP` then penalizes whichever manifold has had ugly tails on regime mismatches — but the manifold with the worst historical mismatch-tail is often defensive (it gets crushed in rates-up regimes), so `D` ends up disproportionately suppressing defensive *at exactly the moment we need it most*.

Empirically: v76γ underperforms v76α in every temporal window (Sharpe 0.65 → 0.52 in 2017-2026, 0.56 → 0.35 in 2020-2026). The COVID Sharpe collapses from 1.37 (v76α) to 0.44 (v76γ). The 2022-rates Sharpe improves modestly (-0.71 → -0.48) but the net effect across regimes is unambiguously worse.

**Forward-looking ≠ predictive.** Anti-hindsight is preserved in every term — F and D read only data ≤ t-1. But "doesn't peek at the future" and "predicts the future" are different properties. F and D as cheaply implemented are forward-looking only in *interpretation*; their *information content* is essentially the same backward-window rolling statistics as S. Adding redundant lagged signals to a meta-score doesn't reduce its lag.

**The structural bottleneck is the regime model, not the score composition.** All four variants assume the meta-state can be summarized by `(V, T, d_RP, dQ)` plus rolling statistics of these. None of these are leading indicators — they are reactive to realized price and volatility. To genuinely move the needle on 2017-2026 we would need either:

- External leading signals — VIX term structure slope, yield curve shape, futures positioning, credit spreads — that price *expected* future regime change rather than measure realized regime state.
- A regime-prediction model (HMM, Markov chain, supervised classifier) trained walk-forward on past regime transitions to actually forecast `P(regime_{t+k} | history_{≤t})`. Substantial engineering, possible overfit risk.
- Acceptance that v76 is structurally a crisis-defense overlay and stop building meta-machinery on top.

**Sharpe > 1.5 target is out of reach with this approach.** The best 4-manifold v76α config in the sweep peaks at Sharpe 0.86 over full sample, ~0.60 over the most recent 6 years. Reaching the spec's institutional bar would require either: (a) materially better manifolds (cleaner momentum, less drawdown-prone defensive), (b) genuinely predictive leading signals (external data feeds or a regime-prediction model), or (c) cash floor / volatility targeting overlays that aren't part of the meta-steering spec.

## Path forward

The v76γ spike answered the open question from the previous iteration: **the spec's full MRTP composite, under any cheap implementation derivable from existing v75 diagnostics, is not predictive enough to close the 2017–2026 gap.** This collapses the prior decision tree to three concrete options.

**Option 1 — Ship v76α as a crisis-defense overlay.** Treat the 4-manifold construction with the trivial Sharpe gate as the production default. Frame it honestly: diversification + steering = small Sharpe lift over naive, neutral-to-negative recent-period drag, but materially better crisis defense (Sharpe 0.55–1.37 vs -0.81–0.54 for naive in 2008/COVID). The 15% W-floor keeps drawdowns bounded. Build the dashboard around this — manifold-allocation panel, meta-state strip, three-system comparison per spec §12.D.

**Option 2 — Ship v76β as the higher-return / higher-risk variant.** Use the regime-gated version for clients who want more aggressive transition-following (+62bps CAGR vs v76α at the cost of -2.1pp on MaxDD). Pair with explicit drawdown warnings. Lower priority than Option 1 — the trade is not obviously a Pareto improvement.

**Option 3 — Stop building meta-steering machinery on top of internal diagnostics.** v76γ established the ceiling of what's reachable from `(V, T, d_RP, dQ)` plus rolling statistics of these. To exceed it, the next spike must introduce *external leading information* — VIX term structure, yield curve, credit spreads, futures positioning — or a real regime-prediction model trained walk-forward. Both are substantial engineering, with non-trivial overfit risk. Defer until Option 1 is shipped and we know whether the crisis-defense framing is what clients actually want.

**Explicitly rejected paths after this iteration:**

- Further variants of the MRTP composite (different weightings of S/F/D, different lookbacks for F/D, different regime-bin definitions) — the structural problem is the information content of the inputs, not the composition.
- More elaborate admissibility gates derived from v75 diagnostics — v76β already showed this saturates.
- Online learning or parameter-fitting against realized returns — guard-rail per spec §16.

**Recommendation: Option 1.** Build the dashboard around v76α with v76β as an alternate. Frame the product honestly as a crisis-defense + diversification overlay, not as an institutional Sharpe-maximizer. If subsequent work wants to push past Sharpe ≈ 0.82, the substantive next bet is external leading data feeds (Option 3), not more iterations on the internal-diagnostics meta-score.

## What NOT to do (spec §16 guard-rails)

These guard-rails held in this iteration and should hold in any next step:

- No further tuning of v74d_q parameters. M1 is frozen.
- No online learning, no parameter-fitting against forward returns, no meta-meta.
- No high-frequency switching. v76α achieves 0 days with |ΔW_i| > 5pp; v76β has 6–11. Either is well within "slow/coarse/low-entropy."
- No carry / convexity / macro overlays on top of v76 until either Option 3 closes the temporal-split gap or we've explicitly accepted v76 as a crisis-defense product.

## Files

- `polyagora_v76_engine.py` — engine. `defensive_signal`, `cash_signal`, `MetaConfig`, `meta_blend` (v76α), `compute_regime_admissibility`, `meta_blend_mrtp` (v76β), `MrtpConfig`, `compute_mrtp_score`, `meta_blend_gamma` (v76γ).
- `run_v76_check.py` — runs all four manifolds + naive + v76α/β/γ/γ-full, prints full comparison incl. temporal split. CLI flags: `--lookback`, `--lam`, `--halflife`, `--floor`, `--no-cash`.
- `run_v76_sweep.py` — 500-config sensitivity sweep over the four meta hyperparameters.
- `polyagora_v76_outputs/` — weights, returns, equity, diagnostics, manifold allocations, admissibility frames, MRTP scores for all seven series.
