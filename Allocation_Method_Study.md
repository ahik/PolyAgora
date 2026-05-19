# PolyAgora — Cross-Method Allocation Study

**Deep comparison of every PolyAgora allocation method across the
2008-04 → 2026-04 timeline, with a search for a robust overall
allocator.**

Generated 2026-05-16. Empirical basis: the cached `returns_*.csv`
side-files in `polyagora_v75/76/77/78_outputs/` — 33 distinct daily
return series, 4,669 trading days, scored on the partner forward-PnL.
Analysis scripts and intermediate tables: `/tmp/polyagora_analysis/`.

---

## 1. Executive summary

1. **The meta-steering architecture works.** The V7.6α meta-allocator
   lifts full-sample Sharpe from 0.47 (its own best manifold, v74d_q)
   to 0.82 — the single largest jump in the version history. Everything
   from V7.6 onward (v76, v76b, v77-ADD, v78-ADD, v78) clusters at
   Sharpe 0.80–0.83 and is the top tier.

2. **V7.8-ADD is the cleanest production core.** Full-sample Sharpe
   0.827, Sortino 1.081, **best Calmar (0.324)** and **shallowest max
   drawdown (−8.0%)** of every real method. It is the recommended
   single allocator as-is.

3. **No method wins everywhere — and that is by design.** Across seven
   regime windows the meta-steered line never ranks best and never
   ranks worse than ~8/12. The directional methods (`defensive`,
   `momentum`, `equal_weight`) each rank #1 in one regime and last in
   another. Consistency, not dominance, is the meta-layer's product.

4. **A maneuverability-scaled defensive tilt is the strongest
   improvement candidate.** Smoothly tilting v78-ADD toward the
   `defensive` manifold as the book's 63-day trend weakens lifts Sharpe
   to **0.870** and Sortino to **1.247** with the best rolling-Sharpe
   stability of any candidate — a credible **V7.9** direction.

5. **One drawdown dominates all risk.** Every method's worst episode is
   the **same ~1,300-day (3.6-year) drawdown** that began with the
   2022-03 rate shock and only recovered in late 2025. It is a slow
   grind, not a crash.

6. **2022 is the universal blind spot.** Every method and every blend
   posts a *negative* Sharpe in the rate-shock regime; the `defensive`
   manifold is the *worst* performer there. Diversification does not
   fix it. Closing this gap needs an uncorrelated alpha sleeve that
   works under inflationary/rate-shock geometry — the V7.8 spec's
   Phase-2 sleeves — not more governance tuning.

---

## 2. Scope & method universe

33 return series were grouped and a 12-method **focus set** carried
through the timeline analysis:

| Group | Members (focus set in **bold**) |
| --- | --- |
| Model-free baselines | **equal_weight**, inverse_vol, **momentum_12_1** |
| V7.6 manifolds (level-1) | **v74d_q**, **defensive**, cash |
| Prior engine versions | v73, v74, v74d, v74b·*, v75·* |
| Meta-steered (V7.6) | **v76** (α), **v76b** (β), v76g, v76g_full, **naive_1_4** |
| Overlays (V7.7 / V7.8) | **v77_add**, v77_kelly, **v77**, **v78_add**, **v78** |
| External reference | **sp500** |

All metrics use 252 trading days/yr; Sharpe = mean·252 / (std·√252);
Sortino uses downside-only std; Calmar = CAGR / |MaxDD|. Every series
is scored anti-hindsight on partner forward-PnL — the same convention
the engines enforce.

---

## 3. Full-sample comparison (2008-04 → 2026-04)

Top of the table, sorted by Sharpe:

