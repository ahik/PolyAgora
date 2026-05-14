"""
PolyAgora V7.4b — Soft Local-Star Manifold Upgrade
==================================================

Per `docs/PolyAgora_V7_4b_Soft_Manifold_Upgrade.pdf`. Replaces V7.4's hard
Local-Star mask 1_{ϕ_i ∈ B*_t} with soft manifold membership over the
top-K coherent blocks:

    Q_m(t)   = µ_m(X_t) · Γ_t(B_m)                         # spec §1.1
    B_t^(K)  = top-K blocks by Q_m(t)                      # spec §1.2
    ρ_m(t)   = exp(τ Q_m) / Σ_{ℓ ∈ B_t^(K)} exp(τ Q_ℓ)     # spec §1.3
    M_i(t)   = Σ_{m ∈ B_t^(K)} ρ_m(t) · 1_{ϕ_i ∈ B_m}      # spec §1.4
    p_i(t)   = A_i · q_i · M_i · G_i(D_t)                  # spec §1.5
    w_raw_i  = p_i / Σ p_j
    w_i(t)   = g(Z_t) · w_raw_i                            # spec §1.6

Spec defaults: K=2, τ=4, λ=0.6.

`block_source` selects how blocks are constructed:

  - "category"  (default) — five disjoint blocks defined by eigenfield
        category (spec §4). Categories are the natural structural
        clustering of Φ; they are exactly what a graph-clustering
        algorithm would recover from S_0 since the prior was built by
        category in the first place. Empirically the strongest mode on
        this universe.

  - "graph"     — connected components of G_t = (Φ, E_t) where
        (i,j) ∈ E_t ⟺ W_t(i,j) ≥ θ_S (spec §1.8). On a 14-strategy
        universe with a category-keyed prior, connected components is
        too lenient — bridge edges through defensive collapse the graph
        into one giant component until θ_S ≳ 0.65, at which point
        singletons dominate. Use cliques or community detection for a
        sharper partition; not implemented in this version.

  - "static"    — V7.4's four hand-coded overlapping blocks (TREND,
        CARRY, STRESS, ROTATION). Provided as a regression baseline.

  - "template"  — V7.3-style allocation primitive: V6.2 reference-polygon
        block probabilities ρ_m drive a soft mixture of the 5 POLYAGORA
        templates (A, B, C, D, G). Strategy-level admissibility and the
        survival matrix are bypassed; only top-K filtering / softmax /
        Driver Seat / gross-exposure machinery wrap v73's allocator.
        Used to verify the continuity theorem — at
        (top_k=5, gate_mode="beta", q_cfg=default) this branch reproduces
        V7.3 exactly, establishing v74b as a strict generalization.

Limit cases:
  - τ → ∞, K=1            ≡ V7.4-style hard selection over the chosen
                            block source.
  - K = #blocks            ⇒ uniform aggregation across all blocks.
  - block_source="template", top_k=5, gate_mode="beta", q_cfg set
                          ≡ V7.3 exactly (recovery anchor).

Everything else (admissibility, survival matrix, zone classification,
Driver Seat, MOM12-1 decomposition, anti-hindsight slicing) is inherited
from `polyagora_v74_engine` unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from polyagora_v63_partner_engine import (
    EngineConfig as V63EngineConfig,
    NEUTRAL_TEMPLATE,
    POLYAGORA_TEMPLATES,
    PolyagoraGateConfig,
    SignalFn,
    UNIVERSE as ASSET_UNIVERSE,
    _TEMPLATE_DF,
    _compute_beta_from_market,
    _proxy_drawdown,
)
from polyagora_v74_engine import (
    BLOCKS,
    CATEGORY,
    MOM_NAME,
    STRATEGIES,
    S_PRIOR,
    V74DriverConfig,
    ZONE_GROSS_BASE,
    _admissibility,
    _block_internal_survival,
    _block_membership,
    _category_multipliers,
    _classify_zone,
    _coordinate_from_x,
    _empirical_survival,
    _momentum_portfolio,
    _synth_mom_pnl,
)


# V7.4b reuses the V7.4 Driver Seat verbatim (same 5 spec dials). Soft-
# manifold parameters K, τ, λ, θ_S are structural manifold settings
# exposed as engine factory parameters, not PM-side dials.
V74bDriverConfig = V74DriverConfig


# =============================================================================
# Dynamic blocks via survivability coherence graph (spec §1.8)
# =============================================================================

def _connected_components(W: pd.DataFrame, threshold: float) -> list[list[str]]:
    """Connected components of G_t = (Φ, E_t) where E_t = {(i,j) : W(i,j) ≥ θ_S}.

    Singletons are returned as 1-element components. Order of returned
    components is deterministic (DFS from STRATEGIES order).
    """
    n = len(STRATEGIES)
    adj = (W.loc[STRATEGIES, STRATEGIES].values >= threshold).copy()
    np.fill_diagonal(adj, False)
    visited = [False] * n
    components: list[list[str]] = []
    for i in range(n):
        if visited[i]:
            continue
        stack = [i]
        comp: list[str] = []
        while stack:
            j = stack.pop()
            if visited[j]:
                continue
            visited[j] = True
            comp.append(STRATEGIES[j])
            for k in range(n):
                if adj[j, k] and not visited[k]:
                    stack.append(k)
        components.append(comp)
    return components


def _dominant_category(members: list[str]) -> str:
    """Most common eigenfield category among members, ties broken alphabetically."""
    if not members:
        return ""
    counts: dict[str, int] = {}
    for s in members:
        counts[CATEGORY[s]] = counts.get(CATEGORY[s], 0) + 1
    best = max(counts.items(), key=lambda kv: (kv[1], -ord(kv[0][0])))
    return best[0]


def _block_label(members: list[str]) -> str:
    """Stable human label for a dynamic block — dominant category + size."""
    if not members:
        return "∅"
    if len(members) == 1:
        return f"{{{members[0]}}}"
    return f"{_dominant_category(members)}·{len(members)}"


# Five disjoint blocks defined by eigenfield category (spec §4).
# Categories are the structural clustering of Φ; this is the default
# block source for V7.4b.
CATEGORY_BLOCKS: dict[str, list[str]] = {
    cat.upper(): [s for s in STRATEGIES if CATEGORY[s] == cat]
    for cat in ("persistence", "carry", "defensive", "convexity", "stress")
}


def _category_blocks() -> list[list[str]]:
    return [list(members) for members in CATEGORY_BLOCKS.values()]


# =============================================================================
# Soft Local-Star aggregation (spec §§1.2–1.4)
# =============================================================================

def _soft_membership_from_blocks(
    adm: dict[str, float],
    W: pd.DataFrame,
    blocks: list[list[str]],
    *,
    top_k: int,
    tau: float,
) -> tuple[dict[str, float], list[dict]]:
    """Soft manifold membership M_i(t) per spec §§1.2–1.4 over arbitrary blocks.

    Parameters
    ----------
    blocks : list of strategy lists. May be static (spec §7) or dynamic
        connected components (spec §1.8). Soft aggregation is correct in
        both cases; dynamic disjoint blocks deliver clean diversification.

    Returns
    -------
    M : dict[str, float] — M_i(t) ∈ [0, 1] for every strategy in Φ.
    top : list[dict]      — per-block summary for the top-K blocks.
    """
    scored: list[tuple[list[str], float, float, float]] = []
    for members in blocks:
        if not members:
            continue
        gamma = _block_internal_survival(W, members)
        mu = _block_membership(adm, members)
        scored.append((members, mu * gamma, gamma, mu))
    scored.sort(key=lambda r: r[1], reverse=True)
    K = max(1, min(top_k, len(scored)))
    top = scored[:K]

    Qs = np.array([r[1] for r in top], dtype=float)
    z = tau * Qs
    z = z - float(z.max())  # softmax stability
    rho = np.exp(z)
    rho = rho / rho.sum()

    M: dict[str, float] = {s: 0.0 for s in STRATEGIES}
    for (members, _, _, _), w in zip(top, rho):
        w_f = float(w)
        for s in members:
            M[s] += w_f

    top_summary = [
        {"label": _block_label(r[0]), "members": list(r[0]),
         "size": len(r[0]),
         "Q": float(r[1]), "gamma": float(r[2]), "mu": float(r[3]),
         "rho": float(w)}
        for r, w in zip(top, rho)
    ]
    return M, top_summary


def _soft_membership(
    adm: dict[str, float],
    W: pd.DataFrame,
    *,
    top_k: int,
    tau: float,
) -> tuple[dict[str, float], list[dict]]:
    """Static-block soft aggregation — uses BLOCKS from polyagora_v74_engine.

    Kept for callers that want spec §1–§1.7 only (no §1.8 dynamic graph).
    """
    return _soft_membership_from_blocks(
        adm, W,
        [list(members) for members in BLOCKS.values()],
        top_k=top_k, tau=tau,
    )


# =============================================================================
# Template-block signal (continuity anchor — v73 recovery path)
# =============================================================================

def _make_v74b_template_signal(
    *, market: pd.DataFrame, realized: pd.DataFrame,
    drivers: V74bDriverConfig | None,
    top_k: int, gate_mode: str,
    gate_cfg: PolyagoraGateConfig | None,
    q_cfg,
    zone_smoothing_halflife: float,
    v62_cfg,
) -> SignalFn:
    """Template-mixture allocator: V6.2 ρ_m × POLYAGORA_TEMPLATES_m.

    The continuity anchor for v74b → v73. With
    (top_k=5, gate_mode="beta", q_cfg=QPolygonConfig()) this branch
    reproduces V7.3 exactly. With top_k < 5 the engine selects only the
    top-K block scores and renormalizes ρ — a stricter regime commitment.
    """
    from polyagora_v62_engine import (
        EngineConfig as V62EngineConfig,
        build_block_history, build_exogenous_x,
    )

    drivers = drivers or V74bDriverConfig()
    base_cfg = v62_cfg or V62EngineConfig()
    gate_cfg = gate_cfg or PolyagoraGateConfig()

    X = build_exogenous_x(market, base_cfg)
    _, block_scores = build_block_history(X, base_cfg)
    block_scores = block_scores.sort_index()  # rows: dates; cols: A B C D G

    beta_series: pd.Series | None = None
    if gate_mode == "beta":
        proxy_dd = _proxy_drawdown(realized)
        beta_series = _compute_beta_from_market(
            market, proxy_dd, gate_cfg,
        ).sort_index()

    neutral = pd.Series(NEUTRAL_TEMPLATE).reindex(ASSET_UNIVERSE).fillna(0.0)

    # Q-polygon helpers, imported lazily — only when q_cfg is supplied
    # (and only relevant on the template branch).
    use_q = q_cfg is not None
    if use_q:
        from polyagora_v73_engine import Q_ADD, Q_BUFFETT, Q_VAIDM
    else:
        Q_VAIDM = Q_ADD = Q_BUFFETT = None  # type: ignore[assignment]

    halflife = max(0.5, zone_smoothing_halflife / max(1e-3, drivers.recovery_aggression))
    alpha = 1.0 - float(np.exp(-np.log(2.0) / halflife))
    state: dict[str, float | None] = {"last_beta_smooth": None}
    diagnostics: list[dict] = []

    def _renorm_gross(s: pd.Series) -> pd.Series:
        g = float(s.abs().sum())
        if not np.isfinite(g) or g < 1e-12:
            return pd.Series(1.0 / max(len(s), 1), index=s.index)
        return s / g

    def _signal(history: pd.DataFrame, live: list[str],
                _cfg: V63EngineConfig) -> pd.Series:
        t = history.index[-1]
        bs_idx = block_scores.index.asof(t)
        if pd.isna(bs_idx):
            return _renorm_gross(neutral.reindex(live).fillna(0.0))

        probs = block_scores.loc[bs_idx]  # series over {A, B, C, D, G}
        K = max(1, min(top_k, len(probs)))
        top = probs.nlargest(K)
        rho = top / top.sum() if top.sum() > 0 else top
        probs_eff = pd.Series(0.0, index=probs.index)
        probs_eff.loc[rho.index] = rho.values

        tilt = _renorm_gross(_TEMPLATE_DF.dot(probs_eff).reindex(live).fillna(0.0))
        neutral_live = _renorm_gross(neutral.reindex(live).fillna(0.0))

        # β gate
        if gate_mode == "beta" and beta_series is not None:
            beta_idx = beta_series.index.asof(t)
            beta = float(beta_series.loc[beta_idx]) if pd.notna(beta_idx) else 0.0
        else:
            # gate_mode == "zone" path on the template branch: use ρ_top as a
            # coherence proxy and map through ZONE_GROSS_BASE.
            coh = float(rho.iloc[0]) if len(rho) else 0.0
            Z = 1 if coh >= 0.55 else 2 if coh >= 0.40 else 3 if coh >= 0.25 else 4
            beta = ZONE_GROSS_BASE[Z]

        if use_q:
            history_lag = history.iloc[:-1]
            q_v = Q_VAIDM(history_lag, q_cfg) if q_cfg.enable_vaidm else 1.0
            q_a, _dd = Q_ADD(history_lag, q_cfg) if q_cfg.enable_add else (1.0, 0.0)
            q_b = Q_BUFFETT(history_lag, q_cfg) if q_cfg.enable_buffett else 1.0
            beta = beta * q_v * q_a * q_b

        # Driver Seat — max_defensive_contraction floors β.
        beta = max(getattr(drivers, "max_defensive_contraction", 0.0), beta)
        # EWM smoothing on β (continuous analog of g(Z_t) smoothing).
        last = state["last_beta_smooth"]
        beta_smooth = (alpha * beta + (1.0 - alpha) * last) if last is not None else beta
        state["last_beta_smooth"] = beta_smooth
        beta_smooth = max(0.0, min(1.0, beta_smooth))

        weights = beta_smooth * tilt + (1.0 - beta_smooth) * neutral_live

        diagnostics.append({
            "date": t, "beta": beta, "beta_smooth": beta_smooth,
            "block_top1": rho.index[0] if len(rho) else "",
            "rho_top1": float(rho.iloc[0]) if len(rho) else 0.0,
            "gross": float(weights.abs().sum()),
            **{f"prob_{b}": float(probs_eff.loc[b]) for b in probs_eff.index},
        })
        return weights

    def diagnostics_df() -> pd.DataFrame:
        if not diagnostics:
            return pd.DataFrame()
        return pd.DataFrame(diagnostics).set_index("date")

    _signal.diagnostics = diagnostics              # type: ignore[attr-defined]
    _signal.diagnostics_df = diagnostics_df        # type: ignore[attr-defined]
    return _signal


# =============================================================================
# V7.4b signal factory
# =============================================================================

def make_v74b_signal(
    market: pd.DataFrame,
    realized: pd.DataFrame,
    drivers: V74bDriverConfig | None = None,
    *,
    block_source: str = "category",
    top_k: int = 2,
    tau: float = 4.0,
    survival_window: int = 60,
    lam: float = 0.6,
    theta_s: float = 0.55,
    zone_smoothing_halflife: float = 5.0,
    gate_mode: str = "zone",
    gate_cfg=None,
    q_cfg=None,
    v62_cfg=None,
) -> SignalFn:
    """V7.4b signal factory — soft Local-Star manifold.

    Parameters
    ----------
    block_source : {"category", "graph", "static", "template"}
        How blocks are constructed (see module docstring). Default
        "category" — the empirically strongest mode on this universe.
    top_k : int
        K in spec §1.2. Blocks ranked by Q_m(t), only the top-K participate.
        Default 2; recommended sweep {2, 3}.
    tau : float
        τ in spec §1.3. Concentration parameter on the softmax over Q_m.
        Default 4.0; recommended sweep {2, 4, 6}.
    survival_window : int
        Rolling window (days) for empirical R_t.
    lam : float
        λ in spec §1.7 — weight on the structural prior S_0. Default 0.6;
        recommended sweep {0.50, 0.65, 0.80}.
    theta_s : float
        θ_S in spec §1.8 — survivability edge threshold. Used only when
        block_source == "graph". Default 0.55; recommended sweep
        {0.45, 0.55, 0.65}.
    zone_smoothing_halflife : float
        EWM half-life on g(Z_t), in days. Scaled down by recovery_aggression.
    gate_mode : {"zone", "beta"}
        Gross-exposure gating. "zone" — discrete g(Z_t) per spec §13.
        "beta" — continuous v73-style β from VIX/SPY/DD soft gates ×
        hard-kill cooldown × EWM (recovers v6.3-gated / v7.3 behavior
        when block_source == "template").
    gate_cfg : PolyagoraGateConfig | None
        Required when gate_mode == "beta". Defaults applied if None.
    q_cfg : QPolygonConfig | None
        When set and block_source == "template", multiplies β by V7.3
        Q polygons (VAIDM × ADD × Buffett). Establishes the v7.3 recovery
        anchor; ignored for other block sources.
    """
    if block_source not in {"category", "graph", "static", "template"}:
        raise ValueError(
            f"block_source must be 'category', 'graph', 'static', or 'template'; "
            f"got {block_source!r}"
        )
    if gate_mode not in {"zone", "beta"}:
        raise ValueError(f"gate_mode must be 'zone' or 'beta'; got {gate_mode!r}")

    if block_source == "template":
        return _make_v74b_template_signal(
            market=market, realized=realized,
            drivers=drivers, top_k=top_k,
            gate_mode=gate_mode, gate_cfg=gate_cfg, q_cfg=q_cfg,
            zone_smoothing_halflife=zone_smoothing_halflife,
            v62_cfg=v62_cfg,
        )
    from polyagora_v62_engine import (
        EngineConfig as V62EngineConfig,
        build_exogenous_x,
    )

    drivers = drivers or V74bDriverConfig()
    base_cfg = v62_cfg or V62EngineConfig()

    X = build_exogenous_x(market, base_cfg).sort_index()
    mom_pnl_full = _synth_mom_pnl(realized).sort_index()
    proxy_dd_full = _proxy_drawdown(realized).sort_index()

    cat_mult = _category_multipliers(drivers)
    halflife = max(0.5, zone_smoothing_halflife / max(1e-3, drivers.recovery_aggression))
    alpha = 1.0 - float(np.exp(-np.log(2.0) / halflife))

    state: dict[str, float | None] = {"last_g_smooth": None, "last_Q1": None}
    diagnostics: list[dict] = []

    def _equal_live(live: list[str]) -> pd.Series:
        if not live:
            return pd.Series(dtype=float)
        return pd.Series(1.0 / len(live), index=live)

    def _signal(history: pd.DataFrame, live: list[str], _cfg: V63EngineConfig) -> pd.Series:
        t = history.index[-1]

        x_idx = X.index.asof(t)
        if pd.isna(x_idx):
            return _equal_live(live)
        coord = _coordinate_from_x(X.loc[x_idx])
        V_, T_, G_, C_, R_ = coord

        adm = _admissibility(coord)

        history_lag = history.iloc[:-1]
        if t in mom_pnl_full.index:
            mom_pnl_lag = mom_pnl_full.loc[:t].iloc[:-1]
        else:
            mom_pnl_lag = mom_pnl_full
        R_emp = _empirical_survival(history_lag, mom_pnl_lag, survival_window)
        W = lam * S_PRIOR + (1.0 - lam) * R_emp

        # Blocks: per `block_source`.
        if block_source == "category":
            blocks = _category_blocks()
        elif block_source == "graph":
            blocks = _connected_components(W, theta_s)
        else:  # "static"
            blocks = [list(members) for members in BLOCKS.values()]
        n_blocks = len(blocks)

        # Soft manifold membership (spec §§1.2–1.4)
        M, top = _soft_membership_from_blocks(
            adm, W, blocks, top_k=top_k, tau=tau,
        )

        # Zone uses top-1 block coherence — primary block drives stress signal.
        # Singleton blocks have Γ ≡ 1 by convention, which would over-promote
        # them in the zone classifier; collapse to the empirical mean of µ
        # for those days so isolated strategies don't masquerade as coherent.
        Q1 = top[0]["Q"]
        gamma1 = top[0]["gamma"] if top[0]["size"] > 1 else top[0]["mu"]
        mu1 = top[0]["mu"]
        last_Q1 = state["last_Q1"]
        dQ = abs(Q1 - last_Q1) if last_Q1 is not None else 0.0
        state["last_Q1"] = Q1

        # Proxy DD ≤ t-1 (anti-hindsight).
        if t in proxy_dd_full.index:
            dd_lag = proxy_dd_full.loc[:t].iloc[:-1]
            proxy_dd = float(dd_lag.iloc[-1]) if len(dd_lag) else 0.0
        else:
            proxy_dd = 0.0

        Z = _classify_zone(gamma1, mu1, coord, dQ, drivers, proxy_dd=proxy_dd)
        g_raw = ZONE_GROSS_BASE[Z]
        last_g = state["last_g_smooth"]
        g_smooth = (alpha * g_raw + (1.0 - alpha) * last_g) if last_g is not None else g_raw
        state["last_g_smooth"] = g_smooth

        # Strategy-level scores: soft membership replaces the hard mask (§1.5)
        p: dict[str, float] = {
            s: adm[s] * cat_mult[CATEGORY[s]] * M[s]  # q_i ≡ 1
            for s in STRATEGIES
        }
        total = sum(p.values())
        if total < 1e-12:
            diagnostics.append({
                "date": t, "V": V_, "T": T_, "G": G_, "C": C_, "R": R_,
                "Z": Z, "g_zone_raw": g_raw, "g_zone": g_smooth,
                "Q_top1": Q1, "gamma_top1": gamma1, "mu_top1": mu1,
                "block_top1": top[0]["label"], "size_top1": top[0]["size"],
                "rho_top1": top[0]["rho"],
                "block_top2": top[1]["label"] if len(top) > 1 else "",
                "size_top2": top[1]["size"] if len(top) > 1 else 0,
                "rho_top2": top[1]["rho"] if len(top) > 1 else 0.0,
                "n_blocks": n_blocks,
                "fallback": "neutral",
            })
            return _equal_live(live)
        w_strategy = {s: g_smooth * p[s] / total for s in STRATEGIES}

        # Decompose MOM12-1 into live constituents. Per-asset contribution is
        # captured for the dashboard "internal view" — these are the asset-band
        # slices driven by the MOM strategy rather than by direct admissibility
        # on the asset itself.
        w_mom = w_strategy.pop(MOM_NAME, 0.0)
        mom_contrib: dict[str, float] = {a: 0.0 for a in live}
        if w_mom > 1e-12:
            mom_port = _momentum_portfolio(history, live)
            for a in live:
                share = w_mom * float(mom_port.get(a, 0.0))
                mom_contrib[a] = share
                w_strategy[a] = w_strategy.get(a, 0.0) + share

        out = pd.Series({a: w_strategy.get(a, 0.0) for a in live})

        # Effective concentration of M (Herfindahl over the |Φ| entries):
        # 1.0 ≡ all weight on one strategy, 1/n ≡ uniform.
        m_arr = np.array([M[s] for s in STRATEGIES], dtype=float)
        m_norm = m_arr / max(m_arr.sum(), 1e-12)
        herfindahl_M = float((m_norm ** 2).sum())

        diag: dict = {
            "date": t,
            "V": V_, "T": T_, "G": G_, "C": C_, "R": R_,
            "Z": Z, "g_zone_raw": g_raw, "g_zone": g_smooth, "dQ": dQ,
            "block_top1": top[0]["label"], "size_top1": top[0]["size"],
            "Q_top1": Q1, "gamma_top1": gamma1, "mu_top1": mu1,
            "rho_top1": top[0]["rho"],
            "A_persistence": adm["ES"], "A_carry": adm["TN"],
            "A_defensive": adm["GC"], "A_convexity": adm["SI"],
            "A_stress":     adm["CL"], "A_mom": adm[MOM_NAME],
            "w_mom": w_mom, "gross": float(out.abs().sum()),
            "M_herfindahl": herfindahl_M,
            "n_blocks": n_blocks,
            **{f"mom_{a}": v for a, v in mom_contrib.items()},
        }
        if len(top) > 1:
            diag.update({
                "block_top2": top[1]["label"], "size_top2": top[1]["size"],
                "Q_top2": top[1]["Q"], "rho_top2": top[1]["rho"],
            })
        if len(top) > 2:
            diag.update({
                "block_top3": top[2]["label"], "size_top3": top[2]["size"],
                "Q_top3": top[2]["Q"], "rho_top3": top[2]["rho"],
            })
        diagnostics.append(diag)
        return out

    def diagnostics_df() -> pd.DataFrame:
        if not diagnostics:
            return pd.DataFrame()
        return pd.DataFrame(diagnostics).set_index("date")

    _signal.diagnostics = diagnostics              # type: ignore[attr-defined]
    _signal.diagnostics_df = diagnostics_df        # type: ignore[attr-defined]
    return _signal
