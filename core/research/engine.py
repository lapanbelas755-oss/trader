"""
Historical Research & Dataset Engine V1 orchestrator.
Coordinates the complete deterministic research pipeline:
RAW DATA -> VALIDATION -> NORMALIZATION -> CANDLES -> FEATURES -> STRUCTURE -> LIQUIDITY -> SETUPS -> OCCURRENCES -> DATASET
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Sequence, Tuple
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert

from core.research.contract import (
    DatasetMetadata,
    DatasetStatus,
    DataValidationReport,
    DataProvenance,
    ResearchManifest,
    ResearchOccurrenceRecord,
    RunStatus,
    SplitType,
    ValidationStatus,
)
from core.research.config import ResearchConfig
from core.research.hashing import hash_candles, hash_occurrences
from core.research.provenance import DataProvenanceTracker
from core.research.validator import HistoricalDataValidator
from core.research.splitter import ChronologicalSplitter
from core.research.occurrence import SetupOccurrenceRecorder
from core.research.report import ResearchReportGenerator
from core.features.engine import MarketFeatureEngine
from core.structure.engine import MarketStructureEngine
from core.liquidity.engine import LiquidityEngine
from core.setups.engine import SetupDetectorEngine
from core.setups.common import get_val, ensure_utc
from database.models import (
    ResearchDataset as ResearchDatasetModel,
    ResearchRun as ResearchRunModel,
    ResearchSetupOccurrence as ResearchSetupOccurrenceModel,
)


class ResearchRunResult:
    """Encapsulates all outputs from a historical research run."""

    def __init__(
        self,
        dataset_metadata: DatasetMetadata,
        provenance: DataProvenance,
        validation_report: DataValidationReport,
        config: ResearchConfig,
        run_id: str,
        run_version: str,
        status: RunStatus,
        occurrences: List[ResearchOccurrenceRecord],
        manifest: ResearchManifest,
        report_text: str,
    ):
        self.dataset_metadata = dataset_metadata
        self.provenance = provenance
        self.validation_report = validation_report
        self.config = config
        self.run_id = run_id
        self.run_version = run_version
        self.status = status
        self.occurrences = occurrences
        self.manifest = manifest
        self.report_text = report_text


class HistoricalResearchEngine:
    """
    End-to-end engine for deterministic historical market data processing,
    auditing, split partitioning, and setup occurrence generation.
    """

    def __init__(
        self,
        symbol: str = "EURUSD",
        timeframe: str = "M5",
        config: Optional[ResearchConfig] = None,
    ):
        self.symbol = symbol.strip().upper()
        self.timeframe = timeframe.strip().upper()
        self.config = config or ResearchConfig()

        self.validator = HistoricalDataValidator(timeframe=self.timeframe)
        self.splitter = ChronologicalSplitter(
            in_sample_ratio=self.config.in_sample_ratio,
            validation_ratio=self.config.validation_ratio,
            out_of_sample_ratio=self.config.out_of_sample_ratio,
        )
        self.feature_engine = MarketFeatureEngine()
        self.structure_engine = MarketStructureEngine(
            left_bars=self.config.swing_left_bars,
            right_bars=self.config.swing_right_bars,
            default_tolerance=self.config.equal_high_low_tolerance,
            default_min_displacement=self.config.bos_displacement_atr_mult * self.config.fallback_atr,
        )
        self.liquidity_engine = LiquidityEngine(
            symbol=self.symbol,
            timeframe=self.timeframe,
            fallback_atr=self.config.fallback_atr,
        )
        self.setup_engine = SetupDetectorEngine(
            symbol=self.symbol,
            timeframe=self.timeframe,
            fallback_atr=self.config.fallback_atr,
        )

    def run_pipeline(
        self,
        candles: Sequence[Any],
        provenance: DataProvenance,
        dataset_name: str,
        dataset_version: str = "1.0.0",
        run_version: str = "1.0.0",
        run_id: Optional[str] = None,
    ) -> ResearchRunResult:
        """
        Executes the full historical research pipeline.
        Causality is strictly preserved: at each point in time T, only information <= T is used.
        """
        active_run_id = run_id or f"run_{uuid.uuid4().hex[:12]}"
        config_hash = self.config.get_config_hash()

        # 1. Validation
        validation_report = self.validator.validate_dataset(candles)
        if validation_report.status == ValidationStatus.REJECTED:
            metadata = DatasetMetadata(
                dataset_name=dataset_name,
                symbol=self.symbol,
                source=provenance.source,
                timeframe=self.timeframe,
                start_time=provenance.first_timestamp or datetime.now(timezone.utc),
                end_time=provenance.last_timestamp or datetime.now(timezone.utc),
                row_count=len(candles),
                dataset_version=dataset_version,
                content_hash=provenance.content_hash,
                status=DatasetStatus.REJECTED,
            )
            manifest = ResearchReportGenerator.generate_manifest(
                dataset_version=dataset_version,
                symbol=self.symbol,
                source=provenance.source,
                timeframe=self.timeframe,
                start_time=metadata.start_time,
                end_time=metadata.end_time,
                row_count=metadata.row_count,
                content_hash=metadata.content_hash,
                config_hash=config_hash,
                occurrences=[],
            )
            report_text = f"RUN REJECTED due to data validation errors: {validation_report.errors}"
            return ResearchRunResult(
                dataset_metadata=metadata,
                provenance=provenance,
                validation_report=validation_report,
                config=self.config,
                run_id=active_run_id,
                run_version=run_version,
                status=RunStatus.FAILED,
                occurrences=[],
                manifest=manifest,
                report_text=report_text,
            )

        # 2. Sort chronologically (normalization)
        sorted_candles = sorted(candles, key=lambda c: ensure_utc(get_val(c, "timestamp")))
        content_hash = hash_candles(sorted_candles)
        start_t = ensure_utc(get_val(sorted_candles[0], "timestamp"))
        end_t = ensure_utc(get_val(sorted_candles[-1], "timestamp"))

        metadata = DatasetMetadata(
            dataset_name=dataset_name,
            symbol=self.symbol,
            source=provenance.source,
            timeframe=self.timeframe,
            start_time=start_t,
            end_time=end_t,
            row_count=len(sorted_candles),
            dataset_version=dataset_version,
            content_hash=content_hash,
            status=DatasetStatus.READY,
        )

        # 3. Chronological Splits
        split_bounds = self.splitter.get_split_boundaries(sorted_candles)

        # 4. Extract Derived Features
        feature_records = self.feature_engine.calculator.calculate_features(sorted_candles)
        atr_map = {ensure_utc(f.timestamp): f.atr for f in feature_records if f.atr is not None}
        current_atr = feature_records[-1].atr if feature_records and feature_records[-1].atr else self.config.fallback_atr

        # 5. Extract Structure Events
        structure_events = self.structure_engine.analyze_structure(sorted_candles, atr_map=atr_map)

        # 6. Extract Liquidity Levels & Process Lifecycle
        swings = self.structure_engine.swing_detector.detect_swings(sorted_candles)
        raw_levels = []
        if swings:
            raw_levels.extend(self.liquidity_engine.level_detector.extract_significant_swings(swings))
            raw_levels.extend(self.liquidity_engine.level_detector.detect_equal_high_low(swings, current_atr=current_atr))
        liquidity_levels = self.liquidity_engine.process_lifecycle(raw_levels, sorted_candles, atr_value=current_atr)

        # 7. Execute Sequential Chronological Setup Evaluation
        setup_records = self.setup_engine.detect_chronological(
            candles=sorted_candles,
            features=feature_records,
            liquidity_levels=liquidity_levels,
            structure_events=structure_events,
        )

        # 8. Snapshot into ResearchOccurrenceRecords
        occurrences: List[ResearchOccurrenceRecord] = []
        for s in setup_records:
            split_type = self.splitter.determine_split_type(s.timestamp, split_bounds)
            occ = SetupOccurrenceRecorder.record_occurrence(
                setup_record=s,
                config_hash=config_hash,
                split_type=split_type,
            )
            occurrences.append(occ)

        # 9. Generate Manifest & Report
        manifest = ResearchReportGenerator.generate_manifest(
            dataset_version=dataset_version,
            symbol=self.symbol,
            source=provenance.source,
            timeframe=self.timeframe,
            start_time=start_t,
            end_time=end_t,
            row_count=len(sorted_candles),
            content_hash=content_hash,
            config_hash=config_hash,
            occurrences=occurrences,
        )

        report_text = ResearchReportGenerator.generate_report_text(
            symbol=self.symbol,
            start_time=start_t,
            end_time=end_t,
            validation_report=validation_report,
            occurrences=occurrences,
            dataset_version=dataset_version,
            content_hash=content_hash,
            config_hash=config_hash,
        )

        return ResearchRunResult(
            dataset_metadata=metadata,
            provenance=provenance,
            validation_report=validation_report,
            config=self.config,
            run_id=active_run_id,
            run_version=run_version,
            status=RunStatus.SUCCESS,
            occurrences=occurrences,
            manifest=manifest,
            report_text=report_text,
        )

    def persist_results(
        self,
        session: Session,
        result: ResearchRunResult,
    ) -> Tuple[int, int, int]:
        """
        Persists dataset metadata, research run, and occurrences to PostgreSQL.
        Enforces immutability: runs are permanently recorded; occurrences are inserted idempotently.
        Returns: (dataset_id, run_id_pk, occurrences_inserted_count)
        """
        meta = result.dataset_metadata

        # 1. Insert or retrieve Dataset
        ds_stmt = insert(ResearchDatasetModel).values(
            dataset_name=meta.dataset_name,
            symbol=meta.symbol,
            source=meta.source,
            timeframe=meta.timeframe,
            start_time=meta.start_time,
            end_time=meta.end_time,
            row_count=meta.row_count,
            dataset_version=meta.dataset_version,
            content_hash=meta.content_hash,
            status=meta.status.value,
        ).on_conflict_do_nothing(
            constraint="uq_research_dataset"
        ).returning(ResearchDatasetModel.id)

        ds_res = session.execute(ds_stmt)
        dataset_id = ds_res.scalar_one_or_none()

        if dataset_id is None:
            # Retrieve existing dataset id
            existing = session.query(ResearchDatasetModel).filter_by(
                dataset_name=meta.dataset_name,
                dataset_version=meta.dataset_version,
                content_hash=meta.content_hash,
            ).first()
            dataset_id = existing.id

        # 2. Insert Research Run
        run_stmt = insert(ResearchRunModel).values(
            run_id=result.run_id,
            dataset_id=dataset_id,
            run_version=result.run_version,
            config_hash=result.config.get_config_hash(),
            started_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
            status=result.status.value,
            input_row_count=meta.row_count,
            output_row_count=len(result.occurrences),
            error_count=len(result.validation_report.errors),
        ).on_conflict_do_nothing(
            constraint="uq_research_run"
        ).returning(ResearchRunModel.id)

        run_res = session.execute(run_stmt)
        run_pk = run_res.scalar_one_or_none()
        if run_pk is None:
            existing_run = session.query(ResearchRunModel).filter_by(run_id=result.run_id).first()
            run_pk = existing_run.id

        # 3. Insert Occurrences
        occ_inserted = 0
        for occ in result.occurrences:
            occ_stmt = insert(ResearchSetupOccurrenceModel).values(
                research_run_id=run_pk,
                setup_id=occ.setup_id,
                setup_code=occ.setup_code,
                symbol=occ.symbol,
                timeframe=occ.timeframe,
                timestamp=occ.timestamp,
                direction=occ.direction,
                status=occ.status,
                regime=occ.regime,
                liquidity_type=occ.liquidity_type,
                structure_type=occ.structure_type,
                split_type=occ.split_type.value,
                evidence_snapshot=occ.evidence_snapshot,
                config_hash=occ.config_hash,
            ).on_conflict_do_nothing(
                constraint="uq_research_occurrence"
            ).returning(ResearchSetupOccurrenceModel.id)

            res_occ = session.execute(occ_stmt)
            if res_occ.scalar_one_or_none() is not None:
                occ_inserted += 1

        session.commit()
        return dataset_id, run_pk, occ_inserted
