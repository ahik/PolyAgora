"""PolyAgora Phase-II — the 13-step (+7A) runtime execution graph.

Implements the mandatory execution sequence of `Implementation_Spec.md` §2.
The `ExecutionGraph` owns the layer objects and runs Steps 1-13 in order for
one weekly bar; ordering is mandatory — each step's output feeds the next.

    Step 1   Market Data Ingestion        (driver — v63 compute_weights)
    Step 2   Polygon Projection           Layer 1
    Step 3   VAIDM Classification         Layer 1
    Step 4   Survival Matrix Update       Layer 1
    Step 5   Admissibility Derivation     Layer 1
    Step 6   Block / Zone Classification  Layer 1
    Step 7   Recoverability Geometry      Layer 5   (stub)
    Step 7A  Exposure Recoverability      Layer 5A  (stub)
    Step 8   ADD Filtering                Layer 2   (stub passthrough)
    Step 9   MRTP Scoring                 Layer 3   (stub)
    Step 10  Dynamic Kelly Sizing         Layer 4   (stub)
    Step 11  Sleeve Allocation            Layer 2   (stub)
    Step 12  Contraction Map              Runtime   (implemented)
    Step 13  Execution Output             Runtime

The graph is exposed as a v63 `SignalFn` via `as_signal_fn()`, so v63's
`compute_weights` drives the date iteration — inception masking, NaN
freezing, and the capital-budget envelope (sum|w_real| + cash = 1).
"""

from __future__ import annotations

import pandas as pd

from polyagora.governance import GovernanceCore
from polyagora.kelly import DynamicKelly
from polyagora.layers import ConvexitySleevesStub, contraction_map
from polyagora.mrtp import MRTPSteering
from polyagora.recoverability import ExposureRecoverability, RecoverabilityGeometry
from polyagora.state import RuntimeState


class ExecutionGraph:
    """The Phase-II runtime execution graph (13 steps + Step 7A)."""

    def __init__(
        self,
        macro_panel: pd.DataFrame,
        universe: list[str],
        *,
        base_provider=None,
        sleeves=None,
        survival_window: int = 126,
    ) -> None:
        self.universe = list(universe)
        # Layer 1(+2) base provider. Default = the v62 re-base (Phase 1);
        # Phase 2 passes a `MoatStackBase` (Option B — the proven V7.10 stack).
        # Any object with `run(state, history)` filling `state.base_w` works.
        self.base = base_provider if base_provider is not None else GovernanceCore(
            macro_panel, universe, survival_window=survival_window)
        # Layers 3 / 4 / 5 / 5A — real (Phases 3-4). Layer 2 — stub (sleeves).
        self.recoverability = RecoverabilityGeometry(
            macro_panel, universe, survival_window=survival_window)
        self.erq = ExposureRecoverability(universe)
        self.mrtp = MRTPSteering()
        self.kelly = DynamicKelly()
        # Layer 2 — real `ConvexitySleeves` when admitted sleeves are passed,
        # else the stub (no sleeves blended).
        self.sleeves = sleeves if sleeves is not None else ConvexitySleevesStub()
        # cross-bar state
        self._prev_w: pd.Series | None = None
        self._prev_block: str | None = None
        self.trace: list[RuntimeState] = []

    # ------------------------------------------------------------------ #
    def run_bar(self, t: pd.Timestamp, history: pd.DataFrame) -> RuntimeState:
        """Execute Steps 2-13 for one weekly bar (Step 1 = the `history` arg)."""
        st = RuntimeState(date=t)

        # Steps 2-6 — Layer 1(+2) base provider
        self.base.run(st, history)
        # Step 7 — Recoverability Geometry (Layer 5)
        self.recoverability.run(st, history)
        # Step 7A — Exposure Recoverability Quality (Layer 5A)
        self.erq.run(st, history)
        # Step 8 — ADD filtering (Layer 2)
        self.sleeves.run_add(st, history)
        # Step 9 — MRTP scoring (Layer 3)
        self.mrtp.run(st, history)
        # Step 10 — Dynamic Kelly sizing (Layer 4)
        self.kelly.run(st, history)
        # Step 11 — Sleeve allocation (Layer 2)
        self.sleeves.run_sleeves(st, history)

        # Step 12 — Contraction map
        base_w = st.base_w if st.base_w is not None else pd.Series(
            0.0, index=self.universe)
        target = base_w * st.f_t
        block_changed = (self._prev_block is not None
                         and st.block_t != self._prev_block)
        st.w_t = contraction_map(
            target, self._prev_w, zone=st.zone_t, block_changed=block_changed)

        # Step 13 — Execution output
        st.log["gross"] = float(st.w_t.abs().sum())
        st.log["step_order"] = list(range(2, 14))

        self._prev_w = st.w_t
        self._prev_block = st.block_t
        self.trace.append(st)
        return st

    # ------------------------------------------------------------------ #
    def as_signal_fn(self):
        """Return a v63 `SignalFn` wrapping the graph.

        v63 `compute_weights` calls this per date with `history` (realized
        rows <= t) and `live` (assets past inception); the graph runs the
        13 steps and returns the final allocation reindexed to `live`.
        """

        def _signal(history: pd.DataFrame, live: list[str], cfg) -> pd.Series:
            t = history.index[-1]
            st = self.run_bar(t, history)
            return st.w_t.reindex(live).fillna(0.0)

        return _signal

    # ------------------------------------------------------------------ #
    def run_full(self, realized_pnl: pd.DataFrame) -> pd.DataFrame:
        """Drive the graph over every bar; return the final weight panel.

        The graph owns the date iteration here (vs `as_signal_fn` + v63
        `compute_weights`). Used by the Phase-2 moat-stack path, where the
        base provider already carries inception/NaN handling. Columns are
        `universe + [CASH]`; CASH is the capital-budget residual.
        """
        from polyagora_v63_partner_engine import CASH

        cols = list(self.universe) + [CASH]
        panel = pd.DataFrame(0.0, index=realized_pnl.index, columns=cols)
        for t in realized_pnl.index:
            st = self.run_bar(t, realized_pnl.loc[:t])
            w = st.w_t.reindex(self.universe).fillna(0.0)
            panel.loc[t, self.universe] = w.values
            panel.loc[t, CASH] = max(0.0, 1.0 - float(w.abs().sum()))
        return panel

    # ------------------------------------------------------------------ #
    def trace_frame(self) -> pd.DataFrame:
        """Per-bar diagnostics from the recorded trace (zones, VAIDM, beta)."""
        rows = [
            {
                "date": s.date,
                "block": s.block_t,
                "zone": s.zone_t,
                "vaidm": s.vaidm_class,
                "vaidm_intensity": s.vaidm_intensity,
                "beta_t": s.beta_t,
                "C_t": s.C_t,
                "P_t": s.P_t,
                "F_t": s.F_t,
                "R_reentry": s.R_t.get("reentry", float("nan")),
                "R_persist": s.R_t.get("persist", float("nan")),
                "erq_book": s.erq.get("book", float("nan")),
                "mrtp": s.mrtp.get("score", float("nan")),
                "kelly_mode": s.log.get("kelly_mode", ""),
                "f_t": s.f_t,
                "gross": s.log.get("gross", float("nan")),
            }
            for s in self.trace
        ]
        return pd.DataFrame(rows).set_index("date") if rows else pd.DataFrame()
