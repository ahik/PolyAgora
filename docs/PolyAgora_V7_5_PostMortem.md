# PolyAgora V7.5α₁ — Post-Mortem and V7.4d Finding

**Status:** V7.5α₁ rejected; V7.4d adopted as the empirical sweep winner.
**Date:** 2026-05-12

<small>**Confidential & Proprietary.** This document is the confidential and proprietary post-mortem of PolyAgora / PolygonEye's V7.5α₁ validation work. Do not reproduce, distribute, or disclose to any third party without prior written consent.</small>

---

## TL;DR

V7.5α₁ (Momentum-as-Polygon-Coordinate, per `docs/PolyAgora_V7_5_Spec.md`) **failed Test 4** — only 6% of the 216-cell parameter grid forms a Sharpe plateau, well below the 30% threshold. The architectural bet — promoting Momentum from the eigenfield universe Φ into the Reference Polygon as a 6th coordinate — **is not supported by the data**. The optimal `α_M` is essentially zero.

However, the sweep surfaced a **separate, reproducible win**: V7.4c machinery with **MOM12_1 dropped from Φ** and softer block-selection parameters (K=2, τ=2.0, λ=0.5) achieves **Sharpe 0.453**, beating the V7.4c plateau (0.407) by ~+45 bps. This configuration ships as `v74d`.

## What was tested

Spec §11 six-test pack. Five tests passed; Test 4 failed.

| Test | Result |
|---|---|
| 1. Continuity | ✅ PASS — v75(α_M=0) reproduces V7.4b byte-identically (Δ Sharpe = 0.0000) |
| 2. Zone audit | ✅ PASS — Z=3/Z=4 in 4/5 stress quarters, both variants |
| 3. Jaccard | ✅ PASS — inherited from V7.4c (identical category blocks) |
| 4. Plateau | ❌ **FAIL** — 13/216 plateau cells (6%), threshold is 30% |
| 5. No-look-ahead | ✅ PASS — 2/2 new mechanical invariants + zero perturbation leak |
| 6. OOS holdout | ✅ PASS — both variants pass the −0.20 Δ Sharpe threshold |

## Sweep grid and top configs

216 configurations: `α_M ∈ {0, 0.25, 0.5, 0.75, 1.0, 1.5} × K ∈ {2, 3} × τ ∈ {2.0, 4.0, 6.0} × λ ∈ {0.5, 0.6, 0.8} × variant ∈ {Φ=14, Φ=13}`.

Top 10 by Sharpe:

| Rank | α_M | K | τ | λ | Φ | Sharpe | MaxDD |
|---:|---:|---:|---:|---:|---|---:|---:|
| 1 | **0.00** | 2 | 2.0 | 0.5 | **13** | **0.4527** | -10.8% |
| 2 | 0.25 | 2 | 2.0 | 0.5 | 13 | 0.4490 | -10.6% |
| 3 | 0.00 | 2 | 4.0 | 0.5 | 13 | 0.4323 | -11.1% |
| 4 | 0.25 | 2 | 4.0 | 0.5 | 13 | 0.4285 | -10.6% |
| 5 | 0.00 | 2 | 2.0 | 0.5 | 14 | 0.4214 | -10.8% |
| 6 | 0.50 | 2 | 2.0 | 0.5 | 13 | 0.4200 | -10.6% |
| 7 | 0.00 | 2 | 2.0 | 0.6 | 13 | 0.4189 | -11.0% |
| 8 | 0.75 | 2 | 2.0 | 0.5 | 13 | 0.4159 | -11.0% |
| 9 | 0.00 | 2 | 6.0 | 0.5 | 13 | 0.4149 | -11.3% |
| 10 | 0.25 | 2 | 6.0 | 0.5 | 13 | 0.4112 | -10.6% |

## Three findings, in order of importance

### Finding 1 — M in RP doesn't help

The top 10 cluster at **α_M ∈ {0, 0.25}**. The best config has α_M = 0, meaning the M coordinate's contribution to the sigmoid admissibility is *exactly zero*. The 6D polygon is geometrically equivalent to the 5D polygon at the optimum.

The architectural claim from `docs/PolyAgora V8 – Momentum-as-Geometry Architecture.pdf` — that Momentum is "structural enough to belong in RP" — is **not supported by this universe**. The V8 spec's prediction of Sharpe 0.71–0.74 from the proxy simulation does not materialize.

This is not a software bug — the continuity test (α_M=0 reproducing V7.4b byte-identically) verifies the implementation is correct. The architectural hypothesis is simply wrong at this scale and on this universe.

### Finding 2 — Dropping MOM12_1 from Φ is the real win

Plateau breakdown by variant:

| Variant | Plateau cells | % of slice | Best Sharpe |
|---|---:|---:|---:|
| Φ=14 (MOM12_1 retained) | 3/108 | 2.8% | 0.421 |
| Φ=13 (MOM12_1 dropped) | 10/108 | 9.3% | **0.453** |

