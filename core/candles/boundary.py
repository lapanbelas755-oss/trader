"""Deterministic fixed UTC candle boundary calculator for M1, M5, M15, and H1."""
from datetime import datetime, timedelta, timezone
from core.candles.contract import Timeframe

def get_candle_bucket(dt: datetime, timeframe: Timeframe) -> tuple[datetime, datetime]:
    """
    Calculate fixed UTC bucket start and bucket end for a given datetime and timeframe.
    Interval is half-open: [bucket_start, bucket_end).
    """
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        utc_dt = dt.replace(tzinfo=timezone.utc)
    else:
        utc_dt = dt.astimezone(timezone.utc)

    minute = utc_dt.minute

    match timeframe:
        case Timeframe.M1:
            bucket_minute = minute
            duration = timedelta(minutes=1)
        case Timeframe.M5:
            bucket_minute = (minute // 5) * 5
            duration = timedelta(minutes=5)
        case Timeframe.M15:
            bucket_minute = (minute // 15) * 15
            duration = timedelta(minutes=15)
        case Timeframe.H1:
            bucket_minute = 0
            duration = timedelta(hours=1)

    bucket_start = utc_dt.replace(minute=bucket_minute, second=0, microsecond=0)
    bucket_end = bucket_start + duration
    return bucket_start, bucket_end

def is_in_bucket(dt: datetime, bucket_start: datetime, bucket_end: datetime) -> bool:
    """Verify half-open interval: bucket_start <= dt < bucket_end."""
    if dt.tzinfo is None:
        utc_dt = dt.replace(tzinfo=timezone.utc)
    else:
        utc_dt = dt.astimezone(timezone.utc)
    return bucket_start <= utc_dt < bucket_end
