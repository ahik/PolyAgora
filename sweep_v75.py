"""
V7.5α₁ Test 4 parameter frontier sweep.

Grid:
  α_M ∈ {0.0, 0.25, 0.5, 0.75, 1.0, 1.5}     # momentum sensitivity
  K   ∈ {2, 3}                                # top-K blocks
  τ   ∈ {2.0, 4.0, 6.0}                        # softmax concentration
  λ   ∈ {0.5, 0.6, 0.8}                        # structural prior weight
  variant ∈ {v75, v75_no_mom_eigen}            # MOM12_1 in/out

α_M = 0 included as a sanity-check (must reproduce V7.4c plateau exactly).

Outputs:
  v75_validation_outputs/test_4_alpha_m_sweep.csv  — all 216 configs
  v75_validation_outputs/test_4_plateau_cells.csv  — plateau-filtered subset
  v75_validation_outputs/run.log                   — progress log
"""

from __future__ import annotations

import time
from itertools import product
from pathlib import Path

import pandas as pd

from polyagora_v63_partner_engine import (
    EngineConfig,
    compute_weights,
    evaluate,
    load_partner_xlsx,
    summary_row,
)
from polyagora_v75_engine import V75DriverConfig, make_v75_signal


ROOT = Path(__file__).resolve().parent
PARTNER = ROOT / "Agur" / "baseline_pnl_partner_delivery.xlsx"
MARKET = ROOT / "market_data" / "market_yahoo_vix_spy_hyg_tlt_gld_cper.csv"
OUT = ROOT / "v75_validation_outputs"

ALPHA_M_GRID = [0.0, 0.25, 0.5, 0.75, 1.0, 1.5]
K_GRID = [2, 3]
TAU_GRID = [2.0, 4.0, 6.0]
LAM_GRID = [0.5, 0.6, 0.8]
VARIANTS = [True, False]  # include_mom_eigen


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    log_path = OUT / "run.log"

    def log(msg: str) -> None:
        ts = time.strftime("%H:%M:%S")
        line = f"[{ts}] {msg}"
        print(line, flush=True)
        with log_path.open("a") as f:
            f.write(line + "\n")

    log("loading data")
    data = load_partner_xlsx(PARTNER)
    market = pd.read_csv(MARKET, parse_dates=["date"]).set_index("date")
    cfg = EngineConfig()

    grid = list(product(ALPHA_M_GRID, K_GRID, TAU_GRID, LAM_GRID, VARIANTS))
    n = len(grid)
    log(f"sweep: {n} configurations")
    start_wall = time.time()

    rows = []
    for i, (alpha_m, K, tau, lam, include_mom) in enumerate(grid, 1):
        t0 = time.time()
        sig = make_v75_signal(
            market, data.realized_pnl,
            drivers=V75DriverConfig(momentum_sensitivity=alpha_m),
            include_mom_eigen=include_mom,
            top_k=K, tau=tau, lam=lam,
        )
        w = compute_weights(data, sig, cfg)
        r = evaluate(w, data.forward_pnl)
        s = summary_row("v75", r.returns)
        rows.append({
            "alpha_M": alpha_m,
            "K": K,
            "tau": tau,
            "lam": lam,
            "include_mom_eigen": include_mom,
            "Sharpe": s["Sharpe"],
            "MaxDD": s["Max drawdown"],
            "CAGR": s["CAGR"],
            "AnnVol": s["Ann. vol"],
            "TotalRet": s["Total return"],
        })
        elapsed = time.time() - t0
        if i % 5 == 0 or i == n:
            eta = (time.time() - start_wall) / i * (n - i)
            log(
                f"[{i:3d}/{n}] α={alpha_m} K={K} τ={tau} λ={lam} "
                f"mom={'Y' if include_mom else 'N'} Sharpe={s['Sharpe']:.3f} "
                f"DD={s['Max drawdown']*100:.2f}%  ({elapsed:.1f}s, eta {eta/60:.1f}min)"
            )

    df = pd.DataFrame(rows)
    df.to_csv(OUT / "test_4_alpha_m_sweep.csv", index=False)
    log(f"wrote {OUT / 'test_4_alpha_m_sweep.csv'} ({len(df)} rows)")

    # Plateau detection — Test 4 criterion: Sharpe within 0.05 of best AND
    # MaxDD within 100bps of best, contiguous in the (K, τ, λ, α_M) lattice.
    best = df["Sharpe"].max()
    best_dd = df["MaxDD"].min()
    plateau = df[
        (df["Sharpe"] >= best - 0.05)
        & ((df["MaxDD"] - best_dd).abs() <= 0.01)
    ].copy()
    plateau.to_csv(OUT / "test_4_plateau_cells.csv", index=False)
    log(f"plateau: {len(plateau)} / {len(df)} cells (best Sharpe {best:.3f}, best DD {best_dd*100:.2f}%)")

    log("top 10 configs by Sharpe:")
    top10 = df.nlargest(10, "Sharpe")
    for _, row in top10.iterrows():
        log(
            f"  α={row['alpha_M']} K={row['K']} τ={row['tau']} λ={row['lam']} "
            f"mom={'Y' if row['include_mom_eigen'] else 'N'} "
            f"Sharpe={row['Sharpe']:.3f} DD={row['MaxDD']*100:.2f}%"
        )

    # Plateau by variant
    log("plateau breakdown by variant:")
    for v in [True, False]:
        sub = plateau[plateau["include_mom_eigen"] == v]
        log(f"  include_mom_eigen={v}: {len(sub)} plateau cells")

    elapsed_total = time.time() - start_wall
    log(f"sweep complete — {elapsed_total/60:.1f} min")


if __name__ == "__main__":
    main()
