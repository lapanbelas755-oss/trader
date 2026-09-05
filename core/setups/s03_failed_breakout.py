"""
Setup Archetype S03: Failed Breakout Trap.
Strictly deterministic and observational.
Evaluates: Breakout -> Failure Return within 3 candles -> Opposite Displacement >= 0.30 ATR -> Opposite Structure Shift -> FIRE.
"""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, List, Optional, Sequence
from core.liquidity.contract import LiquidityLevelRecord, LiquidityLevelType
from core.structure.contract import StructureEvent
from core.setups.contract import (
    SetupCode,
    SetupDirection,
    SetupEvidence,
    SetupRecord,
    SetupStatus,
)
from core.setups.state_machine import SetupStateMachine
from core.setups.common import get_val, ensure_utc, evaluate_execution_conditions


class S03FailedBreakoutDetector:
    """
    Detects and tracks S03 Failed Breakout Trap candidates through the lifecycle:
    OBSERVE -> WATCH -> ARMED -> FIRE.
    """

    def __init__(
        self,
        min_break_atr_mult: Decimal = Decimal("0.10"),
        max_failure_bars: int = 3,
        min_opposite_disp_atr_mult: Decimal = Decimal("0.30"),
        min_structure_atr_mult: Decimal = Decimal("0.10"),
        fallback_atr: Decimal = Decimal("0.00100"),
    ):
        self.min_break_atr_mult = min_break_atr_mult
        self.max_failure_bars = max_failure_bars
        self.min_opposite_disp_atr_mult = min_opposite_disp_atr_mult
        self.min_structure_atr_mult = min_structure_atr_mult
        self.fallback_atr = fallback_atr
        self.state_machine = SetupStateMachine(default_expiry_bars=max_failure_bars)

    def is_high_liquidity(self, level_type: Any) -> bool:
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
        current_atr: Optional[Decimal] = None,
        regime: str = "UNKNOWN",
    ) -> List[SetupRecord]:
        """
        Deterministic evaluation of S03 candidates at time T.
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
        min_opp_disp = self.min_opposite_disp_atr_mult * atr

        for lvl in levels_up_to_t:
            lvl_type = get_val(lvl, "level_type")
            lvl_price = Decimal(str(get_val(lvl, "price")))
            lvl_created = ensure_utc(get_val(lvl, "created_at"))

            is_high = self.is_high_liquidity(lvl_type)
            # A broken high that fails traps buyers -> Reversal is BEARISH
            # A broken low that fails traps sellers -> Reversal is BULLISH
            direction = SetupDirection.BEARISH if is_high else SetupDirection.BULLISH

            # Find candle index where closed breakout occurred
            breakout_idx = None
            for idx, c in enumerate(candles_up_to_t):
                c_ts = ensure_utc(get_val(c, "timestamp"))
                if lvl_created and c_ts < lvl_created:
                    continue

                c_close = Decimal(str(get_val(c, "close")))
                c_high = Decimal(str(get_val(c, "high")))
                c_low = Decimal(str(get_val(c, "low")))

                if is_high:
                    # Wick-only penetration must not be classified as a breakout
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
            setup_id = f"{symbol}_{timeframe}_S03_{direction.value}_{break_ts.strftime('%Y%m%d%H%M')}"
            expires_at = self.state_machine.calculate_expiration(break_ts, num_bars=self.max_failure_bars)

            # Check failure: price must return through the level within 3 closed M5 candles
            # (i.e. between breakout_idx + 1 and breakout_idx + max_failure_bars + 1)
            end_search = min(breakout_idx + self.max_failure_bars + 1, len(candles_up_to_t))
            return_idx = None

            for i in range(breakout_idx + 1, end_search):
                c = candles_up_to_t[i]
                c_close = Decimal(str(get_val(c, "close")))
                if is_high:
                    if c_close < lvl_price:
                        return_idx = i
                        break
                else:
                    if c_close > lvl_price:
                        return_idx = i
                        break

            # If no return happened and 3 candles passed -> EXPIRED (breakout held, not a trap)
            if return_idx is None:
                if len(candles_up_to_t) - 1 >= breakout_idx + self.max_failure_bars:
                    results.append(
                        SetupRecord(
                            setup_id=setup_id,
                            setup_code=SetupCode.S03,
                            symbol=symbol,
                            timeframe=timeframe,
                            timestamp=ts,
                            direction=direction,
                            regime=regime,
                            liquidity_type=str(lvl_type),
                            status=SetupStatus.EXPIRED,
                            evidence=SetupEvidence(
                                trap="BREAKOUT_HELD",
                                regime=regime,
                                confirmation="NO_FAILURE",
                            ),
                            reason="Breakout did not fail within 3 closed candles",
                            created_at=break_ts,
                            expires_at=expires_at,
                        )
                    )
                else:
                    # Still in breakout watch phase
                    results.append(
                        SetupRecord(
                            setup_id=setup_id,
                            setup_code=SetupCode.S03,
                            symbol=symbol,
                            timeframe=timeframe,
                            timestamp=break_ts,
                            direction=direction,
                            regime=regime,
                            liquidity_type=str(lvl_type),
                            status=SetupStatus.WATCH,
                            evidence=SetupEvidence(
                                trap="BREAKOUT_OCCURRED",
                                regime=regime,
                                confirmation="PENDING_FAILURE",
                            ),
                            reason=f"Breakout occurred, watching for trap failure within {self.max_failure_bars} candles",
                            created_at=break_ts,
                            expires_at=expires_at,
                        )
                    )
                continue

            return_candle = candles_up_to_t[return_idx]
            return_ts = ensure_utc(get_val(return_candle, "timestamp"))

            # Check opposite displacement >= 0.30 * ATR
            opp_disp_achieved = False
            opp_disp_idx = None
            max_opp_disp = Decimal("0")

            for i in range(return_idx, len(candles_up_to_t)):
                c = candles_up_to_t[i]
                c_close = Decimal(str(get_val(c, "close")))
                if is_high:
                    disp = lvl_price - c_close
                else:
                    disp = c_close - lvl_price

                if disp > max_opp_disp:
                    max_opp_disp = disp
                if max_opp_disp >= min_opp_disp:
                    opp_disp_achieved = True
                    opp_disp_idx = i
                    break

            watch_record = SetupRecord(
                setup_id=setup_id,
                setup_code=SetupCode.S03,
                symbol=symbol,
                timeframe=timeframe,
                timestamp=return_ts,
                direction=direction,
                regime=regime,
                liquidity_type=str(lvl_type),
                status=SetupStatus.WATCH,
                evidence=SetupEvidence(
                    trap="FAILED_BREAKOUT",
                    price_response="RETURN_THROUGH_LEVEL",
                    regime=regime,
                    confirmation="PENDING_OPPOSITE_DISPLACEMENT",
                ),
                reason="Breakout failed and returned through level",
                created_at=break_ts,
                expires_at=expires_at,
            )

            if not opp_disp_achieved:
                if self.state_machine.is_expired(expires_at, ts):
                    results.append(
                        self.state_machine.transition(
                            watch_record,
                            SetupStatus.EXPIRED,
                            reason="Opposite displacement not achieved within validity window",
                            at_timestamp=ts,
                        )
                    )
                else:
                    results.append(watch_record)
                continue

            disp_candle = candles_up_to_t[opp_disp_idx]
            disp_ts = ensure_utc(get_val(disp_candle, "timestamp"))
            armed_expires = self.state_machine.calculate_expiration(disp_ts, num_bars=self.max_failure_bars)

            # ARMED state: Failed breakout + opposite displacement achieved
            armed_record = SetupRecord(
                setup_id=setup_id,
                setup_code=SetupCode.S03,
                symbol=symbol,
                timeframe=timeframe,
                timestamp=disp_ts,
                direction=direction,
                regime=regime,
                liquidity_type=str(lvl_type),
                status=SetupStatus.ARMED,
                evidence=SetupEvidence(
                    trap="FAILED_BREAKOUT",
                    price_response="OPPOSITE_DISPLACEMENT",
                    regime=regime,
                    confirmation="PENDING_STRUCTURE_BREAK",
                    metrics={"opposite_displacement": max_opp_disp},
                ),
                reason=f"Opposite displacement of {max_opp_disp} achieved",
                created_at=break_ts,
                expires_at=armed_expires,
            )

            # Check Opposite M5 structure break:
            # For broken high: bearish CHoCH or BOS_BEARISH
            # For broken low: bullish CHoCH or BOS_BULLISH
            min_struct_disp = self.min_structure_atr_mult * atr
            matching_structure = None

            for s_evt in structure_events_up_to_t:
                s_ts = ensure_utc(get_val(s_evt, "confirmed_at", get_val(s_evt, "timestamp")))
                if s_ts < return_ts or s_ts > ts:
                    continue

                s_type = str(get_val(s_evt, "structure_type")).upper()
                s_disp = get_val(s_evt, "displacement")
                s_disp_dec = Decimal(str(s_disp)) if s_disp is not None else Decimal("0")

                if is_high:
                    if ("CHOCH_DOWN" in s_type or "BOS_BEARISH" in s_type or "BEARISH" in s_type) and s_disp_dec >= min_struct_disp:
                        matching_structure = s_evt
                        break
                else:
                    if ("CHOCH_UP" in s_type or "BOS_BULLISH" in s_type or "BULLISH" in s_type) and s_disp_dec >= min_struct_disp:
                        matching_structure = s_evt
                        break

            if matching_structure is None:
                if self.state_machine.is_expired(armed_expires, ts):
                    results.append(
                        self.state_machine.transition(
                            armed_record,
                            SetupStatus.EXPIRED,
                            reason="Opposite structure break not confirmed within validity window",
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
                setup_code=SetupCode.S03,
                symbol=symbol,
                timeframe=timeframe,
                timestamp=struct_ts,
                direction=direction,
                regime=regime,
                liquidity_type=str(lvl_type),
                structure_type=struct_type,
                status=SetupStatus.FIRE,
                evidence=SetupEvidence(
                    trap="CONFIRMED_BREAKOUT_TRAP",
                    price_response="STRONG_OPPOSITE_DISPLACEMENT",
                    structure=struct_type,
                    regime=regime,
                    confirmation="VALID",
                    execution=exec_status,
                    metrics={
                        "opposite_displacement": max_opp_disp,
                        "structure_displacement": get_val(matching_structure, "displacement"),
                    },
                ),
                reason="Failed breakout, opposite displacement, and structure shift confirmed",
                created_at=break_ts,
                expires_at=None,
            )
            results.append(fire_record)

        return results