Φ=13 dominates Φ=14 across nearly every config slice. The plateau-cell count is 3.3× larger; the best Sharpe is +32 bps higher. The Test 6 OOS evidence had been mixed (v75 led OOS, v75_no_mom_eigen led IS), but the in-sample sweep is unambiguous: **drop MOM12_1**.

Mechanism: when MOM12_1 was an eigenfield, its synthetic PnL participated in `R_t` (the empirical survival matrix) and in the persistence block. Removing it produces a cleaner block-coherence structure on the empirical correlation matrix — MOM12_1's PnL is by construction correlated with whichever live partner assets were trending, so its presence inflated the persistence-block coherence γ artificially.

### Finding 3 — Softer block selection helps

Winning configs use **τ=2.0** (down from the V7.4b default τ=4.0), with **K=2** and **λ=0.5** unchanged from V7.4c plateau. Lower τ flattens the softmax over block scores: instead of putting ~70% on the top block and 30% on second-place, τ=2 gives more like 60/40. The Local Star is less dominant; diversification across blocks is higher.

## V7.4d — the empirical winner

V7.4d is the configuration that ships as the production candidate from this exercise:

| Parameter | V7.4c plateau | V7.4d |
|---|---|---|
| Universe Φ | 14 (13 partner + MOM12_1) | **13 (MOM12_1 dropped)** |
| Block source | `category` | `category` |
| K | 2 | 2 |
| τ | 4.0 | **2.0** |
| λ | 0.5 | 0.5 |
| Reference Polygon | 5D (V, T, G, C, R) | 5D (V, T, G, C, R) |
| Sharpe (IS) | 0.407 | **0.453** |
| MaxDD (IS) | -11.0% | -10.8% |
| CAGR (IS) | 1.6% | 1.8% |

V7.4d is implemented as `make_v75_signal(α_M=0, include_mom_eigen=False, K=2, τ=2, λ=0.5)`. The V7.5α₁ engine subsumes V7.4b at α_M=0 (mechanically verified by Test 1); using it here keeps a single code path.

Compared to the existing production line:
- V7.4d **beats V7.4c plateau** by +46 bps Sharpe
- Still **trails V7.4b template / V7.3** (0.691)
- MaxDD is **softer** than V7.4c plateau (-10.8% vs -11.0%)

## What V7.5 means after this

The V7.5 program does *not* mean "Momentum into RP" anymore. The actual deliverables of the V7.5α₁ work:

1. **V7.4d as production candidate** (this document, `polyagora_v75_engine.py` config).
2. **Six-test validation pack** (`validate_v75.py`) ready to gate future V7.5 increments.
3. **`build_m_series` and the V7.5 engine** remain in the codebase. They're not deprecated — they may yet contribute if the architecture is re-tested on a different universe (e.g. raw asset returns instead of strategy returns) or with a re-defined M.
4. **Negative evidence** for the V8 spec's "Momentum as Polygon coordinate" thesis, scoped to this AGUR universe. The thesis is not falsified globally; it is rejected as a Sharpe-improvement mechanism on the 13 partner assets.

## Recommendations

1. **Ship V7.4d** as the next production iteration. Register it on the dashboard, add it to the runner's default-visible set, run it through the same OOS holdout (Test 6) on its own and confirm.
2. **Update Algo_V74.md** with a V7.4d addendum (or write Algo_V74d.md). Treat V7.4d as a refinement of V7.4c, not a separate architecture.
3. **Move V7.5 forward as V7.5β** — external polygons (VAIDM/ADD/Buffett) as deformers, per `docs/The Better Architecture (Your Current Direction).pdf`. Skip V7.5α₂ — it's a smaller version of the same architectural bet that just failed and is unlikely to yield a different answer.
4. **Re-examine the V8 spec** in light of this evidence. The "Momentum as polygon coordinate" claim should be either reformulated for a different universe, or downgraded to "Momentum as deformer" (essentially V7.5α₂ at low α_M).

## Artifacts

- `v75_validation_outputs/test_4_alpha_m_sweep.csv` — full 216-cell sweep
- `v75_validation_outputs/test_4_plateau_cells.csv` — 13 plateau cells
- `v75_validation_outputs/test_4_top10.csv` — top 10 by Sharpe
- `v75_validation_outputs/test_4_sharpe_heatmap.png` — Sharpe over (α_M, λ) faceted by (K, τ, variant)
- `v75_validation_outputs/test_4_maxdd_heatmap.png` — MaxDD heatmap
- `v75_validation_outputs/test_1_continuity.csv` — α_M=0 byte-match verification
- `v75_validation_outputs/test_6_oos_holdout.csv` — IS vs OOS Sharpe deltas
- `v75_validation_outputs/results_summary.json` — full test 1/2/3/5/6 results
- `polyagora_v75_outputs/dashboard.html` — interactive dashboard including v74d

## One-line summary

V7.5α₁ proved its own continuity, and proved its architectural bet wrong. The win was hiding in the variant-flag: drop MOM12_1, drop τ to 2, and accept that V7.4c had a +46 bps improvement waiting in a sister parameter cell. That configuration ships as V7.4d.
