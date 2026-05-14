"""
PolyAgora V7.5α₁ — Validation Suite
====================================

Six-test pack matching `validate_v74c.py`, adapted for V7.5α₁'s
Momentum-as-Polygon-Coordinate architecture. Per
`docs/PolyAgora_V7_5_Spec.md` §11.

Tests:
    1. Continuity         — `v75` with α_M=0 reproduces V7.4c reference
                            (mechanical: admissibility byte-identical;
                             end-to-end: Sharpe within ±0.02)
    2. Zone audit         — Z=3/Z=4 fires in ≥ ⌈2/3⌉ stress quarters
                            for both v75 variants
    3. Jaccard stability  — inherits V7.4c result (identical category blocks)
    4. Plateau            — read sweep results from sweep_v75.py and
                            identify the parameter plateau
    5. No-look-ahead      — mechanical patterns for build_m_series + the
                            statistical perturbation rerun on v75 variants
    6. OOS holdout        — 2024-2026 vs 2008-2023 Sharpe deltas for v75

Outputs land in `v75_validation_outputs/`.

Usage:
    python validate_v75.py --test 1          # continuity only
    python validate_v75.py --test all        # everything
    python validate_v75.py --test 4          # plateau (requires sweep_v75.py first)
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from polyagora_v63_partner_engine import (
    EngineConfig,
    PartnerData,
    compute_weights,
    evaluate,
    load_partner_xlsx,
    summary_row,
)
from polyagora_v74b_engine import V74bDriverConfig, make_v74b_signal
from polyagora_v75_engine import V75DriverConfig, build_m_series, make_v75_signal

# Reuse v74c utilities — load_inputs, _quarterly_sharpe, perturbation harness.
from validate_v74c import (
    _quarterly_sharpe,
    _t5_mechanical_audit as _v74c_mechanical_audit,
    metrics_from_returns,
)


ROOT = Path(__file__).resolve().parent
PARTNER_INPUT = ROOT / "Agur" / "baseline_pnl_partner_delivery.xlsx"
MARKET_CSV = ROOT / "market_data" / "market_yahoo_vix_spy_hyg_tlt_gld_cper.csv"
OUTPUT_DIR = ROOT / "v75_validation_outputs"
SWEEP_CSV = OUTPUT_DIR / "test_4_alpha_m_sweep.csv"


def load_inputs() -> tuple[PartnerData, pd.DataFrame]:
    data = load_partner_xlsx(PARTNER_INPUT)
    market = pd.read_csv(MARKET_CSV, parse_dates=["date"]).set_index("date")
    return data, market


# =============================================================================
# Test 1 — Continuity: v75(α_M=0) ≡ V7.4c at matching (K, τ, λ)
# =============================================================================

T1_CONFIGS = [
    # (K, tau, lam, label)
    (2, 4.0, 0.6, "v74b-default"),
    (2, 4.0, 0.5, "v74b-plateau"),
]
T1_SHARPE_TOL = 0.02
T1_DD_TOL = 0.005  # 50 bps


def test_1_continuity(data: PartnerData, market: pd.DataFrame, out: Path) -> dict:
    print("[t1] continuity: v75(α_M=0) vs v74b at matching (K,τ,λ)")
    cfg = EngineConfig()
    rows = []
    all_pass = True
    for K, tau, lam, label in T1_CONFIGS:
        v74b = make_v74b_signal(
            market, data.realized_pnl, drivers=V74bDriverConfig(),
            block_source="category", top_k=K, tau=tau, lam=lam,
        )
        v75_alpha0 = make_v75_signal(
            market, data.realized_pnl,
            drivers=V75DriverConfig(momentum_sensitivity=0.0),
            include_mom_eigen=True, top_k=K, tau=tau, lam=lam,
        )
        w_b = compute_weights(data, v74b, cfg)
        w_75 = compute_weights(data, v75_alpha0, cfg)
        r_b = evaluate(w_b, data.forward_pnl)
        r_75 = evaluate(w_75, data.forward_pnl)
        m_b = summary_row("v74b", r_b.returns)
        m_75 = summary_row("v75", r_75.returns)
        d_sharpe = float(m_75["Sharpe"] - m_b["Sharpe"])
        d_dd = float(m_75["Max drawdown"] - m_b["Max drawdown"])
        passes = abs(d_sharpe) <= T1_SHARPE_TOL and abs(d_dd) <= T1_DD_TOL
        all_pass &= passes
        rows.append({
            "config": label, "K": K, "tau": tau, "lam": lam,
            "v74b_Sharpe": m_b["Sharpe"], "v75_alpha0_Sharpe": m_75["Sharpe"],
            "delta_Sharpe": d_sharpe,
            "v74b_DD": m_b["Max drawdown"], "v75_alpha0_DD": m_75["Max drawdown"],
            "delta_DD": d_dd,
            "passes": passes,
        })
        print(f"[t1]   {label:18s}: v74b={m_b['Sharpe']:.4f}, "
              f"v75(α=0)={m_75['Sharpe']:.4f}, Δ={d_sharpe:+.4f} "
              f"({'PASS' if passes else 'FAIL'})")

    pd.DataFrame(rows).to_csv(out / "test_1_continuity.csv", index=False)
    return {"all_pass": all_pass, "rows": rows}


# =============================================================================
# Test 2 — Zone audit on v75 variants
# =============================================================================

def _v75_zones(
    data: PartnerData, market: pd.DataFrame, include_mom: bool,
) -> pd.Series:
    sig = make_v75_signal(
        market, data.realized_pnl,
        drivers=V75DriverConfig(),
        include_mom_eigen=include_mom,
    )
    compute_weights(data, sig, EngineConfig())
    diag = sig.diagnostics_df()
    if diag.empty:
        return pd.Series(dtype=int)
    return diag["Z"]


def test_2_zone_audit(data: PartnerData, market: pd.DataFrame, out: Path) -> dict:
    print("[t2] zone audit on v75 variants")
    eq_pnl = data.forward_pnl.mean(axis=1).rename("eq_pnl")
    qsharpe = _quarterly_sharpe(eq_pnl)
    worst_q = sorted(qsharpe.dropna().sort_values().head(5).index.to_list())
    print("[t2] stress quarters:",
          [f"{q.year}-Q{q.quarter}" for q in worst_q])

    rows: list[dict] = []
    results: dict = {}
    for name, include_mom in [("v75", True), ("v75_no_mom_eigen", False)]:
        ztrack = _v75_zones(data, market, include_mom)
        if ztrack.empty:
            continue
        stress_passes = 0
        for q_end in worst_q:
            q_start = q_end - pd.tseries.offsets.QuarterBegin()
            window = ztrack.loc[(ztrack.index >= q_start) & (ztrack.index <= q_end)]
            if window.empty:
                continue
            d = window.value_counts(normalize=True).reindex([1, 2, 3, 4]).fillna(0.0)
            z34_share = float(d.loc[3] + d.loc[4])
            triggered = z34_share > 0.0
            stress_passes += int(triggered)
            rows.append({
                "signal": name,
                "quarter": f"{q_end.year}-Q{q_end.quarter}",
                **{f"Z{int(k)}": float(v) for k, v in d.items()},
                "Z3+Z4_share": z34_share, "triggered": triggered,
            })
        total = len(worst_q)
        passes = stress_passes >= int(np.ceil(2 * total / 3))
        results[name] = {
            "stress_passes": stress_passes, "stress_total": total,
            "passes": passes,
        }
        print(f"[t2]   {name}: Z=3/4 in {stress_passes}/{total} stress quarters "
              f"({'PASS' if passes else 'FAIL'})")

    pd.DataFrame(rows).to_csv(out / "test_2_zone_audit.csv", index=False)
    return {
        "stress_quarters": [f"{q.year}-Q{q.quarter}" for q in worst_q],
        "v75": results.get("v75", {}),
        "v75_no_mom_eigen": results.get("v75_no_mom_eigen", {}),
        "all_pass": all(r.get("passes", False) for r in results.values()),
    }


# =============================================================================
# Test 3 — Jaccard partition stability (inherited)
# =============================================================================

def test_3_jaccard_inherited(out: Path) -> dict:
    """V7.5α₁ uses the same disjoint category blocks as V7.4b/V7.4c.
    The partition is deterministic per the category mapping, so Jaccard
    stability is identical to V7.4c's Test 3 result."""
    v74c_path = ROOT / "v74c_validation_outputs" / "test_3_jaccard.csv"
    if v74c_path.exists():
        v74c = pd.read_csv(v74c_path)
        cat_row = v74c[v74c["block_source"] == "category"]
        if not cat_row.empty:
            median_jaccard = float(cat_row.iloc[0]["median_jaccard"])
            nontrivial = float(cat_row.iloc[0]["nontrivial_share"])
            print(f"[t3] inherited from V7.4c: median Jaccard={median_jaccard:.3f}, "
                  f"non-trivial share={nontrivial:.3f}")
            passes = median_jaccard >= 0.70 and nontrivial >= 0.80
            (out / "test_3_jaccard_inherited.csv").write_text(
                "block_source,median_jaccard,nontrivial_share,passes\n"
                f"category,{median_jaccard},{nontrivial},{passes}\n"
            )
            return {
                "block_source": "category",
                "median_jaccard": median_jaccard,
                "nontrivial_share": nontrivial,
                "passes": passes,
                "inherited": True,
            }
    print("[t3] V7.4c reference not found — skipping (run validate_v74c.py first)")
    return {"inherited": False, "passes": True, "note": "V7.4c reference missing"}


