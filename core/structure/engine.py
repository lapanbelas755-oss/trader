"""Market Structure Engine orchestrator for swings, BOS, CHoCH, and MTF alignment."""
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Sequence, Optional
from sqlalchemy import text
from database.connection import get_engine
from core.structure.bos_choch import BreakDetector
from core.structure.classifier import SwingClassifier
from core.structure.contract import MTFAlignment, StructureDirection, StructureEvent, SwingType
from core.structure.strength import StructureStrengthCalculator
from core.structure.swings import SwingDetector

@dataclass
class StructureProcessingResult:
    symbol: str
    timeframe: str
    swings_detected: int
    events_generated: int
    inserted: int
    unchanged: int
    updated: int

class MarketStructureEngine:
    """Orchestrates market structure extraction, classification, and multi-timeframe alignment."""

    def __init__(
        self,
        left_bars: int = 2,
        right_bars: int = 2,
        default_tolerance: Decimal = Decimal("0.000100"),
        default_min_displacement: Decimal = Decimal("0.000100"),
    ):
        self.swing_detector = SwingDetector(left_bars=left_bars, right_bars=right_bars)
        self.classifier = SwingClassifier(default_tolerance=default_tolerance)
        self.break_detector = BreakDetector(default_min_displacement=default_min_displacement)
        self.strength_calc = StructureStrengthCalculator()

    def analyze_structure(
        self,
        candles: Sequence[Any],
        atr_map: dict[datetime, Decimal] | None = None,
    ) -> list[StructureEvent]:
        """
        Analyzes a sequence of candles on a single timeframe and returns all structure events.
        """
        atrs = atr_map or {}
        raw_swings = self.swing_detector.detect_swings(candles)
        if not raw_swings:
            return []

        # Build tolerance map based on 0.05 * ATR
        tol_map: dict[str, Decimal] = {}
        disp_map: dict[datetime, Decimal] = {}
        for s in raw_swings:
            val_atr = atrs.get(s.timestamp)
            if val_atr and val_atr > Decimal("0"):
                tol_map[s.swing_id] = (Decimal("0.05") * val_atr).quantize(Decimal("0.000001"))
                disp_map[s.timestamp] = (Decimal("0.10") * val_atr).quantize(Decimal("0.000001"))

        classified_swings = self.classifier.classify_swings(raw_swings, tolerance_map=tol_map)
        break_events = self.break_detector.detect_breaks(candles, classified_swings, displacement_map=disp_map)

        events: list[StructureEvent] = []

        # Convert swings to StructureEvents
        persistence = 1
        for s in classified_swings:
            event_type = s.classification.value if s.classification else s.swing_type.value
            current_atr = atrs.get(s.timestamp)
            strength = self.strength_calc.calculate_strength(
                displacement=Decimal("0.0"),
                atr=current_atr,
                persistence_count=persistence,
            )
            persistence += 1

            events.append(StructureEvent(
                symbol=s.symbol,
                timeframe=s.timeframe,
                structure_type=event_type,
                price=s.price,
                timestamp=s.timestamp,
                confirmed_at=s.confirmed_at,
                swing_id=s.swing_id,
                reference_swing_id=s.reference_swing_id,
                direction=StructureDirection.BULLISH if s.classification in ("HH", "HL") else (
                    StructureDirection.BEARISH if s.classification in ("LL", "LH") else StructureDirection.UNDEFINED
                ),
                strength=strength,
            ))

        # Add break events (BOS and CHoCH)
        for b in break_events:
            current_atr = atrs.get(b.timestamp)
            strength = self.strength_calc.calculate_strength(
                displacement=b.displacement,
                atr=current_atr,
                persistence_count=persistence,
            )
            events.append(StructureEvent(
                symbol=b.symbol,
                timeframe=b.timeframe,
                structure_type=b.structure_type,
                price=b.price,
                timestamp=b.timestamp,
                confirmed_at=b.confirmed_at,
                reference_swing_id=b.reference_swing_id,
                direction=b.direction,
                displacement=b.displacement,
                strength=strength,
            ))

        events.sort(key=lambda e: (e.confirmed_at, e.timestamp))
        return events

    def process_timeframe(
        self,
        symbol: str,
        timeframe: str,
        candles: Sequence[Any],
        atr_map: dict[datetime, Decimal] | None = None,
    ) -> list[StructureEvent]:
        """Alias for analyze_structure matching timeframe runner syntax."""
        return self.analyze_structure(candles, atr_map=atr_map)

    def derive_mtf_alignment(
        self,
        h1_direction: Optional[StructureDirection],
        m15_direction: Optional[StructureDirection],
        m5_direction: Optional[StructureDirection],
    ) -> MTFAlignment:
        """Alias for align_multi_timeframe with safe handling of None/Optional values."""
        h1 = h1_direction or StructureDirection.UNDEFINED
        m15 = m15_direction or StructureDirection.UNDEFINED
        m5 = m5_direction or StructureDirection.UNDEFINED
        return self.align_multi_timeframe(h1, m15, m5)

    def align_multi_timeframe(
        self,
        h1_direction: StructureDirection,
        m15_direction: StructureDirection,
        m5_direction: StructureDirection,
    ) -> MTFAlignment:
        """Derives multi-timeframe alignment across H1 (Macro), M15 (Context), and M5 (Confirmation)."""
        if h1_direction == StructureDirection.UNDEFINED or m15_direction == StructureDirection.UNDEFINED or m5_direction == StructureDirection.UNDEFINED:
            return MTFAlignment.UNDEFINED

        if h1_direction == StructureDirection.BULLISH and m15_direction == StructureDirection.BULLISH and m5_direction == StructureDirection.BULLISH:
            return MTFAlignment.ALIGNED_BULLISH

        if h1_direction == StructureDirection.BEARISH and m15_direction == StructureDirection.BEARISH and m5_direction == StructureDirection.BEARISH:
            return MTFAlignment.ALIGNED_BEARISH

        if h1_direction == StructureDirection.TRANSITION or m15_direction == StructureDirection.TRANSITION or m5_direction == StructureDirection.TRANSITION:
            return MTFAlignment.TRANSITION

        return MTFAlignment.MIXED

    def upsert_events(self, *args, **kwargs) -> Any:
        """Upsert structure events into PostgreSQL market_structure table idempotently.
        Accepts either (events) or (db_session, events).
        """
        if len(args) == 2:
            db_session, events = args
        elif len(args) == 1:
            if isinstance(args[0], (list, tuple)):
                db_session, events = None, args[0]
            else:
                db_session = args[0]
                events = kwargs.get("events", [])
        else:
            db_session = kwargs.get("session") or kwargs.get("db_session")
            events = kwargs.get("events", [])

        if not events:
            return 0 if db_session is not None else (0, 0, 0)

        inserted = 0
        updated = 0
        unchanged = 0

        def run_on_conn(conn):
            nonlocal inserted, updated, unchanged
            for ev in events:
                check_sql = text("""
                    SELECT price, confirmed_at, direction, displacement, strength
                    FROM market_structure
                    WHERE symbol = :symbol AND timeframe = :tf AND timestamp = :ts AND structure_type = :st
                """)
                existing = conn.execute(check_sql, {
                    "symbol": ev.symbol,
                    "tf": ev.timeframe,
                    "ts": ev.timestamp,
                    "st": ev.structure_type,
                }).fetchone()

                params = {
                    "symbol": ev.symbol,
                    "tf": ev.timeframe,
                    "ts": ev.timestamp,
                    "cat": ev.confirmed_at,
                    "st": ev.structure_type,
                    "price": ev.price,
                    "sw_id": ev.swing_id,
                    "ref_id": ev.reference_swing_id,
                    "dir": ev.direction.value,
                    "disp": ev.displacement,
                    "str": ev.strength,
                }

                if existing is None:
                    insert_sql = text("""
                        INSERT INTO market_structure (
                            symbol, timeframe, timestamp, confirmed_at, structure_type,
                            price, swing_id, reference_swing_id, direction, displacement, strength
                        ) VALUES (
                            :symbol, :tf, :ts, :cat, :st,
                            :price, :sw_id, :ref_id, :dir, :disp, :str
                        );
                    """)
                    conn.execute(insert_sql, params)
                    inserted += 1
                else:
                    ex_price, ex_cat, ex_dir, ex_disp, ex_str = existing
                    same = (
                        Decimal(str(ex_price)) == ev.price
                        and ex_dir == ev.direction.value
                        and ((ex_disp is None and ev.displacement is None) or (Decimal(str(ex_disp)) == ev.displacement))
                        and ((ex_str is None and ev.strength is None) or (Decimal(str(ex_str)) == ev.strength))
                    )
                    if same:
                        unchanged += 1
                    else:
                        update_sql = text("""
                            UPDATE market_structure
                            SET price = :price,
                                confirmed_at = :cat,
                                swing_id = :sw_id,
                                reference_swing_id = :ref_id,
                                direction = :dir,
                                displacement = :disp,
                                strength = :str
                            WHERE symbol = :symbol AND timeframe = :tf AND timestamp = :ts AND structure_type = :st;
                        """)
                        conn.execute(update_sql, params)
                        updated += 1

        if db_session is not None:
            run_on_conn(db_session)
            db_session.commit()
            return len(events)
        else:
            engine = get_engine()
            with engine.begin() as conn:
                run_on_conn(conn)
            return inserted, updated, unchanged
