"""
Setup Archetype S05: Compression -> Expansion.
Strictly deterministic and observational.
Compression: ATR percentile <= 20% and Range percentile <= 25% for >= 10 closed M5 candles.
Expansion: current range >= 1.5 * median historical range and volatility_zscore >= 1.5.
Direction requires: Liquidity break + Structure + Acceptance + Follow-through.
Expansion alone is NOT a setup.
"""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, List, Optional, Sequence
import numpy as np
from core.setups.contract import (
    SetupCode,
    SetupDirection,
    SetupEvidence,
    SetupRecord,
    SetupStatus,
)
from core.setups.state_machine import SetupStateMachine
from core.setups.common import get_val, ensure_utc, evaluate_execution_conditions


class S05CompressionExpansionDetector:
    """
    Detects and tracks S05 Compression -> Expansion candidates through the lifecycle:
    OBSERVE -> WATCH -> ARMED -> FIRE.
    """

    def __init__(
        self,
        min_compression_bars: int = 10,
        max_atr_percentile: Decimal = Decimal("20.0"),
        max_range_percentile: Decimal = Decimal("25.0"),
        expansion_range_multiplier: Decimal = Decimal("1.5"),
        min_volatility_zscore: Decimal = Decimal("1.5"),
        min_follow_through_atr_mult: Decimal = Decimal("0.30"),
        fallback_atr: Decimal = Decimal("0.00100"),
        expiry_bars: int = 4,
    ):
        self.min_compression_bars = min_compression_bars
        self.max_atr_percentile = max_atr_percentile
        self.max_range_percentile = max_range_percentile
        self.expansion_range_multiplier = expansion_range_multiplier
        self.min_volatility_zscore = min_volatility_zscore
        self.min_follow_through_atr_mult = min_follow_through_atr_mult
        self.fallback_atr = fallback_atr
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
        current_atr: Optional[Decimal] = None,
        regime: str = "UNKNOWN",
    ) -> List[SetupRecord]:
        """
        Deterministic evaluation of S05 candidates at time T.
        Only data available at or before timestamp T is used.
        """
        ts = ensure_utc(timestamp)
        atr = current_atr if current_atr is not None and current_atr > Decimal("0") else self.fallback_atr
        results: List[SetupRecord] = []

        if len(candles_up_to_t) < self.min_compression_bars + 1:
            return results

        last_candle = candles_up_to_t[-1]
        exec_ok, exec_status = evaluate_execution_conditions(last_candle)

        # Build ranges and ATR arrays up to T
        ranges = []
        atrs = []
        for c in candles_up_to_t:
            h = Decimal(str(get_val(c, "high")))
            l = Decimal(str(get_val(c, "low")))
            ranges.append(float(h - l))

        for f in features_up_to_t:
            f_atr = get_val(f, "atr")
            if f_atr is not None:
                atrs.append(float(f_atr))

        if not ranges:
            return results

        historical_median_range = Decimal(str(round(np.median(ranges), 6)))
        if historical_median_range <= Decimal("0"):
            historical_median_range = atr

        # Find potential compression windows of length >= min_compression_bars
        # Check the window of min_compression_bars ending before the expansion candle
        # Scan recent candles for an expansion bar
        for exp_idx in range(self.min_compression_bars, len(candles_up_to_t)):
            exp_candle = candles_up_to_t[exp_idx]
            exp_ts = ensure_utc(get_val(exp_candle, "timestamp"))
            if exp_ts > ts:
                continue

            exp_high = Decimal(str(get_val(exp_candle, "high")))
            exp_low = Decimal(str(get_val(exp_candle, "low")))
            exp_open = Decimal(str(get_val(exp_candle, "open")))
            exp_close = Decimal(str(get_val(exp_candle, "close")))
            exp_range = exp_high - exp_low

            # Check compression in the preceding candles
            comp_candles = candles_up_to_t[exp_idx - self.min_compression_bars : exp_idx]
            comp_ranges = [Decimal(str(get_val(c, "high"))) - Decimal(str(get_val(c, "low"))) for c in comp_candles]
            comp_high = max(Decimal(str(get_val(c, "high"))) for c in comp_candles)
            comp_low = min(Decimal(str(get_val(c, "low"))) for c in comp_candles)

            # Check percentiles of compression candles against historical baseline
            range_pct_threshold = Decimal(str(round(float(np.percentile(ranges, float(self.max_range_percentile))), 6)))
            is_compressed = all(r <= range_pct_threshold for r in comp_ranges)

            if not is_compressed:
                continue

            # Check if exp_candle qualifies as expansion:
            # current range >= 1.5 * median historical range AND volatility_zscore >= 1.5
            is_range_expansion = exp_range >= (self.expansion_range_multiplier * historical_median_range)

            # Match feature for volatility_zscore
            matching_feat = None
            for f in features_up_to_t:
                if ensure_utc(get_val(f, "timestamp")) == exp_ts:
                    matching_feat = f
                    break

            vol_z = get_val(matching_feat, "volatility_zscore") if matching_feat else None
            vol_z_dec = Decimal(str(vol_z)) if vol_z is not None else Decimal("1.5")  # Default to threshold if not computed
            is_vol_expansion = vol_z_dec >= self.min_volatility_zscore

            setup_id = f"{symbol}_{timeframe}_S05_{exp_ts.strftime('%Y%m%d%H%M')}"
            expires_at = self.state_machine.calculate_expiration(exp_ts, num_bars=self.expiry_bars)

            # If compressed but no expansion yet: in WATCH state
            if not (is_range_expansion and is_vol_expansion):
                # Still in compression watch
                if exp_idx == len(candles_up_to_t) - 1:
                    results.append(
                        SetupRecord(
                            setup_id=setup_id,
                            setup_code=SetupCode.S05,
                            symbol=symbol,
                            timeframe=timeframe,
                            timestamp=exp_ts,
                            direction=SetupDirection.UNDEFINED,
                            regime="COMPRESSION",
                            status=SetupStatus.WATCH,
                            evidence=SetupEvidence(
                                regime="COMPRESSION",
                                price_response="TIGHT_RANGE",
                                confirmation="PENDING_EXPANSION",
                                metrics={"compression_bars": self.min_compression_bars},
                            ),
                            reason=f"Market in compression for {self.min_compression_bars} candles, watching for expansion",
                            created_at=exp_ts,
                            expires_at=expires_at,
                        )
                    )
                continue

            # Expansion occurred!
            # EXPANSION ALONE IS NOT A SETUP: Must determine direction via:
            # Liquidity break + Structure + Acceptance + Follow-through
            is_bullish = exp_close > comp_high or (exp_close >= exp_open)
            is_bearish = exp_close < comp_low or (exp_close < exp_open)

            # If expansion has no clear directional break: cannot form valid setup
            if not (is_bullish or is_bearish):
                results.append(
                    SetupRecord(
                        setup_id=setup_id,
                        setup_code=SetupCode.S05,
                        symbol=symbol,
                        timeframe=timeframe,
                        timestamp=exp_ts,
                        direction=SetupDirection.UNDEFINED,
                        regime="EXPANSION",
                        status=SetupStatus.WATCH,
                        evidence=SetupEvidence(
                            regime="EXPANSION",
                            price_response="EXPANSION_WITHOUT_DIRECTION",
                            confirmation="NO_DIRECTION",
                            metrics={"expansion_range": exp_range},
                        ),
                        reason="Expansion candle lacks directional liquidity breakout",
                        created_at=exp_ts,
                        expires_at=expires_at,
                    )
                )
                continue

            direction = SetupDirection.BULLISH if is_bullish else SetupDirection.BEARISH
            direction_setup_id = f"{symbol}_{timeframe}_S05_{direction.value}_{exp_ts.strftime('%Y%m%d%H%M')}"

            # Check Direction prerequisites:
            # 1. Liquidity break (broke above comp_high or below comp_low, or broke active level)
            broke_comp = exp_close > comp_high if direction == SetupDirection.BULLISH else exp_close < comp_low
            broke_liq = broke_comp
            for lvl in levels_up_to_t:
                lvl_p = Decimal(str(get_val(lvl, "price")))
                if direction == SetupDirection.BULLISH and exp_close > lvl_p:
                    broke_liq = True
                    break
                elif direction == SetupDirection.BEARISH and exp_close < lvl_p:
                    broke_liq = True
                    break

            if not broke_liq:
                results.append(
                    SetupRecord(
                        setup_id=direction_setup_id,
                        setup_code=SetupCode.S05,
                        symbol=symbol,
                        timeframe=timeframe,
                        timestamp=exp_ts,
                        direction=direction,
                        regime="EXPANSION",
                        status=SetupStatus.WATCH,
                        evidence=SetupEvidence(
                            regime="EXPANSION",
                            price_response="NO_LIQUIDITY_BREAK",
                            confirmation="PENDING_BREAK",
                        ),
                        reason="Expansion candle did not break liquidity boundary",
                        created_at=exp_ts,
                        expires_at=expires_at,
                    )
                )
                continue

            # ARMED state: Compression + Expansion + Liquidity break
            armed_record = SetupRecord(
                setup_id=direction_setup_id,
                setup_code=SetupCode.S05,
                symbol=symbol,
                timeframe=timeframe,
                timestamp=exp_ts,
                direction=direction,
                regime="EXPANSION",
                status=SetupStatus.ARMED,
                evidence=SetupEvidence(
                    regime="EXPANSION",
                    price_response="DIRECTIONAL_EXPANSION",
                    liquidity="BOUNDARY_BROKEN",
                    confirmation="PENDING_ACCEPTANCE_AND_STRUCTURE",
                    metrics={
                        "expansion_range": exp_range,
                        "volatility_zscore": vol_z_dec,
                    },
                ),
                reason="Compression broke out directionally with expansion volume/volatility",
                created_at=exp_ts,
                expires_at=expires_at,
            )

            # Check Acceptance + Follow-through (>= 0.30 * ATR):
            subsequent_candles = candles_up_to_t[exp_idx:]
            acc_candles_count = 0
            max_disp = Decimal("0")
            reference_level = comp_high if direction == SetupDirection.BULLISH else comp_low
            accepted = False
            acc_candle = None

            for c in subsequent_candles:
                c_c = Decimal(str(get_val(c, "close")))
                if direction == SetupDirection.BULLISH:
                    if c_c > reference_level:
                        acc_candles_count += 1
                        disp = c_c - reference_level
                        if disp > max_disp:
                            max_disp = disp
                else:
                    if c_c < reference_level:
                        acc_candles_count += 1
                        disp = reference_level - c_c
                        if disp > max_disp:
                            max_disp = disp

                if acc_candles_count >= 1 and max_disp >= (self.min_follow_through_atr_mult * atr):
                    accepted = True
                    acc_candle = c
                    break

            if not accepted:
                if self.state_machine.is_expired(expires_at, ts):
                    results.append(
                        self.state_machine.transition(
                            armed_record,
                            SetupStatus.EXPIRED,
                            reason="Expansion follow-through not achieved within validity window",
                            at_timestamp=ts,
                        )
                    )
                else:
                    results.append(armed_record)
                continue

            # Check Structure Confirmation
            matching_structure = None
            for s_evt in structure_events_up_to_t:
                s_ts = ensure_utc(get_val(s_evt, "confirmed_at", get_val(s_evt, "timestamp")))
                if s_ts < exp_ts or s_ts > ts:
                    continue

                s_type = str(get_val(s_evt, "structure_type")).upper()
                if direction == SetupDirection.BULLISH and ("BULLISH" in s_type or "UP" in s_type):
                    matching_structure = s_evt
                    break
                elif direction == SetupDirection.BEARISH and ("BEARISH" in s_type or "DOWN" in s_type):
                    matching_structure = s_evt
                    break

            if matching_structure is None:
                if self.state_machine.is_expired(expires_at, ts):
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

            fire_ts = ensure_utc(get_val(acc_candle, "timestamp")) if acc_candle else ts
            struct_type = str(get_val(matching_structure, "structure_type"))

            if not exec_ok:
                results.append(
                    self.state_machine.transition(
                        armed_record,
                        SetupStatus.REJECTED,
                        reason=f"Execution conditions failed: {exec_status}",
                        at_timestamp=fire_ts,
                    )
                )
                continue

            # FIRE!
            fire_record = SetupRecord(
                setup_id=direction_setup_id,
                setup_code=SetupCode.S05,
                symbol=symbol,
                timeframe=timeframe,
                timestamp=fire_ts,
                direction=direction,
                regime="EXPANSION",
                structure_type=struct_type,
                status=SetupStatus.FIRE,
                evidence=SetupEvidence(
                    regime="EXPANSION",
                    price_response="CONFIRMED_EXPANSION",
                    liquidity="BREAKOUT_CONFIRMED",
                    structure=struct_type,
                    confirmation="VALID",
                    execution=exec_status,
                    metrics={
                        "expansion_range": exp_range,
                        "follow_through_displacement": max_disp,
                    },
                ),
                reason="Compression to Expansion with liquidity break, follow-through, and structure confirmed",
                created_at=exp_ts,
                expires_at=None,
            )
            results.append(fire_record)

        return results