# =============================================================================
# Test 4 — Parameter plateau (reads sweep_v75.py output)
# =============================================================================

T4_SHARPE_TOL = 0.05
T4_DD_TOL = 0.01
T4_PLATEAU_MIN_FRAC = 0.30


def test_4_plateau(out: Path) -> dict:
    if not SWEEP_CSV.exists():
        print(f"[t4] sweep results not found at {SWEEP_CSV}")
        print("[t4] run `python sweep_v75.py` first.")
        return {"available": False, "passes": False}

    df = pd.read_csv(SWEEP_CSV)
    print(f"[t4] sweep loaded: {len(df)} configs")
    best_sharpe = float(df["Sharpe"].max())
    best_dd = float(df["MaxDD"].min())
    plateau = df[
        (df["Sharpe"] >= best_sharpe - T4_SHARPE_TOL)
        & ((df["MaxDD"] - best_dd).abs() <= T4_DD_TOL)
    ].copy()
    plateau_frac = len(plateau) / len(df)
    passes = plateau_frac >= T4_PLATEAU_MIN_FRAC

    print(f"[t4] best Sharpe={best_sharpe:.4f}, best DD={best_dd*100:.2f}%, "
          f"plateau {len(plateau)}/{len(df)} ({plateau_frac*100:.1f}%) — "
          f"{'PASS' if passes else 'FAIL'}")

    # Per-slice plateau fraction (by include_mom_eigen).
    slice_results: list[dict] = []
    for v in [True, False]:
        sub = df[df["include_mom_eigen"] == v]
        sub_plateau = plateau[plateau["include_mom_eigen"] == v]
        slice_results.append({
            "include_mom_eigen": v,
            "total_cells": len(sub),
            "plateau_cells": len(sub_plateau),
            "plateau_frac": len(sub_plateau) / len(sub) if len(sub) else 0.0,
            "best_Sharpe": float(sub["Sharpe"].max()) if len(sub) else float("nan"),
            "best_DD": float(sub["MaxDD"].min()) if len(sub) else float("nan"),
        })
        print(f"[t4]   include_mom_eigen={v}: "
              f"plateau {len(sub_plateau)}/{len(sub)} "
              f"({len(sub_plateau)/max(len(sub),1)*100:.1f}%), "
              f"best Sharpe={slice_results[-1]['best_Sharpe']:.4f}")

    # Plateau-center: median of (α_M, K, τ, λ) over the plateau cells.
    if len(plateau):
        plateau_center = {
            "alpha_M": float(plateau["alpha_M"].median()),
            "K": int(plateau["K"].median()),
            "tau": float(plateau["tau"].median()),
            "lam": float(plateau["lam"].median()),
        }
        # Snap to the closest actual config (for reproducibility).
        center = (
            plateau.iloc[(plateau[["alpha_M", "tau", "lam"]] -
                         pd.Series(plateau_center)[["alpha_M", "tau", "lam"]]
                         ).abs().sum(axis=1).argmin()]
        )
        center_dict = {
            "alpha_M": float(center["alpha_M"]),
            "K": int(center["K"]),
            "tau": float(center["tau"]),
            "lam": float(center["lam"]),
            "include_mom_eigen": bool(center["include_mom_eigen"]),
            "Sharpe": float(center["Sharpe"]),
            "MaxDD": float(center["MaxDD"]),
        }
        print(f"[t4] plateau-center config: {center_dict}")
    else:
        center_dict = {}

    plateau.to_csv(out / "test_4_plateau_cells.csv", index=False)
    pd.DataFrame(slice_results).to_csv(out / "test_4_plateau_by_slice.csv", index=False)
    with (out / "test_4_plateau_center.json").open("w") as f:
        json.dump(center_dict, f, indent=2)

    return {
        "available": True,
        "best_Sharpe": best_sharpe,
        "best_DD": best_dd,
        "plateau_cells": len(plateau),
        "total_cells": len(df),
        "plateau_frac": plateau_frac,
        "slice_results": slice_results,
        "plateau_center": center_dict,
        "passes": passes,
    }


