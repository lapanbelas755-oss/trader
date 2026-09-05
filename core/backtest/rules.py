"""
Deterministic backtest rule engine for deriving Entry, SL, and TP.
Strictly causality-preserving: uses ONLY data observable at or before entry timestamp T.
"""

from datetime import datetime
from decimal import Decimal
from typing import Any, List, Optional, Sequence, Tuple
from core.backtest.config import BacktestConfig
from core.backtest.contract import EntryPriceType, TradeResult, TradeStatus
from core.setups.common import ensure_utc, get_val


class BacktestRuleEngine:
    """
    Computes entry price, structural stop loss, and baseline 2R take profit
    for any setup occurrence candidate strictly using observable data <= T.
    """

    def __init__(self, config: Optional[BacktestConfig] = None):
        self.config = config or BacktestConfig()

    def resolve_entry_price(
        self,
        candle: Any,
        direction: str,
    ) -> Tuple[Decimal, EntryPriceType, Decimal]:
        """
        Determines entry price based on real Bid/Ask or explicitly configured fallback.
        Returns (entry_price, entry_price_type, spread).
        """
        bid = get_val(candle, "bid")
        ask = get_val(candle, "ask")
        close = Decimal(str(get_val(candle, "close")))
        candle_spread = get_val(candle, "spread")

        if bid is not None and ask is not None:
            bid_dec = Decimal(str(bid))
            ask_dec = Decimal(str(ask))
            spread = ask_dec - bid_dec
            base_price = ask_dec if direction == "BULLISH" else bid_dec
            price_type = EntryPriceType.REAL_BID_ASK
        elif candle_spread is not None and Decimal(str(candle_spread)) > Decimal("0"):
            spread = Decimal(str(candle_spread))
            bid_dec = close
            ask_dec = close + spread
            base_price = ask_dec if direction == "BULLISH" else bid_dec
            price_type = EntryPriceType.REAL_BID_ASK
        else:
            base_price = close
            spread = self.config.spread_fallback_pips
            price_type = EntryPriceType.FALLBACK_PRICE

        # Apply slippage if configured
        if self.config.slippage_pips > Decimal("0"):
            if direction == "BULLISH":
                entry_price = base_price + self.config.slippage_pips
            else:
                entry_price = base_price - self.config.slippage_pips
        else:
            entry_price = base_price

        return entry_price, price_type, spread

    def derive_structural_stop_loss(
        self,
        setup_code: str,
        direction: str,
        entry_price: Decimal,
        candles_up_to_t: Sequence[Any],
        evidence_snapshot: Optional[dict] = None,
    ) -> Tuple[Optional[Decimal], Optional[str]]:
        """
        Derives setup-specific structural invalidation SL strictly using data <= T.
        - Reversal (S01, S03): SL beyond sweep/false-breakout extreme +/- buffer.
        - Continuation (S02): SL beyond recent structural/liquidity invalidation +/- buffer.
        - Anomaly (S04): SL beyond recent anomaly extreme +/- buffer.
        - Compression (S05): SL beyond opposite compression boundary +/- buffer.
        """
        if not candles_up_to_t:
            return None, "No candles available to derive structural stop loss"

        buffer = self.config.sl_buffer_pips

        # Lookback window for structural extreme based on setup
        if setup_code in ("S01", "S03"):
            window = min(15, len(candles_up_to_t))
        elif setup_code == "S05":
            window = min(20, len(candles_up_to_t))
        else:
            window = min(10, len(candles_up_to_t))

        recent_candles = candles_up_to_t[-window:]

        if direction == "BULLISH":
            lowest_low = min(Decimal(str(get_val(c, "low"))) for c in recent_candles)
            sl = lowest_low - buffer
            if sl >= entry_price:
                return None, f"Calculated bullish SL {sl} is >= entry price {entry_price}"
            return sl, None

        elif direction == "BEARISH":
            highest_high = max(Decimal(str(get_val(c, "high"))) for c in recent_candles)
            sl = highest_high + buffer
            if sl <= entry_price:
                return None, f"Calculated bearish SL {sl} is <= entry price {entry_price}"
            return sl, None

        else:
            return None, f"Unknown setup direction {direction}"

    def calculate_take_profit(
        self,
        direction: str,
        entry_price: Decimal,
        stop_loss: Decimal,
    ) -> Decimal:
        """
        Calculates baseline target R Take Profit: TP = entry +/- (target_r * R).
        Where R = abs(entry - stop_loss).
        """
        r = abs(entry_price - stop_loss)
        if direction == "BULLISH":
            return entry_price + (self.config.target_r * r)
        else:
            return entry_price - (self.config.target_r * r)
