"""
Liquidity Level Engine V1 orchestrator.
Manages level detection, lifecycle tracking, state transitions, and database persistence.
Strictly deterministic and observational.
"""

from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert

from core.candles.contract import AggregatedCandle as Candle
from core.structure.contract import ConfirmedSwing
from core.liquidity.contract import (
    LiquidityLevelRecord,
    LiquidityLevelType,
    LiquidityStatus,
    TradingSession,
    SweepEvent,
)
from core.liquidity.sessions import SessionDetector
from core.liquidity.levels import LiquidityLevelDetector
from core.liquidity.sweep import SweepDetector
from core.liquidity.acceptance import AcceptanceRejectionDetector
from database.models import LiquidityLevel


def _get_val(obj, key):
    if hasattr(obj, key):
        return getattr(obj, key)
    if isinstance(obj, dict) and key in obj:
        return obj[key]
    return getattr(obj, key)


class LiquidityEngine:
    """
    Coordinates liquidity level detection and full 7-step lifecycle tracking.
    """

    def __init__(
        self,
        symbol: str = "EURUSD",
        timeframe: str = "M5",
        tz: timezone = timezone.utc,
        approach_mult: Decimal = Decimal("0.10"),
        touch_mult: Decimal = Decimal("0.05"),
        sweep_min_mult: Decimal = Decimal("0.05"),
        sweep_max_mult: Decimal = Decimal("0.50"),
        rejection_mult: Decimal = Decimal("0.30"),
        acceptance_mult: Decimal = Decimal("0.30"),
        fallback_atr: Decimal = Decimal("0.00100"),
    ):
        self.symbol = symbol
        self.timeframe = timeframe
        self.tz = tz
        self.approach_mult = approach_mult
        self.touch_mult = touch_mult
        self.fallback_atr = fallback_atr

        self.level_detector = LiquidityLevelDetector(symbol=symbol, tz=tz)
        self.session_detector = SessionDetector(tz=tz)
        self.sweep_detector = SweepDetector(
            min_sweep_atr_mult=sweep_min_mult,
            max_sweep_atr_mult=sweep_max_mult,
            fallback_atr=fallback_atr,
        )
        self.acceptance_detector = AcceptanceRejectionDetector(
            rejection_atr_mult=rejection_mult,
            acceptance_atr_mult=acceptance_mult,
            fallback_atr=fallback_atr,
        )

    def process_lifecycle(
        self,
        levels: List[LiquidityLevelRecord],
        candles: List[Any],
        atr_value: Optional[Decimal] = None,
    ) -> List[LiquidityLevelRecord]:
        """
        Advance each level's status through the lifecycle based on chronological candle price action.
        Only candles occurring at or after level.created_at are evaluated.
        """
        atr = atr_value if atr_value is not None and atr_value > Decimal("0") else self.fallback_atr
        approach_thresh = self.approach_mult * atr
        touch_thresh = self.touch_mult * atr

        for lvl in levels:
            # Filter candles occurring strictly at or after level creation
            active_candles = []
            for c in candles:
                ts = _get_val(c, "timestamp")
                c_dt = ts.astimezone(self.tz) if ts.tzinfo else ts.replace(tzinfo=self.tz)
                lvl_dt = lvl.created_at.astimezone(self.tz) if lvl.created_at.tzinfo else lvl.created_at.replace(tzinfo=self.tz)
                if c_dt >= lvl_dt:
                    active_candles.append(c)

            if not active_candles or lvl.status in (LiquidityStatus.INVALIDATED, LiquidityStatus.ACCEPTED, LiquidityStatus.REJECTED):
                continue

            is_high = self.sweep_detector.is_high_type(lvl.level_type)
            lvl_price = lvl.price

            for idx, candle in enumerate(active_candles):
                c_high = Decimal(str(_get_val(candle, "high")))
                c_low = Decimal(str(_get_val(candle, "low")))
                c_close = Decimal(str(_get_val(candle, "close")))

                # Step 1: APPROACHED
                if lvl.status == LiquidityStatus.UNTOUCHED:
                    dist = (lvl_price - c_high) if is_high else (c_low - lvl_price)
                    if Decimal("0") <= dist <= approach_thresh:
                        lvl.status = LiquidityStatus.APPROACHED

                # Step 2: TOUCHED
                if lvl.status in (LiquidityStatus.UNTOUCHED, LiquidityStatus.APPROACHED):
                    if is_high:
                        if c_high >= lvl_price - touch_thresh:
                            lvl.status = LiquidityStatus.TOUCHED
                    else:
                        if c_low <= lvl_price + touch_thresh:
                            lvl.status = LiquidityStatus.TOUCHED

                # Step 3: Check for SWEEP
                # Sweep requires penetration beyond level [0.05 * ATR, 0.50 * ATR]
                has_penetrated = (c_high >= lvl_price + (self.sweep_detector.min_sweep_atr_mult * atr)) if is_high else (c_low <= lvl_price - (self.sweep_detector.min_sweep_atr_mult * atr))
                if has_penetrated:
                    sweep_evt = self.sweep_detector.evaluate_sweep(lvl, active_candles, idx, atr_value=atr)
                    if sweep_evt:
                        lvl.status = LiquidityStatus.SWEPT
                        lvl.swept_at = sweep_evt.sweep_timestamp
                        lvl.sweep_depth = sweep_evt.sweep_depth

                        # Check for REJECTION from return
                        # Find candles after return_timestamp
                        subsequent = []
                        for c in active_candles:
                            ts = _get_val(c, "timestamp")
                            c_dt = ts.astimezone(self.tz) if ts.tzinfo else ts.replace(tzinfo=self.tz)
                            ret_dt = sweep_evt.return_timestamp.astimezone(self.tz) if sweep_evt.return_timestamp.tzinfo else sweep_evt.return_timestamp.replace(tzinfo=self.tz)
                            if c_dt >= ret_dt:
                                subsequent.append(c)

                        is_rej, disp, rej_c = self.acceptance_detector.evaluate_rejection(
                            lvl, sweep_evt, subsequent, atr_value=atr
                        )
                        if is_rej and rej_c:
                            lvl.status = LiquidityStatus.REJECTED
                            rej_ts = _get_val(rej_c, "timestamp")
                            lvl.rejected_at = rej_ts
                        break

                # Step 4: Check for ACCEPTANCE (if closed beyond level)
                has_closed_beyond = (c_close > lvl_price) if is_high else (c_close < lvl_price)
                if has_closed_beyond:
                    is_acc, disp, acc_c = self.acceptance_detector.evaluate_acceptance(
                        lvl, active_candles[idx:], atr_value=atr
                    )
                    if is_acc and acc_c:
                        lvl.status = LiquidityStatus.ACCEPTED
                        acc_ts = _get_val(acc_c, "timestamp")
                        lvl.accepted_at = acc_ts
                        break

        return levels

    def upsert_levels(self, db_session: Session, levels: List[LiquidityLevelRecord]) -> int:
        """
        Upserts liquidity levels into database idempotently.
        """
        if not levels:
            return 0

        rows = [
            {
                "symbol": lvl.symbol,
                "timeframe": lvl.timeframe,
                "level_type": lvl.level_type.value,
                "price": lvl.price,
                "start_timestamp": lvl.created_at,
                "created_at": lvl.created_at,
                "strength": lvl.strength,
                "status": lvl.status.value,
                "swept_at": lvl.swept_at,
                "rejected_at": lvl.rejected_at,
                "accepted_at": lvl.accepted_at,
                "invalidated_at": lvl.invalidated_at,
                "source_swing_id": lvl.source_swing_id,
                "session": lvl.session,
                "tolerance": lvl.tolerance,
                "sweep_depth": lvl.sweep_depth,
            }
            for lvl in levels
        ]

        stmt = insert(LiquidityLevel).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["symbol", "timeframe", "level_type", "price", "start_timestamp"],
            set_={
                "status": stmt.excluded.status,
                "swept_at": stmt.excluded.swept_at,
                "rejected_at": stmt.excluded.rejected_at,
                "accepted_at": stmt.excluded.accepted_at,
                "invalidated_at": stmt.excluded.invalidated_at,
                "sweep_depth": stmt.excluded.sweep_depth,
                "strength": stmt.excluded.strength,
            },
        )

        db_session.execute(stmt)
        db_session.commit()
        return len(rows)
