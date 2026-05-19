"""Deliverable B/C — convexity sleeve research.

Phase 5/6 found the two first-cut candidates rejected. This harness widens
the search: it constructs a breadth of Type-B (expansion / relative-value)
and Type-C (transition / breakout) sleeve candidates across parameters,
plus Type-A (crisis-trend) references, and runs every one through the full
6-gate admission pipeline against the V7.10 book.

The gates decide. A leaderboard is printed; whatever clears admission is
blended into the runtime and re-scored on the §12.2 moat gate and the
acceptance scorecard. A universe-wide rejection is itself a finding —
honest evidence about where cost-survivable edge does and does not exist.

    agora/bin/python run_sleeve_research.py
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from polyagora_v63_partner_engine import (
    UNIVERSE, EngineConfig, compute_weights, evaluate, load_partner_xlsx)
from polyagora_v710_engine import make_trend_sleeve_signal
from polyagora_sleeve_registry import SleeveSpec
from polyagora_validation import cost_adjust
from polyagora.governance.moat import MoatStackBase
from polyagora.regression import RegressionGate, metrics
from polyagora.runtime import ExecutionGraph
from polyagora.sleeves import (
    ConvexitySleeves, admit_sleeve, make_breakout_signal, make_xs_expansion_signal)

ROOT = Path(__file__).resolve().parent
INPUT = ROOT / "Agur" / "baseline_pnl_partner_delivery.xlsx"
MARKET = ROOT / "market_data" / "market_yahoo_vix_spy_hyg_tlt_gld_cper.csv"
V710_DIR = ROOT / "polyagora_v710_outputs"
OUTPUT = ROOT / "polyagora_sleeve_research_outputs"

HAVENS = ["TN", "FGBL", "GC", "DX"]
COMMOD = ["CL", "GC", "HG", "SI", "ZS", "ZW"]


def _spec(sid: str, stype: str, mech: str) -> SleeveSpec:
    return SleeveSpec(strategy_id=sid, sleeve_type=stype, horizon="varies",
                      economic_mechanism=mech, regime_affinity=[],
                      failure_modes=[], polyagora_block="-")


def _candidates():
    """(spec, signal, cost_bps) — Type-B / Type-C sweep + Type-A references."""
    out = []
    # Type-B — cross-sectional expansion (long leaders / short laggards)
    for lb in (63, 126, 252):
        out.append((_spec(f"B_xs_expansion_{lb}", "B",
                           "cross-sectional dispersion — long leaders/short laggards"),
                    make_xs_expansion_signal(lookback=lb), 5.0))
    # Type-C — transition breakout (fast trend clears slow baseline)
    for fast, slow in ((10, 63), (21, 126), (42, 252)):
        out.append((_spec(f"C_breakout_{fast}_{slow}", "C",
                           "time-series breakout — fast trend clears slow baseline"),
                    make_breakout_signal(fast=fast, slow=slow), 6.0))
    # Type-A references — crisis trend on subsets (the admitted-sleeve template)
    out.append((_spec("A_trend_all13_252", "A", "broad cross-asset time-series trend"),
                make_trend_sleeve_signal(list(UNIVERSE), 252, 21), 3.0))
    out.append((_spec("A_trend_havens_252", "A", "crisis trend on the safe-haven complex"),
                make_trend_sleeve_signal(HAVENS, 252, 21), 3.0))
    out.append((_spec("A_trend_commod_252", "A", "trend on the commodity complex"),
                make_trend_sleeve_signal(COMMOD, 252, 21), 3.0))
    return out


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    data = load_partner_xlsx(INPUT)
    macro = pd.read_csv(MARKET, parse_dates=["date"]).set_index("date")
    reference = pd.read_csv(V710_DIR / "returns_v710.csv",
                            parse_dates=["trading_date"]).set_index("trading_date").iloc[:, 0]
    cfg = EngineConfig()

    print("=== Deliverable B/C — sleeve research: 6-gate admission leaderboard ===")
    print(f"  {'candidate':<22}{'ty':>3}{'Shrp':>7}{'DSR':>6}{'corrBk':>8}"
          f"{'degr':>6}{'blend':>7}{'gates':>7}{'verdict':>10}")
    print("  " + "-" * 78)

    admissions, rows = [], []
    for spec, signal, bps in _candidates():
        panel = compute_weights(data, signal, cfg)
        sret = cost_adjust(evaluate(panel, data.forward_pnl).returns, panel, cost_bps=bps)
        res = admit_sleeve(spec, panel, sret, reference, UNIVERSE)
        admissions.append(res)
        e = res.evaluation
        n_gates = sum(e.gates.values()) + int(res.fragility_ok)
        print(f"  {spec.strategy_id:<22}{spec.sleeve_type:>3}"
              f"{e.metrics.get('sharpe', 0):>7.2f}{e.dsr.dsr_pvalue:>6.2f}"
              f"{e.corr_to_book:>8.2f}{e.degradation.degradation_ratio:>6.2f}"
              f"{e.contribution.get('blend_sharpe', 0):>7.3f}{n_gates:>5}/6"
              f"{('ADMITTED' if res.admitted else 'rejected'):>10}")
        rows.append({"id": spec.strategy_id, "type": spec.sleeve_type,
                     "standalone_sharpe": e.metrics.get("sharpe", 0),
                     "dsr": e.dsr.dsr_pvalue, "corr_book": e.corr_to_book,
                     "degradation": e.degradation.degradation_ratio,
                     "blend_sharpe": e.contribution.get("blend_sharpe", 0),
                     "erq": res.erq, "gates_passed": n_gates,
                     "admitted": res.admitted})
    pd.DataFrame(rows).to_csv(OUTPUT / "sleeve_research_leaderboard.csv", index=False)

    admitted = [a for a in admissions if a.admitted]
    print(f"\n  -> {len(admitted)}/{len(admissions)} candidates cleared all 6 gates")

    if not admitted:
        print("\n[research] FINDING: no candidate cleared admission. The V7.10 book "
              "already harvests the cost-survivable edge available on this 13-futures "
              "universe; the contribution / DSR / degradation gates reject the rest.")
        return

    # --- integrate the admitted sleeve(s) and re-score ----------------------
    print("\n=== Admitted sleeve(s) integrated — full runtime re-score ===")
    moat = MoatStackBase(V710_DIR / "weights_v710.csv", macro, UNIVERSE)
    graph = ExecutionGraph(macro, UNIVERSE, base_provider=moat,
                           sleeves=ConvexitySleeves(admissions, UNIVERSE))
    panel = graph.run_full(data.realized_pnl)
    candidate = evaluate(panel, data.forward_pnl).returns
    panel.to_csv(OUTPUT / "sleeve_research_weights.csv", index_label="trading_date")

    spy = macro["SPY"].pct_change().rename("SPY")
    result = RegressionGate(reference, spy=spy).evaluate(candidate)
    cm, rm = metrics(candidate), metrics(reference)
    print(f"  §12.2 moat gate: {'PASS' if result.passed else 'FAIL'} "
          f"({sum(x.passed for x in result.checks)}/{len(result.checks)})")
    print(f"  Sharpe : V7.10 {rm['sharpe']:.4f} -> Phase-II {cm['sharpe']:.4f}")
    print(f"  Sortino: V7.10 {rm['sortino']:.4f} -> Phase-II {cm['sortino']:.4f}")
    print(f"  Calmar : V7.10 {rm['calmar']:.4f} -> Phase-II {cm['calmar']:.4f}")
    print(f"  Max DD : V7.10 {rm['max_dd']:.4f} -> Phase-II {cm['max_dd']:.4f}")
    print(f"\n[research] outputs -> {OUTPUT}")


if __name__ == "__main__":
    main()
