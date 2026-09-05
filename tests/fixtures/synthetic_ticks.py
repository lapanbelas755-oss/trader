"""Synthetic test fixtures covering all 12 edge cases from Phase 10."""

# 1. Valid tick
VALID_TICK_1 = {
    "timestamp": "2026-09-01T10:00:00.100Z",
    "symbol": "EURUSD",
    "bid": "1.08520",
    "ask": "1.08530",
    "last": "1.08525",
    "volume": "1.0",
    "source": "SYNTHETIC_TEST",
}

# 2. Duplicate tick (exact same as VALID_TICK_1)
DUPLICATE_TICK_1 = dict(VALID_TICK_1)

# 3. Invalid bid (<= 0)
INVALID_BID_TICK = {
    "timestamp": "2026-09-01T10:00:01.000Z",
    "symbol": "EURUSD",
    "bid": "0.00000",
    "ask": "1.08530",
    "volume": "1.0",
    "source": "SYNTHETIC_TEST",
}

# 4. Invalid ask (<= 0)
INVALID_ASK_TICK = {
    "timestamp": "2026-09-01T10:00:02.000Z",
    "symbol": "EURUSD",
    "bid": "1.08520",
    "ask": "-1.08530",
    "volume": "1.0",
    "source": "SYNTHETIC_TEST",
}

# 5. Inverted spread (ask < bid)
INVERTED_SPREAD_TICK = {
    "timestamp": "2026-09-01T10:00:03.000Z",
    "symbol": "EURUSD",
    "bid": "1.08550",
    "ask": "1.08510",
    "volume": "1.0",
    "source": "SYNTHETIC_TEST",
}

# 6. Negative volume
NEGATIVE_VOLUME_TICK = {
    "timestamp": "2026-09-01T10:00:04.000Z",
    "symbol": "EURUSD",
    "bid": "1.08520",
    "ask": "1.08530",
    "volume": "-5.0",
    "source": "SYNTHETIC_TEST",
}

# 7. Missing timestamp
MISSING_TIMESTAMP_TICK = {
    "timestamp": None,
    "symbol": "EURUSD",
    "bid": "1.08520",
    "ask": "1.08530",
    "volume": "1.0",
    "source": "SYNTHETIC_TEST",
}

# 8. Timezone conversion (naive timestamp and custom timezone string)
NAIVE_TIMESTAMP_TICK = {
    "timestamp": "2026-09-01 10:00:05",  # naive string
    "symbol": "EURUSD",
    "bid": "1.08522",
    "ask": "1.08532",
    "volume": "2.0",
    "source": "SYNTHETIC_TEST",
}

# 9. Multiple ticks with same timestamp
SAME_TIMESTAMP_TICK_A = {
    "timestamp": "2026-09-01T10:00:06.000Z",
    "symbol": "EURUSD",
    "bid": "1.08520",
    "ask": "1.08530",
    "volume": "1.0",
    "source": "SYNTHETIC_TEST",
}
SAME_TIMESTAMP_TICK_B = {
    "timestamp": "2026-09-01T10:00:06.000Z",
    "symbol": "EURUSD",
    "bid": "1.08521",  # distinct bid
    "ask": "1.08531",
    "volume": "3.0",
    "source": "SYNTHETIC_TEST",
}

# 10. Timestamp backward (timestamp is earlier than previous tick)
BACKWARD_TIMESTAMP_TICK = {
    "timestamp": "2026-09-01T09:59:50.000Z",  # backward
    "symbol": "EURUSD",
    "bid": "1.08518",
    "ask": "1.08528",
    "volume": "1.0",
    "source": "SYNTHETIC_TEST",
}

# 11. Weekend gap (> 48 hours later)
WEEKEND_GAP_TICK = {
    "timestamp": "2026-09-04T10:00:00.000Z",  # 3 days later
    "symbol": "EURUSD",
    "bid": "1.08600",
    "ask": "1.08610",
    "volume": "1.0",
    "source": "SYNTHETIC_TEST",
}

# 12. Malformed row (non-numeric corrupt value)
MALFORMED_ROW_TICK = {
    "timestamp": "2026-09-01T10:00:07.000Z",
    "symbol": "EURUSD",
    "bid": "CORRUPT_NOT_A_NUMBER",
    "ask": "1.08530",
    "volume": "1.0",
    "source": "SYNTHETIC_TEST",
}
