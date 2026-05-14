"""
PolyAgora V7.4 — Strategy Manifold V1
=====================================

Per `docs/PolyAgora_Strategy_Manifold_V1.pdf`. Strategies become
semi-independent eigenfields inside the Reference Polygon. Allocation
is admissibility × Local Star × zone-gross × Driver Seat — a runtime
governance layer over Φ rather than a regime-tilt allocator.

Universe Φ = 13 partner-asset streams + Momentum 12-1 = 14 strategies.
Categories per spec §4:
    Persistence:      ES, FESX, NKD, MOM12_1
    Carry:            TN, FGBL
    Defensive:        GC, DX
    Convexity:        SI, BTC
    Commodity Stress: CL, HG, ZS, ZW

Pipeline at time t:
    X_t        = (V, T, G, C, R)                        # exogenous (v62)
    A_i(t)     = σ(coef_category · X_t)                 # spec §6, §12
    R_t(i,j)   = (corr + 1)/2 over realized ≤ t-1       # spec §8 empirical
    W_t        = λ·S_0 + (1-λ)·R_t                      # spec §9
    Γ_t(B_m)   = min off-diag W_t over B_m               # spec §10
    µ_m(X_t)   = mean A_i over B_m                      # spec §11
    Q_m(t)     = µ_m · Γ_t(B_m)
    B*_t       = argmax_m Q_m(t)
    Z_t        = zone(Γ, µ, d_RP, ΔQ)                   # spec §13
    g(Z_t)     = {1.0, 0.6, 0.3, 0.1}
    A~_i(t)    = A_i · G_i(D_t) · 1[i ∈ B*_t]           # spec §14
    p_i(t)     = A~_i · q_i, q_i ≡ 1                    # spec §15
    w_raw_i    = p_i / Σ p_j
    w_i(t)     = g(Z_t) · w_raw_i
    cash       = 1 − Σ |w_assets|

MOM12-1's allocated weight is decomposed back to constituent live
assets via a long-only positive-momentum portfolio before the engine
emits the partner-asset weight panel.

Anti-hindsight invariants:
  - X_t already shifted by `feature_lag` inside build_exogenous_x.
  - W_t reads only history.iloc[:-1] (rows ≤ t-1) and the precomputed
    MOM PnL stream sliced to ≤ t-1.
  - The synthetic MOM PnL series uses .shift(skip+1) on rolling
    cumulative returns, so the value at index t depends solely on
    realized rows ≤ t-skip-1.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from polyagora_v63_partner_engine import (
    EngineConfig as V63EngineConfig,
    SignalFn,
    UNIVERSE,
)


# =============================================================================
# Strategy universe and eigenfield categories (spec §4)
# =============================================================================

MOM_NAME: str = "MOM12_1"

# Φ — 14 strategy eigenfields. The 13 partner assets are themselves treated
# as eigenfields per the proxy benchmark in
# `docs/Manifold V1 looks promising - on paper at least.pdf`.
STRATEGIES: list[str] = list(UNIVERSE) + [MOM_NAME]

CATEGORY: dict[str, str] = {
    # Persistence (Trend / Momentum)
    "ES": "persistence", "FESX": "persistence", "NKD": "persistence",
    MOM_NAME: "persistence",
    # Carry (Yield / Stability)
    "TN": "carry", "FGBL": "carry",
    # Defensive (Capital preservation)
    "GC": "defensive", "DX": "defensive",
    # Convexity (Stress asymmetry)
    "SI": "convexity", "BTC": "convexity",
    # Commodity Stress (Macro rupture)
    "CL": "stress", "HG": "stress", "ZS": "stress", "ZW": "stress",
}
CATEGORIES: list[str] = ["persistence", "carry", "defensive", "convexity", "stress"]
assert set(CATEGORY) == set(STRATEGIES)


# Admissibility coefficients per category (spec §12 generalization).
# A_i(t) = σ(coef · (V, T, G, C, R)).
# Sign conventions follow spec §12: persistence rewards T, dislikes V/G/R;
# carry rewards C, dislikes V/R; defensive admissible when V/R high;
# convexity & stress admissible under high V and Gold–Copper dislocation.
ADMISSIBILITY_COEFS: dict[str, np.ndarray] = {
    #                            V      T      G      C      R   (X_t order)
    "persistence": np.array([-1.5, +2.5, -0.5, +1.0, -0.5]),
    "carry":       np.array([-1.0, +0.5, -0.5, +1.5, -2.0]),
    "defensive":   np.array([+1.0, -0.5, +0.5, -0.5, +1.0]),
    "convexity":   np.array([+2.0, -0.5, +1.5, -0.5, +0.5]),
    "stress":      np.array([+1.0, -0.5, +2.0, -0.5, +0.5]),
}


# Pre-defined block coalitions (spec §7 examples projected onto Φ).
BLOCKS: dict[str, list[str]] = {
    "TREND":    ["ES", "FESX", "NKD", MOM_NAME, "TN", "FGBL"],
    "CARRY":    ["TN", "FGBL", "GC", "DX", "ES", "FESX"],
    "STRESS":   ["GC", "DX", "SI", "BTC", "CL", "HG", "ZS", "ZW"],
    "ROTATION": ["SI", "BTC", "CL", "HG", "ZS", "ZW", "ES", "FESX", "NKD", MOM_NAME],
}


# =============================================================================
# Driver Seat (spec §14)
# =============================================================================

@dataclass
class V74DriverConfig:
    """Five PM-level dials. Defaults reduce to the pure-spec Manifold V1.

    All dials deform parameters / category preferences inside structurally
    admissible regions. They never override Local Star membership or X_t.
    """
    # Category-preference multipliers G_i(D_t) ≥ 0.
    convexity_preference: float = 0.0   # amplifies convexity & stress categories
    carry_preference: float = 0.0       # amplifies carry category
    defensive_preference: float = 0.0   # amplifies defensive category

    # Boundary sensitivity scales zone thresholds (spec §13).
    # > 1 ⇒ thresholds tighter — engine drops to lower zones (smaller g) sooner.
    boundary_sensitivity: float = 1.0

    # Recovery aggression scales the EWM half-life on g(Z_t).
    # > 1 ⇒ shorter half-life — faster reflation after stress.
    recovery_aggression: float = 1.0


def _category_multipliers(drivers: V74DriverConfig) -> dict[str, float]:
    """G_i(D_t) per category (spec §14)."""
    return {
        "persistence": 1.0,
        "carry":       max(0.0, 1.0 + drivers.carry_preference),
        "defensive":   max(0.0, 1.0 + drivers.defensive_preference),
        "convexity":   max(0.0, 1.0 + drivers.convexity_preference),
        # stress co-amplified with convexity (both rupture-side fields)
        "stress":      max(0.0, 1.0 + drivers.convexity_preference),
    }


# =============================================================================
# Survival matrix (spec §§8–9)
# =============================================================================

# Pairwise structural prior — symmetric, indexed by category pair.
_CAT_PRIOR: dict[tuple[str, str], float] = {
    ("persistence", "persistence"): 0.90,
    ("carry",       "carry"):       0.90,
    ("defensive",   "defensive"):   0.90,
    ("convexity",   "convexity"):   0.85,
    ("stress",      "stress"):      0.80,

    ("carry",       "persistence"): 0.70,
    ("defensive",   "persistence"): 0.40,
    ("convexity",   "persistence"): 0.50,
    ("persistence", "stress"):      0.35,

    ("carry",       "defensive"):   0.65,
    ("carry",       "convexity"):   0.40,
    ("carry",       "stress"):      0.30,

    ("convexity",   "defensive"):   0.70,
    ("defensive",   "stress"):      0.55,

    ("convexity",   "stress"):      0.65,
}


def _structural_prior() -> pd.DataFrame:
    """S_0 ∈ [0,1]^{n×n}. Diagonal 1.0; off-diagonal from category-pair prior."""
    n = len(STRATEGIES)
    S = np.zeros((n, n))
    for i, si in enumerate(STRATEGIES):
        for j, sj in enumerate(STRATEGIES):
            if i == j:
                S[i, j] = 1.0
                continue
            ci, cj = CATEGORY[si], CATEGORY[sj]
            key = tuple(sorted((ci, cj)))
            S[i, j] = _CAT_PRIOR.get(key, 0.5)
    return pd.DataFrame(S, index=STRATEGIES, columns=STRATEGIES)


S_PRIOR: pd.DataFrame = _structural_prior()


def _empirical_survival(
    history_lag: pd.DataFrame,
    mom_pnl_lag: pd.Series,
    window: int,
) -> pd.DataFrame:
    """R_t — rolling pairwise survivability over Φ from realized PnL ≤ t-1.

    Built from rolling correlation, mapped (corr + 1)/2 ∈ [0,1]. Falls back
    to 0.5 (uninformative) when there isn't enough history yet.
    """
    n = len(STRATEGIES)
    if len(history_lag) < window // 2:
        return pd.DataFrame(np.full((n, n), 0.5), index=STRATEGIES, columns=STRATEGIES)

    panel = history_lag.tail(window).copy()
    panel[MOM_NAME] = mom_pnl_lag.reindex(panel.index)
    panel = panel[STRATEGIES]
    corr = panel.corr().fillna(0.0)
    R_arr = ((corr.values + 1.0) / 2.0).clip(0.0, 1.0)
    np.fill_diagonal(R_arr, 1.0)
    return pd.DataFrame(R_arr, index=STRATEGIES, columns=STRATEGIES)


def _block_internal_survival(W: pd.DataFrame, members: list[str]) -> float:
    """Γ_t(B_m) = min over ordered off-diagonal pairs in B_m (spec §10)."""
    if len(members) <= 1:
        return 1.0
    sub = W.loc[members, members].values
    n = sub.shape[0]
    mask = ~np.eye(n, dtype=bool)
    return float(sub[mask].min())


def _block_membership(adm: dict[str, float], members: list[str]) -> float:
    """µ_m(X_t) — block soft membership via mean admissibility (spec §11)."""
    return float(np.mean([adm[s] for s in members]))


def _select_local_star(
    adm: dict[str, float], W: pd.DataFrame
) -> tuple[str, list[str], float, float, float]:
    """Returns (block_name, members, Q, Γ, µ). Spec §10–§11."""
    best: tuple[str, list[str], float, float, float] | None = None
    for name, members in BLOCKS.items():
        gamma = _block_internal_survival(W, members)
        mu = _block_membership(adm, members)
        Q = mu * gamma
        if best is None or Q > best[2]:
            best = (name, members, Q, gamma, mu)
    assert best is not None
    return best


# =============================================================================
# Admissibility (spec §6, §12)
# =============================================================================

def _coordinate_from_x(x_row: pd.Series) -> np.ndarray:
    """X_t in (V, T, G, C, R) order — Reference Polygon coordinate.

    Mirrors v62's compute_coordinate so V7.4 reads X_t the same way V6.3
    does: tanh-bounded [-1, 1] components.
    """
    V = np.tanh((float(x_row["vix"]) - 18.0) / 10.0)
    T = np.tanh(5.0 * float(x_row["spy_trend_63d"]))
    G = np.tanh(2.0 * (float(x_row["gold_copper_ratio"]) - 4.5) / 4.5)
    C = np.tanh(10.0 * float(x_row["hyg_trend_63d"]))
    R = -np.tanh(5.0 * float(x_row["tlt_trend_63d"]))
    return np.array([V, T, G, C, R])


def _admissibility(coord: np.ndarray) -> dict[str, float]:
    """A_i(t) = σ(coef · X_t) replicated by category over all 14 strategies."""
    cat_a: dict[str, float] = {}
    for cat, coef in ADMISSIBILITY_COEFS.items():
        z = float(coef @ coord)
        cat_a[cat] = 1.0 / (1.0 + np.exp(-z))
    return {s: cat_a[CATEGORY[s]] for s in STRATEGIES}


# =============================================================================
# Zone classification (spec §13)
# =============================================================================

ZONE_GROSS_BASE: dict[int, float] = {1: 1.00, 2: 0.60, 3: 0.30, 4: 0.10}


def _classify_zone(
    gamma: float, mu: float, coord: np.ndarray, dQ: float,
    drivers: V74DriverConfig, proxy_dd: float = 0.0,
) -> int:
    """Zone label ∈ {1, 2, 3, 4} from coherence + stress markers + ΔQ.

    Stress markers (V7.4c update — addresses zone-collapse blocker from
    `docs/Evaluation of V7.4b (1).pdf` §1.4):
      - V/G saturation:  V_t or G_t close to ±1 in tanh-space means VIX
        or Gold/Copper-ratio extremes. Attenuates coh aggressively past
        |stress_axis| > 0.60.
      - Drawdown:        equal-weight proxy DD ≤ -3% additionally
        attenuates coh — mirrors v73's dd_gate so zone classifier responds
        to realized portfolio stress, not just exogenous market state.

    Both signals are anti-hindsight: coord comes from shift-lagged X_t;
    proxy_dd is computed from realized rows ≤ t-1.
    """
    s = max(1e-3, drivers.boundary_sensitivity)
    V_ = abs(float(coord[0]))
    G_ = abs(float(coord[2]))
    stress_axis = max(V_, G_)

    coh = gamma * mu
    # V/G saturation — kicks in at 0.60 (≈ VIX ≥ 22), drops to 0.10x
    # at full saturation (V_t ≈ 1.0 ≡ VIX ≥ 50). Aggressive trigger so
    # Z≥3 fires in ≥ 2/3 of the historical stress quarters (Test 2 spec
    # §1.4 — non-negotiable zone-collapse remediation).
    if stress_axis > 0.60:
        coh *= max(0.10, 1.0 - (stress_axis - 0.60) * 2.25)
    # Drawdown attenuation — kicks in at -3%, drops to 0.10x at -13.5%.
    # Compounds multiplicatively with V/G; together they trigger the
    # defensive zones across the major historical stress events
    # (2008-Q3, 2015-Q3, 2020-Q1, 2022-Q2, 2023-Q3).
    if proxy_dd < -0.03:
        coh *= max(0.10, 1.0 - (-proxy_dd - 0.03) * 8.0)
    # Q-flux dampener (smoother transitions).
    coh *= (1.0 - 0.30 * min(1.0, dQ * 5.0))

    # Boundary sensitivity > 1 ⇒ tighter thresholds (Z↑ sooner).
    if coh >= 0.35 / s:
        return 1
    if coh >= 0.22 / s:
        return 2
    if coh >= 0.12 / s:
        return 3
    return 4


# =============================================================================
# Momentum 12-1 — synthetic stream and decomposition
# =============================================================================

MOM_LOOKBACK: int = 252
MOM_SKIP: int = 21


def _momentum_portfolio(
    history: pd.DataFrame, live: list[str],
    lookback: int = MOM_LOOKBACK, skip: int = MOM_SKIP,
) -> pd.Series:
    """Long-only positive-momentum portfolio over `live`, gross = 1.

    Uses cumulative sum over [-lookback-skip, -skip), so the most recent
    `skip` rows of `history` are excluded — the t row of `history` is
    therefore not informative regardless of caller anti-hindsight setup.
    """
    if not live:
        return pd.Series(dtype=float)
    if len(history) < lookback + skip:
        return pd.Series(1.0 / len(live), index=live)
    window = history.iloc[-(lookback + skip):-skip]
    cum = window[live].sum(axis=0, min_count=lookback // 2).fillna(0.0)
    raw = cum.clip(lower=0.0)
    g = float(raw.abs().sum())
    if g > 1e-12:
        return raw / g
    return pd.Series(1.0 / len(live), index=live)


def _synth_mom_pnl(
    realized: pd.DataFrame,
    lookback: int = MOM_LOOKBACK,
    skip: int = MOM_SKIP,
) -> pd.Series:
    """Build the MOM12-1 PnL stream from the realized panel — vectorized.

    Anti-hindsight: signal at t is `cum.shift(skip + 1)`, so the long-only
    portfolio applied at t depends solely on realized rows ≤ t-skip-1.
    """
    cum = realized.rolling(window=lookback, min_periods=lookback // 2).sum()
    signal = cum.shift(skip + 1)
    pos = signal.clip(lower=0.0).fillna(0.0)
    gross = pos.sum(axis=1)
    weights = pos.div(gross.replace(0.0, np.nan), axis=0).fillna(0.0)
    pnl = (weights * realized.fillna(0.0)).sum(axis=1)
    return pnl


# =============================================================================
# V7.4 signal factory
# =============================================================================

def make_v74_signal(
    market: pd.DataFrame,
    realized: pd.DataFrame,
    drivers: V74DriverConfig | None = None,
    *,
    survival_window: int = 60,
    lam: float = 0.6,
    zone_smoothing_halflife: float = 5.0,
    v62_cfg=None,
) -> SignalFn:
    """V7.4 signal factory — Strategy Manifold V1.

    Parameters
    ----------
    market : market CSV with columns VIX, SPY, HYG, TLT, GLD, CPER (v62 conv.).
    realized : partner realized_pnl panel (13 assets, daily).
    drivers : V74DriverConfig — five PM-level dials.
    survival_window : rolling window for empirical R_t (default 60d).
    lam : weight on structural prior S_0; (1-lam) on R_t. Default 0.6 (spec §9).
    zone_smoothing_halflife : EWM half-life on g(Z_t), in days. Scaled down by
        recovery_aggression so the gross-exposure reflows quickly when set high.
    """
    from polyagora_v62_engine import (
        EngineConfig as V62EngineConfig,
        build_exogenous_x,
    )

    from polyagora_v63_partner_engine import _proxy_drawdown

    drivers = drivers or V74DriverConfig()
    base_cfg = v62_cfg or V62EngineConfig()

    X = build_exogenous_x(market, base_cfg).sort_index()
    mom_pnl_full = _synth_mom_pnl(realized).sort_index()
    proxy_dd_full = _proxy_drawdown(realized).sort_index()

    cat_mult = _category_multipliers(drivers)
    halflife = max(0.5, zone_smoothing_halflife / max(1e-3, drivers.recovery_aggression))
    alpha = 1.0 - float(np.exp(-np.log(2.0) / halflife))

    state: dict[str, float | None] = {"last_g_smooth": None, "last_Q": None}
    diagnostics: list[dict] = []

    def _equal_live(live: list[str]) -> pd.Series:
        if not live:
            return pd.Series(dtype=float)
        return pd.Series(1.0 / len(live), index=live)

    def _signal(history: pd.DataFrame, live: list[str], _cfg: V63EngineConfig) -> pd.Series:
        t = history.index[-1]

        # X_t — already shift(feature_lag)-ed inside build_exogenous_x.
        x_idx = X.index.asof(t)
        if pd.isna(x_idx):
            return _equal_live(live)
        coord = _coordinate_from_x(X.loc[x_idx])
        V_, T_, G_, C_, R_ = coord
        d_RP = float(np.max(np.abs(coord)))  # ∞-norm distance to ∂RP

        adm = _admissibility(coord)

        # W_t — rolling empirical from realized rows ≤ t-1.
        history_lag = history.iloc[:-1]
        if t in mom_pnl_full.index:
            mom_pnl_lag = mom_pnl_full.loc[:t].iloc[:-1]
        else:
            mom_pnl_lag = mom_pnl_full
        R_emp = _empirical_survival(history_lag, mom_pnl_lag, survival_window)
        W = lam * S_PRIOR + (1.0 - lam) * R_emp

        # Local Star.
        star_name, members, Q, gamma, mu = _select_local_star(adm, W)
        last_Q = state["last_Q"]
        dQ = abs(Q - last_Q) if last_Q is not None else 0.0
        state["last_Q"] = Q

        # Proxy DD ≤ t-1 (anti-hindsight).
        if t in proxy_dd_full.index:
            dd_lag = proxy_dd_full.loc[:t].iloc[:-1]
            proxy_dd = float(dd_lag.iloc[-1]) if len(dd_lag) else 0.0
        else:
            proxy_dd = 0.0

        # Zone.
        Z = _classify_zone(gamma, mu, coord, dQ, drivers, proxy_dd=proxy_dd)
        g_raw = ZONE_GROSS_BASE[Z]
        last_g = state["last_g_smooth"]
        g_smooth = (alpha * g_raw + (1.0 - alpha) * last_g) if last_g is not None else g_raw
        state["last_g_smooth"] = g_smooth

        # Strategy-level scores: only Local Star members participate.
        member_set = set(members)
        p: dict[str, float] = {}
        for s in STRATEGIES:
            if s in member_set:
                p[s] = adm[s] * cat_mult[CATEGORY[s]]  # q_i ≡ 1 (spec §15)
            else:
                p[s] = 0.0
        total = sum(p.values())
        if total < 1e-12:
            diagnostics.append({
                "date": t, "V": V_, "T": T_, "G": G_, "C": C_, "R": R_,
                "d_RP": d_RP, "Z": Z, "g_zone_raw": g_raw, "g_zone": g_smooth,
                "Q_star": Q, "gamma_star": gamma, "mu_star": mu,
                "block_star": star_name, "fallback": "neutral",
            })
            return _equal_live(live)
        w_strategy = {s: g_smooth * p[s] / total for s in STRATEGIES}

        # Decompose MOM12-1 into live constituents (long-only positive momentum).
        # Track per-asset MOM contribution for the dashboard "internal view".
        w_mom = w_strategy.pop(MOM_NAME, 0.0)
        mom_contrib: dict[str, float] = {a: 0.0 for a in live}
        if w_mom > 1e-12:
            mom_port = _momentum_portfolio(history, live)
            for a in live:
                share = w_mom * float(mom_port.get(a, 0.0))
                mom_contrib[a] = share
                w_strategy[a] = w_strategy.get(a, 0.0) + share

        out = pd.Series({a: w_strategy.get(a, 0.0) for a in live})

        diagnostics.append({
            "date": t,
            "V": V_, "T": T_, "G": G_, "C": C_, "R": R_, "d_RP": d_RP,
            "block_star": star_name, "Q_star": Q,
            "gamma_star": gamma, "mu_star": mu, "dQ": dQ,
            "Z": Z, "g_zone_raw": g_raw, "g_zone": g_smooth,
            "A_persistence": adm["ES"], "A_carry": adm["TN"],
            "A_defensive": adm["GC"], "A_convexity": adm["SI"],
            "A_stress":     adm["CL"], "A_mom": adm[MOM_NAME],
            "w_mom": w_mom, "gross": float(out.abs().sum()),
            **{f"mom_{a}": v for a, v in mom_contrib.items()},
        })
        return out

    def diagnostics_df() -> pd.DataFrame:
        if not diagnostics:
            return pd.DataFrame()
        return pd.DataFrame(diagnostics).set_index("date")

    _signal.diagnostics = diagnostics              # type: ignore[attr-defined]
    _signal.diagnostics_df = diagnostics_df        # type: ignore[attr-defined]
    return _signal
