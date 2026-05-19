"""Phase-1 smoke test — run the 13-step execution graph end to end.

Phase 1 delivers the runtime *architecture*: the state schema, the 13-step
execution graph, and a real Layer-1 Governance Core (V6.2 re-base). Layers
2-5A are stubs. This runner proves the graph executes over the full
2008-2026 partner history, holds the capital-budget envelope, and produces
an inspectable trace.

It is NOT a performance test — Phase 2 ("reproduce the V7.10 moat") is the
first run whose numbers matter. Here the headline metrics are reported only
to confirm the pipeline is wired and stable.

    agora/bin/python run_phase1_smoke.py
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from polyagora_v63_partner_engine import (
    UNIVERSE,
    EngineConfig,
    compute_weights,
    evaluate,
    load_partner_xlsx,
    summary_row,
)
from polyagora.runtime import ExecutionGraph

ROOT = Path(__file__).resolve().parent
INPUT = ROOT / "Agur" / "baseline_pnl_partner_delivery.xlsx"
MARKET = ROOT / "market_data" / "market_yahoo_vix_spy_hyg_tlt_gld_cper.csv"
OUTPUT = ROOT / "polyagora_phase1_outputs"


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    data = load_partner_xlsx(INPUT)
    macro = pd.read_csv(MARKET, parse_dates=["date"]).set_index("date")
    print(f"[phase1] partner data: {data.realized_pnl.index.min().date()} -> "
          f"{data.realized_pnl.index.max().date()}  "
          f"({len(data.realized_pnl)} rows, {len(UNIVERSE)} futures)")

    # --- run the 13-step execution graph over the full history --------------
    graph = ExecutionGraph(macro, UNIVERSE)
    weights = compute_weights(data, graph.as_signal_fn(), EngineConfig())
    res = evaluate(weights, data.forward_pnl)
    print(f"[phase1] graph executed {len(graph.trace)} bars without error")

    # --- envelope invariant check -------------------------------------------
    real = [c for c in weights.columns if c != "CASH"]
    gross = weights[real].abs().sum(axis=1)
    cash = weights["CASH"]
    envelope = (gross + cash)
    ok_env = bool(np.allclose(envelope, 1.0, atol=1e-6))
    ok_cash = bool((cash >= -1e-9).all())
    print(f"[phase1] envelope sum|w_real|+cash == 1 : {ok_env}")
    print(f"[phase1] cash >= 0 on every bar         : {ok_cash}")

    # --- trace diagnostics --------------------------------------------------
    trace = graph.trace_frame()
    trace.to_csv(OUTPUT / "phase1_trace.csv", index_label="date")
    weights.to_csv(OUTPUT / "phase1_weights.csv", index_label="trading_date")
    res.returns.to_csv(OUTPUT / "phase1_returns.csv", index_label="trading_date")

    print("\n=== Zone distribution (5-mode classifier) ===")
    print(trace["zone"].value_counts().to_string())
    print("\n=== VAIDM class distribution ===")
    print(trace["vaidm"].value_counts().to_string())
    print(f"\nbeta_t: mean={trace['beta_t'].mean():.3f}  "
          f"min={trace['beta_t'].min():.3f}  max={trace['beta_t'].max():.3f}")
    print(f"gross : mean={trace['gross'].mean():.3f}  "
          f"min={trace['gross'].min():.3f}  max={trace['gross'].max():.3f}")

    # --- headline (pipeline-sanity only, NOT a performance gate) ------------
    row = summary_row("phase1-graph", res.returns)
    print("\n=== Headline (pipeline sanity only — Phase 2 is the real gate) ===")
    for k, v in row.items():
        if k != "Series":
            print(f"  {k:<16} {v:.4f}" if isinstance(v, float) else f"  {k:<16} {v}")

    print(f"\n[phase1] outputs -> {OUTPUT}")
    if ok_env and ok_cash and len(graph.trace) == len(data.realized_pnl):
        print("[phase1] SMOKE TEST PASSED — runtime architecture is wired.")
    else:
        print("[phase1] SMOKE TEST FAILED — see invariant checks above.")


if __name__ == "__main__":
    main()