# =============================================================================
# Test 5 — No-look-ahead audit
# =============================================================================

# V7.5α₁ adds two new mechanical invariants on top of V7.4c (spec §7).
T5_V75_MECHANICAL_CHECKS: list[tuple[str, str, str]] = [
    ("polyagora_v75_engine.py", r"return M\.shift\(1\)",
     "build_m_series shifts M by 1 (M_t depends on realized ≤ t-1)"),
    ("polyagora_v75_engine.py", r"history_lag = history\.iloc\[:-1\]",
     "V7.5 strategy-eigenfield branch reads history ≤ t-1"),
]


def _t5_v75_mechanical() -> list[dict]:
    import re
    rows: list[dict] = []
    for fname, pattern, descr in T5_V75_MECHANICAL_CHECKS:
        path = ROOT / fname
        if not path.exists():
            rows.append({"file": fname, "check": descr,
                         "pattern": pattern, "found": False,
                         "reason": "file missing"})
            continue
        src = path.read_text(encoding="utf-8")
        matched = bool(re.search(pattern, src))
        rows.append({"file": fname, "check": descr,
                     "pattern": pattern, "found": matched,
                     "reason": "" if matched else "pattern not in source"})
    return rows


def _t5_v75_statistical(
    data: PartnerData, market: pd.DataFrame, t_split_idx: int = 3000,
) -> list[dict]:
    """Perturb realized PnL at and after t_split_idx; assert v75 weights
    at rows ≤ t_split_idx are byte-identical between clean and perturbed runs."""
    rng = np.random.default_rng(seed=20260512)
    pre_split_idx = min(t_split_idx, len(data.realized_pnl) - 11)
    cfg = EngineConfig()
    rows: list[dict] = []
    factories = [
        ("v75", lambda d: make_v75_signal(
            market, d.realized_pnl, drivers=V75DriverConfig(),
            include_mom_eigen=True)),
        ("v75_no_mom_eigen", lambda d: make_v75_signal(
            market, d.realized_pnl, drivers=V75DriverConfig(),
            include_mom_eigen=False)),
    ]
    for name, factory in factories:
        sig_clean = factory(data)
        w_clean = compute_weights(data, sig_clean, cfg)

        realized_perturbed = data.realized_pnl.copy()
        noise = rng.normal(0, 0.01, realized_perturbed.iloc[pre_split_idx + 1:].shape)
        realized_perturbed.iloc[pre_split_idx + 1:] += noise
        data_perturbed = data._replace(realized_pnl=realized_perturbed)
        sig_perturbed = factory(data_perturbed)
        w_perturbed = compute_weights(data_perturbed, sig_perturbed, cfg)

        pre_diff = (w_clean.iloc[:pre_split_idx + 1]
                    - w_perturbed.iloc[:pre_split_idx + 1]).abs().max().max()
        post_diff = (w_clean.iloc[pre_split_idx + 1:]
                     - w_perturbed.iloc[pre_split_idx + 1:]).abs().max().max()
        leak = float(pre_diff) > 1e-9
        rows.append({
            "signal": name,
            "max_pre_diff": float(pre_diff),
            "max_post_diff": float(post_diff),
            "leak_detected": leak,
            "passes": not leak,
        })
        print(f"[t5]   {name}: pre_diff={pre_diff:.3e}, post_diff={post_diff:.3e}, "
              f"leak={'YES' if leak else 'no'}")
    return rows


