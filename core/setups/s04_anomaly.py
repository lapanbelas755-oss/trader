"""
Setup Archetype S04: Effort vs Result Anomaly.
Strictly deterministic and observational.
Tick activity is NOT buyer/seller volume or institutional order flow.
Anomaly candidate: activity_zscore >= 2.0 and price_response significantly below baseline.
Strong anomaly: activity_zscore >= 2.5 and price_response_zscore <= -1.5.
Anomaly alone MUST NOT fire. Requires contextual confirmation + directional confirmation.
"""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, List, Optional, Sequence
from core.setups.contract import (
    SetupCode,
    SetupDirection,
    SetupEvidence,
    SetupRecord,
    SetupStatus,
)
from core.setups.state_machine import SetupStateMachine
from core.setups.common import get_val, ensure_utc, evaluate_execution_conditions


class S04EffortResultAnomalyDetector:
    """
    Detects and tracks S04 Effort vs Result Anomaly candidates through the lifecycle:
    OBSERVE -> WATCH -> ARMED -> FIRE.
    """

    def __init__(
        self,
        candidate_activity_zscore: Decimal = Decimal("2.0"),
        strong_activity_zscore: Decimal = Decimal("2.5"),
        strong_price_response_zscore: Decimal = Decimal("-1.5"),
        candidate_price_response_zscore: Decimal = Decimal("-1.0"),
        expiry_bars: int = 3,
    ):
        self.candidate_activity_zscore = candidate_activity_zscore
        self.strong_activity_zscore = strong_activity_zscore
        self.strong_price_response_zscore = strong_price_response_zscore
        self.candidate_price_response_zscore = candidate_price_response_zscore
        self.expiry_bars = expiry_bars
        self.state_machine = SetupStateMachine(default_expiry_bars=expiry_bars)

    def evaluate_at_timestamp(
        self,
        timestamp: datetime,
        symbol: str,
        timeframe: str,
        candles_up_to_t: Sequence[Any],
        features_up_to_t: Sequence[Any],
        levels_up_to_t: Sequence[Any],
        structure_events_up_to_t: Sequence[Any],
        regime: str = "UNKNOWN",
    ) -> List[SetupRecord]:
        """
        Deterministic evaluation of S04 candidates at time T.
        Only data available at or before timestamp T is used.
        """
        ts = ensure_utc(timestamp)
        results: List[SetupRecord] = []

        if not candles_up_to_t or not features_up_to_t:
            return results

        last_candle = candles_up_to_t[-1]
        exec_ok, exec_status = evaluate_execution_conditions(last_candle)

        # Match features with candle timestamps
        feat_map = {}
        for f in features_up_to_t:
            f_ts = ensure_utc(get_val(f, "timestamp"))
            feat_map[f_ts] = f

        candle_map = {}
        for c in candles_up_to_t:
            c_ts = ensure_utc(get_val(c, "timestamp"))
            candle_map[c_ts] = c

        # Scan for anomalies in features up to T
        for f_ts, feat in feat_map.items():
            if f_ts > ts:
                continue

            act_z = get_val(feat, "activity_zscore")
            resp_z = get_val(feat, "price_response_zscore")
            is_cand = get_val(feat, "is_anomaly_candidate", False)
            is_strong = get_val(feat, "is_strong_anomaly", False)

            act_z_dec = Decimal(str(act_z)) if act_z is not None else None
            resp_z_dec = Decimal(str(resp_z)) if resp_z is not None else None

            # Check criteria
            is_strong_flag = is_strong or (
                act_z_dec is not None
                and resp_z_dec is not None
                and act_z_dec >= self.strong_activity_zscore
                and resp_z_dec <= self.strong_price_response_zscore
            )
            is_cand_flag = is_cand or (
                act_z_dec is not None
                and resp_z_dec is not None
                and act_z_dec >= self.candidate_activity_zscore
                and resp_z_dec <= self.candidate_price_response_zscore
            )

            if not (is_strong_flag or is_cand_flag):
                continue

            anomaly_type = "STRONG_ANOMALY" if is_strong_flag else "ANOMALY_CANDIDATE"

            # Determine anomaly bar direction
            c_bar = candle_map.get(f_ts)
            c_open = Decimal(str(get_val(c_bar, "open"))) if c_bar else Decimal("0")
            c_close = Decimal(str(get_val(c_bar, "close"))) if c_bar else Decimal("0")
            c_high = Decimal(str(get_val(c_bar, "high"))) if c_bar else Decimal("0")
            c_low = Decimal(str(get_val(c_bar, "low"))) if c_bar else Decimal("0")

            # High effort with weak result suggests absorption/exhaustion:
            # If bar tried to push up (close > open or long upper wick), potential absorption is bearish
            # If bar tried to push down (close < open or long lower wick), potential absorption is bullish
            direction = SetupDirection.BEARISH if c_close >= c_open else SetupDirection.BULLISH

            setup_id = f"{symbol}_{timeframe}_S04_{direction.value}_{f_ts.strftime('%Y%m%d%H%M')}"
            expires_at = self.state_machine.calculate_expiration(f_ts, num_bars=self.expiry_bars)

            # WATCH state: Anomaly candidate detected
            watch_record = SetupRecord(
                setup_id=setup_id,
                setup_code=SetupCode.S04,
                symbol=symbol,
                timeframe=timeframe,
                timestamp=f_ts,
                direction=direction,
                regime=regime,
                anomaly_type=anomaly_type,
                status=SetupStatus.WATCH,
                evidence=SetupEvidence(
                    anomaly=anomaly_type,
                    price_response="DISPROPORTIONATELY_WEAK",
                    regime=regime,
                    confirmation="PENDING_CONTEXT",
                    metrics={
                        "activity_zscore": act_z_dec,
                        "price_response_zscore": resp_z_dec,
                    },
                ),
                reason=f"Effort vs Result Anomaly: activity_z={act_z_dec}, response_z={resp_z_dec}",
                created_at=f_ts,
                expires_at=expires_at,
            )

            # Contextual confirmations check (must have at least one):
            # 1. Liquidity interaction: active level touched, swept, or approached around f_ts
            # 2. Structure failure: failed structure break or rejection around f_ts
            # 3. Failed expectation: candle effort large but resulting body < 25% of range (pinbar/doji)
            has_liquidity_context = False
            has_structure_context = False
            has_failed_expectation = False
            context_reason = []

            # Check 1: Liquidity interaction
            for lvl in levels_up_to_t:
                lvl_p = Decimal(str(get_val(lvl, "price")))
                lvl_type = str(get_val(lvl, "level_type"))
                # If high was near level or low was near level
                if abs(c_high - lvl_p) <= Decimal("0.00030") or abs(c_low - lvl_p) <= Decimal("0.00030"):
                    has_liquidity_context = True
                    context_reason.append(f"Liquidity interaction at {lvl_type}")
                    break

            # Check 2: Structure failure / interaction
            for s_evt in structure_events_up_to_t:
                s_ts = ensure_utc(get_val(s_evt, "confirmed_at", get_val(s_evt, "timestamp")))
                if abs((s_ts - f_ts).total_seconds()) <= 3600:  # Within 1 hour
                    has_structure_context = True
                    context_reason.append(f"Structure context: {get_val(s_evt, 'structure_type')}")
                    break

            # Check 3: Failed expectation
            rng = c_high - c_low
            body = abs(c_close - c_open)
            if rng > Decimal("0") and (body / rng) <= Decimal("0.30"):
                has_failed_expectation = True
                context_reason.append("Disproportionately small body despite high activity (pinbar/absorption)")

            has_context = has_liquidity_context or has_structure_context or has_failed_expectation

            # Anomaly ALONE must NOT fire or advance without context!
            if not has_context:
                if self.state_machine.is_expired(expires_at, ts):
                    results.append(
                        self.state_machine.transition(
                            watch_record,
                            SetupStatus.EXPIRED,
                            reason="Anomaly has no contextual confirmation within validity window",
                            at_timestamp=ts,
                        )
                    )
                else:
                    results.append(watch_record)
                continue

            # Context confirmed -> ARMED state
            armed_record = SetupRecord(
                setup_id=setup_id,
                setup_code=SetupCode.S04,
                symbol=symbol,
                timeframe=timeframe,
                timestamp=f_ts,
                direction=direction,
                regime=regime,
                anomaly_type=anomaly_type,
                status=SetupStatus.ARMED,
                evidence=SetupEvidence(
                    anomaly=anomaly_type,
                    price_response="ABSORPTION_CANDIDATE",
                    trap="FAILED_EXPECTATION" if has_failed_expectation else None,
                    liquidity="INTERACTION" if has_liquidity_context else None,
                    structure="CONTEXT_PRESENT" if has_structure_context else None,
                    regime=regime,
                    confirmation="PENDING_DIRECTIONAL_CONFIRMATION",
                    metrics={
                        "activity_zscore": act_z_dec,
                        "price_response_zscore": resp_z_dec,
                    },
                ),
                reason=f"Anomaly with context: {'; '.join(context_reason)}",
                created_at=f_ts,
                expires_at=expires_at,
            )

            # Directional confirmation:
            # Need confirmation structure shift or subsequent candle confirming move in setup direction
            matching_confirmation = None
            for s_evt in structure_events_up_to_t:
                s_ts = ensure_utc(get_val(s_evt, "confirmed_at", get_val(s_evt, "timestamp")))
                if s_ts <= f_ts or s_ts > ts:
                    continue

                s_type = str(get_val(s_evt, "structure_type")).upper()
                if direction == SetupDirection.BEARISH and ("BEARISH" in s_type or "DOWN" in s_type):
                    matching_confirmation = s_evt
                    break
                elif direction == SetupDirection.BULLISH and ("BULLISH" in s_type or "UP" in s_type):
                    matching_confirmation = s_evt
                    break

            if matching_confirmation is None:
                # Also allow confirmation via subsequent candle closing strongly in direction
                conf_candle = None
                for c in candles_up_to_t:
                    c_t = ensure_utc(get_val(c, "timestamp"))
                    if c_t > f_ts and c_t <= ts:
                        c_o = Decimal(str(get_val(c, "open")))
                        c_cl = Decimal(str(get_val(c, "close")))
                        if direction == SetupDirection.BEARISH and c_cl < c_o:
                            conf_candle = c
                            break
                        elif direction == SetupDirection.BULLISH and c_cl > c_o:
                            conf_candle = c
                            break

                if conf_candle is None:
                    if self.state_machine.is_expired(expires_at, ts):
                        results.append(
                            self.state_machine.transition(
                                armed_record,
                                SetupStatus.EXPIRED,
                                reason="Directional confirmation not found within validity window",
                                at_timestamp=ts,
                            )
                        )
                    else:
                        results.append(armed_record)
                    continue

                conf_ts = ensure_utc(get_val(conf_candle, "timestamp"))
            else:
                conf_ts = ensure_utc(get_val(matching_confirmation, "confirmed_at", get_val(matching_confirmation, "timestamp")))

            if not exec_ok:
                results.append(
                    self.state_machine.transition(
                        armed_record,
                        SetupStatus.REJECTED,
                        reason=f"Execution conditions failed: {exec_status}",
                        at_timestamp=conf_ts,
                    )
                )
                continue

            # FIRE!
            fire_record = SetupRecord(
                setup_id=setup_id,
                setup_code=SetupCode.S04,
                symbol=symbol,
                timeframe=timeframe,
                timestamp=conf_ts,
                direction=direction,
                regime=regime,
                anomaly_type=anomaly_type,
                status=SetupStatus.FIRE,
                evidence=SetupEvidence(
                    anomaly=anomaly_type,
                    price_response="CONFIRMED_ABSORPTION",
                    structure=str(get_val(matching_confirmation, "structure_type")) if matching_confirmation else "CANDLE_CONFIRMATION",
                    trap="FAILED_EXPECTATION" if has_failed_expectation else None,
                    regime=regime,
                    confirmation="VALID",
                    execution=exec_status,
                    metrics={
                        "activity_zscore": act_z_dec,
                        "price_response_zscore": resp_z_dec,
                    },
                ),
                reason="Effort vs result anomaly, contextual confirmation, and directional confirmation verified",
                created_at=f_ts,
                expires_at=None,
            )
            results.append(fire_record)

        return results
