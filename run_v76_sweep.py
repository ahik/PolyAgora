"""
V7.6α hyperparameter sensitivity sweep.

We already ran the manifolds once; reuse the cached returns/weights from
`polyagora_v76_outputs/` and just re-blend across a grid of (lookback,
lam, halflife, floor). Tells us whether the headline Sharpe 0.82 is a
hyperparameter accident.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from polyagora_v63_partner_engine import (
    CASH,
    UNIVERSE,
    evaluate,
    load_partner_xlsx,
    summary_row,
)
from polyagora_v76_engine import MetaConfig, meta_blend


ROOT = Path(__file__).resolve().parent
OUT = ROOT / "polyagora_v76_outputs"


def _load_run(name: str) -> tuple[pd.DataFrame, pd.Series]:
    w = pd.read_csv(OUT / f"weights_{name}.csv", parse_dates=["trading_date"]).set_index("trading_date")
    r = pd.read_csv(OUT / f"returns_{name}.csv", parse_dates=["trading_date"]).set_index("trading_date").iloc[:, 0]
    return w, r


def _metrics(rets: pd.Series) -> dict:
    s = summary_row("x", rets)
    eq = (1 + rets).cumprod()
    dd = (eq / eq.cummax() - 1.0).min()
    down = rets[rets < 0]
    sortino = (rets.mean() * 252) / (down.std() * np.sqrt(252)) if len(down) and down.std() > 0 else float("nan")
    cagr = s["CAGR"]
    calmar = cagr / abs(dd) if abs(dd) > 1e-9 else float("nan")
    return {"Sharpe": s["Sharpe"], "Sortino": sortino, "Calmar": calmar,
            "CAGR": cagr, "MaxDD": dd, "Vol": s["Ann. vol"]}


def main() -> None:
    data = load_partner_xlsx(ROOT / "Agur" / "baseline_pnl_partner_delivery.xlsx")
    names = ["v74d_q", "momentum_12_1", "defensive", "cash"]
    weights = {n: _load_run(n)[0] for n in names}
    returns = {n: _load_run(n)[1] for n in names}

    # Single-axis sweeps from baseline cfg = (63, 2.0, 10.0, 0.05)
    grid: list[dict] = []
    base = dict(lookback=63, lam=2.0, ewm_halflife=10.0, min_floor=0.05)

    for lb in [21, 42, 63, 126, 252]:
        for lam in [0.5, 1.0, 2.0, 4.0, 8.0]:
            for hl in [1.0, 5.0, 10.0, 21.0, 60.0]:
                for fl in [0.0, 0.05, 0.10, 0.20]:
                    cfg = MetaConfig(lookback=lb, lam=lam, ewm_halflife=hl, min_floor=fl)
                    w, _alloc = meta_blend(weights, returns, cfg)
                    w = w.reindex(data.forward_pnl.index).fillna(0.0)
                    res = evaluate(w, data.forward_pnl)
                    grid.append({"lookback": lb, "lam": lam, "halflife": hl, "floor": fl,
                                 **_metrics(res.returns)})

    df = pd.DataFrame(grid).sort_values("Sharpe", ascending=False)
    df.to_csv(OUT / "sweep_v76.csv", index=False)

    print(f"[sweep] {len(df)} configs")
    print()
    print("Top 15 by Sharpe:")
    print(df.head(15).to_string(index=False,
        formatters={c: "{:.4f}".format for c in df.columns if c not in ["lookback"]}))
    print()
    print("Bottom 5 by Sharpe (sanity):")
    print(df.tail(5).to_string(index=False,
        formatters={c: "{:.4f}".format for c in df.columns if c not in ["lookback"]}))
    print()
    print("Sharpe distribution:")
    print(df["Sharpe"].describe().to_string())
    print()
    print("By lookback (median Sharpe):")
    print(df.groupby("lookback")["Sharpe"].median().to_string())
    print()
    print("By lam (median Sharpe):")
    print(df.groupby("lam")["Sharpe"].median().to_string())
    print()
    print("By halflife (median Sharpe):")
    print(df.groupby("halflife")["Sharpe"].median().to_string())
    print()
    print("By floor (median Sharpe):")
    print(df.groupby("floor")["Sharpe"].median().to_string())


if __name__ == "__main__":
    main()
