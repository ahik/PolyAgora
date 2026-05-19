"""PolyAgora Phase-II runtime package.

The layered architecture of `docs/PolyAgora_PhaseII_Implementation_Spec.md`:

    Layer 1   Governance Core            polyagora.governance
    Layer 2   Convexity Sleeves          polyagora.layers (stub — Phase 3/4)
    Layer 3   MRTP Steering              polyagora.layers (stub — Phase 4)
    Layer 4   Dynamic Kelly              polyagora.layers (stub — Phase 4)
    Layer 5   Recoverability Geometry    polyagora.layers (stub — Phase 3)
    Layer 5A  Exposure Recoverability    polyagora.layers (stub — Phase 3)
    Runtime   13-step execution graph    polyagora.runtime

Phase 1 (this build) delivers the runtime *architecture*: the state schema,
the 13-step execution graph, and a real Layer-1 Governance Core re-based on
V6.2. Layers 2–5A are honest typed stubs. Phase 2 reproduces the V7.10 moat.
"""

__version__ = "phase2-0.1"  # Phase-1 runtime architecture