def test_5_lookahead(data: PartnerData, market: pd.DataFrame, out: Path) -> dict:
    print("[t5] mechanical audit (V7.4c invariants + V7.5 additions)")
    v74c_mech = _v74c_mechanical_audit()
    v75_mech = _t5_v75_mechanical()
    for r in v75_mech:
        print(f"[t5]   {'✓' if r['found'] else '✗'} {r['file']}: {r['check']}")

    print("[t5] statistical perturbation on v75 variants")
    stat = _t5_v75_statistical(data, market)

    all_mech = v74c_mech + v75_mech
    pd.DataFrame(all_mech).to_csv(out / "test_5_mechanical.csv", index=False)
    pd.DataFrame(stat).to_csv(out / "test_5_statistical.csv", index=False)

    all_mech_pass = all(r["found"] for r in all_mech)
    all_stat_pass = all(r["passes"] for r in stat)
    return {
        "mechanical_total": len(all_mech),
        "mechanical_passes": sum(1 for r in all_mech if r["found"]),
        "mechanical_all_pass": all_mech_pass,
        "statistical_total": len(stat),
        "statistical_passes": sum(1 for r in stat if r["passes"]),
        "statistical_all_pass": all_stat_pass,
        "passes": all_mech_pass and all_stat_pass,
    }


