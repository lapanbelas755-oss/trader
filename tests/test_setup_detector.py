"""
Deterministic Test Suite for Setup Detector Engine V1.
Covers all setup archetypes (S01-S05), state machine lifecycle, causality,
database persistence, and the mandatory test_setup_has_no_future_leakage().
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import pytest
from sqlalchemy import text

from core.liquidity.contract import (
    LiquidityLevelRecord,
    LiquidityLevelType,
    LiquidityStatus,
)
from core.structure.contract import (
    StructureEvent,
    StructureDirection,
    BreakType,
)
from core.setups.contract import (
    SetupCode,
    SetupStatus,
    SetupDirection,
    SetupEvidence,
    SetupRecord,
)
from core.setups.state_machine import SetupStateMachine
from core.setups.s01_sweep_reversal import S01SweepReversalDetector
from core.setups.s02_acceptance import S02LiquidityAcceptanceDetector
from core.setups.s03_failed_breakout import S03FailedBreakoutDetector
from core.setups.s04_anomaly import S04EffortResultAnomalyDetector
from core.setups.s05_compression import S05CompressionExpansionDetector
from core.setups.engine import SetupDetectorEngine
from database.connection import get_session_factory
from database.models import Setup as SetupModel, SetupEvidence as SetupEvidenceModel


def make_candle(
    ts: datetime,
    o: float,
    h: float,
    l: float,
    c: float,
    tf: str = "M5",
    sym: str = "EURUSD",
    spread: float = 1.0,
):
    """Creates a deterministic synthetic candle dictionary."""
    return {
        "symbol": sym,
        "timeframe": tf,
        "timestamp": ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc),
        "open": Decimal(str(round(o, 5))),
        "high": Decimal(str(round(h, 5))),
        "low": Decimal(str(round(l, 5))),
        "close": Decimal(str(round(c, 5))),
        "tick_volume": 100,
        "real_volume": 0,
        "spread": Decimal(str(spread)),
    }


def make_level(
    level_type: LiquidityLevelType,
    price: float,
    created_at: datetime,
    sym: str = "EURUSD",
    tf: str = "M5",
):
    """Creates a synthetic liquidity level record."""
    return LiquidityLevelRecord(
        symbol=sym,
        timeframe=tf,
        level_type=level_type,
        price=Decimal(str(round(price, 5))),
        created_at=created_at if created_at.tzinfo else created_at.replace(tzinfo=timezone.utc),
        status=LiquidityStatus.UNTOUCHED,
    )


def make_structure(
    s_type: str,
    price: float,
    ts: datetime,
    conf_at: datetime,
    disp: float = 0.00030,
    dir_val: StructureDirection = StructureDirection.BULLISH,
):
    """Creates a synthetic market structure event."""
    return StructureEvent(
        symbol="EURUSD",
        timeframe="M5",
        structure_type=s_type,
        price=Decimal(str(round(price, 5))),
        timestamp=ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc),
        confirmed_at=conf_at if conf_at.tzinfo else conf_at.replace(tzinfo=timezone.utc),
        direction=dir_val,
        displacement=Decimal(str(disp)),
    )


def make_feature(
    ts: datetime,
    act_z: float = 0.0,
    resp_z: float = 0.0,
    atr: float = 0.00100,
    vol_z: float = 0.0,
    is_cand: bool = False,
    is_strong: bool = False,
):
    """Creates a synthetic market feature dictionary."""
    return {
        "symbol": "EURUSD",
        "timeframe": "M5",
        "timestamp": ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc),
        "activity_zscore": Decimal(str(round(act_z, 4))),
        "price_response_zscore": Decimal(str(round(resp_z, 4))),
        "atr": Decimal(str(round(atr, 5))),
        "volatility_zscore": Decimal(str(round(vol_z, 4))),
        "is_anomaly_candidate": is_cand,
        "is_strong_anomaly": is_strong,
    }


# ==============================================================================
# 1. S01 — LIQUIDITY SWEEP REVERSAL TESTS
# ==============================================================================

def test_s01_valid_bearish_sweep_reversal():
    """Valid bearish sweep reversal: high swept, returned in 1 candle, rejected, structure confirmed -> FIRE."""
    t0 = datetime(2026, 9, 5, 10, 0, tzinfo=timezone.utc)
    level = make_level(LiquidityLevelType.SESSION_HIGH, 1.10000, t0)
    atr = Decimal("0.00100")  # ATR = 10 pips

    # C1: Sweeps high to 1.10020 (depth 0.20 ATR) and closes below at 1.09980 (returned)
    c1 = make_candle(t0 + timedelta(minutes=5), 1.09950, 1.10020, 1.09940, 1.09980)
    # C2: Rejection displaces to 1.09950 (disp = 1.10000 - 1.09650 = 0.35 ATR)
    c2 = make_candle(t0 + timedelta(minutes=10), 1.09980, 1.09990, 1.09650, 1.09660)

    # Structure shift: CHOCH_DOWN confirmed at t0 + 10m
    struct = make_structure("CHOCH_DOWN", 1.09660, t0 + timedelta(minutes=10), t0 + timedelta(minutes=10), disp=0.00030)

    detector = S01SweepReversalDetector(fallback_atr=atr)
    records = detector.evaluate_at_timestamp(
        timestamp=t0 + timedelta(minutes=10),
        symbol="EURUSD",
        timeframe="M5",
        candles_up_to_t=[c1, c2],
        levels_up_to_t=[level],
        structure_events_up_to_t=[struct],
        current_atr=atr,
    )

    fires = [r for r in records if r.status == SetupStatus.FIRE]
    assert len(fires) == 1
    f = fires[0]
    assert f.setup_code == SetupCode.S01
    assert f.direction == SetupDirection.BEARISH
    assert f.evidence.liquidity == "SWEPT"
    assert f.evidence.confirmation == "VALID"


def test_s01_valid_bullish_sweep_reversal():
    """Valid bullish sweep reversal: low swept, returned, rejected, structure confirmed -> FIRE."""
    t0 = datetime(2026, 9, 5, 10, 0, tzinfo=timezone.utc)
    level = make_level(LiquidityLevelType.SESSION_LOW, 1.10000, t0)
    atr = Decimal("0.00100")

    # C1: Sweeps low to 1.09980 (depth 0.20 ATR) and closes above at 1.10020
    c1 = make_candle(t0 + timedelta(minutes=5), 1.10050, 1.10060, 1.09980, 1.10020)
    # C2: Rejection displaces upward to 1.10035 (disp = 0.35 ATR)
    c2 = make_candle(t0 + timedelta(minutes=10), 1.10020, 1.10040, 1.10010, 1.10035)

    struct = make_structure("CHOCH_UP", 1.10035, t0 + timedelta(minutes=10), t0 + timedelta(minutes=10), disp=0.00030)

    detector = S01SweepReversalDetector(fallback_atr=atr)
    records = detector.evaluate_at_timestamp(
        timestamp=t0 + timedelta(minutes=10),
        symbol="EURUSD",
        timeframe="M5",
        candles_up_to_t=[c1, c2],
        levels_up_to_t=[level],
        structure_events_up_to_t=[struct],
        current_atr=atr,
    )

    fires = [r for r in records if r.status == SetupStatus.FIRE]
    assert len(fires) == 1
    assert fires[0].direction == SetupDirection.BULLISH


def test_s01_no_sweep_penetration_too_small():
    """Penetration below min_sweep_atr_mult (0.05 ATR) produces no sweep."""
    t0 = datetime(2026, 9, 5, 10, 0, tzinfo=timezone.utc)
    level = make_level(LiquidityLevelType.SESSION_HIGH, 1.10000, t0)
    atr = Decimal("0.00100")

    # Penetration is only 0.00002 (0.02 ATR < 0.05 ATR min)
    c1 = make_candle(t0 + timedelta(minutes=5), 1.09980, 1.10002, 1.09970, 1.09990)
    detector = S01SweepReversalDetector(fallback_atr=atr)
    records = detector.evaluate_at_timestamp(
        timestamp=t0 + timedelta(minutes=5),
        symbol="EURUSD",
        timeframe="M5",
        candles_up_to_t=[c1],
        levels_up_to_t=[level],
        structure_events_up_to_t=[],
        current_atr=atr,
    )
    assert len(records) == 0


def test_s01_penetration_too_deep_invalidated():
    """Penetration > 0.50 ATR exceeds sweep boundary and is invalidated as a clean sweep."""
    t0 = datetime(2026, 9, 5, 10, 0, tzinfo=timezone.utc)
    level = make_level(LiquidityLevelType.SESSION_HIGH, 1.10000, t0)
    atr = Decimal("0.00100")

    # High hits 1.10060 (depth 0.60 ATR > 0.50 ATR max)
    c1 = make_candle(t0 + timedelta(minutes=5), 1.09980, 1.10060, 1.09970, 1.09990)
    detector = S01SweepReversalDetector(fallback_atr=atr)
    records = detector.evaluate_at_timestamp(
        timestamp=t0 + timedelta(minutes=5),
        symbol="EURUSD",
        timeframe="M5",
        candles_up_to_t=[c1],
        levels_up_to_t=[level],
        structure_events_up_to_t=[],
        current_atr=atr,
    )
    fires = [r for r in records if r.status == SetupStatus.FIRE]
    assert len(fires) == 0


def test_s01_no_return_within_3_candles_expires():
    """If price sweeps and stays beyond level without returning across it, it expires."""
    t0 = datetime(2026, 9, 5, 10, 0, tzinfo=timezone.utc)
    level = make_level(LiquidityLevelType.SESSION_HIGH, 1.10000, t0)
    atr = Decimal("0.00100")

    c1 = make_candle(t0 + timedelta(minutes=5), 1.09980, 1.10020, 1.09970, 1.10015)  # Swept, closed above
    c2 = make_candle(t0 + timedelta(minutes=10), 1.10015, 1.10030, 1.10010, 1.10025) # Still above
    c3 = make_candle(t0 + timedelta(minutes=15), 1.10025, 1.10040, 1.10015, 1.10035) # Still above
    c4 = make_candle(t0 + timedelta(minutes=20), 1.10035, 1.10045, 1.10020, 1.10040) # 3 candles passed

    detector = S01SweepReversalDetector(fallback_atr=atr)
    records = detector.evaluate_at_timestamp(
        timestamp=t0 + timedelta(minutes=20),
        symbol="EURUSD",
        timeframe="M5",
        candles_up_to_t=[c1, c2, c3, c4],
        levels_up_to_t=[level],
        structure_events_up_to_t=[],
        current_atr=atr,
    )

    expired = [r for r in records if r.status == SetupStatus.EXPIRED]
    assert len(expired) >= 1
    assert "return" in expired[0].reason.lower()


def test_s01_insufficient_rejection_displacement_does_not_arm():
    """If price returns across level but fails to displace >= 0.30 ATR, remains in WATCH or expires."""
    t0 = datetime(2026, 9, 5, 10, 0, tzinfo=timezone.utc)
    level = make_level(LiquidityLevelType.SESSION_HIGH, 1.10000, t0)
    atr = Decimal("0.00100")

    # C1: Sweeps and returns
    c1 = make_candle(t0 + timedelta(minutes=5), 1.09980, 1.10020, 1.09970, 1.09990)
    # C2: Closes at 1.09985 (displacement only 0.15 pips < 0.30 ATR)
    c2 = make_candle(t0 + timedelta(minutes=10), 1.09990, 1.09995, 1.09980, 1.09985)

    detector = S01SweepReversalDetector(fallback_atr=atr)
    records = detector.evaluate_at_timestamp(
        timestamp=t0 + timedelta(minutes=10),
        symbol="EURUSD",
        timeframe="M5",
        candles_up_to_t=[c1, c2],
        levels_up_to_t=[level],
        structure_events_up_to_t=[],
        current_atr=atr,
    )

    armed = [r for r in records if r.status in (SetupStatus.ARMED, SetupStatus.FIRE)]
    assert len(armed) == 0


def test_s01_missing_structure_confirmation_does_not_fire():
    """If rejection occurs but structure shift does not happen, setup remains ARMED."""
    t0 = datetime(2026, 9, 5, 10, 0, tzinfo=timezone.utc)
    level = make_level(LiquidityLevelType.SESSION_HIGH, 1.10000, t0)
    atr = Decimal("0.00100")

    c1 = make_candle(t0 + timedelta(minutes=5), 1.09980, 1.10020, 1.09940, 1.09980)
    c2 = make_candle(t0 + timedelta(minutes=10), 1.09980, 1.09990, 1.09650, 1.09660)

    detector = S01SweepReversalDetector(fallback_atr=atr)
    records = detector.evaluate_at_timestamp(
        timestamp=t0 + timedelta(minutes=10),
        symbol="EURUSD",
        timeframe="M5",
        candles_up_to_t=[c1, c2],
        levels_up_to_t=[level],
        structure_events_up_to_t=[],  # No structure shift
        current_atr=atr,
    )

    fires = [r for r in records if r.status == SetupStatus.FIRE]
    armed = [r for r in records if r.status == SetupStatus.ARMED]
    assert len(fires) == 0
    assert len(armed) == 1


# ==============================================================================
# 2. S02 — LIQUIDITY ACCEPTANCE CONTINUATION TESTS
# ==============================================================================

def test_s02_valid_bullish_acceptance_fire():
    """Valid bullish acceptance: break >= 0.10 ATR, 2 candles acceptance, follow-through >= 0.30 ATR, BOS -> FIRE."""
    t0 = datetime(2026, 9, 5, 10, 0, tzinfo=timezone.utc)
    level = make_level(LiquidityLevelType.PREVIOUS_DAY_HIGH, 1.10000, t0)
    atr = Decimal("0.00100")

    # C1: Breakout candle closing at 1.10015 (disp 0.15 ATR >= 0.10 ATR)
    c1 = make_candle(t0 + timedelta(minutes=5), 1.09980, 1.10020, 1.09970, 1.10015)
    # C2: Acceptance bar 1 closing at 1.10025
    c2 = make_candle(t0 + timedelta(minutes=10), 1.10015, 1.10030, 1.10010, 1.10025)
    # C3: Acceptance bar 2 + follow-through closing at 1.10035 (disp 0.35 ATR >= 0.30 ATR)
    c3 = make_candle(t0 + timedelta(minutes=15), 1.10025, 1.10040, 1.10020, 1.10035)

    struct = make_structure("BOS_BULLISH", 1.10035, t0 + timedelta(minutes=15), t0 + timedelta(minutes=15), disp=0.00035)

    detector = S02LiquidityAcceptanceDetector(fallback_atr=atr)
    records = detector.evaluate_at_timestamp(
        timestamp=t0 + timedelta(minutes=15),
        symbol="EURUSD",
        timeframe="M5",
        candles_up_to_t=[c1, c2, c3],
        levels_up_to_t=[level],
        structure_events_up_to_t=[struct],
        htf_direction="BULLISH",
        current_atr=atr,
    )

    fires = [r for r in records if r.status == SetupStatus.FIRE]
    assert len(fires) == 1
    assert fires[0].direction == SetupDirection.BULLISH
    assert fires[0].evidence.liquidity == "ACCEPTED"


def test_s02_breakout_insufficient_displacement_ignored():
    """Breakout closing with displacement < 0.10 ATR does not qualify as a valid break."""
    t0 = datetime(2026, 9, 5, 10, 0, tzinfo=timezone.utc)
    level = make_level(LiquidityLevelType.PREVIOUS_DAY_HIGH, 1.10000, t0)
    atr = Decimal("0.00100")

    # Close is 1.10005 (0.05 ATR < 0.10 ATR)
    c1 = make_candle(t0 + timedelta(minutes=5), 1.09980, 1.10010, 1.09970, 1.10005)
    detector = S02LiquidityAcceptanceDetector(fallback_atr=atr)
    records = detector.evaluate_at_timestamp(
        timestamp=t0 + timedelta(minutes=5),
        symbol="EURUSD",
        timeframe="M5",
        candles_up_to_t=[c1],
        levels_up_to_t=[level],
        structure_events_up_to_t=[],
        current_atr=atr,
    )
    assert len(records) == 0


def test_s02_wick_only_penetration_ignored():
    """Wick-only penetration (high exceeds level, close <= level) is NOT a breakout."""
    t0 = datetime(2026, 9, 5, 10, 0, tzinfo=timezone.utc)
    level = make_level(LiquidityLevelType.PREVIOUS_DAY_HIGH, 1.10000, t0)
    atr = Decimal("0.00100")

    # High 1.10030, but close 1.09990
    c1 = make_candle(t0 + timedelta(minutes=5), 1.09980, 1.10030, 1.09970, 1.09990)
    detector = S02LiquidityAcceptanceDetector(fallback_atr=atr)
    records = detector.evaluate_at_timestamp(
        timestamp=t0 + timedelta(minutes=5),
        symbol="EURUSD",
        timeframe="M5",
        candles_up_to_t=[c1],
        levels_up_to_t=[level],
        structure_events_up_to_t=[],
        current_atr=atr,
    )
    assert len(records) == 0


def test_s02_immediate_return_invalidates_acceptance():
    """Immediate return across level during acceptance window invalidates the setup."""
    t0 = datetime(2026, 9, 5, 10, 0, tzinfo=timezone.utc)
    level = make_level(LiquidityLevelType.PREVIOUS_DAY_HIGH, 1.10000, t0)
    atr = Decimal("0.00100")

    c1 = make_candle(t0 + timedelta(minutes=5), 1.09980, 1.10020, 1.09970, 1.10015)
    c2 = make_candle(t0 + timedelta(minutes=10), 1.10015, 1.10018, 1.09970, 1.09980)  # Returned below level

    detector = S02LiquidityAcceptanceDetector(fallback_atr=atr)
    records = detector.evaluate_at_timestamp(
        timestamp=t0 + timedelta(minutes=10),
        symbol="EURUSD",
        timeframe="M5",
        candles_up_to_t=[c1, c2],
        levels_up_to_t=[level],
        structure_events_up_to_t=[],
        current_atr=atr,
    )

    rejected = [r for r in records if r.status == SetupStatus.REJECTED]
    assert len(rejected) == 1
    assert "immediate return" in rejected[0].reason.lower()


def test_s02_opposing_higher_timeframe_rejects():
    """Bullish breakout setup with opposing BEARISH Higher Timeframe is rejected."""
    t0 = datetime(2026, 9, 5, 10, 0, tzinfo=timezone.utc)
    level = make_level(LiquidityLevelType.PREVIOUS_DAY_HIGH, 1.10000, t0)
    atr = Decimal("0.00100")

    c1 = make_candle(t0 + timedelta(minutes=5), 1.09980, 1.10020, 1.09970, 1.10015)
    detector = S02LiquidityAcceptanceDetector(fallback_atr=atr)
    records = detector.evaluate_at_timestamp(
        timestamp=t0 + timedelta(minutes=5),
        symbol="EURUSD",
        timeframe="M5",
        candles_up_to_t=[c1],
        levels_up_to_t=[level],
        structure_events_up_to_t=[],
        htf_direction="BEARISH",  # Strongly opposes bullish breakout
        current_atr=atr,
    )

    rejected = [r for r in records if r.status == SetupStatus.REJECTED]
    assert len(rejected) == 1
    assert "opposes" in rejected[0].reason.lower()


# ==============================================================================
# 3. S03 — FAILED BREAKOUT TRAP TESTS
# ==============================================================================

def test_s03_valid_failed_breakout_fire():
    """Valid failed breakout: breakout closes beyond level, returns in 2 candles, opposite disp >= 0.30 ATR, CHoCH -> FIRE."""
    t0 = datetime(2026, 9, 5, 10, 0, tzinfo=timezone.utc)
    level = make_level(LiquidityLevelType.SESSION_HIGH, 1.10000, t0)
    atr = Decimal("0.00100")

    # C1: Breakout candle closes at 1.10015
    c1 = make_candle(t0 + timedelta(minutes=5), 1.09980, 1.10020, 1.09970, 1.10015)
    # C2: Failure return candle closes back at 1.09980 (returned in 1 candle < 3 max)
    c2 = make_candle(t0 + timedelta(minutes=10), 1.10015, 1.10018, 1.09970, 1.09980)
    # C3: Opposite displacement closes at 1.09650 (disp 0.35 ATR >= 0.30 ATR)
    c3 = make_candle(t0 + timedelta(minutes=15), 1.09980, 1.09990, 1.09640, 1.09650)

    struct = make_structure("CHOCH_DOWN", 1.09650, t0 + timedelta(minutes=15), t0 + timedelta(minutes=15), disp=0.00030)

    detector = S03FailedBreakoutDetector(fallback_atr=atr)
    records = detector.evaluate_at_timestamp(
        timestamp=t0 + timedelta(minutes=15),
        symbol="EURUSD",
        timeframe="M5",
        candles_up_to_t=[c1, c2, c3],
        levels_up_to_t=[level],
        structure_events_up_to_t=[struct],
        current_atr=atr,
    )

    fires = [r for r in records if r.status == SetupStatus.FIRE]
    assert len(fires) == 1
    assert fires[0].setup_code == SetupCode.S03
    assert fires[0].direction == SetupDirection.BEARISH
    assert fires[0].evidence.trap == "CONFIRMED_BREAKOUT_TRAP"


def test_s03_failure_too_late_expires():
    """If breakout does not return through level within 3 candles, it is not a trap and expires."""
    t0 = datetime(2026, 9, 5, 10, 0, tzinfo=timezone.utc)
    level = make_level(LiquidityLevelType.SESSION_HIGH, 1.10000, t0)
    atr = Decimal("0.00100")

    c1 = make_candle(t0 + timedelta(minutes=5), 1.09980, 1.10020, 1.09970, 1.10015)
    c2 = make_candle(t0 + timedelta(minutes=10), 1.10015, 1.10025, 1.10010, 1.10020)
    c3 = make_candle(t0 + timedelta(minutes=15), 1.10020, 1.10030, 1.10015, 1.10025)
    c4 = make_candle(t0 + timedelta(minutes=20), 1.10025, 1.10035, 1.10015, 1.10025)  # 3 candles passed without failure

    detector = S03FailedBreakoutDetector(fallback_atr=atr)
    records = detector.evaluate_at_timestamp(
        timestamp=t0 + timedelta(minutes=20),
        symbol="EURUSD",
        timeframe="M5",
        candles_up_to_t=[c1, c2, c3, c4],
        levels_up_to_t=[level],
        structure_events_up_to_t=[],
        current_atr=atr,
    )

    expired = [r for r in records if r.status == SetupStatus.EXPIRED]
    assert len(expired) == 1


# ==============================================================================
# 4. S04 — EFFORT VS RESULT ANOMALY TESTS
# ==============================================================================

def test_s04_normal_activity_produces_no_anomaly():
    """Normal activity (zscore < 2.0) produces no setup."""
    t0 = datetime(2026, 9, 5, 10, 0, tzinfo=timezone.utc)
    c = make_candle(t0, 1.10000, 1.10020, 1.09980, 1.10010)
    f = make_feature(t0, act_z=0.5, resp_z=0.2)

    detector = S04EffortResultAnomalyDetector()
    records = detector.evaluate_at_timestamp(
        timestamp=t0,
        symbol="EURUSD",
        timeframe="M5",
        candles_up_to_t=[c],
        features_up_to_t=[f],
        levels_up_to_t=[],
        structure_events_up_to_t=[],
    )
    assert len(records) == 0


def test_s04_anomaly_without_context_does_not_fire():
    """Anomaly candidate alone without contextual confirmation must NOT fire."""
    t0 = datetime(2026, 9, 5, 10, 0, tzinfo=timezone.utc)
    # Candle with wide body and no liquidity or structure interaction
    c = make_candle(t0, 1.10000, 1.10050, 1.09990, 1.10045)
    f = make_feature(t0, act_z=2.6, resp_z=-1.6, is_strong=True)

    detector = S04EffortResultAnomalyDetector()
    records = detector.evaluate_at_timestamp(
        timestamp=t0,
        symbol="EURUSD",
        timeframe="M5",
        candles_up_to_t=[c],
        features_up_to_t=[f],
        levels_up_to_t=[],
        structure_events_up_to_t=[],
    )

    fires = [r for r in records if r.status == SetupStatus.FIRE]
    armed = [r for r in records if r.status == SetupStatus.ARMED]
    assert len(fires) == 0
    assert len(armed) == 0


def test_s04_anomaly_with_liquidity_context_and_confirmation_fires():
    """Anomaly candidate near liquidity with confirmation candle fires S04."""
    t0 = datetime(2026, 9, 5, 10, 0, tzinfo=timezone.utc)
    level = make_level(LiquidityLevelType.SESSION_HIGH, 1.10000, t0)

    # Anomaly candle near level with pinbar (open 1.09980, high 1.10010, close 1.09985)
    c1 = make_candle(t0, 1.09980, 1.10010, 1.09970, 1.09985)
    f1 = make_feature(t0, act_z=2.6, resp_z=-1.6, is_strong=True)

    # Subsequent confirmation candle closing down
    c2 = make_candle(t0 + timedelta(minutes=5), 1.09985, 1.09990, 1.09930, 1.09940)
    f2 = make_feature(t0 + timedelta(minutes=5), act_z=1.0, resp_z=0.5)

    detector = S04EffortResultAnomalyDetector()
    records = detector.evaluate_at_timestamp(
        timestamp=t0 + timedelta(minutes=5),
        symbol="EURUSD",
        timeframe="M5",
        candles_up_to_t=[c1, c2],
        features_up_to_t=[f1, f2],
        levels_up_to_t=[level],
        structure_events_up_to_t=[],
    )

    fires = [r for r in records if r.status == SetupStatus.FIRE]
    assert len(fires) == 1
    assert fires[0].setup_code == SetupCode.S04
    assert fires[0].direction == SetupDirection.BEARISH
    assert fires[0].evidence.anomaly == "STRONG_ANOMALY"


# ==============================================================================
# 5. S05 — COMPRESSION TO EXPANSION TESTS
# ==============================================================================

def test_s05_insufficient_compression_duration():
    """Less than 10 candles of compression does not qualify for S05."""
    t0 = datetime(2026, 9, 5, 10, 0, tzinfo=timezone.utc)
    candles = [make_candle(t0 + timedelta(minutes=5 * i), 1.10000, 1.10005, 1.09995, 1.10000) for i in range(8)]
    detector = S05CompressionExpansionDetector()
    records = detector.evaluate_at_timestamp(
        timestamp=t0 + timedelta(minutes=35),
        symbol="EURUSD",
        timeframe="M5",
        candles_up_to_t=candles,
        features_up_to_t=[],
        levels_up_to_t=[],
        structure_events_up_to_t=[],
    )
    assert len(records) == 0


def test_s05_valid_directional_expansion_fire():
    """Compression for 10 bars followed by expansion candle breaking liquidity, acceptance, and BOS -> FIRE."""
    t0 = datetime(2026, 9, 5, 10, 0, tzinfo=timezone.utc)
    atr = Decimal("0.00100")

    # 10 very tight compression bars (range 0.00006)
    candles = []
    features = []
    for i in range(10):
        t = t0 + timedelta(minutes=5 * i)
        candles.append(make_candle(t, 1.10000, 1.10004, 1.09998, 1.10001))
        features.append(make_feature(t, act_z=0.1, atr=0.00020, vol_z=0.2))

    # C11: Huge expansion candle breaking above compression high (range 0.00045, close 1.10045)
    t_exp = t0 + timedelta(minutes=50)
    c_exp = make_candle(t_exp, 1.10001, 1.10048, 1.10000, 1.10045)
    f_exp = make_feature(t_exp, act_z=2.2, atr=0.00100, vol_z=2.5)
    candles.append(c_exp)
    features.append(f_exp)

    # C12: Follow-through acceptance candle
    t_acc = t0 + timedelta(minutes=55)
    c_acc = make_candle(t_acc, 1.10045, 1.10080, 1.10040, 1.10075)
    candles.append(c_acc)

    struct = make_structure("BOS_BULLISH", 1.10075, t_acc, t_acc, disp=0.00040)

    detector = S05CompressionExpansionDetector(fallback_atr=atr)
    records = detector.evaluate_at_timestamp(
        timestamp=t_acc,
        symbol="EURUSD",
        timeframe="M5",
        candles_up_to_t=candles,
        features_up_to_t=features,
        levels_up_to_t=[],
        structure_events_up_to_t=[struct],
        current_atr=atr,
    )

    fires = [r for r in records if r.status == SetupStatus.FIRE]
    assert len(fires) == 1
    assert fires[0].setup_code == SetupCode.S05
    assert fires[0].direction == SetupDirection.BULLISH
    assert fires[0].evidence.regime == "EXPANSION"


# ==============================================================================
# 6. ENGINE ORCHESTRATION, CAUSALITY, AND NO-LOOKAHEAD TESTS
# ==============================================================================

def test_setup_has_no_future_leakage():
    """
    CRITICAL NO-LOOKAHEAD TEST:
    1. Evaluate setups on historical dataset up to timestamp T.
    2. Save all setup states.
    3. Append future extreme candles (> T).
    4. Recalculate setups at timestamp T.
    5. Assert historical setup observations are strictly identical.
    """
    t0 = datetime(2026, 9, 5, 8, 0, tzinfo=timezone.utc)
    atr = Decimal("0.00100")
    level = make_level(LiquidityLevelType.SESSION_HIGH, 1.10000, t0)

    candles = [
        make_candle(t0 + timedelta(minutes=5), 1.09950, 1.10020, 1.09940, 1.09980),
        make_candle(t0 + timedelta(minutes=10), 1.09980, 1.09990, 1.09650, 1.09660),
    ]
    struct = [make_structure("CHOCH_DOWN", 1.09660, t0 + timedelta(minutes=10), t0 + timedelta(minutes=10), disp=0.00030)]

    engine = SetupDetectorEngine(fallback_atr=atr)

    # 1. Historical evaluation at T = t0 + 10m
    t_eval = t0 + timedelta(minutes=10)
    baseline_setups = engine.detect_at_timestamp(
        timestamp=t_eval,
        candles=candles,
        liquidity_levels=[level],
        structure_events=struct,
    )
    baseline_summary = [(s.setup_id, s.setup_code.value, s.status.value, str(s.direction.value)) for s in baseline_setups]
    assert len(baseline_summary) > 0

    # 2. Append future extreme candles (flash crash or monster breakout at T + 30m)
    future_candles = list(candles) + [
        make_candle(t_eval + timedelta(minutes=5), 1.09660, 1.15000, 1.09000, 1.14500),
        make_candle(t_eval + timedelta(minutes=10), 1.14500, 1.20000, 1.14000, 1.19500),
    ]
    future_struct = list(struct) + [
        make_structure("BOS_BULLISH", 1.20000, t_eval + timedelta(minutes=10), t_eval + timedelta(minutes=10))
    ]

    # 3. Recalculate at exact historical timestamp T
    recalc_setups = engine.detect_at_timestamp(
        timestamp=t_eval,
        candles=future_candles,
        liquidity_levels=[level],
        structure_events=future_struct,
    )
    recalc_summary = [(s.setup_id, s.setup_code.value, s.status.value, str(s.direction.value)) for s in recalc_setups]

    # 4. Assert zero deviation
    assert baseline_summary == recalc_summary


def test_database_idempotency_and_persistence():
    """Verify that setups and evidence persist correctly to PostgreSQL without duplicate violations."""
    t0 = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)
    engine = SetupDetectorEngine()
    session_factory = get_session_factory()

    rec = SetupRecord(
        setup_id="EURUSD_M5_S01_BEARISH_TEST001",
        setup_code=SetupCode.S01,
        symbol="EURUSD",
        timeframe="M5",
        timestamp=t0,
        direction=SetupDirection.BEARISH,
        regime="RANGE",
        liquidity_type="SESSION_HIGH",
        structure_type="CHOCH_DOWN",
        status=SetupStatus.FIRE,
        evidence=SetupEvidence(
            liquidity="SWEPT",
            structure="CHOCH_DOWN",
            confirmation="VALID",
            metrics={"sweep_depth": 0.00025},
        ),
        reason="Deterministic test fire",
        created_at=t0,
    )

    with session_factory() as session:
        session.query(SetupEvidenceModel).filter_by(setup_id="EURUSD_M5_S01_BEARISH_TEST001").delete()
        session.query(SetupModel).filter_by(setup_id="EURUSD_M5_S01_BEARISH_TEST001").delete()
        session.commit()

        # First insertion
        count1 = engine.save_setups(session, [rec])
        assert count1 == 1

        # Re-running save_setups with identical record must NOT fail and must insert 0 (idempotency)
        count2 = engine.save_setups(session, [rec])
        assert count2 == 0

        # Query database directly
        db_setup = session.query(SetupModel).filter_by(setup_id="EURUSD_M5_S01_BEARISH_TEST001").first()
        assert db_setup is not None
        assert db_setup.setup_code == "S01"
        assert db_setup.status == "FIRE"

        evidence = session.query(SetupEvidenceModel).filter_by(setup_id="EURUSD_M5_S01_BEARISH_TEST001").all()
        assert len(evidence) >= 1


# ==============================================================================
# 7. ADDITIONAL SPECIFIC ARCHETYPE & ROBUSTNESS TESTS
# ==============================================================================

def test_s01_wick_only_without_penetration():
    """Wick touching level exactly without >= 0.05 ATR penetration is ignored."""
    t0 = datetime(2026, 9, 5, 10, 0, tzinfo=timezone.utc)
    level = make_level(LiquidityLevelType.SESSION_HIGH, 1.10000, t0)
    atr = Decimal("0.00100")
    # High reaches 1.10001 (0.01 ATR < 0.05 ATR)
    c1 = make_candle(t0 + timedelta(minutes=5), 1.09980, 1.10001, 1.09970, 1.09990)
    detector = S01SweepReversalDetector(fallback_atr=atr)
    records = detector.evaluate_at_timestamp(
        timestamp=t0 + timedelta(minutes=5),
        symbol="EURUSD",
        timeframe="M5",
        candles_up_to_t=[c1],
        levels_up_to_t=[level],
        structure_events_up_to_t=[],
        current_atr=atr,
    )
    assert len(records) == 0


def test_s02_no_acceptance_expires():
    """S02 breakout candle occurs, but fails to maintain acceptance candles -> expires."""
    t0 = datetime(2026, 9, 5, 10, 0, tzinfo=timezone.utc)
    level = make_level(LiquidityLevelType.PREVIOUS_DAY_HIGH, 1.10000, t0)
    atr = Decimal("0.00100")

    # C1: Breakout
    c1 = make_candle(t0 + timedelta(minutes=5), 1.09980, 1.10020, 1.09970, 1.10015)
    # Subsequent bars hover without achieving 2 closed candles outside + 0.30 ATR follow-through
    c2 = make_candle(t0 + timedelta(minutes=10), 1.10015, 1.10018, 1.10005, 1.10010)
    c3 = make_candle(t0 + timedelta(minutes=15), 1.10010, 1.10015, 1.10005, 1.10010)
    c4 = make_candle(t0 + timedelta(minutes=20), 1.10010, 1.10015, 1.10005, 1.10010)
    c5 = make_candle(t0 + timedelta(minutes=25), 1.10010, 1.10015, 1.10005, 1.10010)

    detector = S02LiquidityAcceptanceDetector(fallback_atr=atr, expiry_bars=3)
    records = detector.evaluate_at_timestamp(
        timestamp=t0 + timedelta(minutes=25),
        symbol="EURUSD",
        timeframe="M5",
        candles_up_to_t=[c1, c2, c3, c4, c5],
        levels_up_to_t=[level],
        structure_events_up_to_t=[],
        current_atr=atr,
    )
    expired = [r for r in records if r.status == SetupStatus.EXPIRED]
    assert len(expired) >= 1


def test_s03_no_failure_holds_breakout():
    """S03 breakout holds without returning through the level -> no trap FIRE."""
    t0 = datetime(2026, 9, 5, 10, 0, tzinfo=timezone.utc)
    level = make_level(LiquidityLevelType.SESSION_HIGH, 1.10000, t0)
    atr = Decimal("0.00100")

    c1 = make_candle(t0 + timedelta(minutes=5), 1.09980, 1.10020, 1.09970, 1.10015)
    c2 = make_candle(t0 + timedelta(minutes=10), 1.10015, 1.10050, 1.10010, 1.10045)
    c3 = make_candle(t0 + timedelta(minutes=15), 1.10045, 1.10070, 1.10040, 1.10065)

    detector = S03FailedBreakoutDetector(fallback_atr=atr)
    records = detector.evaluate_at_timestamp(
        timestamp=t0 + timedelta(minutes=15),
        symbol="EURUSD",
        timeframe="M5",
        candles_up_to_t=[c1, c2, c3],
        levels_up_to_t=[level],
        structure_events_up_to_t=[],
        current_atr=atr,
    )
    fires = [r for r in records if r.status == SetupStatus.FIRE]
    assert len(fires) == 0


def test_s03_insufficient_opposite_displacement():
    """S03 returns through level but opposite displacement is < 0.30 ATR -> does not arm."""
    t0 = datetime(2026, 9, 5, 10, 0, tzinfo=timezone.utc)
    level = make_level(LiquidityLevelType.SESSION_HIGH, 1.10000, t0)
    atr = Decimal("0.00100")

    c1 = make_candle(t0 + timedelta(minutes=5), 1.09980, 1.10020, 1.09970, 1.10015)
    c2 = make_candle(t0 + timedelta(minutes=10), 1.10015, 1.10018, 1.09980, 1.09990) # Returned
    # Only displaces to 1.09985 (0.15 ATR < 0.30 ATR)
    c3 = make_candle(t0 + timedelta(minutes=15), 1.09990, 1.09995, 1.09980, 1.09985)

    detector = S03FailedBreakoutDetector(fallback_atr=atr)
    records = detector.evaluate_at_timestamp(
        timestamp=t0 + timedelta(minutes=15),
        symbol="EURUSD",
        timeframe="M5",
        candles_up_to_t=[c1, c2, c3],
        levels_up_to_t=[level],
        structure_events_up_to_t=[],
        current_atr=atr,
    )
    armed = [r for r in records if r.status in (SetupStatus.ARMED, SetupStatus.FIRE)]
    assert len(armed) == 0


def test_s03_missing_structure_shift():
    """S03 opposite displacement achieved but structure shift is missing -> remains ARMED."""
    t0 = datetime(2026, 9, 5, 10, 0, tzinfo=timezone.utc)
    level = make_level(LiquidityLevelType.SESSION_HIGH, 1.10000, t0)
    atr = Decimal("0.00100")

    c1 = make_candle(t0 + timedelta(minutes=5), 1.09980, 1.10020, 1.09970, 1.10015)
    c2 = make_candle(t0 + timedelta(minutes=10), 1.10015, 1.10018, 1.09970, 1.09980)
    c3 = make_candle(t0 + timedelta(minutes=15), 1.09980, 1.09990, 1.09640, 1.09650)

    detector = S03FailedBreakoutDetector(fallback_atr=atr)
    records = detector.evaluate_at_timestamp(
        timestamp=t0 + timedelta(minutes=15),
        symbol="EURUSD",
        timeframe="M5",
        candles_up_to_t=[c1, c2, c3],
        levels_up_to_t=[level],
        structure_events_up_to_t=[],  # Missing structure shift
        current_atr=atr,
    )
    fires = [r for r in records if r.status == SetupStatus.FIRE]
    armed = [r for r in records if r.status == SetupStatus.ARMED]
    assert len(fires) == 0
    assert len(armed) == 1


def test_s04_candidate_vs_strong_anomaly():
    """Differentiates between ANOMALY_CANDIDATE and STRONG_ANOMALY."""
    t0 = datetime(2026, 9, 5, 10, 0, tzinfo=timezone.utc)
    # Candidate: act_z = 2.1, resp_z = -1.1 (pinbar for context)
    c1 = make_candle(t0, 1.10000, 1.10030, 1.09970, 1.10005)
    f1 = make_feature(t0, act_z=2.1, resp_z=-1.1, is_cand=True)

    detector = S04EffortResultAnomalyDetector()
    records = detector.evaluate_at_timestamp(
        timestamp=t0,
        symbol="EURUSD",
        timeframe="M5",
        candles_up_to_t=[c1],
        features_up_to_t=[f1],
        levels_up_to_t=[],
        structure_events_up_to_t=[],
    )
    assert len(records) == 1
    assert records[0].anomaly_type == "ANOMALY_CANDIDATE"


def test_s04_anomaly_with_structure_failure_context():
    """Anomaly near structure event qualifies for ARMED status."""
    t0 = datetime(2026, 9, 5, 10, 0, tzinfo=timezone.utc)
    c = make_candle(t0, 1.10000, 1.10020, 1.09980, 1.10015)
    f = make_feature(t0, act_z=2.6, resp_z=-1.6, is_strong=True)
    struct = make_structure("CHOCH_DOWN", 1.10000, t0, t0)

    detector = S04EffortResultAnomalyDetector()
    records = detector.evaluate_at_timestamp(
        timestamp=t0,
        symbol="EURUSD",
        timeframe="M5",
        candles_up_to_t=[c],
        features_up_to_t=[f],
        levels_up_to_t=[],
        structure_events_up_to_t=[struct],
    )
    armed = [r for r in records if r.status == SetupStatus.ARMED]
    assert len(armed) == 1


def test_s05_insufficient_expansion_range_does_not_fire():
    """Compressed market with next candle range < 1.5 * median range does not fire."""
    t0 = datetime(2026, 9, 5, 10, 0, tzinfo=timezone.utc)
    candles = [make_candle(t0 + timedelta(minutes=5 * i), 1.10000, 1.10004, 1.09998, 1.10001) for i in range(10)]
    # 11th candle has normal small range
    c11 = make_candle(t0 + timedelta(minutes=50), 1.10001, 1.10005, 1.10000, 1.10003)
    candles.append(c11)

    detector = S05CompressionExpansionDetector()
    records = detector.evaluate_at_timestamp(
        timestamp=t0 + timedelta(minutes=50),
        symbol="EURUSD",
        timeframe="M5",
        candles_up_to_t=candles,
        features_up_to_t=[],
        levels_up_to_t=[],
        structure_events_up_to_t=[],
    )
    fires = [r for r in records if r.status == SetupStatus.FIRE]
    assert len(fires) == 0


def test_state_transitions_and_immutability():
    """State machine transitions enforce allowed transitions and model immutability."""
    sm = SetupStateMachine()
    t0 = datetime(2026, 9, 5, 10, 0, tzinfo=timezone.utc)
    rec = SetupRecord(
        setup_id="TEST_STATE",
        setup_code=SetupCode.S01,
        symbol="EURUSD",
        timeframe="M5",
        timestamp=t0,
        direction=SetupDirection.BULLISH,
        status=SetupStatus.WATCH,
        created_at=t0,
    )

    # Valid transition: WATCH -> ARMED
    armed = sm.transition(rec, SetupStatus.ARMED, reason="Valid rejection")
    assert armed.status == SetupStatus.ARMED
    # Original record remains untouched (immutability)
    assert rec.status == SetupStatus.WATCH

    # Invalid transition: WATCH -> FIRE (must go through ARMED)
    with pytest.raises(ValueError):
        sm.transition(rec, SetupStatus.FIRE)


def test_insufficient_data_and_zero_atr():
    """Engine gracefully handles empty data and zero ATR without throwing division errors."""
    engine = SetupDetectorEngine(fallback_atr=Decimal("0.00100"))
    t0 = datetime(2026, 9, 5, 10, 0, tzinfo=timezone.utc)

    # Empty data
    empty_records = engine.detect_at_timestamp(
        timestamp=t0,
        candles=[],
    )
    assert empty_records == []

    # Candle with zero ATR feature
    c = make_candle(t0, 1.10000, 1.10000, 1.10000, 1.10000)
    f = make_feature(t0, atr=0.0)
    records = engine.detect_at_timestamp(
        timestamp=t0,
        candles=[c],
        features=[f],
    )
    assert isinstance(records, list)


def test_deterministic_repeated_execution():
    """Repeated runs on the same input dataset return identical setup records."""
    t0 = datetime(2026, 9, 5, 10, 0, tzinfo=timezone.utc)
    atr = Decimal("0.00100")
    level = make_level(LiquidityLevelType.SESSION_HIGH, 1.10000, t0)
    candles = [
        make_candle(t0 + timedelta(minutes=5), 1.09950, 1.10020, 1.09940, 1.09980),
        make_candle(t0 + timedelta(minutes=10), 1.09980, 1.09990, 1.09650, 1.09660),
    ]
    struct = [make_structure("CHOCH_DOWN", 1.09660, t0 + timedelta(minutes=10), t0 + timedelta(minutes=10), disp=0.00030)]

    engine = SetupDetectorEngine(fallback_atr=atr)
    t_eval = t0 + timedelta(minutes=10)

    run1 = engine.detect_at_timestamp(timestamp=t_eval, candles=candles, liquidity_levels=[level], structure_events=struct)
    run2 = engine.detect_at_timestamp(timestamp=t_eval, candles=candles, liquidity_levels=[level], structure_events=struct)

    assert len(run1) == len(run2)
    for r1, r2 in zip(run1, run2):
        assert r1.setup_id == r2.setup_id
        assert r1.status == r2.status
        assert r1.direction == r2.direction
        assert r1.evidence.model_dump() == r2.evidence.model_dump()