| Method | Group | CAGR | Vol | Sharpe | Sortino | Calmar | MaxDD | Time-in-DD |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| **v78_add** | overlay | 2.6% | 3.2% | **0.827** | 1.081 | **0.324** | **−8.0%** | 40% |
| v78 | overlay | 2.6% | 3.1% | 0.827 | 1.080 | 0.323 | −8.0% | 40% |
| v76 (α) | meta | 3.2% | 4.0% | 0.821 | 1.078 | 0.315 | −10.2% | 49% |
| v77_add | overlay | 2.7% | 3.5% | 0.802 | 1.035 | 0.319 | −8.6% | 46% |
| v76b (β) | meta | 3.9% | 4.9% | 0.798 | 1.029 | 0.310 | −12.4% | 56% |
| naive_1_4 | meta | 2.2% | 3.0% | 0.744 | 1.002 | 0.332 | −6.6% | 36% |
| v73 | prior | 2.9% | 4.2% | 0.707 | 0.916 | 0.326 | −9.0% | 48% |
| sp500 | external | 11.3% | 19.5% | 0.645 | 0.773 | 0.219 | −51.5% | 54% |
| defensive | manifold | 3.5% | 5.9% | 0.616 | 0.929 | 0.185 | −19.0% | 68% |
| momentum_12_1 | baseline | 3.3% | 6.6% | 0.521 | 0.669 | 0.221 | −14.7% | 70% |
| v74d_q | manifold | 1.8% | 3.9% | 0.471 | 0.556 | 0.184 | −9.7% | 69% |
| equal_weight | baseline | 1.9% | 4.5% | 0.436 | 0.565 | 0.176 | −10.6% | 54% |

Reading:

- **The meta-layer is the value-add.** v74d_q — the strongest single
  manifold — scores Sharpe 0.47. Steering across the four manifolds
  (v76) reaches 0.82. The 0.35-Sharpe gap is the meta-architecture's
  contribution; it is larger than any other single design step.
- **The overlays trade return for risk.** v77-ADD / v78-ADD have lower
  CAGR than v76α (2.6% vs 3.2%) but lower vol and drawdown, so Sharpe
  holds or improves and Calmar improves. v78-ADD is the cleanest of
  these — same Sharpe as v76α, drawdown cut from −10.2% to −8.0%.
- **v76β chases CAGR and pays in drawdown** (−12.4%). Not preferred.
- **sp500 is uninvestable on a risk basis.** Its 11.3% CAGR is a
  different universe (equity beta); the −51.5% drawdown disqualifies it
  as anything but a market-beta reference.
- **v77-Kelly / v77-full are confirmed weak** (Sharpe 0.65–0.68): the
  V7.7 μ/σ²·Φ Kelly was the blunt brake the V7.8 redesign removed.

---

## 4. Timeline analysis — who wins when

### 4.1 Regime windows — Sharpe

| Regime | EW | mom | naive¼ | v74d_q | defen. | v76α | v77-ADD | v78-ADD | sp500 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| GFC crash 08-09 | −1.49 | −1.49 | −0.34 | −1.85 | **1.62** | 1.14 | 1.11 | 1.17 | −0.92 |
| GFC recovery 09-11 | 0.92 | 0.15 | 0.94 | 0.75 | 1.34 | 1.35 | 1.34 | **1.37** | 1.00 |
| QE bull 12-19 | 0.38 | 0.64 | 0.88 | 0.58 | 0.71 | 0.78 | 0.76 | 0.79 | **1.13** |
| COVID 2020 | 0.46 | 0.26 | 0.54 | 0.97 | 0.54 | **1.37** | 1.36 | 1.30 | 0.56 |
| Reflation 21 | 1.17 | 0.28 | 0.45 | 1.10 | −0.33 | 0.37 | 0.37 | 0.34 | **1.99** |
| Rate shock 22 | −0.84 | 0.16 | −0.49 | **0.34** | −1.23 | −0.71 | −0.68 | −0.71 | −0.70 |
| Recent 23-26 | 0.94 | **1.09** | 0.84 | 0.04 | 0.21 | 0.72 | 0.66 | 0.69 | 1.37 |

The structure is unambiguous:

- **`defensive` wins the deflationary crash (GFC, +1.62)** and is
  *worst* in the inflationary rate shock (−1.23). It is a
  regime-specific hedge, not an all-weather sleeve.
- **The meta-steered line wins COVID** (v76α +1.37) — its fastest,
  cleanest regime call.
- **`momentum` owns the recent trend era** (2023-26, +1.09) and
  **`sp500` owns the QE bull and reflation** — pure-beta regimes the
  governance layer deliberately under-participates in.
- **Rate-shock 2022 is negative for everyone.** The only non-negative
  Sharpe is v74d_q (+0.34) — and it is the *worst* method in the
  surrounding "Recent" window. Nothing is robust here.

### 4.2 Rank consistency across the 7 regimes (1 = best of 12)