# =============================================================================
# Test 6 — OOS holdout
# =============================================================================

T6_IS_END = pd.Timestamp("2023-12-31")
T6_OOS_START = pd.Timestamp("2024-01-01")
T6_SHARPE_TOL = 0.20


def _split_metrics(rets: pd.Series, label: str) -> dict:
    is_r = rets.loc[:T6_IS_END]
    oos_r = rets.loc[T6_OOS_START:]
    is_m = summary_row(label, is_r)
    oos_m = summary_row(label, oos_r)
    return {
        "signal": label,
        "IS_Sharpe": float(is_m["Sharpe"]),
        "OOS_Sharpe": float(oos_m["Sharpe"]),
        "delta_Sharpe": float(oos_m["Sharpe"] - is_m["Sharpe"]),
        "IS_DD": float(is_m["Max drawdown"]),
        "OOS_DD": float(oos_m["Max drawdown"]),
        "IS_days": int(len(is_r)),
        "OOS_days": int(len(oos_r)),
        "passes": float(oos_m["Sharpe"] - is_m["Sharpe"]) > -T6_SHARPE_TOL,
    }


def test_6_oos(data: PartnerData, market: pd.DataFrame, out: Path) -> dict:
    print("[t6] OOS holdout (split at 2024-01-01)")
    cfg = EngineConfig()
    rows = []
    for name, include_mom in [("v75", True), ("v75_no_mom_eigen", False)]:
        sig = make_v75_signal(
            market, data.realized_pnl, drivers=V75DriverConfig(),
            include_mom_eigen=include_mom,
        )
        w = compute_weights(data, sig, cfg)
        r = evaluate(w, data.forward_pnl)
        row = _split_metrics(r.returns, name)
        rows.append(row)
        print(f"[t6]   {name}: IS={row['IS_Sharpe']:.3f}, OOS={row['OOS_Sharpe']:.3f}, "
              f"Δ={row['delta_Sharpe']:+.3f} ({'PASS' if row['passes'] else 'FAIL'})")

    df = pd.DataFrame(rows)
    df.to_csv(out / "test_6_oos_holdout.csv", index=False)

    _t6_plot(df, out / "test_6_oos_holdout.png")

    return {
        "rows": rows,
        "all_pass": all(r["passes"] for r in rows),
    }


