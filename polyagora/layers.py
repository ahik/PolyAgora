"""PolyAgora Phase-II — Layer stubs (L2/L3/L4/L5/L5A) + the contraction map.

Phase 1 delivers the runtime *architecture*. Layers 2-5A are honest typed
stubs: each satisfies the execution-graph contract — `run(state, history)` —
and writes valid, neutral values into the state, but carries no behavior yet.
Every stub records a `state.log[...]` entry so the 13-step trace is fully
inspectable. Phases 3-4 replace these stubs with the real layers:

    Step 7   RecoverabilityGeometryStub   -> Phase 3  (Deliverable B / §4)
    Step 7A  ExposureRecoverabilityStub   -> Phase 3  (Deliverable A / §5)
    Step 9   MRTPSteeringStub             -> Phase 4  (Deliverable D / §6)
    Step 10  DynamicKellyStub             -> Phase 4  (Deliverable C / §7)
    Steps 8,11 ConvexitySleevesStub       -> Phase 4  (Deliverable B / §8)

The contraction map (Step 12) is implemented for real — it is small, in the
Runtime layer, and needed for the graph to produce a stable allocation.
"""

from __future__ import annotations

import pandas as pd


# =============================================================================
# Step 7 — Layer 5: Recoverability Geometry  (STUB)
# =============================================================================

class RecoverabilityGeometryStub:
    """Layer 5 stub. Leaves the neutral `R_t/C_t/F_t/P_t` defaults in place.

    Phase 3 implements the five estimators of Impl Spec §4.
    """

    def run(self, state, history):
        state.log["L5_recoverability"] = "stub: neutral R/C/F/P"
        return state


# =============================================================================
# Step 7A — Layer 5A: Exposure Recoverability Quality  (STUB)
# =============================================================================

class ExposureRecoverabilityStub:
    """Layer 5A stub. No exposures scored yet (no sleeves in Phase 1).

    Phase 3 implements the six-component geometric-mean ERQ of Impl Spec §5.
    """

    def run(self, state, history):
        state.erq = {}
        state.log["L5A_erq"] = "stub: no exposures scored"
        return state


# =============================================================================
# Step 9 — Layer 3: MRTP Steering  (STUB)
# =============================================================================

class MRTPSteeringStub:
    """Layer 3 stub. No trajectory scoring yet.

    Phase 4 implements `MRTP_i = a*R + b*C - c*F - d*P + e*ERQ` (Impl Spec §6,
    coefficients alpha=1.00 gamma=0.90 delta=0.75 beta=0.55 eta=0.45).
    """

    def run(self, state, history):
        state.mrtp = {}
        state.log["L3_mrtp"] = "stub: no trajectory scoring"
        return state


# =============================================================================
# Step 10 — Layer 4: Dynamic Kelly  (STUB)
# =============================================================================

class DynamicKellyStub:
    """Layer 4 stub. `f_t = 1.0` — no leverage expansion in Phase 1.

    Records the RUPTURE -> Kelly-FLOOR conditional branch in the trace, but
    does not act on it (expansion/contraction dynamics are Phase 4).
    Phase 4 implements `f_t = f(beta,R,F,C,ERQ)`, asymmetric, cap 1.25x.
    """

    def run(self, state, history):
        state.f_t = 1.0
        if state.vaidm_class == "RUPTURE":
            state.log["rupture_override"] = "VAIDM=RUPTURE -> Kelly FLOOR (Phase 4)"
        state.log["L4_kelly"] = f"stub: f_t={state.f_t:.2f}"
        return state


# =============================================================================
# Steps 8 & 11 — Layer 2: Convexity Sleeves  (STUB)
# =============================================================================

class ConvexitySleevesStub:
    """Layer 2 stub. ADD filtering (Step 8) is a passthrough; no sleeves are
    activated (Step 11). The base allocation flows through unchanged.

    Phase 4 implements the typed sleeve catalog + 6-gate admission pipeline
    (Impl Spec §8) and the per-zone sleeve-cap governance (§9).
    """

    def run_add(self, state, history):
        state.log["L2_add"] = "stub: ADD passthrough"
        return state

    def run_sleeves(self, state, history):
        state.pi_t = pd.Series(dtype=float)
        state.log["L2_sleeves"] = "stub: no sleeves activated"
        return state


# =============================================================================
# Step 12 — Contraction map (Runtime layer — implemented)
# =============================================================================

def contraction_map(
    target: pd.Series,
    prev: pd.Series | None,
    *,
    zone: str,
    block_changed: bool,
    lam: float = 0.40,
    tau: float = 0.60,
) -> pd.Series:
    """Banach contraction blend for block transitions (Impl Spec §2 Step 12).

    `w_new = lam*target + tau*prev` when the corridor is ambiguous — the
    active block just flipped, or the zone is BUFFER ("do not collapse
    possibility space too early"). Otherwise the target passes through.
    With `tau = 0.60` the map is a contraction (Lipschitz 0.60 < 1), so
    repeated application converges and damps whipsaw across transitions.
    """
    if prev is None:
        return target.copy()
    if zone == "BUFFER" or block_changed:
        idx = target.index.union(prev.index)
        t = target.reindex(idx).fillna(0.0)
        p = prev.reindex(idx).fillna(0.0)
        return lam * t + tau * p
    return target.copy()
