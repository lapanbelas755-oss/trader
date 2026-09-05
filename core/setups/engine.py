"""
Setup Detector Engine V1 orchestrator.
Orchestrates S01-S05 detectors, enforces strict causality, deterministic lifecycle,
auditable evidence tracking, and database persistence.
"""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Sequence
from sqlalchemy.orm import Session
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert

from core.setups.contract import (
    SetupCode,
    SetupDirection,
    SetupEvidence,
    SetupRecord,
    SetupStatus,
)
from core.setups.common import get_val, ensure_utc
from core.setups.s01_sweep_reversal import S01SweepReversalDetector
from core.setups.s02_acceptance import S02LiquidityAcceptanceDetector
from core.setups.s03_failed_breakout import S03FailedBreakoutDetector
from core.setups.s04_anomaly import S04EffortResultAnomalyDetector
from core.setups.s05_compression import S05CompressionExpansionDetector
from database.models import Setup as SetupModel, SetupEvidence as SetupEvidenceModel


class SetupDetectorEngine:
    """
    Coordinates evaluation of all 5 deterministic setup archetypes (S01-S05).
    Guarantees strict causality (No Look-Ahead) and historical immutability.
    """

    def __init__(
        self,
        symbol: str = "EURUSD",
        timeframe: str = "M5",
        fallback_atr: Decimal = Decimal("0.00100"),
    ):
        self.symbol = symbol.strip().upper()
        self.timeframe = timeframe.strip().upper()
        self.fallback_atr = fallback_atr

        self.s01_detector = S01SweepReversalDetector(fallback_atr=fallback_atr)
        self.s02_detector = S02LiquidityAcceptanceDetector(fallback_atr=fallback_atr)
        self.s03_detector = S03FailedBreakoutDetector(fallback_atr=fallback_atr)
        self.s04_detector = S04EffortResultAnomalyDetector()
        self.s05_detector = S05CompressionExpansionDetector(fallback_atr=fallback_atr)

    def extract_atr_map(self, features: Sequence[Any]) -> Dict[datetime, Decimal]:
        """Extracts candle timestamp -> ATR decimal mapping."""
        atr_map = {}
        for f in features:
            ts = ensure_utc(get_val(f, "timestamp"))
            atr = get_val(f, "atr")
            if ts and atr is not None:
                atr_map[ts] = Decimal(str(atr))
        return atr_map

    def get_latest_regime(self, features: Sequence[Any], default: str = "UNKNOWN") -> str:
        """Determines market regime from available features."""
        if not features:
            return default
        last_f = features[-1]
        is_strong = get_val(last_f, "is_strong_anomaly", False)
        if is_strong:
            return "HIGH_VOLATILITY"
        return default

    def detect_at_timestamp(
        self,
        timestamp: datetime,
        candles: Sequence[Any],
        features: Optional[Sequence[Any]] = None,
        liquidity_levels: Optional[Sequence[Any]] = None,
        structure_events: Optional[Sequence[Any]] = None,
        htf_direction: Optional[str] = None,
        target_setups: Optional[Sequence[SetupCode]] = None,
    ) -> List[SetupRecord]:
        """
        Evaluates setups at exact timestamp T.
        STRICT CAUSALITY GUARANTEE:
        Filters all inputs so ONLY records <= timestamp are available to detectors.
        """
        t = ensure_utc(timestamp)

        # 1. Filter candles <= T
        causal_candles = [c for c in candles if ensure_utc(get_val(c, "timestamp")) <= t]
        if not causal_candles:
            return []

        # 2. Filter features <= T
        all_features = features or []
        causal_features = [f for f in all_features if ensure_utc(get_val(f, "timestamp")) <= t]

        # 3. Filter liquidity levels <= T
        all_levels = liquidity_levels or []
        causal_levels = []
        for lvl in all_levels:
            lvl_created = ensure_utc(get_val(lvl, "created_at", get_val(lvl, "start_timestamp")))
            if lvl_created is None or lvl_created <= t:
                causal_levels.append(lvl)

        # 4. Filter structure events <= T (using confirmed_at)
        all_structures = structure_events or []
        causal_structures = []
        for s in all_structures:
            s_conf = ensure_utc(get_val(s, "confirmed_at", get_val(s, "timestamp")))
            if s_conf is None or s_conf <= t:
                causal_structures.append(s)

        # Determine current ATR and regime
        current_atr = None
        if causal_features:
            atr_val = get_val(causal_features[-1], "atr")
            if atr_val is not None:
                current_atr = Decimal(str(atr_val))

        regime = self.get_latest_regime(causal_features)

        selected_codes = set(target_setups) if target_setups else {
            SetupCode.S01, SetupCode.S02, SetupCode.S03, SetupCode.S04, SetupCode.S05
        }

        detected: List[SetupRecord] = []

        # S01: Liquidity Sweep Reversal
        if SetupCode.S01 in selected_codes:
            s01_records = self.s01_detector.evaluate_at_timestamp(
                timestamp=t,
                symbol=self.symbol,
                timeframe=self.timeframe,
                candles_up_to_t=causal_candles,
                levels_up_to_t=causal_levels,
                structure_events_up_to_t=causal_structures,
                current_atr=current_atr,
                regime=regime,
            )
            detected.extend(s01_records)

        # S02: Liquidity Acceptance Continuation
        if SetupCode.S02 in selected_codes:
            s02_records = self.s02_detector.evaluate_at_timestamp(
                timestamp=t,
                symbol=self.symbol,
                timeframe=self.timeframe,
                candles_up_to_t=causal_candles,
                levels_up_to_t=causal_levels,
                structure_events_up_to_t=causal_structures,
                htf_direction=htf_direction,
                current_atr=current_atr,
                regime=regime,
            )
            detected.extend(s02_records)

        # S03: Failed Breakout Trap
        if SetupCode.S03 in selected_codes:
            s03_records = self.s03_detector.evaluate_at_timestamp(
                timestamp=t,
                symbol=self.symbol,
                timeframe=self.timeframe,
                candles_up_to_t=causal_candles,
                levels_up_to_t=causal_levels,
                structure_events_up_to_t=causal_structures,
                current_atr=current_atr,
                regime=regime,
            )
            detected.extend(s03_records)

        # S04: Effort vs Result Anomaly
        if SetupCode.S04 in selected_codes:
            s04_records = self.s04_detector.evaluate_at_timestamp(
                timestamp=t,
                symbol=self.symbol,
                timeframe=self.timeframe,
                candles_up_to_t=causal_candles,
                features_up_to_t=causal_features,
                levels_up_to_t=causal_levels,
                structure_events_up_to_t=causal_structures,
                regime=regime,
            )
            detected.extend(s04_records)

        # S05: Compression -> Expansion
        if SetupCode.S05 in selected_codes:
            s05_records = self.s05_detector.evaluate_at_timestamp(
                timestamp=t,
                symbol=self.symbol,
                timeframe=self.timeframe,
                candles_up_to_t=causal_candles,
                features_up_to_t=causal_features,
                levels_up_to_t=causal_levels,
                structure_events_up_to_t=causal_structures,
                current_atr=current_atr,
                regime=regime,
            )
            detected.extend(s05_records)

        return detected

    def detect_chronological(
        self,
        candles: Sequence[Any],
        features: Optional[Sequence[Any]] = None,
        liquidity_levels: Optional[Sequence[Any]] = None,
        structure_events: Optional[Sequence[Any]] = None,
        htf_direction: Optional[str] = None,
        target_setups: Optional[Sequence[SetupCode]] = None,
    ) -> List[SetupRecord]:
        """
        Executes sequential historical evaluation across each candle timestamp.
        Prevents duplicate setup records for the same setup and status.
        """
        all_setups: List[SetupRecord] = []
        seen_keys: set[tuple] = set()

        for c in candles:
            c_ts = ensure_utc(get_val(c, "timestamp"))
            setups_at_t = self.detect_at_timestamp(
                timestamp=c_ts,
                candles=candles,
                features=features,
                liquidity_levels=liquidity_levels,
                structure_events=structure_events,
                htf_direction=htf_direction,
                target_setups=target_setups,
            )
            for s in setups_at_t:
                key = (s.symbol, s.timeframe, s.setup_code.value, s.timestamp, s.status.value, s.direction.value)
                if key not in seen_keys:
                    seen_keys.add(key)
                    all_setups.append(s)

        return all_setups

    def save_setups(self, session: Session, setups: Sequence[SetupRecord]) -> int:
        """
        Persists setup records and auditable evidence to PostgreSQL idempotently.
        Prevents duplicate setup creation using ON CONFLICT DO NOTHING.
        """
        if not setups:
            return 0

        inserted_count = 0
        for s in setups:
            stmt = insert(SetupModel).values(
                setup_id=s.setup_id,
                setup_code=s.setup_code.value,
                symbol=s.symbol,
                timeframe=s.timeframe,
                timestamp=s.timestamp,
                direction=s.direction.value,
                regime=s.regime,
                liquidity_type=s.liquidity_type,
                structure_type=s.structure_type,
                anomaly_type=s.anomaly_type,
                status=s.status.value,
                reason=s.reason,
                created_at=s.created_at,
                expires_at=s.expires_at,
            ).on_conflict_do_nothing(
                constraint="uq_setup_event"
            ).returning(SetupModel.id)
            res = session.execute(stmt)
            if res.scalar_one_or_none() is not None:
                inserted_count += 1

            # Insert evidence items idempotently
            for item in s.evidence.to_evidence_items():
                ev_stmt = insert(SetupEvidenceModel).values(
                    setup_id=s.setup_id,
                    evidence_key=item.key,
                    evidence_value=item.value,
                    numeric_value=item.numeric_value,
                    details=item.details,
                ).on_conflict_do_nothing(
                    constraint="uq_setup_evidence"
                )
                session.execute(ev_stmt)

        session.commit()
        return inserted_count
