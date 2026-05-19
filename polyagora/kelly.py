"""PolyAgora Phase-II — Layer 4: Dynamic Kelly (Impl Spec §7).

Phase 4. Replaces `DynamicKellyStub`. The recoverability-aware leverage
multiplier `f_t = f(beta, R, F, C, ERQ)`.

Phase-4 design — deliberately conservative, moat-respecting. Under Option B
the base IS the proven V7.10 stack, which already de-risks in stress. So
Phase-4 Kelly only ever *adds* recoverable convexity on top:

    f_t in [base=1.00, cap=1.25]

It never cuts below `base` — the moat base is the floor; re-cutting what the
moat already cut would double-count and risk the §12.2 crisis windows.

Asymmetric dynamics (Impl Spec §7 / CTO_Response Risk 3):
  - EXPANSION  — slow: f_t creeps up only in a pristine LOCAL_STAR with
                 ERQ > theta_erq, C rising, F & P not rising, VAIDM BENIGN,
                 and MRTP in EXPAND.
  - FLOOR      — instant: any stress / rupture / boundary -> f_t = base now.
  - HOLD       — leverage decays back toward base when conditions are merely
                 un-pristine (not stressed).

`theta_erq` is provisional (Phase-5 calibration — Impl Spec §5, Open-Q6).
"""

from __future__ import annotations

import numpy as np


class DynamicKelly:
    """Layer 4. Emits `f_t` in [base, cap] — recoverable-convexity leverage."""

    def __init__(
        self,
        *,
        cap: float = 1.25,
        base: float = 1.00,
        theta_erq: float = 0.70,
        expand_step: float = 0.015,
        decay: float = 0.70,
        cooldown: int = 63,
    ) -> None:
        self.cap, self.base = cap, base
        self.theta_erq = theta_erq
        self.expand_step, self.decay = expand_step, decay
        # post-stress cooldown — bars of confirmed-clean regime required
        # before re-leveraging ("expand only when the corridor is proven
        # stable"; keeps Kelly at base through stress-saturated periods).
        self.cooldown = cooldown
        self._f_prev = base
        self._since_stress = 0
        self._C_prev: float | None = None
        self._F_prev: float | None = None
        self._P_prev: float | None = None

    def run(self, state, history):
        C, F, P = state.C_t, state.F_t, state.P_t
        ERQ = state.erq.get("book", 0.5)
        mrtp = state.mrtp.get("score", 0.0)
        Cp, Fp, Pp = self._C_prev, self._F_prev, self._P_prev

        stressed = (state.vaidm_class in ("RUPTURE", "HIGH_STRESS")
                    or state.zone_t in ("BOUNDARY", "BUFFER"))
        self._since_stress = 0 if stressed else self._since_stress + 1
        # EXPANSION gate — every condition must hold (Impl Spec §7).
        expand_ok = (
            not stressed
            and self._since_stress >= self.cooldown   # corridor proven stable
            and state.zone_t == "LOCAL_STAR"
            and state.vaidm_class == "BENIGN"
            and ERQ > self.theta_erq
            and (Cp is not None and C > Cp)            # corridor widening
            and (Fp is None or F <= Fp)                # fragmentation not rising
            and (Pp is None or P <= Pp)                # ridge pressure not rising
            and state.mrtp.get("decision") == "EXPAND"
        )

        if stressed:
            f_t, mode = self.base, "FLOOR"             # instant — no leverage
        elif expand_ok:
            f_t = min(self.cap, self._f_prev + self.expand_step)
            mode = "EXPANSION"
        else:
            # un-pristine but not stressed: bleed any leverage back toward base
            f_t = self.base + self.decay * (self._f_prev - self.base)
            mode = "RE-ENGAGEMENT" if self._f_prev > self.base + 1e-6 else "HOLD"

        state.f_t = float(np.clip(f_t, self.base, self.cap))
        state.log["kelly_mode"] = mode
        state.log["L4_kelly"] = (
            f"f_t={state.f_t:.3f} [{mode}]  ERQ={ERQ:.2f} MRTP={mrtp:.2f}")
        self._f_prev = state.f_t
        self._C_prev, self._F_prev, self._P_prev = C, F, P
        return state