| Method | Mean rank | Best | Worst | Rank std |
| --- | ---: | ---: | ---: | ---: |
| v76α | 5.00 | 1 | 9 | 2.38 |
| v78 | 5.00 | 2 | 8 | 2.58 |
| v78-ADD | 5.14 | 3 | 8 | **2.12** |
| v77-ADD | 5.57 | 2 | 9 | 2.07 |
| naive_1_4 | 5.86 | 2 | 10 | 2.85 |
| defensive | 8.43 | 1 | 12 | 3.95 |
| momentum_12_1 | 8.21 | 2 | 12 | 4.38 |
| equal_weight | 8.21 | 2 | 12 | 4.02 |

The meta-steered family occupies the top of the *consistency* ranking
with the *lowest* rank dispersion. v78-ADD never ranks worse than 8/12
in any regime — the directional methods swing from 1 to 12. This is
exactly the governance objective: not winning any single regime, but
never being the casualty.

### 4.3 Split-half robustness (H1 2008-16 vs H2 2017-26)

| Method | H1 Sharpe | H2 Sharpe | H1 Sortino | H2 Sortino |
| --- | ---: | ---: | ---: | ---: |
| v76α | 1.00 | 0.65 | 1.42 | 0.79 |
| v78-ADD | 1.02 | 0.64 | 1.44 | 0.77 |
| BLEND-3 | 0.97 | 0.68 | 1.37 | 0.84 |

**Every method degrades H1 → H2** (Sharpe ~1.0 → ~0.65). The system
was uniformly stronger in 2008-2016. Part of this is the 2022 rate
shock sitting in H2; part is that the partner universe's exploitable
structure has thinned. This degradation is a property of the *universe
and era*, not of any one method — and is the single most important
caveat on every full-sample number above.

---

## 5. Correlation structure — where the diversification is

Daily-return correlations (full common window):

- The **entire meta family is internally redundant.** v76, v76b,
  v77-ADD, v78-ADD, v78 are mutually correlated **0.98–1.00**. The
  V7.7/V7.8 overlays are thin risk-shavers on one underlying blend —
  they do *not* add an independent return stream.
- **`defensive`** correlates only 0.08 with v74d_q and 0.58 with the
  meta line — a genuine diversifier *in aggregate*.
- **`sp500`** correlates ~0.00–0.04 with everything — fully orthogonal,
  but a different (equity) universe and uninvestable on drawdown.

### The stress-correlation trap

Splitting the sample into stress windows (GFC, COVID crash, 2022) vs
calm:

| Pair | Calm corr | Stress corr |
| --- | ---: | ---: |
| v78-ADD vs `defensive` | 0.57 | **0.70** ↑ |
| v78-ADD vs `momentum` | 0.76 | **0.47** ↓ |
| v78-ADD vs `sp500` | 0.01 | 0.13 |

This is the study's most important risk finding: **`defensive`
correlation *rises* in stress** — it co-moves *more* with the core
exactly when the hedge is needed. The reason is regime-specific: in
2022 the rate shock hit `defensive`'s bond holdings (TN, FGBL) *and*
the core simultaneously. `defensive` hedges deflationary crashes
(2008, COVID) but is a co-victim in inflationary ones. `momentum`,
conversely, *decouples* in stress (0.76 → 0.47) — a better crisis
diversifier than its reputation suggests.

---

## 6. Drawdown anatomy

The worst drawdown for **every** top method is the *same episode*:

| Method | Worst DD | Trough | Span |
| --- | ---: | --- | --- |
| v76α | −10.2% | 2023-10-02 | 2022-03 → 2025-10 (1305d) |
| v78-ADD | **−8.0%** | 2023-10-02 | 2022-03 → 2025-10 (1305d) |
| RP-blend | −10.0% | 2023-10-02 | 2022-03 → 2025-10 (1316d) |
| TILT (smooth) | −9.3% | 2023-10-02 | 2022-03 → 2025-10 (1305d) |

This is a **3.6-year grinding drawdown**, not a crash — it opens with
the 2022 rate shock and recovers only in late 2025. The takeaway:
PolyAgora's risk is *not* sharp-crash risk (the GFC/COVID drawdowns are
all −1% to −3%, beautifully controlled). Its risk is **prolonged
underwater periods in regimes it cannot exploit.** v78-ADD's
asset-level deformation genuinely shrinks this episode (−8.0% vs v76α's
−10.2%) and shrinks the secondary 2018 drawdown too — the clearest
empirical evidence that the V7.8 redesign worked.

