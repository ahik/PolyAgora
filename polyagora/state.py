"""PolyAgora Phase-II — runtime state schema.

Implements the state schema of `Implementation_Spec.md` §3. `RuntimeState`
is the per-bar object the 13-step execution graph populates step by step.

Phase 1: Layer-1 fields (`X_t`, `S_ij`, `A`, `beta_t`, `zone_t`, …) are
populated for real; Layer 2–5A fields carry stub values until Phases 3–4.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

# The 5-mode zone classifier (Impl Spec §9) and the VAIDM classes (§2 Step 3).
ZONES = ["LOCAL_STAR", "TRANSITION", "LEAST_BAD", "BUFFER", "BOUNDARY"]
VAIDM_CLASSES = ["BENIGN", "ELEVATED", "HIGH_STRESS", "RUPTURE"]

# Regime blocks (V6.2 lineage); G is the boundary block.
BLOCKS = ["A", "B", "C", "D", "G"]


@dataclass
class RuntimeState:
    """Per-bar runtime state — one object per weekly execution of the graph.

    Field groups follow the layer that produces them (Impl Spec §3). A field
    is `None` / its neutral default until the producing step runs.
    """

    date: pd.Timestamp

    # --- Layer 1 — Governance Core (Steps 2-6) -------------------------------
    X_t: np.ndarray | None = None          # (5,) reference-polygon coord V,T,G,C,R
    vaidm_class: str = "BENIGN"            # RUPTURE / HIGH_STRESS / ELEVATED / BENIGN
    vaidm_intensity: float = 0.0           # [0,1] stress multiplier
    vaidm_axes: np.ndarray | None = None   # (6,) six-axis VAIDM vector
    S_ij: pd.DataFrame | None = None       # 13x13 survival matrix
    A: pd.DataFrame | None = None          # 13x5 admissibility (futures x blocks)
    beta_t: float = 0.0                    # [0,1] beta-admissibility scalar
    block_t: str = "G"                     # active regime block
    zone_t: str = "LEAST_BAD"              # 5-mode zone
    base_w: pd.Series | None = None        # governance base allocation (real assets)

    # --- Layer 5 — Recoverability Geometry (Step 7) — STUB in Phase 1 --------
    R_t: dict = field(default_factory=lambda: {"reentry": 0.5, "persist": 0.5})
    C_t: float = 0.5                       # corridor width
    F_t: float = 0.0                       # fragmentation
    P_t: float = 0.0                       # ridge pressure

    # --- Layer 5A — Exposure Recoverability Quality (Step 7A) — STUB --------
    erq: dict = field(default_factory=dict)  # exposure_id -> ERQ in [0,1]

    # --- Layer 3 — MRTP Steering (Step 9) — STUB ----------------------------
    mrtp: dict = field(default_factory=dict)

    # --- Layer 4 — Dynamic Kelly (Step 10) — STUB ---------------------------
    f_t: float = 1.0                       # leverage multiplier (cap 1.25x)

    # --- Layer 2 — Convexity Sleeves (Steps 8, 11) — STUB -------------------
    pi_t: pd.Series | None = None          # sleeve weights

    # --- Step 13 — Execution Output -----------------------------------------
    w_t: pd.Series | None = None           # final allocation (real assets)

    # --- diagnostics --------------------------------------------------------
    log: dict = field(default_factory=dict)
