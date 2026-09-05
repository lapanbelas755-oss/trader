"""
Setup Detector Engine V1 package.
Exposes contracts, models, state machine, detectors, and engine orchestrator.
"""

from core.setups.contract import (
    SetupCode,
    SetupStatus,
    SetupDirection,
    SetupEvidence,
    SetupEvidenceItem,
    SetupRecord,
)
from core.setups.state_machine import SetupStateMachine
from core.setups.s01_sweep_reversal import S01SweepReversalDetector
from core.setups.s02_acceptance import S02LiquidityAcceptanceDetector
from core.setups.s03_failed_breakout import S03FailedBreakoutDetector
from core.setups.s04_anomaly import S04EffortResultAnomalyDetector
from core.setups.s05_compression import S05CompressionExpansionDetector
from core.setups.engine import SetupDetectorEngine

__all__ = [
    "SetupCode",
    "SetupStatus",
    "SetupDirection",
    "SetupEvidence",
    "SetupEvidenceItem",
    "SetupRecord",
    "SetupStateMachine",
    "S01SweepReversalDetector",
    "S02LiquidityAcceptanceDetector",
    "S03FailedBreakoutDetector",
    "S04EffortResultAnomalyDetector",
    "S05CompressionExpansionDetector",
    "SetupDetectorEngine",
]
