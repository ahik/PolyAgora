"""Phase 5 (calibration) + Phase 6 (validation) — final Phase-II run.

  Phase 5 — calibration. The coefficients are PolygonEye's initial
    philosophical configuration; theta_erq is the falsification-derived
    admissibility boundary. Per the doctrine, coefficients are NOT
    return-optimized — that would collapse the architecture into
    conventional optimization.

  Deliverable C — typed sleeves. Two candidates (Type-B cross-sectional
    expansion, Type-C transition breakout) are run through the 6-gate
    admission pipeline; whatever clears is blended by Layer 2.

  Phase 6 — validation. The full runtime (all six layers) is scored on
    the §12.2 moat gate and the first-test acceptance scorecard.

    agora/bin/python run_phase56_validation.py
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from polyagora_v63_partner_engine import (
    UNIVERSE, EngineConfig, compute_weights, evaluate, load_partner_xlsx)
from polyagora_sleeve_registry import SleeveSpec
from polyagora_validation import cost_adjust
from polyagora.governance.moat import MoatStackBase
from polyagora.mrtp import MRTP_COEFFICIENTS
from polyagora.regression import RegressionGate, metrics
from polyagora.runtime import ExecutionGraph
from polyagora.sleeves import (
    ConvexitySleeves, admit_sleeve, make_breakout_signal, make_xs_expansion_signal)

ROOT = Path(__file__).resolve().parent
INPUT = ROOT / "Agur" / "baseline_pnl_partner_delivery.xlsx"
MARKET = ROOT / "market_data" / "market_yahoo_vix_spy_hyg_tlt_gld_cper.csv"
V710_DIR = ROOT / "polyagora_v710_outputs"
OUTPUT = ROOT / "polyagora_phase56_outputs"
THETA_ERQ = 0.70   # Phase-5: falsification-derived admissibility boundary

# First-test acceptance targets (Impl Spec §12.3 — the convexity goals).
TARGETS = {"sharpe": (1.2, ">"), "sortino": (1.5, ">"), "calmar": (1.0, ">"),
           "max_dd": (-0.08, ">"), "corr_spy": (0.15, "<")}


def _load_returns(path: Path) -> pd.Series:
    c = pd.read_csv(path, nrows=0).columns[0]
    return pd.read_csv(path, parse_dates=[c]).set_index(c).iloc[:, 0]


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    data = load_partner_xlsx(INPUT)
    macro = pd.read_csv(MARKET, parse_dates=["date"]).set_index("date")
    reference = _load_returns(V710_DIR / "returns_v710.csv")
    spy = macro["SPY"].pct_change().rename("SPY")
    cfg = EngineConfig()

    # --- Phase 5 — calibration (principled, not return-optimized) -----------
    c = MRTP_COEFFICIENTS
    print("=== Phase 5 — calibration ===")
    print(f"  MRTP coefficients (PolygonEye initial config): "
          f"alpha={c['alpha']} gamma={c['gamma']} delta={c['delta']} "
          f"beta={c['beta']} eta={c['eta']}")
    hier_ok = min(c['alpha'], c['gamma'], c['delta']) > max(c['beta'], c['eta'])
    print(f"  hierarchy alpha,gamma,delta > beta,eta : "
          f"{'OK' if hier_ok else 'VIOLATED'}  "
          f"(Recoverability > Convexity > Return preserved)")
    print(f"  theta_erq = {THETA_ERQ}  (Type-I/II admissibility boundary)")

    # --- Deliverable C — typed sleeves through 6-gate admission -------------
    print("\n=== Deliverable C — convexity sleeve admission ===")
    candidates = [
        (SleeveSpec(strategy_id="xs_expansion", sleeve_type="B", horizon="medium",
                    economic_mechanism="Cross-sectional dispersion — long leaders, "
                    "short laggards; harvests expansion without directional beta.",
                    regime_affinity=["persistent reflation", "stable bull"],
                    failure_modes=["sharp cross-sectional reversal"],
                    polyagora_block="C"),
         make_xs_expansion_signal(), 5.0),
        (SleeveSpec(strategy_id="transition_breakout", sleeve_type="C", horizon="fast",
                    economic_mechanism="Time-series breakout — fast trend clears slow "
                    "baseline; early-transition participation.",
                    regime_affinity=["regime transition", "early breakout"],
                    failure_modes=["whipsaw / high fragmentation"],
                    polyagora_block="B"),
         make_breakout_signal(), 3.0),
    ]
    admissions = []
    for spec, signal, bps in candidates:
        panel = compute_weights(data, signal, cfg)
        sret = cost_adjust(evaluate(panel, data.forward_pnl).returns, panel, cost_bps=bps)
        res = admit_sleeve(spec, panel, sret, reference, UNIVERSE, theta_erq=THETA_ERQ)
        admissions.append(res)
        print("  " + res.summary().replace("\n", "\n  "))
    admitted = [a for a in admissions if a.admitted]
    print(f"  -> {len(admitted)}/{len(admissions)} admitted")

    # --- Phase 6 — validation: full runtime, all six layers -----------------
    moat = MoatStackBase(V710_DIR / "weights_v710.csv", macro, UNIVERSE)
    graph = ExecutionGraph(macro, UNIVERSE, base_provider=moat,
                           sleeves=ConvexitySleeves(admissions, UNIVERSE))
    panel = graph.run_full(data.realized_pnl)
    candidate = evaluate(panel, data.forward_pnl).returns
    panel.to_csv(OUTPUT / "phase56_weights.csv", index_label="trading_date")
    candidate.to_csv(OUTPUT / "phase56_returns.csv", index_label="trading_date")

    print("\n=== Phase 6 — §12.2 moat gate ===")
    result = RegressionGate(reference, spy=spy).evaluate(candidate)
    print(f"  {'PASS' if result.passed else 'FAIL'} — "
          f"{sum(x.passed for x in result.checks)}/{len(result.checks)} checks")
    for x in result.checks:
        if not x.passed:
            print(f"    FAIL {x.metric}: ref={x.reference:.4f} cand={x.candidate:.4f}")

    # --- acceptance scorecard — first-test convexity targets ----------------
    cm = metrics(candidate)
    rm = metrics(reference)
    j = pd.concat([candidate, spy], axis=1, join="inner").dropna()
    cm["corr_spy"] = float(j.iloc[:, 0].corr(j.iloc[:, 1]))
    jr = pd.concat([reference, spy], axis=1, join="inner").dropna()
    rm["corr_spy"] = float(jr.iloc[:, 0].corr(jr.iloc[:, 1]))
    print("\n=== Phase 6 — acceptance scorecard (first-test convexity targets) ===")
    print(f"  {'metric':<10}{'V7.10':>10}{'Phase-II':>11}{'target':>10}{'verdict':>9}")
    met = 0
    for k, (tgt, op) in TARGETS.items():
        v, rv = cm[k], rm[k]
        ok = (v > tgt) if op == ">" else (v < tgt)
        met += ok
        print(f"  {k:<10}{rv:>10.3f}{v:>11.3f}{tgt:>10.2f}"
              f"{('PASS' if ok else 'below') if op == '>' else ('PASS' if ok else 'above'):>9}")
    print(f"  -> {met}/{len(TARGETS)} first-test targets met")
    print(f"\n[phase56] outputs -> {OUTPUT}")


if __name__ == "__main__":
    main()