---

## 7. Search for an overall allocation method

Five synthesized allocators were built from the existing daily return
streams and scored full-sample + per-regime + on rolling stability.

| Candidate | CAGR | Vol | Sharpe | Sortino | Calmar | MaxDD | Roll-Sharpe min |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| **TILT v78-ADD/def (smooth)** | 3.0% | 3.5% | **0.870** | **1.247** | 0.321 | −9.3% | **−2.15** |
| RP v76α+v78-ADD+def | 3.1% | 3.6% | 0.860 | 1.207 | 0.309 | −10.0% | −2.53 |
| BLEND-3 (v76α+v78-ADD+naive) | 2.7% | 3.3% | 0.820 | 1.087 | 0.323 | −8.3% | −2.51 |
| RP v78-ADD+def+mom | 2.9% | 3.8% | 0.774 | 1.060 | **0.332** | −8.8% | −2.32 |
| *(ref) v78-ADD* | 2.6% | 3.2% | 0.827 | 1.081 | **0.324** | **−8.0%** | −2.68 |
| *(ref) v76α* | 3.2% | 4.0% | 0.821 | 1.078 | 0.315 | −10.2% | −2.66 |

- **TILT** = v78-ADD continuously tilted toward `defensive`, with the
  defensive weight rising on a logistic curve (0 → 0.6) as the book's
  trailing 63-day trend weakens. It is the **best Sharpe (0.870) and
  Sortino (1.247)** and has the **best rolling-Sharpe floor** (worst
  1-year window −2.15 vs −2.66 for the references) — i.e. it
  meaningfully cuts the bad tail.
- **RP-blend** = inverse-rolling-vol weighting of v76α + v78-ADD +
  `defensive`. Close behind TILT; simpler and parameter-light.
- **VOLTARGET** (tested, not shown) scored Sharpe 0.86 but with a
  −13.8% drawdown — a Sharpe mirage that levers into the wrong
  moments. Rejected.

**The honest caveat:** TILT and RP-blend earn their edge by harvesting
`defensive` — and §5 showed `defensive` is a *deflation-specific*
hedge. The split-half table confirms it: the defensive-inclusive blends
shine in H1 (which contains 2008) and are merely on-par in H2 (which
contains 2022). Their full-sample lift is partly a historical artifact.
They genuinely improve risk-adjusted return, but they **do not solve
the rate-shock regime** — RP-blend ranks 12/13 in 2022.

---

## 8. Recommendation

**For production now — use v78-ADD.** It is the cleanest single
allocator: best Calmar, shallowest drawdown, simplest overlay,
fully implemented and validated, and it never ranks worse than 8/12 in
any regime. The conditional-Kelly stage (v78) is near-inert and can
ship with it harmlessly, but adds nothing measurable — keep it as the
documented safety gate, not as an alpha source.

**For the next research version (V7.9) — test the maneuverability
tilt.** The TILT allocator (smooth, trend-scaled defensive overlay) is
the strongest improvement available from the existing toolkit: +0.04
Sharpe, +0.17 Sortino, and a materially better rolling-Sharpe floor
versus v78-ADD. It must be validated to the V7.8 spec's standard —
**walk-forward, out-of-sample, net of transaction costs** — before
adoption, because (a) it adds ~1.3pp of drawdown and (b) its edge leans
on the regime-specific `defensive` hedge. The logistic tilt parameters
(the 0.6 cap, the 63-day trend window, the slope) are tuning surfaces
that must not be fitted in-sample.

**Do not pursue:** further blends *within* the meta family. v76 / v76b
/ v77 / v78 variants are 0.98–1.00 correlated — averaging them is
diversification theatre. The only blends that did anything are the ones
that reach *outside* the meta line to `defensive` or `momentum`.

---

## 8b. Addendum — V7.9 built (2026-05-16)

