"""
PolyAgora V6.2 — Alignment-Driven Runtime Allocation Engine
===========================================================

Canonical root-level engine generated from the V6.2 production package.

Core rule:
    w_t = f(X_{t-1}^{market}, S_{t-1}^{strategy}, A_t)

where:
    X_{t-1}^{market} is built only from VIX, SPY, HYG, TLT, GLD, CPER.
    S_{t-1}^{strategy} is the trailing Survival Matrix over strategies.
    A_t is X-SM alignment.

Main entry points:
    load_market_csv(path)
    load_strategy_returns_csv(path)
    run_backtest(market_df, strategy_returns_df, EngineConfig())
    summary_row(name, returns, equity)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional
from pathlib import Path
import numpy as np
import pandas as pd




# =============================================================================
# MODULE: config.py
# =============================================================================



AGOR_STRATEGIES: List[str] = [
    "Backwardation Carry",
    "Low Volatility",
    "ORB Baseline",
    "UK FTSE 350 HiLo Vol L/S",
    "VIX Roll Yield",
    "Bloomberg Europe 600 LS Momentum",
    "Contango Roll Carry",
    "Cross Sectional Trend Factor",
    "FTW US Buyback LS Factor",
    "G10 FX Carry",
    "Gold-Copper Ratio MR",
    "Long-Short Momentum",
    "Long-Only Momentum",
]


@dataclass(frozen=True)
class BlockSpec:
    name: str
    label: str
    vertex: np.ndarray
    anchors: List[str]
    is_boundary: bool = False


BLOCKS: Dict[str, BlockSpec] = {
    "A": BlockSpec(
        name="A",
        label="Vol-Carry",
        vertex=np.array([-0.40, 0.00, 0.00, +0.50, 0.00]),
        anchors=["G10 FX Carry", "UK FTSE 350 HiLo Vol L/S", "Low Volatility"],
    ),
    "B": BlockSpec(
        name="B",
        label="Commodity Stress",
        vertex=np.array([+0.40, -0.20, +0.70, -0.30, +0.40]),
        anchors=["Cross Sectional Trend Factor", "FTW US Buyback LS Factor", "Gold-Copper Ratio MR"],
    ),
    "C": BlockSpec(
        name="C",
        label="Momentum",
        vertex=np.array([-0.20, +0.70, 0.00, +0.30, 0.00]),
        anchors=["Bloomberg Europe 600 LS Momentum", "Long-Short Momentum", "Long-Only Momentum"],
    ),
    "D": BlockSpec(
        name="D",
        label="Low Volatility",
        vertex=np.array([-0.70, +0.10, 0.00, +0.60, -0.10]),
        anchors=["Low Volatility", "G10 FX Carry", "FTW US Buyback LS Factor"],
    ),
    "G": BlockSpec(
        name="G",
        label="Boundary",
        vertex=np.array([+0.90, -0.50, +0.50, -0.70, 0.00]),
        anchors=["VIX Roll Yield"],
        is_boundary=True,
    ),
}


@dataclass
class EngineConfig:
    # Feature engineering
    trend_window: int = 63
    feature_lag: int = 1
    boundary_vix: float = 35.0

    # Star zones
    zone1_star_threshold: float = 0.58
    zone2_star_threshold: float = 0.34
    star_delta_window: int = 5

    # Payoff calibration
    payoff_lookback: int = 504
    min_regime_obs: int = 40
    sigma_penalty: float = 0.55
    drawdown_penalty: float = 0.50
    anchor_boost: float = 0.05
    overlay_top_k: int = 4
    overlay_temperature: float = 0.35

    # Allocation
    max_core_weight: float = 0.45
    max_overlay_weight: float = 0.50

    # Governor
    soft_dd: float = 0.08
    hard_dd: float = 0.17
    hard_min_scale: float = 0.07
    buffer_floor: float = 0.25
    target_vol: float = 0.16
    vol_floor: float = 0.15
    boundary_max_scale: float = 0.20
    transaction_cost_bps: float = 10.0

    # Pre-emptive market risk governor
    vix_soft: float = 26.0
    vix_hard: float = 34.0
    stress_soft: float = 0.48
    stress_hard: float = 0.82
    min_market_risk_scale: float = 0.22

    # Dynamic SM micro-blocks
    enable_sm_microblocks: bool = True
    sm_window: int = 126
    sm_min_obs: int = 40
    sm_threshold: float = 0.62

    # V6.2 X-SM alignment amplifier
    enable_x_sm_alignment: bool = True
    alignment_floor: float = 0.55
    alignment_boost: float = 0.85
    min_alignment_to_amplify: float = 0.55

    # Driver controls
    driver_alpha: float = 1.0  # 0 conservative, 1 balanced, >1 aggressive
    driver_risk: float = 1.0   # <1 conservative, 1 balanced, >1 aggressive
    alignment_dimmer: float = 1.0  # 0 neutralizes alignment, 1 baseline, >1 stronger


# =============================================================================
# MODULE: features.py
# =============================================================================



REQUIRED_RAW_MARKET = ["VIX", "SPY", "HYG", "TLT", "GLD", "CPER"]
REQUIRED_X = ["vix", "spy_trend_63d", "gold_copper_ratio", "hyg_trend_63d", "tlt_trend_63d"]


def build_exogenous_x(market: pd.DataFrame, cfg: EngineConfig) -> pd.DataFrame:
    """
    Build X_{t-1}^{market} using only exogenous market instruments.

    No AGUR strategy returns are used here.
    """
    missing = set(REQUIRED_RAW_MARKET) - set(market.columns)
    if missing:
        raise ValueError(f"Missing market columns: {sorted(missing)}")

    X = pd.DataFrame(index=market.index)
    X["vix"] = pd.to_numeric(market["VIX"], errors="coerce")
    X["spy_trend_63d"] = pd.to_numeric(market["SPY"], errors="coerce").pct_change(cfg.trend_window)
    X["gold_copper_ratio"] = pd.to_numeric(market["GLD"], errors="coerce") / pd.to_numeric(market["CPER"], errors="coerce")
    X["hyg_trend_63d"] = pd.to_numeric(market["HYG"], errors="coerce").pct_change(cfg.trend_window)
    X["tlt_trend_63d"] = pd.to_numeric(market["TLT"], errors="coerce").pct_change(cfg.trend_window)

    X = X.shift(cfg.feature_lag).dropna()
    validate_x(X)
    return X


def validate_x(X: pd.DataFrame) -> None:
    missing = set(REQUIRED_X) - set(X.columns)
    if missing:
        raise ValueError(f"Missing X columns: {sorted(missing)}")
    for col in REQUIRED_X:
        if not np.isfinite(X[col].dropna()).all():
            raise ValueError(f"Non-finite values found in X column: {col}")


def compute_coordinate(x_row: pd.Series) -> np.ndarray:
    """Convert X-row into bounded Reference Polygon coordinate."""
    V = np.tanh((float(x_row["vix"]) - 18.0) / 10.0)
    T = np.tanh(5.0 * float(x_row["spy_trend_63d"]))
    G = np.tanh(2.0 * (float(x_row["gold_copper_ratio"]) - 4.5) / 4.5)
    C = np.tanh(10.0 * float(x_row["hyg_trend_63d"]))
    R = -np.tanh(5.0 * float(x_row["tlt_trend_63d"]))
    return np.array([V, T, G, C, R])


# =============================================================================
# MODULE: geometry.py
# =============================================================================



def softmax(scores: Dict[str, float], temperature: float = 0.35) -> Dict[str, float]:
    keys = list(scores.keys())
    vals = np.array([scores[k] for k in keys], dtype=float)
    vals = vals / max(temperature, 1e-9)
    vals -= vals.max()
    expv = np.exp(vals)
    probs = expv / expv.sum()
    return {k: float(v) for k, v in zip(keys, probs)}


def block_scores_from_x(x: np.ndarray, *, boundary_active: bool = False) -> Dict[str, float]:
    """g_b(X): Reference Polygon membership scores."""
    if boundary_active:
        return {b: (1.0 if b == "G" else 0.0) for b in BLOCKS}

    V, T, Gc, C, R = x
    raw = {}

    for name, block in BLOCKS.items():
        if block.is_boundary:
            continue
        raw[name] = -float(np.linalg.norm(x - block.vertex))

    raw["A"] += 0.35 * C - 0.20 * abs(V) - 0.10 * max(Gc, 0)
    raw["B"] += 0.45 * max(V, 0) + 0.45 * max(Gc, 0) + 0.30 * max(R, 0) - 0.25 * C
    raw["C"] += 0.60 * max(T, 0) + 0.15 * C - 0.20 * max(V - 0.6, 0)
    raw["D"] += 0.50 * max(-V, 0) + 0.25 * C + 0.15 * max(-R, 0)

    probs = softmax(raw, temperature=0.35)
    probs["G"] = 0.0
    return probs


def classify_block(x_row: pd.Series, cfg: EngineConfig) -> Tuple[str, Dict[str, float]]:
    boundary = float(x_row["vix"]) >= cfg.boundary_vix
    coord = compute_coordinate(x_row)
    scores = block_scores_from_x(coord, boundary_active=boundary)
    block = max(scores, key=scores.get)
    return block, scores


def build_block_history(X: pd.DataFrame, cfg: EngineConfig) -> Tuple[pd.Series, pd.DataFrame]:
    blocks = []
    score_rows = []
    for date in X.index:
        b, scores = classify_block(X.loc[date], cfg)
        blocks.append(b)
        score_rows.append(scores)
    return pd.Series(blocks, index=X.index), pd.DataFrame(score_rows, index=X.index).fillna(0.0)


# =============================================================================
# MODULE: zones.py
# =============================================================================



def star_zone(
    market_scores: pd.DataFrame,
    date: pd.Timestamp,
    block: str,
    cfg: EngineConfig,
) -> Tuple[str, float, float]:
    """
    Three semantic star zones:
    Zone 1 — strong star / exploitation
    Zone 2 — transition / fading-emerging star
    Zone 3 — defensive / pre-star
    """
    strength = float(market_scores.loc[date, block])
    idx = market_scores.index.get_loc(date)
    if isinstance(idx, slice):
        idx = idx.start
    prev_idx = max(0, idx - cfg.star_delta_window)
    prev_date = market_scores.index[prev_idx]
    prev_strength = float(market_scores.loc[prev_date, block])
    delta = strength - prev_strength

    if strength >= cfg.zone1_star_threshold and delta >= -0.08:
        return "zone1_star", strength, delta
    if strength >= cfg.zone2_star_threshold:
        return "zone2_transition", strength, delta
    return "zone3_defensive", strength, delta


def zone_mix(zone: str, delta_strength: float, cfg: EngineConfig) -> tuple[float, float, float]:
    """
    Returns overlay_alpha, gross_base, gross_boost.
    """
    driver_alpha = cfg.driver_alpha

    if zone == "zone1_star":
        alpha = (0.45 + 0.20 * max(delta_strength, 0.0)) * driver_alpha
        return min(max(alpha, 0.35), 0.75), 0.88, 0.35

    if zone == "zone2_transition":
        alpha = (0.20 + 0.15 * max(delta_strength, 0.0)) * driver_alpha
        return min(max(alpha, 0.10), 0.45), 0.62, 0.20

    return 0.05 * driver_alpha, 0.25, 0.05


# =============================================================================
# MODULE: survival_cluster.py
# =============================================================================



def rolling_survival_matrix(
    strategy_returns: pd.DataFrame,
    *,
    window: int = 126,
    min_obs: int = 40,
) -> pd.DataFrame:
    """
    Continuous Survival Matrix S_t.

    S_t(i,j) is high when strategies i and j can co-survive:
      - not jointly negative too often,
      - positively co-performing,
      - not destructively correlated.

    This is NOT used to define the top-level market block.
    It is used to discover micro-blocks inside the active block.
    """
    r = strategy_returns.reindex(columns=AGOR_STRATEGIES).tail(window).fillna(0.0)
    S = pd.DataFrame(0.0, index=AGOR_STRATEGIES, columns=AGOR_STRATEGIES)

    if len(r) < min_obs:
        return pd.DataFrame(
            np.eye(len(AGOR_STRATEGIES), dtype=float),
            index=AGOR_STRATEGIES,
            columns=AGOR_STRATEGIES,
        )

    X = r.values.astype(float)
    with np.errstate(divide="ignore", invalid="ignore"):
        corr = np.corrcoef(X, rowvar=False)
    corr = np.nan_to_num(corr, nan=0.0, posinf=0.0, neginf=0.0)

    neg = (X < 0).astype(float)
    pos = (X > 0).astype(float)

    corr_score = (corr + 1.0) / 2.0
    joint_bad = neg.T @ neg / len(r)
    co_pos = pos.T @ pos / len(r)

    score = 0.40 * corr_score + 0.40 * (1.0 - joint_bad) + 0.20 * co_pos
    score = np.clip(score, 0.0, 1.0)
    np.fill_diagonal(score, 1.0)

    S.loc[:, :] = score
    return S


def graph_microblocks(
    S: pd.DataFrame,
    candidates: List[str],
    *,
    threshold: float = 0.62,
    min_cluster_size: int = 1,
) -> List[List[str]]:
    """
    Discover dynamic micro-blocks from S_t inside the active top-level block.

    Implementation:
        strategies are graph nodes;
        edge exists if S_t(i,j) >= threshold;
        micro-blocks are connected components.

    This is deliberately dependency-light and production-safe.
    """
    candidates = [s for s in candidates if s in S.index]
    if not candidates:
        return []

    visited = set()
    clusters: List[List[str]] = []

    adj = {s: [] for s in candidates}
    for i, a in enumerate(candidates):
        for b in candidates[i+1:]:
            if float(S.loc[a, b]) >= threshold or float(S.loc[b, a]) >= threshold:
                adj[a].append(b)
                adj[b].append(a)

    for s in candidates:
        if s in visited:
            continue
        stack = [s]
        comp = []
        visited.add(s)
        while stack:
            u = stack.pop()
            comp.append(u)
            for v in adj[u]:
                if v not in visited:
                    visited.add(v)
                    stack.append(v)
        if len(comp) >= min_cluster_size:
            clusters.append(sorted(comp))

    # stable ordering: largest first, then alphabetical
    clusters.sort(key=lambda c: (-len(c), c[0]))
    return clusters


def microblock_star_scores(
    S: pd.DataFrame,
    clusters: List[List[str]],
) -> Dict[int, float]:
    """
    Local star score of a micro-block = worst-case internal co-survival.
    Singletons receive their diagonal survival = 1.0.
    """
    scores: Dict[int, float] = {}
    for k, cluster in enumerate(clusters):
        if len(cluster) == 1:
            scores[k] = float(S.loc[cluster[0], cluster[0]]) if cluster[0] in S.index else 1.0
            continue
        vals = []
        for a in cluster:
            for b in cluster:
                if a != b and a in S.index and b in S.columns:
                    vals.append(float(S.loc[a, b]))
        scores[k] = float(min(vals)) if vals else 0.0
    return scores


def allocate_across_microblocks(
    cluster_scores: Dict[int, float],
    *,
    temperature: float = 0.25,
) -> Dict[int, float]:
    """
    Allocate across micro-blocks using softmax over local star scores.
    """
    if not cluster_scores:
        return {}

    keys = list(cluster_scores.keys())
    vals = np.array([cluster_scores[k] for k in keys], dtype=float)
    vals = vals - vals.max()
    e = np.exp(vals / max(temperature, 1e-9))
    w = e / e.sum()
    return {k: float(v) for k, v in zip(keys, w)}


def cluster_aware_weights(
    base_weights: Dict[str, float],
    S: pd.DataFrame,
    candidates: List[str],
    *,
    threshold: float = 0.62,
) -> Tuple[Dict[str, float], dict]:
    """
    Transform ordinary strategy weights into cluster-aware weights.

    Purpose:
        Avoid over-concentrating in one noisy local star.
        Allocate across dynamic SM micro-blocks first, then inside each cluster.

    Returns:
        adjusted_weights, diagnostics
    """
    candidates = [s for s in candidates if s in AGOR_STRATEGIES]
    clusters = graph_microblocks(S, candidates, threshold=threshold)

    if not clusters:
        return base_weights, {
            "microblocks": [],
            "microblock_scores": {},
            "microblock_weights": {},
            "sm_threshold": threshold,
        }

    scores = microblock_star_scores(S, clusters)
    cluster_w = allocate_across_microblocks(scores)

    adjusted: Dict[str, float] = {}

    for k, cluster in enumerate(clusters):
        cw = cluster_w.get(k, 0.0)
        # preserve within-cluster preference from base weights if available
        base = {s: max(float(base_weights.get(s, 0.0)), 0.0) for s in cluster}
        total = sum(base.values())
        if total <= 0:
            for s in cluster:
                adjusted[s] = adjusted.get(s, 0.0) + cw / len(cluster)
        else:
            for s in cluster:
                adjusted[s] = adjusted.get(s, 0.0) + cw * base[s] / total

    total_adj = sum(adjusted.values())
    if total_adj > 0:
        adjusted = {s: v / total_adj for s, v in adjusted.items()}

    diagnostics = {
        "microblocks": clusters,
        "microblock_scores": scores,
        "microblock_weights": cluster_w,
        "sm_threshold": threshold,
    }
    return adjusted, diagnostics


# ---------------------------------------------------------------------------
# V6.2: X-SM Alignment
# ---------------------------------------------------------------------------

def strategy_block_membership(blocks: dict) -> Dict[str, List[str]]:
    """
    Reverse map: strategy -> top-level blocks where it is an anchor/member.
    """
    out: Dict[str, List[str]] = {s: [] for s in AGOR_STRATEGIES}
    for b, spec in blocks.items():
        anchors = getattr(spec, "anchors", [])
        for s in anchors:
            if s in out:
                out[s].append(b)
    return out


def compute_x_sm_alignment(
    active_block: str,
    clusters: List[List[str]],
    cluster_weights: Dict[int, float],
    blocks: dict,
) -> float:
    """
    Alignment A_t between exogenous geometry X_{t-1} and Survival Matrix micro-structure.

    A_t is high when the SM-discovered micro-blocks are populated by strategies
    that semantically belong to the active X-selected block.

    This is honest:
        X uses exogenous market data up to t-1.
        S_t uses strategy returns only up to t-1.
        Alignment is computed at runtime without future returns.
    """
    if not clusters or not cluster_weights:
        return 0.0

    membership = strategy_block_membership(blocks)
    aligned_mass = 0.0
    total_mass = 0.0

    for k, cluster in enumerate(clusters):
        cw = float(cluster_weights.get(k, 0.0))
        if cw <= 0:
            continue

        total_mass += cw

        # cluster alignment = fraction of cluster strategies belonging to active block
        if not cluster:
            continue
        frac = sum(1.0 for s in cluster if active_block in membership.get(s, [])) / len(cluster)
        aligned_mass += cw * frac

    if total_mass <= 0:
        return 0.0

    return float(max(0.0, min(1.0, aligned_mass / total_mass)))


def alignment_multiplier(
    alignment: float,
    *,
    floor: float = 0.55,
    boost: float = 0.75,
    dimmer: float = 1.0,
    min_alignment_to_amplify: float = 0.55,
) -> float:
    """
    Convert A_t into the nonlinear gross/alpha multiplier f(A_t; gamma).

    The alignment dimmer gamma interpolates around a neutral multiplier of 1:
    gamma=0 removes the alignment effect, gamma=1 is the production baseline,
    and gamma>1 increases sensitivity.

    Low alignment suppresses convex expression. High alignment amplifies the
    local star.
    """
    a = max(0.0, min(1.0, float(alignment)))
    gamma = max(0.0, min(2.0, float(dimmer)))
    raw = floor + boost * a

    if a < min_alignment_to_amplify:
        raw = max(0.35, raw * 0.70)

    return float(1.0 + gamma * (raw - 1.0))


def driver_risk_multiplier(cfg: EngineConfig) -> float:
    """Risk Dial: scale total expression without changing strategy ranking."""
    return float(np.clip(cfg.driver_risk, 0.25, 1.50))


# =============================================================================
# MODULE: allocation.py
# =============================================================================



def maxdd_from_returns(r: pd.Series) -> float:
    eq = (1.0 + r.fillna(0.0)).cumprod()
    return float((eq / eq.cummax() - 1.0).min())


def inverse_vol_weights(hist: pd.DataFrame, names: List[str], cfg: EngineConfig) -> Dict[str, float]:
    names = [s for s in names if s in hist.columns]
    if not names:
        return {}

    h = hist[names].dropna(how="all")
    if len(h) < 30:
        return {s: 1.0 / len(names) for s in names}

    vol = h.std().replace(0.0, np.nan)
    inv = (1.0 / (vol + 1e-6)).replace([np.inf, -np.inf], np.nan).fillna(0.0)

    if inv.sum() <= 0:
        return {s: 1.0 / len(names) for s in names}

    w = inv / inv.sum()
    w = w.clip(upper=cfg.max_core_weight)
    w = w / w.sum()
    return {k: float(v) for k, v in w.items()}


def payoff_scores(strategy_returns: pd.DataFrame, market_blocks: pd.Series, date: pd.Timestamp, block: str, cfg: EngineConfig) -> Dict[str, float]:
    hist_index = strategy_returns.loc[:date].iloc[:-1].tail(cfg.payoff_lookback).index
    same_block = hist_index[market_blocks.reindex(hist_index).eq(block)]

    if len(same_block) < cfg.min_regime_obs:
        return {}

    hist = strategy_returns.loc[same_block, AGOR_STRATEGIES].fillna(0.0)
    scores = {}

    for s in AGOR_STRATEGIES:
        r = hist[s].dropna()
        if len(r) < cfg.min_regime_obs:
            continue
        ann_ret = float(r.mean() * 252)
        ann_vol = float(r.std() * np.sqrt(252))
        mdd = abs(maxdd_from_returns(r))
        scores[s] = ann_ret - cfg.sigma_penalty * ann_vol - cfg.drawdown_penalty * mdd

    for s in BLOCKS[block].anchors:
        if s in scores:
            scores[s] += cfg.anchor_boost

    return scores


def convex_overlay(scores: Dict[str, float], cfg: EngineConfig) -> Dict[str, float]:
    if not scores:
        return {}

    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:cfg.overlay_top_k]
    names = [x[0] for x in ranked]
    vals = np.array([x[1] for x in ranked], dtype=float)
    vals -= vals.max()

    q = np.exp(vals / max(cfg.overlay_temperature, 1e-9))
    q = q / q.sum()
    q = np.minimum(q, cfg.max_overlay_weight)
    q = q / q.sum()

    return {s: float(w) for s, w in zip(names, q)}


def blend(core: Dict[str, float], overlay: Dict[str, float], overlay_alpha: float) -> Dict[str, float]:
    names = sorted(set(core) | set(overlay))
    if not names:
        return {}

    w = {s: (1.0 - overlay_alpha) * core.get(s, 0.0) + overlay_alpha * overlay.get(s, 0.0) for s in names}
    total = sum(max(v, 0.0) for v in w.values())
    if total <= 0:
        return {}
    return {s: max(v, 0.0) / total for s, v in w.items()}


def raw_allocation(strategy_returns: pd.DataFrame, market_blocks: pd.Series, market_scores: pd.DataFrame, date: pd.Timestamp, cfg: EngineConfig) -> tuple[pd.Series, dict]:
    """
    Build raw portfolio before governor.
    """
    weights = pd.Series(0.0, index=AGOR_STRATEGIES + ["CASH"])
    block = market_blocks.loc[date]

    if block == "G":
        weights["VIX Roll Yield"] = 0.18
        weights["CASH"] = 0.82
        return weights, {
            "block": block,
            "zone": "boundary",
            "star_strength": 1.0,
            "overlay_alpha": 0.0,
            "gross": 0.18,
            "driver_alpha": cfg.driver_alpha,
            "driver_risk": cfg.driver_risk,
            "alignment_dimmer": cfg.alignment_dimmer,
            "driver_risk_multiplier": driver_risk_multiplier(cfg),
        }

    hist = strategy_returns.loc[:date].iloc[:-1].tail(126)
    zone, strength, delta = star_zone(market_scores, date, block, cfg)
    overlay_alpha, gross_base, gross_boost = zone_mix(zone, delta, cfg)

    anchors = [s for s in BLOCKS[block].anchors if s in AGOR_STRATEGIES]
    core = inverse_vol_weights(hist, anchors, cfg)

    scores = payoff_scores(strategy_returns, market_blocks, date, block, cfg)
    overlay = convex_overlay(scores, cfg)

    if not core and not overlay:
        if anchors:
            core = {s: 1.0 / len(anchors) for s in anchors}
            overlay = core.copy()
        else:
            weights["CASH"] = 1.0
            return weights, {"block": block, "zone": zone, "star_strength": strength, "overlay_alpha": 0.0, "gross": 0.0}

    if not core:
        core = overlay.copy()
    if not overlay:
        overlay = core.copy()

    combined = blend(core, overlay, overlay_alpha)
    if not combined:
        weights["CASH"] = 1.0
        return weights, {"block": block, "zone": zone, "star_strength": strength, "overlay_alpha": overlay_alpha, "gross": 0.0}

    # V6.1/V6.2: dynamic SM micro-blocks inside the active top-level block.
    # Top-level block remains fixed by exogenous X_{t-1};
    # internal structure adapts through S_t.
    sm_diag = {}
    alignment = 0.0
    align_mult = 1.0

    if cfg.enable_sm_microblocks:
        S_t = rolling_survival_matrix(
            strategy_returns.loc[:date].iloc[:-1],
            window=cfg.sm_window,
            min_obs=cfg.sm_min_obs,
        )
        candidates = sorted(set(anchors) | set(combined.keys()))
        combined, sm_diag = cluster_aware_weights(
            combined,
            S_t,
            candidates,
            threshold=cfg.sm_threshold,
        )

        if cfg.enable_x_sm_alignment:
            alignment = compute_x_sm_alignment(
                block,
                sm_diag.get("microblocks", []),
                sm_diag.get("microblock_weights", {}),
                BLOCKS,
            )
            align_mult = alignment_multiplier(
                alignment,
                floor=cfg.alignment_floor,
                boost=cfg.alignment_boost,
                dimmer=cfg.alignment_dimmer,
                min_alignment_to_amplify=cfg.min_alignment_to_amplify,
            )

    # V6.2 alpha amplification:
    # Gross is amplified only when X-selected geometry and SM micro-structure agree.
    gross = gross_base + gross_boost * max(strength - cfg.zone2_star_threshold, 0.0)

    if cfg.enable_x_sm_alignment:
        gross *= align_mult
    # No-leverage invariant: zone caps must stay <= 1.0 so that
    # sum(strategy weights) + CASH = 1 with CASH >= 0.
    if zone == "zone1_star":
        gross = float(np.clip(gross, 0.75, 1.00))
    elif zone == "zone2_transition":
        gross = float(np.clip(gross, 0.45, 0.80))
    else:
        gross = float(np.clip(gross, 0.15, 0.35))
    gross *= driver_risk_multiplier(cfg)
    # Risk dial (clamped to 1.50) can re-leverage above 1.0; clamp again to preserve invariant.
    gross = min(gross, 1.0)

    for s, w in combined.items():
        weights[s] = gross * w

    weights["CASH"] = max(0.0, 1.0 - weights[AGOR_STRATEGIES].sum())
    meta = {
        "block": block,
        "zone": zone,
        "star_strength": strength,
        "delta_strength": delta,
        "overlay_alpha": overlay_alpha,
        "gross": gross,
        "sm_microblocks": sm_diag.get("microblocks", []),
        "sm_microblock_scores": sm_diag.get("microblock_scores", {}),
        "sm_microblock_weights": sm_diag.get("microblock_weights", {}),
        "sm_threshold": sm_diag.get("sm_threshold", None),
        "x_sm_alignment": alignment,
        "alignment_multiplier": align_mult,
        "driver_alpha": cfg.driver_alpha,
        "driver_risk": cfg.driver_risk,
        "alignment_dimmer": cfg.alignment_dimmer,
        "driver_risk_multiplier": driver_risk_multiplier(cfg),
    }
    return weights, meta


# =============================================================================
# MODULE: governor.py
# =============================================================================



def drawdown_scale(current_dd: float, cfg: EngineConfig) -> Tuple[float, str]:
    dd = abs(float(current_dd))

    if dd <= cfg.soft_dd:
        return 1.0, "soft"

    if dd <= cfg.hard_dd:
        frac = (dd - cfg.soft_dd) / max(cfg.hard_dd - cfg.soft_dd, 1e-9)
        return max(cfg.buffer_floor, 1.0 - frac * (1.0 - cfg.buffer_floor)), "buffer"

    return cfg.hard_min_scale, "hard"


def vol_scale(raw_weights: pd.Series, hist_returns: pd.DataFrame, cfg: EngineConfig) -> float:
    if hist_returns.empty:
        return 1.0

    basket = (hist_returns.reindex(columns=AGOR_STRATEGIES).fillna(0.0) * raw_weights[AGOR_STRATEGIES]).sum(axis=1)
    rv = float(basket.std() * np.sqrt(252))

    if not np.isfinite(rv) or rv <= 1e-9:
        return 1.0

    return max(cfg.vol_floor, min(1.0, cfg.target_vol / rv))


def market_risk_scale(x_row: pd.Series, cfg: EngineConfig) -> Tuple[float, str]:
    vix = float(x_row["vix"])
    spy = float(x_row["spy_trend_63d"])
    gc = float(x_row["gold_copper_ratio"])
    hyg = float(x_row["hyg_trend_63d"])

    vix_stress = np.clip((vix - cfg.vix_soft) / max(cfg.vix_hard - cfg.vix_soft, 1e-9), 0.0, 1.0)
    gc_stress = np.clip((gc - 4.5) / 1.2, 0.0, 1.0)
    trend_stress = np.clip(-spy / 0.12, 0.0, 1.0)
    credit_stress = np.clip(-hyg / 0.08, 0.0, 1.0)

    composite = 0.40 * vix_stress + 0.25 * gc_stress + 0.20 * credit_stress + 0.15 * trend_stress

    if composite <= cfg.stress_soft:
        return 1.0, "market_soft"

    if composite >= cfg.stress_hard:
        return cfg.min_market_risk_scale, "market_hard"

    frac = (composite - cfg.stress_soft) / max(cfg.stress_hard - cfg.stress_soft, 1e-9)
    scale = 1.0 - frac * (1.0 - cfg.min_market_risk_scale)
    return float(np.clip(scale, cfg.min_market_risk_scale, 1.0)), "market_buffer"


def apply_governor(raw_weights: pd.Series, hist_returns: pd.DataFrame, current_dd: float, x_row: pd.Series, cfg: EngineConfig) -> tuple[pd.Series, dict]:
    dd_s, dd_zone = drawdown_scale(current_dd, cfg)
    vol_s = vol_scale(raw_weights, hist_returns, cfg)
    mr_s, mr_zone = market_risk_scale(x_row, cfg)

    boundary = float(x_row["vix"]) >= cfg.boundary_vix

    if boundary:
        scale = min(dd_s, vol_s, mr_s, cfg.boundary_max_scale)
        governor_zone = "boundary_hard"
    else:
        scale = min(dd_s, vol_s, mr_s)
        if scale == dd_s and dd_zone != "soft":
            governor_zone = dd_zone
        elif scale == mr_s and mr_zone != "market_soft":
            governor_zone = mr_zone
        elif scale == vol_s and vol_s < 1.0:
            governor_zone = "vol_buffer"
        else:
            governor_zone = "soft"

    governed = pd.Series(0.0, index=AGOR_STRATEGIES + ["CASH"])
    governed[AGOR_STRATEGIES] = raw_weights[AGOR_STRATEGIES] * scale
    governed["CASH"] = max(0.0, 1.0 - governed[AGOR_STRATEGIES].sum())

    meta = {"scale": scale, "governor_zone": governor_zone, "dd_scale": dd_s, "vol_scale": vol_s, "market_risk_scale": mr_s}
    return governed, meta


# =============================================================================
# MODULE: dashboard.py
# =============================================================================



def dashboard_payload(date, x_row: pd.Series, allocation_meta: dict, governor_meta: dict, weights: pd.Series) -> dict:
    gross = float(weights[AGOR_STRATEGIES].sum())
    top_weights = weights[weights > 0].sort_values(ascending=False).head(8).to_dict()

    return {
        "date": str(pd.Timestamp(date).date()),
        "x_t_minus_1": {
            "vix": float(x_row["vix"]),
            "spy_trend_63d": float(x_row["spy_trend_63d"]),
            "gold_copper_ratio": float(x_row["gold_copper_ratio"]),
            "hyg_trend_63d": float(x_row["hyg_trend_63d"]),
            "tlt_trend_63d": float(x_row["tlt_trend_63d"]),
        },
        "block": allocation_meta.get("block"),
        "star_zone": allocation_meta.get("zone"),
        "star_strength": allocation_meta.get("star_strength"),
        "overlay_alpha": allocation_meta.get("overlay_alpha"),
        "gross": gross,
        "cash": float(weights.get("CASH", 0.0)),
        "governor": governor_meta,
        "top_weights": top_weights,
        "sm_microblocks": allocation_meta.get("sm_microblocks", []),
        "sm_microblock_scores": allocation_meta.get("sm_microblock_scores", {}),
        "sm_microblock_weights": allocation_meta.get("sm_microblock_weights", {}),
        "x_sm_alignment": allocation_meta.get("x_sm_alignment"),
        "alignment_multiplier": allocation_meta.get("alignment_multiplier"),
        "driver_controls": {
            "alpha": allocation_meta.get("driver_alpha"),
            "risk": allocation_meta.get("driver_risk"),
            "alignment_dimmer": allocation_meta.get("alignment_dimmer"),
            "risk_multiplier": allocation_meta.get("driver_risk_multiplier"),
        },
        "driver_instruction": instruction(allocation_meta, governor_meta),
    }


def instruction(allocation_meta: dict, governor_meta: dict) -> str:
    zone = allocation_meta.get("zone")
    gov = governor_meta.get("governor_zone")

    if gov in {"boundary_hard", "hard", "market_hard"}:
        return "Boundary or hard-risk state: reduce alpha pressure and preserve capital."
    if zone == "zone1_star":
        return "Star regime active: express alpha through convex overlay while monitoring boundary risk."
    if zone == "zone2_transition":
        return "Transition state: keep RP core dominant, allow only controlled convex tilt."
    if zone == "zone3_defensive":
        return "No stable star: defensive posture, wait for new admissible structure."
    return "Monitor structure; maintain governed allocation."


# =============================================================================
# MODULE: engine.py
# =============================================================================



@dataclass
class EngineStep:
    date: pd.Timestamp
    raw_weights: pd.Series
    final_weights: pd.Series
    allocation_meta: dict
    governor_meta: dict
    dashboard: dict


class PolyAgoraEngine:
    def __init__(self, cfg: EngineConfig | None = None):
        self.cfg = cfg or EngineConfig()

    def prepare_market(self, market: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series, pd.DataFrame]:
        X = build_exogenous_x(market, self.cfg)
        blocks, scores = build_block_history(X, self.cfg)
        return X, blocks, scores

    def decide(
        self,
        date: pd.Timestamp,
        strategy_returns: pd.DataFrame,
        X: pd.DataFrame,
        market_blocks: pd.Series,
        market_scores: pd.DataFrame,
        current_dd: float,
    ) -> EngineStep:
        raw_w, alloc_meta = raw_allocation(strategy_returns, market_blocks, market_scores, date, self.cfg)
        hist_returns = strategy_returns.loc[:date].iloc[:-1].tail(126)
        final_w, gov_meta = apply_governor(raw_w, hist_returns, current_dd, X.loc[date], self.cfg)
        dash = dashboard_payload(date, X.loc[date], alloc_meta, gov_meta, final_w)
        return EngineStep(date, raw_w, final_w, alloc_meta, gov_meta, dash)


# =============================================================================
# MODULE: backtest.py
# =============================================================================



@dataclass
class BacktestResult:
    equity: pd.Series
    returns: pd.Series
    weights: pd.DataFrame
    raw_weights: pd.DataFrame
    dashboard_log: list
    blocks: pd.Series
    market_scores: pd.DataFrame


def run_backtest(
    market: pd.DataFrame,
    strategy_returns: pd.DataFrame,
    cfg: EngineConfig | None = None,
    rebalance_freq: str = "W-FRI",
) -> BacktestResult:
    cfg = cfg or EngineConfig()
    engine = PolyAgoraEngine(cfg)

    strategy_returns = strategy_returns.reindex(columns=AGOR_STRATEGIES).fillna(0.0)
    X, blocks, market_scores = engine.prepare_market(market)

    common = strategy_returns.index.intersection(X.index)
    strategy_returns = strategy_returns.loc[common]
    X = X.loc[common]
    blocks = blocks.loc[common]
    market_scores = market_scores.loc[common]

    rebals = set(strategy_returns.resample(rebalance_freq).last().index.intersection(strategy_returns.index))

    weights = pd.DataFrame(0.0, index=strategy_returns.index, columns=AGOR_STRATEGIES + ["CASH"])
    raw_weights = pd.DataFrame(0.0, index=strategy_returns.index, columns=AGOR_STRATEGIES + ["CASH"])
    turnover = pd.Series(0.0, index=strategy_returns.index)

    current_w = pd.Series(0.0, index=AGOR_STRATEGIES + ["CASH"])
    current_w["CASH"] = 1.0
    equity_live = 1.0
    peak = 1.0
    dashboard_log = []

    for i, date in enumerate(strategy_returns.index):
        if i > 0:
            r_today = float((current_w[AGOR_STRATEGIES] * strategy_returns.loc[date, AGOR_STRATEGIES]).sum())
            equity_live *= (1.0 + r_today)
            peak = max(peak, equity_live)

        if date in rebals:
            current_dd = equity_live / peak - 1.0
            step = engine.decide(date, strategy_returns, X, blocks, market_scores, current_dd)
            turnover.loc[date] = float((step.final_weights[AGOR_STRATEGIES] - current_w[AGOR_STRATEGIES]).abs().sum())
            current_w = step.final_weights.copy()
            raw_weights.loc[date] = step.raw_weights
            dashboard_log.append(step.dashboard)

        weights.loc[date] = current_w

    aligned = weights.shift(1).fillna(0.0)
    costs = turnover * (cfg.transaction_cost_bps / 10000.0)
    portfolio_returns = (aligned[AGOR_STRATEGIES] * strategy_returns[AGOR_STRATEGIES]).sum(axis=1) - costs
    equity = (1.0 + portfolio_returns).cumprod()

    return BacktestResult(equity, portfolio_returns, weights, raw_weights, dashboard_log, blocks, market_scores)


# =============================================================================
# MODULE: metrics.py
# =============================================================================



def max_drawdown(equity: pd.Series) -> float:
    return float((equity / equity.cummax() - 1.0).min())


def cagr(equity: pd.Series) -> float:
    years = (equity.index[-1] - equity.index[0]).days / 365.25
    return float(equity.iloc[-1] ** (1.0 / years) - 1.0)


def annual_vol(returns: pd.Series) -> float:
    return float(returns.std() * np.sqrt(252))


def sharpe(returns: pd.Series) -> float:
    v = annual_vol(returns)
    return float((returns.mean() * 252) / v) if v > 0 else float("nan")


def summary_row(name: str, returns: pd.Series, equity: pd.Series) -> dict:
    return {
        "Series": name,
        "Total return": equity.iloc[-1] - 1,
        "CAGR": cagr(equity),
        "Ann. vol": annual_vol(returns),
        "Sharpe": sharpe(returns),
        "Max drawdown": max_drawdown(equity),
    }


# =============================================================================
# MODULE: data.py
# =============================================================================



def load_market_csv(path: str | Path) -> pd.DataFrame:
    """Load raw market panel: date, VIX, SPY, HYG, TLT, GLD, CPER."""
    df = pd.read_csv(path)
    if "date" not in df.columns:
        raise ValueError("Market CSV must contain a 'date' column.")
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    df = df.set_index("date").sort_index()
    return df


def load_strategy_returns_csv(path: str | Path) -> pd.DataFrame:
    """Load AGUR strategy returns panel indexed by date."""
    df = pd.read_csv(path)
    if "date" not in df.columns:
        raise ValueError("Strategy CSV must contain a 'date' column.")
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    df = df.set_index("date").sort_index()
    return df.apply(pd.to_numeric, errors="coerce").fillna(0.0)


if __name__ == "__main__":
    print("PolyAgora V6.2 single-file engine loaded.")
    print("Use run_backtest(market_df, strategy_returns_df, EngineConfig()).")
