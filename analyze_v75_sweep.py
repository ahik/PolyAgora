"""
V7.5α₁ Sweep Analyzer.

Ingests `v75_validation_outputs/test_4_alpha_m_sweep.csv` produced by
`sweep_v75.py` and produces:

  - Sharpe heatmaps over (α_M, λ), faceted by (K, τ, variant)
  - MaxDD heatmaps same layout
  - Plateau-overlay heatmap (highlights cells within Sharpe ±0.05 of best)
  - Top-10 configs table (printed + CSV)
  - Per-variant plateau breakdown
  - Plateau-center recommendation

Usage:
    python analyze_v75_sweep.py
    python analyze_v75_sweep.py --sweep <path>  # custom CSV
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parent
DEFAULT_SWEEP = ROOT / "v75_validation_outputs" / "test_4_alpha_m_sweep.csv"
DEFAULT_OUT = ROOT / "v75_validation_outputs"

PLATEAU_SHARPE_TOL = 0.05
PLATEAU_DD_TOL = 0.01


def plot_heatmaps(
    df: pd.DataFrame,
    metric: str,
    out_path: Path,
    *,
    cmap: str = "viridis",
    fmt: str = "{:.3f}",
    title_prefix: str = "Sharpe",
    annotate_plateau: bool = False,
    best_sharpe: float | None = None,
    best_dd: float | None = None,
) -> None:
    """One heatmap per (K, τ, variant) facet — α_M on x, λ on y."""
    K_vals = sorted(df["K"].unique())
    tau_vals = sorted(df["tau"].unique())
    variants = sorted(df["include_mom_eigen"].unique(), reverse=True)

    n_rows = len(variants) * len(K_vals)
    n_cols = len(tau_vals)
    fig, axes = plt.subplots(
        n_rows, n_cols, figsize=(3.6 * n_cols, 3.4 * n_rows), squeeze=False,
    )

    alpha_vals = sorted(df["alpha_M"].unique())
    lam_vals = sorted(df["lam"].unique())

    vmin = df[metric].min()
    vmax = df[metric].max()

    for ri, (variant, K) in enumerate([(v, k) for v in variants for k in K_vals]):
        for ci, tau in enumerate(tau_vals):
            ax = axes[ri][ci]
            sub = df[
                (df["K"] == K) & (df["tau"] == tau)
                & (df["include_mom_eigen"] == variant)
            ]
            pivot = (
                sub.pivot_table(index="lam", columns="alpha_M", values=metric)
                .reindex(index=lam_vals, columns=alpha_vals)
            )
            im = ax.imshow(
                pivot.values, cmap=cmap, vmin=vmin, vmax=vmax,
                aspect="auto", origin="lower",
            )
            ax.set_xticks(range(len(alpha_vals)))
            ax.set_xticklabels([f"{a:g}" for a in alpha_vals], fontsize=8)
            ax.set_yticks(range(len(lam_vals)))
            ax.set_yticklabels([f"{l:g}" for l in lam_vals], fontsize=8)
            mom_tag = "Φ=14" if variant else "Φ=13"
            ax.set_title(f"{mom_tag}, K={K}, τ={tau}", fontsize=10)
            if ci == 0:
                ax.set_ylabel("λ", fontsize=9)
            if ri == n_rows - 1:
                ax.set_xlabel("α_M", fontsize=9)

            for yi, lam in enumerate(lam_vals):
                for xi, am in enumerate(alpha_vals):
                    val = pivot.iloc[yi, xi] if not np.isnan(pivot.iloc[yi, xi]) else None
                    if val is None:
                        continue
                    color = "white" if (val - vmin) / max(vmax - vmin, 1e-9) < 0.5 else "black"
                    label = fmt.format(val)
                    if annotate_plateau and best_sharpe is not None:
                        in_plateau = val >= best_sharpe - PLATEAU_SHARPE_TOL
                        if in_plateau:
                            ax.add_patch(plt.Rectangle(
                                (xi - 0.45, yi - 0.45), 0.9, 0.9,
                                fill=False, edgecolor="red", linewidth=2,
                            ))
                    ax.text(xi, yi, label, ha="center", va="center",
                            color=color, fontsize=7)

    fig.suptitle(f"V7.5α₁ — {title_prefix} surface", fontsize=12, y=0.995)
    fig.tight_layout(rect=[0, 0, 1, 0.985])
    cbar_ax = fig.add_axes([1.01, 0.15, 0.02, 0.7])
    fig.colorbar(im, cax=cbar_ax)
    fig.savefig(out_path, dpi=120, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sweep", type=Path, default=DEFAULT_SWEEP)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    if not args.sweep.exists():
        raise SystemExit(f"sweep CSV not found: {args.sweep}\n"
                         f"  → run `python sweep_v75.py` first.")

    args.out.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(args.sweep)
    print(f"[analyze] loaded {len(df)} configs from {args.sweep}")

    best_sharpe = float(df["Sharpe"].max())
    best_dd = float(df["MaxDD"].min())
    plateau = df[
        (df["Sharpe"] >= best_sharpe - PLATEAU_SHARPE_TOL)
        & ((df["MaxDD"] - best_dd).abs() <= PLATEAU_DD_TOL)
    ].copy()

    print(f"[analyze] best Sharpe={best_sharpe:.4f}, best DD={best_dd*100:.2f}%")
    print(f"[analyze] plateau: {len(plateau)}/{len(df)} cells "
          f"({len(plateau)/len(df)*100:.1f}%)")

    print("\nTop 10 configs by Sharpe:")
    top10 = df.nlargest(10, "Sharpe")
    print(top10.to_string(index=False))
    top10.to_csv(args.out / "test_4_top10.csv", index=False)

    print("\nPlateau by variant:")
    for v in [True, False]:
        sub_total = df[df["include_mom_eigen"] == v]
        sub_pl = plateau[plateau["include_mom_eigen"] == v]
        tag = "Φ=14 (MOM12_1 kept)" if v else "Φ=13 (MOM12_1 dropped)"
        if len(sub_total):
            print(f"  {tag}: plateau {len(sub_pl)}/{len(sub_total)} "
                  f"({len(sub_pl)/len(sub_total)*100:.1f}%), "
                  f"best Sharpe={sub_total['Sharpe'].max():.4f}")

    # Recommended plateau-center config
    if len(plateau):
        median = pd.Series({
            "alpha_M": plateau["alpha_M"].median(),
            "tau": plateau["tau"].median(),
            "lam": plateau["lam"].median(),
        })
        dists = (plateau[["alpha_M", "tau", "lam"]] - median).abs().sum(axis=1)
        center = plateau.iloc[dists.values.argmin()]
        print("\nPlateau-center recommendation (closest plateau cell to medians):")
        print(f"  α_M = {center['alpha_M']}")
        print(f"  K   = {int(center['K'])}")
        print(f"  τ   = {center['tau']}")
        print(f"  λ   = {center['lam']}")
        print(f"  Φ   = {'14 (keep MOM12_1)' if center['include_mom_eigen'] else '13 (drop MOM12_1)'}")
        print(f"  → Sharpe {center['Sharpe']:.4f}, MaxDD {center['MaxDD']*100:.2f}%")

    # Heatmaps
    print("\n[analyze] generating heatmaps")
    plot_heatmaps(
        df, "Sharpe", args.out / "test_4_sharpe_heatmap.png",
        cmap="viridis", title_prefix="Sharpe",
        annotate_plateau=True, best_sharpe=best_sharpe, best_dd=best_dd,
    )
    plot_heatmaps(
        df, "MaxDD", args.out / "test_4_maxdd_heatmap.png",
        cmap="magma_r", title_prefix="MaxDD",
        fmt="{:.2%}",
    )
    print(f"[analyze] wrote heatmaps to {args.out}")


if __name__ == "__main__":
    main()