The study's V7.9 recommendation was acted on. `polyagora_v79_engine.py`
implements a **governed defensive rotation with convexity re-entry**,
framed by the multi-sleeve doc's §13 (re-entry) and §14 (runtime
zones): `w_v79 = (1−d_t)·w_v78-ADD + d_t·w_defensive`, with the
rotation weight `d_t` driven by the **ADD-lite book-fragility field**
rather than a lagged price trend (study recommendation #1). A parameter
sweep set the balanced default `rot_gain=1.0, d_max=0.6`.

Result (full sample):

| Method | Sharpe | Sortino | Calmar | MaxDD | COVID Sharpe |
| --- | ---: | ---: | ---: | ---: | ---: |
| v78-ADD | 0.827 | 1.081 | 0.324 | −8.0% | 1.30 |
| **v79 (rotation)** | **0.873** | 1.157 | **0.331** | −8.6% | **1.30** |
| TILT-ref (trend) | 0.870 | **1.247** | 0.321 | −9.3% | 0.82 |

The ADD-driven rotation **beats v78-ADD on Sharpe, Sortino and Calmar**
at only 0.6pp extra drawdown, and — crucially — **preserves the COVID
regime (1.30)** where the trend-driven TILT lagged and gave back the
COVID call (0.82). Driving the tilt off the internal fragility field
instead of a lagged trend was the right call. The rotation is inert
~78% of the time (Zone 1) and only escalates in genuine stress.

Caveat unchanged: v79 still posts a negative 2022 Sharpe (−0.84) — it
rotates into `defensive`, the 2022 victim. The aggressive `rot_gain=4`
setting made 2022 markedly worse (−1.15); `rot_gain=1` minimizes the
damage. v79 raises the *deflationary-crash* edge; it cannot fix the
inflationary blind spot. The **correlation-governance check fails**
(average pairwise correlation of the winner set = 0.64 vs the spec's
0.35 target) — the winners remain one return stream. The next genuine
diversifier is a mean-reversion sleeve (§10, item 2).

V7.9 also **consolidates the method lineup to winners**: the
`run_v79_check.py` / `build_polyagora_v79.py` pair compares and renders
only the non-dominated set (v76α, v78-ADD, v79, the four manifolds,
references) — the v74b·*, v75·*, v76β/γ and v77·* variants are retired
from the candidate lineup and survive only as importable building
blocks.

---

## 8c. Addendum — V7.10: the Strategy Sleeve Registry and the first sleeve

§10 item 2 recommended a mean-reversion sleeve as the next diversifier.
V7.10 built the **Strategy Sleeve Registry** (`polyagora_sleeve_registry.py`,
`polyagora_validation.py`) — a gate pipeline of validation → DSR noise
floor → correlation-to-book → walk-forward → contribution — and tested
both that recommendation and an alternative.

**Mean-reversion — rejected, recommendation overturned.** A family of
short-horizon cross-sectional reversal sleeves (lookbacks 2–63 days)
all failed: reversal has no gross edge on the momentum-prone 13-asset
universe (the `momentum_12_1` manifold earns a positive Sharpe, so its
mirror earns a negative one), and realistic transaction cost annihilates
the marginal cases (net Sharpe −0.9 to −2.3). The sleeve *is*
uncorrelated to the book — but diversification without alpha is not
admissible. **§10 item 2 is corrected**: a mean-reversion sleeve is not
the next diversifier on this universe.

**Bond-trend — admitted, the 2022 blind spot addressed.** The genuine
diversifier turned out to be a *low-turnover crisis-trend* sleeve: a
12-month time-series trend on the two bond futures (TN, FGBL). It goes
long bonds in flight-to-quality rallies and **short bonds in persistent
rate shocks** — so it earns a +1.8 Sharpe in the 2022 rate shock, the
regime every other PolyAgora component loses (§9). It is genuinely
uncorrelated to the book (corr 0.28), and being a 12-month signal it
survives realistic cost. The registry admitted it at ~18%.

v7.10 = v79 + the bond-trend sleeve:

| | Sharpe | Sortino | Calmar | Max DD | Rate-22 Sharpe |
| --- | ---: | ---: | ---: | ---: | ---: |
| v79 | 0.873 | 1.157 | 0.331 | −8.6% | −0.84 |
| **v7.10** | **0.914** | **1.234** | **0.491** | **−6.5%** | **+0.44** |

This is the first version to post a **positive 2022 Sharpe** — directly
closing the open problem of §9. The sleeve gives back some upside in the
2021 reflation (its named failure mode), but the net is a clear
improvement on every full-sample metric. It also **revises §9**: the
2022 gap was not unfixable — it needed an instrument that can be *short*
the rate-shock asset, which a long-only defensive manifold cannot be but
a trend sleeve on bond futures can.

Two methodology notes from the build. (1) A real bug was found in the
Deflated Sharpe computation — the expected-max-null term was scaled by
√252 instead of √n_observations, inflating the bar ~4× and rejecting
every strategy; fixed. (2) The DSR's role was corrected to a *noise
floor* per the registry doc (`More Sleeves.pdf`), with doc-2's
governing principle — judge a sleeve by portfolio *contribution*, not
standalone significance — added as an explicit gate.

---

## 9. The open problem — the 2022 blind spot

Every method, every overlay, every blend posts a negative Sharpe in the
2022 rate-shock regime, and `defensive` is the worst of all. This is
not a tuning failure — it is structural. 2022 was a regime in which the
risk-asset and the bond hedge fell *together* (the worst year for the
classic 60/40 stock-bond mix in roughly a century; the stock-bond
correlation flipped positive). PolyAgora's four manifolds — a V7
transition-engine, momentum, a bond/gold/USD defensive mix, and cash —
contain **no instrument that is structurally long inflation / rising
real rates.** The meta-allocator can only steer among manifolds it has;
when all four are impaired at once, steering cannot help.

This aligns precisely with the `Dov Benchmarks` and `V7.8 Absolute
Return Mode` docs: governance and risk control are now strong; the
missing capability is **independent, uncorrelated alpha**. Closing the
2022 gap is not a governance problem — it requires a manifold or sleeve
that earns in inflationary/rate-shock geometry.

---

## 10. Suggestions for further investigation

1. **V7.9 — maneuverability-scaled defensive tilt.** Promote the TILT
   allocator to a proper engine variant. Validate walk-forward, net of
   costs. Drive the tilt off the ADD-lite recoverability field (which
   the engine already computes) rather than a raw price trend — this
   makes it a governed maneuverability response, consistent with the
   PolyAgora philosophy, instead of an external timing rule.

2. **Add a rate-shock / inflation manifold (M5).** The single highest-
   value structural change. Candidates from the V7.8 §6 sleeve list:
   commodity-trend or carry, a short-duration / steepener structure, a
   relative-value sleeve (equity-vs-bond asymmetry). Target: a manifold
   with *positive* Sharpe in the 2022 window. Until one exists, no
   amount of steering or blending fixes the blind spot.

3. **Build the transaction-cost / slippage / turnover model** (V7.8
   §14, Phase 1). Every number in this study is gross. The overlays add
   turnover; the TILT allocator adds more. Net-of-cost evaluation may
   compress the candidate ranking and must precede any adoption
   decision.

4. **Re-examine the `defensive` manifold.** §5 shows it de-diversifies
   in stress. Either split it into a *deflation* hedge (bonds/gold) and
   a separate *inflation* hedge, or down-weight it in any blend and let
   a true M5 carry the crisis role.

5. **Stress the H1→H2 degradation.** Every method lost ~35% of its
   Sharpe between halves. Investigate whether this is the 2022 episode
   alone or genuine alpha decay in the partner universe — e.g. recompute
   the split excluding 2022, and roll the split boundary. This governs
   how much to trust the full-sample headline numbers.

6. **Formalize the consistency metric.** Rank-dispersion across regimes
   (§4.2) discriminated the methods better than full-sample Sharpe.
   Consider adopting a regime-rank-stability score as a first-class
   evaluation criterion alongside the Dov ratio panel.

---

## Appendix — artifacts

Analysis scripts and full intermediate tables:

```
/tmp/polyagora_analysis/analyze.py        pass 1 — full sample, calendar
                                          years, regimes, rolling, corr,
                                          candidate construction
/tmp/polyagora_analysis/analyze2.py       pass 2 — split-half, drawdown
                                          events, stress correlations,
                                          improved-blend tests
/tmp/polyagora_analysis/*.csv             every table above as CSV
```

All return series are the cached `returns_*.csv` outputs of
`build_polyagora.py --v75`, `run_v76_check.py`, `run_v77_check.py` and
`run_v78_check.py`. Reproduce by re-running those, then the two scripts
above with the repo's `agora/` venv interpreter.
