"""PolyAgora Phase-II — Layer 3: MRTP Convexity Scoring (Impl Spec §6).

Phase 4. Replaces `MRTPSteeringStub`. MRTP evolves from crisis steering to
admissible convex-trajectory governance:

    MRTP_t = alpha*R + beta*C - gamma*F - delta*P + eta*ERQ

with the PolygonEye coefficients (Answers to Questions, 2026-05-19):
alpha=1.00 (recoverability priority), gamma=0.90 (fragmentation aversion),
delta=0.75 (ridge-pressure sensitivity), beta=0.55 (expansion confidence),
eta=0.45 (recoverable-convexity preference — the "temptation dial").

The ordering alpha,gamma,delta > beta,eta encodes the sacred hierarchy
`Recoverability > Convexity > Return`. These are the *initial philosophical
configuration*, not final — Phase 5 calibrates them.

MRTP does not deform the allocation itself; it emits a convexity decision
that Layer 4 (Dynamic Kelly) consumes. It may modulate convex participation
within an admitted regime but never overrides the base allocation.
"""

from __future__ import annotations

# Initial coefficients (Impl Spec §6 / Open-Questions Q7). Phase 5 calibrates.
MRTP_COEFFICIENTS: dict[str, float] = {
    "alpha": 1.00,   # R — recoverability priority (supreme invariant)
    "beta":  0.55,   # C — expansion confidence (subordinate to survivability)
    "gamma": 0.90,   # F — fragmentation aversion (anti-chaos)
    "delta": 0.75,   # P — ridge-pressure sensitivity (anticipatory contraction)
    "eta":   0.45,   # ERQ — recoverable-convexity preference (evolve LAST)
}

# Convexity-decision thresholds on the MRTP score (provisional — Phase 5).
EXPAND_ABOVE = 0.65
CONTRACT_BELOW = 0.25


class MRTPSteering:
    """Layer 3. Scores `MRTP_t` and emits the convexity decision."""

    def __init__(self, coefficients: dict[str, float] | None = None) -> None:
        self.coef = dict(MRTP_COEFFICIENTS)
        if coefficients:
            self.coef.update(coefficients)

    def run(self, state, history):
        R = 0.5 * (state.R_t.get("reentry", 0.5) + state.R_t.get("persist", 0.5))
        C, F, P = state.C_t, state.F_t, state.P_t
        ERQ = state.erq.get("book", 0.5)
        c = self.coef
        score = (c["alpha"] * R + c["beta"] * C
                 - c["gamma"] * F - c["delta"] * P + c["eta"] * ERQ)

        if score > EXPAND_ABOVE:
            decision = "EXPAND"
        elif score < CONTRACT_BELOW:
            decision = "CONTRACT"
        else:
            decision = "HOLD"

        state.mrtp = {"score": float(score), "decision": decision,
                      "R": R, "C": C, "F": F, "P": P, "ERQ": ERQ}
        state.log["L3_mrtp"] = f"MRTP={score:.3f} [{decision}]"
        return state
