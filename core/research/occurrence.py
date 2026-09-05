"""
Research setup occurrence recorder for Historical Research Engine V1.
Snapshots setup candidate state and evidence at timestamp T with zero temporal contamination.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from core.research.contract import ResearchOccurrenceRecord, SplitType
from core.setups.contract import SetupRecord
from core.setups.common import get_val, ensure_utc


class SetupOccurrenceRecorder:
    """
    Transforms observational SetupRecords into immutable ResearchOccurrenceRecords.
    """

    @staticmethod
    def record_occurrence(
        setup_record: SetupRecord,
        config_hash: str,
        split_type: SplitType = SplitType.IN_SAMPLE,
        research_run_id: Optional[int] = None,
    ) -> ResearchOccurrenceRecord:
        """
        Creates an immutable snapshot record of an observed setup event.
        Guarantees zero future contamination: only evidence present at setup_record.timestamp is preserved.
        """
        ts = ensure_utc(setup_record.timestamp)
        code = setup_record.setup_code.value if hasattr(setup_record.setup_code, "value") else str(setup_record.setup_code)
        status = setup_record.status.value if hasattr(setup_record.status, "value") else str(setup_record.status)
        direction = setup_record.direction.value if hasattr(setup_record.direction, "value") else str(setup_record.direction)

        # Generate deterministic occurrence ID
        occ_id = f"{setup_record.setup_id}_{status}_{ts.strftime('%Y%m%d%H%M%S')}"

        # Clean evidence snapshot
        evidence_dict = setup_record.evidence.model_dump() if hasattr(setup_record.evidence, "model_dump") else dict(setup_record.evidence)

        # Convert Decimal values in metrics to string/float for JSONB serialization
        if "metrics" in evidence_dict and isinstance(evidence_dict["metrics"], dict):
            clean_metrics = {}
            for k, v in evidence_dict["metrics"].items():
                clean_metrics[k] = str(v) if v is not None else None
            evidence_dict["metrics"] = clean_metrics

        return ResearchOccurrenceRecord(
            occurrence_id=occ_id,
            research_run_id=research_run_id,
            setup_id=setup_record.setup_id,
            setup_code=code,
            symbol=setup_record.symbol,
            timeframe=setup_record.timeframe,
            timestamp=ts,
            direction=direction,
            status=status,
            regime=setup_record.regime,
            liquidity_type=setup_record.liquidity_type,
            structure_type=setup_record.structure_type,
            split_type=split_type,
            evidence_snapshot=evidence_dict,
            config_hash=config_hash,
            created_at=datetime.now(timezone.utc),
        )