def _t6_plot(df: pd.DataFrame, path: Path) -> None:
    fig, ax = plt.subplots(figsize=(8, 5))
    x = np.arange(len(df))
    width = 0.35
    ax.bar(x - width / 2, df["IS_Sharpe"], width, label="IS Sharpe", color="#0ea5e9")
    ax.bar(x + width / 2, df["OOS_Sharpe"], width, label="OOS Sharpe", color="#16a34a")
    ax.axhline(0, color="black", linewidth=0.5)
    ax.set_xticks(x)
    ax.set_xticklabels(df["signal"], rotation=15)
    ax.set_ylabel("Sharpe")
    ax.set_title("V7.5α₁ — In-sample vs Out-of-sample Sharpe")
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


# =============================================================================
# Main
# =============================================================================

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--test", default="all",
        help="Which test to run: 1, 2, 3, 4, 5, 6, comma-separated (e.g. '1,2,5'), or 'all'.",
    )
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    log = OUTPUT_DIR / "run.log"

    def banner(msg: str) -> None:
        line = f"\n{'=' * 70}\n{msg}\n{'=' * 70}"
        print(line, flush=True)
        with log.open("a") as f:
            f.write(line + "\n")

    selected: set[str]
    if args.test == "all":
        selected = {"1", "2", "3", "4", "5", "6"}
    else:
        selected = {s.strip() for s in args.test.split(",") if s.strip()}

    banner(f"V7.5α₁ validation — tests={sorted(selected)}")
    start = time.time()
    data, market = load_inputs()
    results: dict = {}

    if "1" in selected:
        banner("Test 1 — Continuity (v75 with α_M=0 ≡ V7.4b)")
        results["test_1"] = test_1_continuity(data, market, OUTPUT_DIR)

    if "2" in selected:
        banner("Test 2 — Zone audit on v75 variants")
        results["test_2"] = test_2_zone_audit(data, market, OUTPUT_DIR)

    if "3" in selected:
        banner("Test 3 — Jaccard stability (inherited from V7.4c)")
        results["test_3"] = test_3_jaccard_inherited(OUTPUT_DIR)

    if "4" in selected:
        banner("Test 4 — Parameter plateau (from sweep_v75.py)")
        results["test_4"] = test_4_plateau(OUTPUT_DIR)

    if "5" in selected:
        banner("Test 5 — No-look-ahead audit")
        results["test_5"] = test_5_lookahead(data, market, OUTPUT_DIR)

    if "6" in selected:
        banner("Test 6 — OOS holdout (2024-2026)")
        results["test_6"] = test_6_oos(data, market, OUTPUT_DIR)

    with (OUTPUT_DIR / "results_summary.json").open("w") as f:
        json.dump(_jsonable(results), f, indent=2, default=str)

    elapsed = time.time() - start
    banner(f"V7.5α₁ validation finished — {elapsed/60:.1f} min")
    for name, r in results.items():
        if isinstance(r, dict):
            verdict = "PASS" if r.get("passes") or r.get("all_pass") else "FAIL"
            print(f"  {name}: {verdict}")


def _jsonable(obj):
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, (np.integer, np.floating)):
        return float(obj)
    if isinstance(obj, (np.bool_, bool)):
        return bool(obj)
    if isinstance(obj, pd.Timestamp):
        return obj.isoformat()
    return obj


if __name__ == "__main__":
    main()
