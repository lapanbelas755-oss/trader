"""Market Structure Package for Trader Machine V1."""
from core.structure.contract import (
    SwingType,
    StructureClassification,
    BreakType,
    StructureDirection,
    MTFAlignment,
    ConfirmedSwing,
    StructureEvent,
)
from core.structure.swings import SwingDetector
from core.structure.classifier import SwingClassifier
from core.structure.bos_choch import BreakDetector
from core.structure.strength import StructureStrengthCalculator
from core.structure.engine import MarketStructureEngine, StructureProcessingResult

__all__ = [
    "SwingType",
    "StructureClassification",
    "BreakType",
    "StructureDirection",
    "MTFAlignment",
    "ConfirmedSwing",
    "StructureEvent",
    "SwingDetector",
    "SwingClassifier",
    "BreakDetector",
    "StructureStrengthCalculator",
    "MarketStructureEngine",
    "StructureProcessingResult",
]
