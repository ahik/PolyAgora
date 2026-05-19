"""PolyAgora Phase-II — Layer 1+2: Moat Stack Base (Phase-2, Option B).

Phase-2 fork decision (2026-05-19). The v62-re-based Governance Core
(`polyagora.governance.core`) failed the §12.2 moat gate — Sharpe 0.42 vs
the V7.10 reference 0.91 — exactly as CTO_Response Risk 1 predicted: the
V7.10 moat does not rest on v62, it rests on the v75/v76/v78/v79 stack.

Per the chosen Option B, the **proven V7.10 allocator becomes the Phase-II
base**. `MoatStackBase` consumes the V7.10 weight panel — the canonical
output of `run_v710_check.py` — as the runtime's Layer-1+2 base allocation.
The Phase-II convexity layers (5, 5A, 3, 4) deform this base in Phases 3-4;
in Phase 2 they are stubs, so the runtime reproduces V7.10 by construction
and the §12.2 gate passes.

The v62 core is retained as `polyagora.governance.core` for reference and
as a potential geometry source for later phases.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from polyagora_v62_engine import EngineConfig as V62Config, build_exogenous_x
from polyagora.governance.core import classify_vaidm

# VAIDM class -> 5-mode zone (Phase-2 coarse map; informational only — the
# Phase-2 allocation is the V7.10 panel regardless. Never emits BUFFER, so
# the Step-12 contraction map passes the base through unchanged).
_VAIDM_TO_ZONE = {
    "BENIGN": "LOCAL_STAR",
    "ELEVATED": "TRANSITION",
    "HIGH_STRESS": "LEAST_BAD",
    "RUPTURE": "BOUNDARY",
}


class MoatStackBase:
    """Layer 1+2 — the V7.10 moat stack, consumed as the Phase-II base.

    Loads the V7.10 weight panel and serves it per bar. Also populates the
    governance-state fields (VAIDM, zone, beta) for the trace and for the
    Phase-3/4 layers — these do not affect the Phase-2 allocation.
    """

    def __init__(
        self,
        weights_v710_path: str | Path,
        macro_panel: pd.DataFrame,
        universe: list[str],
        *,
        v62cfg: V62Config | None = None,
    ) -> None:
        path = Path(weights_v710_path)
        if not path.exists():
            raise FileNotFoundError(
                f"V7.10 weight panel not found: {path}\n"
                "Run `run_v710_check.py` first — it is the canonical producer "
                "of the moat-stack base allocation."
            )
        panel = pd.read_csv(path, parse_dates=["trading_date"]).set_index("trading_date")
        self.universe = list(universe)
        missing = set(self.universe) - set(panel.columns)
        if missing:
            raise ValueError(f"V7.10 panel missing universe columns: {sorted(missing)}")
        self.panel = panel[self.universe].sort_index()
        # polygon features for the VAIDM reading (shift(1)-lagged inside).
        self.X_5d = build_exogenous_x(macro_panel, v62cfg or V62Config()).sort_index()

    def run(self, state, history: pd.DataFrame):
        """Fill `state` for bar `state.date` from the V7.10 moat panel."""
        t = state.date

        # --- base allocation: the V7.10 moat-stack weights ------------------
        if t in self.panel.index:
            state.base_w = self.panel.loc[t].astype(float)
        else:
            state.base_w = pd.Series(0.0, index=self.universe)

        # --- governance state (informational in Phase 2) -------------------
        idx = self.X_5d.index.asof(t)
        if idx is not None and not pd.isna(idx):
            x_row = self.X_5d.loc[idx]
            state.vaidm_class, state.vaidm_intensity, state.vaidm_axes = \
                classify_vaidm(x_row)
        state.zone_t = _VAIDM_TO_ZONE.get(state.vaidm_class, "TRANSITION")
        state.block_t = "MOAT"            # no v62 block under Option B
        state.beta_t = float(state.base_w.abs().sum())   # deployed gross

        state.log["base"] = (
            f"moat-stack v7.10  gross={state.beta_t:.3f}  "
            f"vaidm={state.vaidm_class}  zone={state.zone_t}"
        )
        return state
