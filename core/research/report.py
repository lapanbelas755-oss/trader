"""
Research summary report and machine-readable manifest generator for Historical Research Engine V1.
Strictly records occurrences and structural metrics without profitability claims.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence
from core.research.contract import (
    DataValidationReport,
    ResearchManifest,
    ResearchOccurrenceRecord,
    SplitType,
)
from core.setups.common import get_val, ensure_utc

ENGINE_VERSIONS = {
    "ingestion_version": "1.0.0",
    "candle_version": "1.0.0",
    "feature_version": "1.0.0",
    "structure_version": "1.0.0",
    "liquidity_version": "1.0.0",
    "setup_version": "1.0.0",
    "research_version": "1.0.0",
}


class ResearchReportGenerator:
    """
    Produces human-readable summary text and machine-readable JSON manifests.
    """

    @staticmethod
    def generate_manifest(
        dataset_version: str,
        symbol: str,
        source: str,
        timeframe: str,
        start_time: datetime,
        end_time: datetime,
        row_count: int,
        content_hash: str,
        config_hash: str,
        occurrences: Sequence[ResearchOccurrenceRecord],
    ) -> ResearchManifest:
        """Constructs a deterministic machine-readable manifest."""
        occ_counts = {"S01": 0, "S02": 0, "S03": 0, "S04": 0, "S05": 0}
        split_counts = {
            SplitType.IN_SAMPLE.value: 0,
            SplitType.VALIDATION.value: 0,
            SplitType.OUT_OF_SAMPLE.value: 0,
        }

        for occ in occurrences:
            code = str(get_val(occ, "setup_code"))
            split = str(get_val(occ, "split_type"))
            if code in occ_counts:
                occ_counts[code] += 1
            if split in split_counts:
                split_counts[split] += 1

        return ResearchManifest(
            dataset_version=dataset_version,
            symbol=symbol.strip().upper(),
            source=source.strip().upper(),
            timeframe=timeframe.strip().upper(),
            start_time=ensure_utc(start_time),
            end_time=ensure_utc(end_time),
            row_count=row_count,
            content_hash=content_hash,
            config_hash=config_hash,
            engine_versions=dict(ENGINE_VERSIONS),
            occurrence_counts=occ_counts,
            split_counts=split_counts,
            created_at=datetime.now(timezone.utc),
        )

    @staticmethod
    def generate_report_text(
        symbol: str,
        start_time: datetime,
        end_time: datetime,
        validation_report: DataValidationReport,
        occurrences: Sequence[ResearchOccurrenceRecord],
        dataset_version: str,
        content_hash: str,
        config_hash: str,
    ) -> str:
        """Constructs a structured text summary for the research run."""
        s_time = ensure_utc(start_time).strftime("%Y-%m-%d %H:%M")
        e_time = ensure_utc(end_time).strftime("%Y-%m-%d %H:%M")

        occ_counts = {"S01": 0, "S02": 0, "S03": 0, "S04": 0, "S05": 0}
        fire_counts = {"S01": 0, "S02": 0, "S03": 0, "S04": 0, "S05": 0}
        split_counts = {
            SplitType.IN_SAMPLE.value: 0,
            SplitType.VALIDATION.value: 0,
            SplitType.OUT_OF_SAMPLE.value: 0,
        }

        for occ in occurrences:
            code = str(get_val(occ, "setup_code"))
            status = str(get_val(occ, "status"))
            split = str(get_val(occ, "split_type"))

            if code in occ_counts:
                occ_counts[code] += 1
            if code in fire_counts and status == "FIRE":
                fire_counts[code] += 1
            if split in split_counts:
                split_counts[split] += 1

        lines = [
            "==================================================",
            "TRADER MACHINE — HISTORICAL RESEARCH REPORT",
            "==================================================",
            f"Symbol:           {symbol}",
            f"Range:            {s_time} -> {e_time}",
            f"Dataset Version:  {dataset_version}",
            f"Content Hash:     {content_hash[:16]}...",
            f"Config Hash:      {config_hash[:16]}...",
            "--------------------------------------------------",
            "DATA QUALITY AUDIT",
            "--------------------------------------------------",
            f"Status:           {validation_report.status.value}",
            f"Total Candles:    {validation_report.total_candles}",
            f"Valid Candles:    {validation_report.valid_candles}",
            f"Duplicates:       {validation_report.duplicate_count}",
            f"Missing Intervals:{validation_report.missing_intervals}",
            f"Warnings Count:   {len(validation_report.warnings)}",
            f"Errors Count:     {len(validation_report.errors)}",
            "--------------------------------------------------",
            "SETUP OCCURRENCES (OBSERVED)",
            "--------------------------------------------------",
            f"S01 Total / FIRE: {occ_counts['S01']} / {fire_counts['S01']}",
            f"S02 Total / FIRE: {occ_counts['S02']} / {fire_counts['S02']}",
            f"S03 Total / FIRE: {occ_counts['S03']} / {fire_counts['S03']}",
            f"S04 Total / FIRE: {occ_counts['S04']} / {fire_counts['S04']}",
            f"S05 Total / FIRE: {occ_counts['S05']} / {fire_counts['S05']}",
            "--------------------------------------------------",
            "CHRONOLOGICAL SPLITS",
            "--------------------------------------------------",
            f"IN_SAMPLE:        {split_counts[SplitType.IN_SAMPLE.value]} occurrences",
            f"VALIDATION:       {split_counts[SplitType.VALIDATION.value]} occurrences",
            f"OUT_OF_SAMPLE:    {split_counts[SplitType.OUT_OF_SAMPLE.value]} occurrences",
            "==================================================",
            "NOTE: This report records deterministic market occurrences only.",
            "Zero profitability claims. Backtesting belongs to a separate stage.",
            "==================================================",
        ]
        return "\n".join(lines)
