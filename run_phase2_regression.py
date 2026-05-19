"""Phase-2 regression run — reproduce the V7.10 moat (Option B).

Phase-2 fork (2026-05-19): the v62 re-base failed the §12.2 moat gate, so
per the chosen Option B the proven V7.10 stack becomes the Phase-II base
(`MoatStackBase`). This runner:

  1. captures the V7.10 reference return stream (`polyagora_v710_outputs/`),
  2. runs the Phase-II execution graph with the moat-stack base,
  3. scores the candidate against the reference on the §12.2 band.

With the convexity layers still stubbed (Phase 2), the runtime reproduces
V7.10 by construction — the §12.2 gate should PASS. Phases 3-4 then add the
real layers, re-checking this gate at every increment.

    agora/bin/python run_phase2_regression.py
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
OUTPUT = ROOT / "polyagora_phase2_outputs"


def _load_returns(path: Path) -> pd.Series:
    col0 = pd.read_csv(path, nrows=0).columns[0]
    return pd.read_csv(path, parse_dates=[col0]).set_index(col0).iloc[:, 0]


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)

    ref_path = V710_DIR / "returns_v710.csv"
    if not ref_path.exists():
        raise SystemExit(f"V7.10 reference missing: {ref_path} — run run_v710_check.py")
    reference = _load_returns(ref_path)
    rm = metrics(reference)
    print(f"[phase2] V7.10 reference : {len(reference)} bars  "
          f"Sharpe={rm['sharpe']:.4f}  MaxDD={rm['max_dd']:.4f}")

    # --- run the Phase-II graph with the moat-stack base (Option B) ---------
    data = load_partner_xlsx(INPUT)
    macro = pd.read_csv(MARKET, parse_dates=["date"]).set_index("date")
    moat = MoatStackBase(V710_DIR / "weights_v710.csv", macro, UNIVERSE)
    graph = ExecutionGraph(macro, UNIVERSE, base_provider=moat)
    panel = graph.run_full(data.realized_pnl)
    candidate = evaluate(panel, data.forward_pnl).returns
    cm = metrics(candidate)
    print(f"[phase2] Phase-II graph  : {len(candidate)} bars  "
          f"Sharpe={cm['sharpe']:.4f}  MaxDD={cm['max_dd']:.4f}")

    panel.to_csv(OUTPUT / "phase2_weights.csv", index_label="trading_date")
    candidate.to_csv(OUTPUT / "phase2_candidate_returns.csv",
                     index_label="trading_date")

    # --- score against the §12.2 band ---------------------------------------
    spy = macro["SPY"].pct_change().rename("SPY") if "SPY" in macro.columns else None
    gate = RegressionGate(reference, spy=spy)
    result = gate.evaluate(candidate)
    print()
    print(result.report())

    # exact-reproduction check (Option B should be bit-for-bit on real assets)
    diff = (candidate - reference.reindex(candidate.index)).abs().max()
    print(f"\n[phase2] max |candidate - reference| per-bar return = {diff:.2e}")

    pd.DataFrame(
        [{"metric": c.metric, "reference": c.reference, "candidate": c.candidate,
          "rule": c.rule, "passed": c.passed} for c in result.checks]
    ).to_csv(OUTPUT / "phase2_regression_band.csv", index=False)
    print(f"[phase2] band detail -> {OUTPUT / 'phase2_regression_band.csv'}")


if __name__ == "__main__":
    main()
