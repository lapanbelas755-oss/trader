"""
Deterministic state machine managing setup candidate lifecycle transitions.
Transitions:
OBSERVE -> WATCH -> ARMED -> FIRE
Terminal / Alternate states: EXPIRED, REJECTED
"""

from datetime import datetime, timedelta, timezone
from typing import Optional
from core.setups.contract import SetupStatus, SetupRecord


class SetupStateMachine:
    """
    Validates and executes lifecycle transitions for setup candidates.
    Enforces deterministic expiration and historical immutability.
    """

    ALLOWED_TRANSITIONS = {
        SetupStatus.OBSERVE: {SetupStatus.WATCH, SetupStatus.REJECTED, SetupStatus.EXPIRED},
        SetupStatus.WATCH: {SetupStatus.ARMED, SetupStatus.REJECTED, SetupStatus.EXPIRED},
        SetupStatus.ARMED: {SetupStatus.FIRE, SetupStatus.REJECTED, SetupStatus.EXPIRED},
        SetupStatus.FIRE: set(),       # Terminal for detector stage
        SetupStatus.EXPIRED: set(),    # Terminal
        SetupStatus.REJECTED: set(),   # Terminal
    }

    def __init__(self, default_expiry_bars: int = 3, bar_duration_minutes: int = 5):
        self.default_expiry_bars = default_expiry_bars
        self.bar_duration_minutes = bar_duration_minutes

    def calculate_expiration(self, from_time: datetime, num_bars: Optional[int] = None) -> datetime:
        """Calculate deterministic expiration timestamp based on closed candle count."""
        bars = num_bars if num_bars is not None else self.default_expiry_bars
        t = from_time if from_time.tzinfo else from_time.replace(tzinfo=timezone.utc)
        return t + timedelta(minutes=bars * self.bar_duration_minutes)

    def can_transition(self, current: SetupStatus, target: SetupStatus) -> bool:
        """Check whether the transition from current to target status is valid."""
        return target in self.ALLOWED_TRANSITIONS.get(current, set())

    def is_expired(self, expires_at: Optional[datetime], current_time: datetime) -> bool:
        """Check whether current_time has strictly passed the setup expiration time."""
        if expires_at is None:
            return False
        cur = current_time if current_time.tzinfo else current_time.replace(tzinfo=timezone.utc)
        exp = expires_at if expires_at.tzinfo else expires_at.replace(tzinfo=timezone.utc)
        return cur > exp

    def transition(
        self,
        record: SetupRecord,
        target_status: SetupStatus,
        reason: Optional[str] = None,
        at_timestamp: Optional[datetime] = None,
    ) -> SetupRecord:
        """
        Transition record to target status if allowed.
        Returns a new SetupRecord preserving immutability of historical states.
        """
        if not self.can_transition(record.status, target_status):
            raise ValueError(
                f"Illegal state transition from {record.status} to {target_status} for setup {record.setup_id}"
            )

        ts = at_timestamp or record.timestamp
        ts_utc = ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)

        updated = record.model_copy(deep=True)
        updated.status = target_status
        updated.timestamp = ts_utc
        if reason:
            updated.reason = reason
        return updated
