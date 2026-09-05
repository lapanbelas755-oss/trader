"""
Setup Archetype S02: Liquidity Acceptance Continuation.
Strictly deterministic and observational.
Evaluates: Break -> Acceptance -> Follow-through -> Structure Continuation -> FIRE.
"""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, List, Optional, Sequence
from core.liquidity.contract import LiquidityLevelRecord, LiquidityLevelType
from core.structure.contract import StructureEvent, StructureDirection
from core.setups.contract import (
    SetupCode,
    SetupDirection,
    SetupEvidence,
    SetupRecord,
    SetupStatus,
)
from core.setups.state_machine import SetupStateMachine
from core.setups.common import get_val, ensure_utc, evaluate_execution_conditions, check_htf_alignment


class S02LiquidityAcceptanceDetector:
    """
    Detects and tracks S02 Liquidity Acceptance Continuation candidates through the lifecycle:
    OBSERVE -> WATCH -> ARMED -> FIRE.
    """

    def __init__(
        self,
        min_break_atr_mult: Decimal = Decimal("0.10"),
        min_acceptance_candles: int = 2,
        min_follow_through_atr_mult: Decimal = Decimal("0.30"),
        min_structure_atr_mult: Decimal = Decimal("0.10"),
        fallback_atr: Decimal = Decimal("0.00100"),
        expiry_bars: int = 4,
    ):
        self.min_break_atr_mult = min_break_atr_mult
        self.min_acceptance_candles = min_acceptance_candles
        self.min_follow_through_atr_mult = min_follow_through_atr_mult
        self.min_structure_atr_mult = min_structure_atr_mult
        self.fallback_atr = fallback_atr
        self.expiry_bars = expiry_bars
        self.state_machine = SetupStateMachine(default_expiry_bars=expiry_bars)

    def is_high_liquidity(self, level_type: Any) -> bool:
        """Determines if the level is a high level (bullish continuation above high)."""
        lt = str(get_val(level_type, "value", level_type)).upper()
        return any(
            x in lt for x in ("HIGH", "PREVIOUS_DAY_HIGH", "PREVIOUS_WEEK_HIGH", "SESSION_HIGH", "EQUAL_HIGH", "SWING_HIGH")
        )

    def evaluate_at_timestamp(
        self,
        timestamp: datetime,
        symbol: str,
        timeframe: str,
        candles_up_to_t: Sequence[Any],
        levels_up_to_t: Sequence[Any],
        structure_events_up_to_t: Sequence[Any],
        htf_direction: Optional[str] = None,
        current_atr: Optional[Decimal] = None,
        regime: str = "UNKNOWN",
    ) -> List[SetupRecord]:
        """
        Deterministic evaluation of S02 candidates at time T.
        Only data available at or before timestamp T is used.
        """
        ts = ensure_utc(timestamp)
        atr = current_atr if current_atr is not None and current_atr > Decimal("0") else self.fallback_atr
        results: List[SetupRecord] = []

        if not candles_up_to_t:
            return results

        last_candle = candles_up_to_t[-1]
        exec_ok, exec_status = evaluate_execution_conditions(last_candle)

        min_break_disp = self.min_break_atr_mult * atr
        follow_through_disp = self.min_follow_through_atr_mult * atr

        for lvl in levels_up_to_t:
            lvl_type = get_val(lvl, "level_type")
            lvl_price = Decimal(str(get_val(lvl, "price")))
            lvl_created = ensure_utc(get_val(lvl, "created_at"))

            is_high = self.is_high_liquidity(lvl_type)
            direction = SetupDirection.BULLISH if is_high else SetupDirection.BEARISH

            # Find candle index where closed breakout beyond level occurred with min_break_disp
            breakout_idx = None
            for idx, c in enumerate(candles_up_to_t):
                c_ts = ensure_utc(get_val(c, "timestamp"))
                if lvl_created and c_ts < lvl_created:
                    continue

                c_close = Decimal(str(get_val(c, "close")))
                c_high = Decimal(str(get_val(c, "high")))
                c_low = Decimal(str(get_val(c, "low")))

                if is_high:
                    # Wick-only check: high exceeded level, but close is <= level -> NOT A BREAKOUT
                    if c_high > lvl_price and c_close <= lvl_price:
                        continue
                    if c_close - lvl_price >= min_break_disp:
                        breakout_idx = idx
                        break
                else:
                    if c_low < lvl_price and c_close >= lvl_price:
                        continue
                    if lvl_price - c_close >= min_break_disp:
                        breakout_idx = idx
                        break

            if breakout_idx is None:
                continue

            break_candle = candles_up_to_t[breakout_idx]
            break_ts = ensure_utc(get_val(break_candle, "timestamp"))
            break_disp = (
                Decimal(str(get_val(break_candle, "close"))) - lvl_price
                if is_high
                else lvl_price - Decimal(str(get_val(break_candle, "close")))
            )

            setup_id = f"{symbol}_{timeframe}_S02_{direction.value}_{break_ts.strftime('%Y%m%d%H%M')}"
            expires_at = self.state_machine.calculate_expiration(break_ts, num_bars=self.expiry_bars)

            # Check HTF alignment: H1/M15 must not strongly oppose
            htf_aligned, htf_reason = check_htf_alignment(direction, htf_direction)

            # S02 reached WATCH state at breakout
            watch_record = SetupRecord(
                setup_id=setup_id,
                setup_code=SetupCode.S02,
                symbol=symbol,
                timeframe=timeframe,
                timestamp=break_ts,
                direction=direction,
                regime=regime,
                liquidity_type=str(lvl_type),
                structure_type=None,
                anomaly_type=None,
                status=SetupStatus.WATCH,
                evidence=SetupEvidence(
                    liquidity="BROKEN",
                    regime=regime,
                    confirmation="PENDING_ACCEPTANCE",
                    metrics={"breakout_displacement": break_disp},
                ),
                reason=f"Closed breakout beyond {lvl_type} by {break_disp}",
                created_at=break_ts,
                expires_at=expires_at,
            )

            if not htf_aligned:
                results.append(
                    self.state_machine.transition(
                        watch_record,
                        SetupStatus.REJECTED,
                        reason=f"Higher timeframe strongly opposes setup: {htf_reason}",
                        at_timestamp=ts,
                    )
                )
                continue

            # Check acceptance beyond breakout:
            # 1. Minimum 2 closed candles maintaining breakout side
            # 2. Immediate return through level -> INVALID / REJECTED
            # 3. Follow-through displacement >= 0.30 * ATR
            candles_from_break = candles_up_to_t[breakout_idx:]
            immediate_return = False
            consecutive_outside = 0
            max_disp = Decimal("0")
            acceptance_idx = None

            for i, c in enumerate(candles_from_break):
                c_close = Decimal(str(get_val(c, "close")))
                if is_high:
                    if c_close <= lvl_price:
                        immediate_return = True
                        break
                    consecutive_outside += 1
                    disp = c_close - lvl_price
                    if disp > max_disp:
                        max_disp = disp
                else:
                    if c_close >= lvl_price:
                        immediate_return = True
                        break
                    consecutive_outside += 1
                    disp = lvl_price - c_close
                    if disp > max_disp:
                        max_disp = disp

                if consecutive_outside >= self.min_acceptance_candles and max_disp >= follow_through_disp:
                    acceptance_idx = breakout_idx + i
                    break

            if immediate_return:
                results.append(
                    self.state_machine.transition(
                        watch_record,
                        SetupStatus.REJECTED,
                        reason="Immediate return through breakout level invalidates acceptance",
                        at_timestamp=ts,
                    )
                )
                continue

            if acceptance_idx is None:
                if self.state_machine.is_expired(expires_at, ts):
                    results.append(
                        self.state_machine.transition(
                            watch_record,
                            SetupStatus.EXPIRED,
                            reason="Acceptance and follow-through not established within window",
                            at_timestamp=ts,
                        )
                    )
                else:
                    results.append(watch_record)
                continue

            # Acceptance + follow-through achieved -> ARMED state
            acc_candle = candles_up_to_t[acceptance_idx]
            acc_ts = ensure_utc(get_val(acc_candle, "timestamp"))
            armed_expires = self.state_machine.calculate_expiration(acc_ts, num_bars=self.expiry_bars)

            armed_record = SetupRecord(
                setup_id=setup_id,
                setup_code=SetupCode.S02,
                symbol=symbol,
                timeframe=timeframe,
                timestamp=acc_ts,
                direction=direction,
                regime=regime,
                liquidity_type=str(lvl_type),
                structure_type=None,
                anomaly_type=None,
                status=SetupStatus.ARMED,
                evidence=SetupEvidence(
                    liquidity="ACCEPTED",
                    price_response="FOLLOW_THROUGH",
                    regime=regime,
                    confirmation="PENDING_STRUCTURE",
                    metrics={"follow_through_displacement": max_disp},
                ),
                reason=f"Acceptance confirmed with follow-through {max_disp}",
                created_at=break_ts,
                expires_at=armed_expires,
            )

            # Check Structure Confirmation:
            # Need M5 structure confirmation in breakout direction (BOS_BULLISH for high, BOS_BEARISH for low)
            min_struct_disp = self.min_structure_atr_mult * atr
            matching_structure = None

            for s_evt in structure_events_up_to_t:
                s_ts = ensure_utc(get_val(s_evt, "confirmed_at", get_val(s_evt, "timestamp")))
                if s_ts < break_ts or s_ts > ts:
                    continue

                s_type = str(get_val(s_evt, "structure_type")).upper()
                s_disp = get_val(s_evt, "displacement")
                s_disp_dec = Decimal(str(s_disp)) if s_disp is not None else Decimal("0")

                if is_high:
                    if ("BOS_BULLISH" in s_type or "CHOCH_UP" in s_type) and s_disp_dec >= min_struct_disp:
                        matching_structure = s_evt
                        break
                else:
                    if ("BOS_BEARISH" in s_type or "CHOCH_DOWN" in s_type) and s_disp_dec >= min_struct_disp:
                        matching_structure = s_evt
                        break

            if matching_structure is None:
                if self.state_machine.is_expired(armed_expires, ts):
                    results.append(
                        self.state_machine.transition(
                            armed_record,
                            SetupStatus.EXPIRED,
                            reason="Structure confirmation not found within validity window",
                            at_timestamp=ts,
                        )
                    )
                else:
                    results.append(armed_record)
                continue

            struct_ts = ensure_utc(get_val(matching_structure, "confirmed_at", get_val(matching_structure, "timestamp")))
            struct_type = str(get_val(matching_structure, "structure_type"))

            if not exec_ok:
                results.append(
                    self.state_machine.transition(
                        armed_record,
                        SetupStatus.REJECTED,
                        reason=f"Execution conditions failed: {exec_status}",
                        at_timestamp=struct_ts,
                    )
                )
                continue

            # FIRE!
            fire_record = SetupRecord(
                setup_id=setup_id,
                setup_code=SetupCode.S02,
                symbol=symbol,
                timeframe=timeframe,
                timestamp=struct_ts,
                direction=direction,
                regime=regime,
                liquidity_type=str(lvl_type),
                structure_type=struct_type,
                anomaly_type=None,
                status=SetupStatus.FIRE,
                evidence=SetupEvidence(
                    liquidity="ACCEPTED",
                    price_response="STRONG_FOLLOW_THROUGH",
                    structure=struct_type,
                    regime=regime,
                    confirmation="VALID",
                    execution=exec_status,
                    metrics={
                        "breakout_displacement": break_disp,
                        "follow_through_displacement": max_disp,
                        "structure_displacement": get_val(matching_structure, "displacement"),
                    },
                ),
                reason="Breakout, acceptance, follow-through, and structure confirmed",
                created_at=break_ts,
                expires_at=None,
            )
            results.append(fire_record)

        return results
