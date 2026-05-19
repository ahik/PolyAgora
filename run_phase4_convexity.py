"""Phase-4 run — integrate recoverable convexity (MRTP + Dynamic Kelly).

Phase 4 turns on the layers that *deform* the allocation: Layer 3 (MRTP
convexity scoring) and Layer 4 (Dynamic Kelly). Kelly adds recoverable
leverage (f_t in [1.00, 1.25]) only in pristine LOCAL_STAR regimes and
returns to base instantly under any stress.

The §12.2 moat gate is the hard guard: Phase 4 is accepted only if the
runtime still holds the V7.10 moat within the regression band — especially
the sacred crisis windows.

    agora/bin/python run_phase4_convexity.py
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from polyagora_v63_partner_engine import UNIVERSE, evaluate, load_partner_xlsx
from polyagora.governance.moat import MoatStackBase
from polyagora.regression import RegressionGate, metrics
from polyagora.runtime import ExecutionGraph

ROOT = Path(__file__).resolve().parent
INPUT = ROOT / "Agur" / "baseline_pnl_partner_delivery.xlsx"
MARKET = ROOT / "market_data" / "market_yahoo_vix_spy_hyg_tlt_gld_cper.csv"
V710_DIR = ROOT / "polyagora_v710_outputs"
OUTPUT = ROOT / "polyagora_phase4_outputs"


def _load_returns(path: Path) -> pd.Series:
    col0 = pd.read_csv(path, nrows=0).columns[0]
    return pd.read_csv(path, parse_dates=[col0]).set_index(col0).iloc[:, 0]


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)

    data = load_partner_xlsx(INPUT)
    macro = pd.read_csv(MARKET, parse_dates=["date"]).set_index("date")
    reference = _load_returns(V710_DIR / "returns_v710.csv")
    rm = metrics(reference)

    # --- run the Phase-II graph with MRTP + Kelly live ----------------------
    moat = MoatStackBase(V710_DIR / "weights_v710.csv", macro, UNIVERSE)
    graph = ExecutionGraph(macro, UNIVERSE, base_provider=moat)
    panel = graph.run_full(data.realized_pnl)
    candidate = evaluate(panel, data.forward_pnl).returns
    cm = metrics(candidate)

    panel.to_csv(OUTPUT / "phase4_weights.csv", index_label="trading_date")
    candidate.to_csv(OUTPUT / "phase4_returns.csv", index_label="trading_date")
    trace = graph.trace_frame()
    trace.to_csv(OUTPUT / "phase4_trace.csv", index_label="date")

    print(f"[phase4] V7.10 reference : Sharpe={rm['sharpe']:.4f}  "
          f"MaxDD={rm['max_dd']:.4f}  CAGR={rm['cagr']:.4f}")
    print(f"[phase4] Phase-II (MRTP+Kelly): Sharpe={cm['sharpe']:.4f}  "
          f"MaxDD={cm['max_dd']:.4f}  CAGR={cm['cagr']:.4f}")

    # --- Kelly / MRTP activity ----------------------------------------------
    print("\n=== Kelly leverage activity ===")
    print(f"  f_t: mean={trace['f_t'].mean():.4f}  "
          f"max={trace['f_t'].max():.4f}  "
          f"bars with f_t>1.0: {int((trace['f_t'] > 1.0 + 1e-9).sum())} "
          f"({(trace['f_t'] > 1.0 + 1e-9).mean():.1%})")
    print("  Kelly mode counts:")
    for mode, n in trace["kelly_mode"].value_counts().items():
        print(f"    {mode:<14} {n}")
    print(f"  MRTP score: mean={trace['mrtp'].mean():.3f}  "
          f"min={trace['mrtp'].min():.3f}  max={trace['mrtp'].max():.3f}")

    # --- §12.2 moat gate — the hard guard -----------------------------------
    spy = macro["SPY"].pct_change().rename("SPY") if "SPY" in macro.columns else None
    result = RegressionGate(reference, spy=spy).evaluate(candidate)
    print()
    print(result.report())

    pd.DataFrame(
        [{"metric": c.metric, "reference": c.reference, "candidate": c.candidate,
          "rule": c.rule, "passed": c.passed} for c in result.checks]
    ).to_csv(OUTPUT / "phase4_regression_band.csv", index=False)
    print(f"\n[phase4] outputs -> {OUTPUT}")


if __name__ == "__main__":
    main()
