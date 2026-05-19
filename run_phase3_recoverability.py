"""Phase-3 run — integrate Layer 5 (Recoverability Geometry) + Layer 5A (ERQ).

Phase 3 makes the recoverability layers real. They are *measurement* layers,
so this runner checks two things:

  1. §12.2 moat gate — still 10/10. Layers 5/5A only populate state; they do
     not deform the allocation, so the runtime must still reproduce V7.10.
  2. Falsification protocol (Impl Spec §10) — the estimators must land in the
     correct tercile across the known regime episodes (rupture vs bull).
     An estimator that does not respond is flagged, not calibrated.

    agora/bin/python run_phase3_recoverability.py
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from polyagora_v63_partner_engine import UNIVERSE, evaluate, load_partner_xlsx
from polyagora.governance.moat import MoatStackBase
from polyagora.regression import RegressionGate, metrics
from polyagora.runtime import ExecutionGraph

ROOT = Path(__file__).resolve().parent
INPUT = ROOT / "Agur" / "baseline_pnl_partner_delivery.xlsx"
MARKET = ROOT / "market_data" / "market_yahoo_vix_spy_hyg_tlt_gld_cper.csv"
V710_DIR = ROOT / "polyagora_v710_outputs"
OUTPUT = ROOT / "polyagora_phase3_outputs"

# Falsification episodes (Impl Spec §10). exp = expected tercile for the
# "rupture-low" estimators C, R, ERQ; the "rupture-high" estimators P, F take
# the opposite. "-" = transitional episode, reported but not gated.
EPISODES = {
    "GFC rupture":   ("2008-04-01", "2009-03-31", "low"),
    "GFC recovery":  ("2009-04-01", "2011-12-31", "-"),
    "QE bull":       ("2012-01-01", "2019-12-31", "high"),
    "COVID rupture": ("2020-02-15", "2020-12-31", "low"),
    "Post-2020":     ("2021-01-01", "2021-12-31", "-"),
    "2022 shock":    ("2022-01-01", "2022-12-31", "low"),
}
RUPTURE_LOW = ["C_t", "R", "erq_book"]   # low in rupture, high in bull
RUPTURE_HIGH = ["P_t", "F_t"]            # high in rupture, low in bull


def _load_returns(path: Path) -> pd.Series:
    col0 = pd.read_csv(path, nrows=0).columns[0]
    return pd.read_csv(path, parse_dates=[col0]).set_index(col0).iloc[:, 0]


def _tercile(value: float, q33: float, q66: float) -> str:
    return "low" if value < q33 else ("high" if value > q66 else "mid")


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)

    # --- run the Phase-II graph (moat base + real Layers 5/5A) --------------
    data = load_partner_xlsx(INPUT)
    macro = pd.read_csv(MARKET, parse_dates=["date"]).set_index("date")
    moat = MoatStackBase(V710_DIR / "weights_v710.csv", macro, UNIVERSE)
    graph = ExecutionGraph(macro, UNIVERSE, base_provider=moat)
    panel = graph.run_full(data.realized_pnl)
    candidate = evaluate(panel, data.forward_pnl).returns

    # --- check 1 — §12.2 moat gate (must still pass 10/10) ------------------
    reference = _load_returns(V710_DIR / "returns_v710.csv")
    spy = macro["SPY"].pct_change().rename("SPY") if "SPY" in macro.columns else None
    result = RegressionGate(reference, spy=spy).evaluate(candidate)
    print("=== Check 1 — §12.2 moat gate (Layers 5/5A must not deform alloc) ===")
    print(f"  {'PASS' if result.passed else 'FAIL'} — "
          f"{sum(c.passed for c in result.checks)}/{len(result.checks)} checks  "
          f"| max|cand-ref| = "
          f"{(candidate - reference.reindex(candidate.index)).abs().max():.2e}")

    # --- check 2 — falsification protocol -----------------------------------
    trace = graph.trace_frame()
    trace["R"] = 0.5 * (trace["R_reentry"] + trace["R_persist"])
    trace.to_csv(OUTPUT / "phase3_trace.csv", index_label="date")
    estimators = RUPTURE_LOW + RUPTURE_HIGH

    terc = {e: (trace[e].quantile(0.33), trace[e].quantile(0.66)) for e in estimators}
    print("\n=== Check 2 — falsification protocol (Impl Spec §10) ===")
    header = f"{'estimator':<10}" + "".join(f"{name:>16}" for name in EPISODES)
    print(header)
    print("-" * len(header))

    rows, gate_pass, gate_total = [], 0, 0
    for est in estimators:
        q33, q66 = terc[est]
        cells, line = [], f"{est:<10}"
        for name, (a, b, exp) in EPISODES.items():
            seg = trace.loc[a:b, est]
            m = float(seg.mean()) if len(seg) else float("nan")
            tc = _tercile(m, q33, q66)
            want = exp if est in RUPTURE_LOW else (
                {"low": "high", "high": "low", "-": "-"}[exp])
            ok = (want == "-") or (tc == want)
            if want != "-":
                gate_total += 1
                gate_pass += int(ok)
            mark = "" if want == "-" else (" ok" if ok else " XX")
            line += f"{m:>11.3f}[{tc[0]}]{mark:<3}"
            cells.append({"estimator": est, "episode": name, "mean": m,
                          "tercile": tc, "expected": want, "passed": ok})
        print(line)
        rows.extend(cells)

    pd.DataFrame(rows).to_csv(OUTPUT / "phase3_falsification.csv", index=False)
    print("-" * len(header))
    print(f"tercile test: {gate_pass}/{gate_total} episode-checks in the "
          f"expected tercile  (legend: [l]ow [m]id [h]igh; ok / XX vs expected)")

    # --- directional check — the actual §2.2 intent -------------------------
    # An estimator falsifies if it MOVES the right way at ruptures vs the calm
    # bull baseline. This is robust to the tercile test's two blunt edges:
    # the GFC outlier skewing extremes, and the bull occupying the mid tercile.
    bull = trace.loc["2012-01-01":"2019-12-31"]
    ruptures = {"GFC": ("2008-04-01", "2009-03-31"),
                "COVID": ("2020-02-15", "2020-12-31"),
                "2022": ("2022-01-01", "2022-12-31")}
    print("\n=== Directional check — rupture mean vs QE-bull baseline (§2.2) ===")
    dir_pass = dir_total = 0
    for est in estimators:
        b = float(bull[est].mean())
        lower = est in RUPTURE_LOW          # C/R/ERQ drop in rupture; P/F rise
        line, okc = f"{est:<10} bull={b:.3f}  |", 0
        for rn, (a, c) in ruptures.items():
            rm = float(trace.loc[a:c, est].mean())
            correct = (rm < b) if lower else (rm > b)
            okc += correct
            dir_total += 1
            line += f"  {rn}={rm:.3f}{'v' if rm < b else '^'}{'ok' if correct else 'XX'}"
        dir_pass += okc
        print(f"{line}  [{okc}/3]")
    print(f"directional test: {dir_pass}/{dir_total} rupture-vs-bull moves "
          f"in the expected direction")
    print(f"\n[phase3] outputs -> {OUTPUT}")


if __name__ == "__main__":
    main()
