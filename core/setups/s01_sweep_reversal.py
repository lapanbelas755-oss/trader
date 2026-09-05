"""
Setup Archetype S01: Liquidity Sweep Reversal.
Strictly deterministic and observational.
Evaluates: Sweep -> Return -> Rejection -> Failed Expectation -> Structure Shift -> FIRE.
"""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, List, Optional, Sequence
from core.liquidity.contract import LiquidityLevelRecord, LiquidityLevelType, SweepEvent
from core.liquidity.sweep import SweepDetector
from core.liquidity.acceptance import AcceptanceRejectionDetector
from core.structure.contract import StructureEvent, BreakType
from core.setups.contract import (
    SetupCode,
    SetupDirection,
    SetupEvidence,
    SetupRecord,
    SetupStatus,
)
from core.setups.state_machine import SetupStateMachine
from core.setups.common import get_val, ensure_utc, evaluate_execution_conditions


class S01SweepReversalDetector:
    """
    Detects and tracks S01 Liquidity Sweep Reversal candidates through the lifecycle:
    OBSERVE -> WATCH -> ARMED -> FIRE.
    """

    def __init__(
        self,
        min_sweep_atr_mult: Decimal = Decimal("0.05"),
        max_sweep_atr_mult: Decimal = Decimal("0.50"),
        max_return_bars: int = 3,
        rejection_atr_mult: Decimal = Decimal("0.30"),
        structure_displacement_atr_mult: Decimal = Decimal("0.10"),
        fallback_atr: Decimal = Decimal("0.00100"),
    ):
        self.min_sweep_atr_mult = min_sweep_atr_mult
        self.max_sweep_atr_mult = max_sweep_atr_mult
        self.max_return_bars = max_return_bars
        self.rejection_atr_mult = rejection_atr_mult
        self.structure_displacement_atr_mult = structure_displacement_atr_mult
        self.fallback_atr = fallback_atr

        self.sweep_detector = SweepDetector(
            min_sweep_atr_mult=min_sweep_atr_mult,
            max_sweep_atr_mult=max_sweep_atr_mult,
            fallback_atr=fallback_atr,
            max_return_bars=max_return_bars,
        )
        self.acceptance_detector = AcceptanceRejectionDetector(
            rejection_atr_mult=rejection_atr_mult,
            acceptance_atr_mult=rejection_atr_mult,
            fallback_atr=fallback_atr,
        )
        self.state_machine = SetupStateMachine(default_expiry_bars=max_return_bars)

    def is_high_liquidity(self, level_type: Any) -> bool:
        """Determines if the level is a high/buy-side liquidity pool (swept high -> sell reversal)."""
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
        Deterministic evaluation of S01 candidates at time T.
        Only data available at or before timestamp T is used.
        """
        ts = ensure_utc(timestamp)
        atr = current_atr if current_atr is not None and current_atr > Decimal("0") else self.fallback_atr
        results: List[SetupRecord] = []

        if not candles_up_to_t:
            return results

        last_candle = candles_up_to_t[-1]
        exec_ok, exec_status = evaluate_execution_conditions(last_candle)

        # Iterate active/historical levels to check for sweeps
        for lvl in levels_up_to_t:
            lvl_type = get_val(lvl, "level_type")
            lvl_price = Decimal(str(get_val(lvl, "price")))
            lvl_created = ensure_utc(get_val(lvl, "created_at"))

            is_high = self.is_high_liquidity(lvl_type)
            direction = SetupDirection.BEARISH if is_high else SetupDirection.BULLISH

            # Find candle index where penetration of level first occurred
            penetration_idx = None
            min_pen = self.min_sweep_atr_mult * atr
            max_pen = self.max_sweep_atr_mult * atr

            for idx, c in enumerate(candles_up_to_t):
                c_ts = ensure_utc(get_val(c, "timestamp"))
                if lvl_created and c_ts < lvl_created:
                    continue

                c_high = Decimal(str(get_val(c, "high")))
                c_low = Decimal(str(get_val(c, "low")))
                c_close = Decimal(str(get_val(c, "close")))

                if is_high:
                    pen = c_high - lvl_price
                    if pen >= min_pen:
                        penetration_idx = idx
                        break
                else:
                    pen = lvl_price - c_low
                    if pen >= min_pen:
                        penetration_idx = idx
                        break

            if penetration_idx is None:
                continue

            pen_candle = candles_up_to_t[penetration_idx]
            pen_ts = ensure_utc(get_val(pen_candle, "timestamp"))

            # Check sweep & return across level within max 3 candles
            sweep_evt: Optional[SweepEvent] = None
            max_end = min(penetration_idx + self.max_return_bars + 1, len(candles_up_to_t))
            sweep_extreme = Decimal(str(get_val(pen_candle, "high" if is_high else "low")))
            return_idx = None

            for i in range(penetration_idx, max_end):
                c = candles_up_to_t[i]
                c_h = Decimal(str(get_val(c, "high")))
                c_l = Decimal(str(get_val(c, "low")))
                c_c = Decimal(str(get_val(c, "close")))

                if is_high:
                    if c_h > sweep_extreme:
                        sweep_extreme = c_h
                    sweep_depth = sweep_extreme - lvl_price
                    if sweep_depth > max_pen:
                        # Exceeded maximum allowed sweep penetration -> Invalidated as clean sweep
                        break
                    if c_c < lvl_price:
                        return_idx = i
                        sweep_evt = SweepEvent(
                            symbol=symbol,
                            level_type=lvl_type,
                            level_price=lvl_price,
                            sweep_direction="HIGH_SWEPT",
                            sweep_timestamp=pen_ts,
                            sweep_extreme=sweep_extreme,
                            sweep_depth=sweep_depth,
                            return_timestamp=ensure_utc(get_val(c, "timestamp")),
                        )
                        break
                else:
                    if c_l < sweep_extreme:
                        sweep_extreme = c_l
                    sweep_depth = lvl_price - sweep_extreme
                    if sweep_depth > max_pen:
                        break
                    if c_c > lvl_price:
                        return_idx = i
                        sweep_evt = SweepEvent(
                            symbol=symbol,
                            level_type=lvl_type,
                            level_price=lvl_price,
                            sweep_direction="LOW_SWEPT",
                            sweep_timestamp=pen_ts,
                            sweep_extreme=sweep_extreme,
                            sweep_depth=sweep_depth,
                            return_timestamp=ensure_utc(get_val(c, "timestamp")),
                        )
                        break

            setup_id = f"{symbol}_{timeframe}_S01_{direction.value}_{pen_ts.strftime('%Y%m%d%H%M')}"
            expires_at = self.state_machine.calculate_expiration(pen_ts, num_bars=self.max_return_bars)

            # Check if return occurred too late or didn't return
            if sweep_evt is None:
                # If we have passed the 3-candle window without return
                if len(candles_up_to_t) - 1 >= penetration_idx + self.max_return_bars:
                    rec = SetupRecord(
                        setup_id=setup_id,
                        setup_code=SetupCode.S01,
                        symbol=symbol,
                        timeframe=timeframe,
                        timestamp=ts,
                        direction=direction,
                        regime=regime,
                        liquidity_type=str(lvl_type),
                        structure_type=None,
                        anomaly_type=None,
                        status=SetupStatus.EXPIRED,
                        evidence=SetupEvidence(
                            liquidity="NO_RETURN",
                            trap="BREAKOUT_CONTINUED",
                            regime=regime,
                            confirmation="EXPIRED",
                        ),
                        reason="Failed to return across liquidity level within 3 candles",
                        created_at=pen_ts,
                        expires_at=expires_at,
                    )
                    results.append(rec)
                continue

            # Level swept and returned -> WATCH state reached
            watch_record = SetupRecord(
                setup_id=setup_id,
                setup_code=SetupCode.S01,
                symbol=symbol,
                timeframe=timeframe,
                timestamp=sweep_evt.return_timestamp,
                direction=direction,
                regime=regime,
                liquidity_type=str(lvl_type),
                structure_type=None,
                anomaly_type=None,
                status=SetupStatus.WATCH,
                evidence=SetupEvidence(
                    liquidity="SWEPT",
                    trap="FAILED_ACCEPTANCE",
                    regime=regime,
                    confirmation="PENDING_REJECTION",
                    metrics={"sweep_depth": sweep_evt.sweep_depth},
                ),
                reason=f"Liquidity {lvl_type} swept by {sweep_evt.sweep_depth} and returned",
                created_at=pen_ts,
                expires_at=expires_at,
            )

            # Check for Rejection displacement >= 0.30 * ATR
            subsequent_candles = candles_up_to_t[return_idx:]
            is_rejected, rej_disp, rej_candle = self.acceptance_detector.evaluate_rejection(
                lvl, sweep_evt, subsequent_candles, atr_value=atr
            )

            if not is_rejected:
                # Still in WATCH or EXPIRED if time exceeded
                if self.state_machine.is_expired(expires_at, ts):
                    results.append(
                        self.state_machine.transition(
                            watch_record,
                            SetupStatus.EXPIRED,
                            reason="Rejection displacement not achieved within window",
                            at_timestamp=ts,
                        )
                    )
                else:
                    results.append(watch_record)
                continue

            rej_ts = ensure_utc(get_val(rej_candle, "timestamp"))
            armed_expires = self.state_machine.calculate_expiration(rej_ts, num_bars=self.max_return_bars)

            # Rejection displacement achieved -> ARMED state
            armed_record = SetupRecord(
                setup_id=setup_id,
                setup_code=SetupCode.S01,
                symbol=symbol,
                timeframe=timeframe,
                timestamp=rej_ts,
                direction=direction,
                regime=regime,
                liquidity_type=str(lvl_type),
                structure_type=None,
                anomaly_type=None,
                status=SetupStatus.ARMED,
                evidence=SetupEvidence(
                    liquidity="SWEPT",
                    price_response="REJECTED",
                    trap="FAILED_ACCEPTANCE",
                    regime=regime,
                    confirmation="PENDING_STRUCTURE_SHIFT",
                    metrics={"sweep_depth": sweep_evt.sweep_depth, "rejection_displacement": rej_disp},
                ),
                reason=f"Sweep rejected with displacement {rej_disp}",
                created_at=pen_ts,
                expires_at=armed_expires,
            )

            # Check Structure shift confirmation:
            # Need M5 structure shift (CHoCH or BOS in the reversal direction) confirmed at or after rej_ts and <= ts
            min_struct_disp = self.structure_displacement_atr_mult * atr
            matching_structure_shift = None

            for s_evt in structure_events_up_to_t:
                s_ts = ensure_utc(get_val(s_evt, "confirmed_at", get_val(s_evt, "timestamp")))
                if s_ts < rej_ts or s_ts > ts:
                    continue

                s_type = str(get_val(s_evt, "structure_type")).upper()
                s_disp = get_val(s_evt, "displacement")
                s_disp_dec = Decimal(str(s_disp)) if s_disp is not None else Decimal("0")

                if is_high:
                    # Looking for bearish shift: CHOCH_DOWN or BOS_BEARISH
                    if ("CHOCH_DOWN" in s_type or "BEARISH" in s_type) and s_disp_dec >= min_struct_disp:
                        matching_structure_shift = s_evt
                        break
                else:
                    # Looking for bullish shift: CHOCH_UP or BOS_BULLISH
                    if ("CHOCH_UP" in s_type or "BULLISH" in s_type) and s_disp_dec >= min_struct_disp:
                        matching_structure_shift = s_evt
                        break

            if matching_structure_shift is None:
                if self.state_machine.is_expired(armed_expires, ts):
                    results.append(
                        self.state_machine.transition(
                            armed_record,
                            SetupStatus.EXPIRED,
                            reason="Structure confirmation not met within window",
                            at_timestamp=ts,
                        )
                    )
                else:
                    results.append(armed_record)
                continue

            # Structure shift confirmed! Check execution conditions
            shift_ts = ensure_utc(get_val(matching_structure_shift, "confirmed_at", get_val(matching_structure_shift, "timestamp")))
            shift_type = str(get_val(matching_structure_shift, "structure_type"))

            if not exec_ok:
                results.append(
                    self.state_machine.transition(
                        armed_record,
                        SetupStatus.REJECTED,
                        reason=f"Execution conditions failed: {exec_status}",
                        at_timestamp=shift_ts,
                    )
                )
                continue

            # FIRE!
            fire_record = SetupRecord(
                setup_id=setup_id,
                setup_code=SetupCode.S01,
                symbol=symbol,
                timeframe=timeframe,
                timestamp=shift_ts,
                direction=direction,
                regime=regime,
                liquidity_type=str(lvl_type),
                structure_type=shift_type,
                anomaly_type=None,
                status=SetupStatus.FIRE,
                evidence=SetupEvidence(
                    liquidity="SWEPT",
                    price_response="STRONG_REJECTION",
                    structure=shift_type,
                    trap="FAILED_ACCEPTANCE",
                    regime=regime,
                    confirmation="VALID",
                    execution=exec_status,
                    metrics={
                        "sweep_depth": sweep_evt.sweep_depth,
                        "rejection_displacement": rej_disp,
                        "structure_displacement": get_val(matching_structure_shift, "displacement"),
                    },
                ),
                reason="Sweep, rejection, and structure shift confirmed",
                created_at=pen_ts,
                expires_at=None,
            )
            results.append(fire_record)

        return results
