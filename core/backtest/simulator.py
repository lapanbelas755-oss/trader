"""
Trade path simulator for Backtest Engine V1.
Simulates sequential candle progression, intrabar ambiguity detection,
MAE/MFE excursion tracking, and deterministic timeout execution.
"""

from datetime import datetime
from decimal import Decimal
from typing import Any, List, Optional, Sequence, Tuple
from core.backtest.config import BacktestConfig
from core.backtest.contract import BacktestTradeRecord, TradeResult, TradeStatus
from core.setups.common import ensure_utc, get_val


class TradePathSimulator:
    """
    Simulates price action candle-by-candle following trade entry.
    Strictly preserves causality: decisions at entry timestamp T do not change;
    subsequent candles only determine simulated exit execution.
    """

    def __init__(self, config: Optional[BacktestConfig] = None):
        self.config = config or BacktestConfig()

    def simulate_trade(
        self,
        trade: BacktestTradeRecord,
        subsequent_candles: Sequence[Any],
    ) -> BacktestTradeRecord:
        """
        Processes subsequent candles following entry_time until TP, SL, timeout, or ambiguity.
        """
        if trade.result == TradeResult.INVALID:
            return trade

        entry_price = trade.entry_price
        stop_loss = trade.stop_loss
        take_profit = trade.take_profit
        direction = trade.direction
        r_unit = abs(entry_price - stop_loss)

        if r_unit == Decimal("0"):
            trade.result = TradeResult.DATA_ERROR
            trade.status = TradeStatus.INVALID
            trade.ambiguity_reason = "Zero risk distance R"
            return trade

        mae_r = Decimal("0.0")
        mfe_r = Decimal("0.0")
        bars_held = 0

        for candle in subsequent_candles:
            c_ts = ensure_utc(get_val(candle, "timestamp"))
            if c_ts <= trade.entry_time:
                continue

            bars_held += 1
            high = Decimal(str(get_val(candle, "high")))
            low = Decimal(str(get_val(candle, "low")))
            close = Decimal(str(get_val(candle, "close")))

            # Update MAE and MFE
            if direction == "BULLISH":
                adverse = max(Decimal("0.0"), entry_price - low)
                favorable = max(Decimal("0.0"), high - entry_price)
            else:
                adverse = max(Decimal("0.0"), high - entry_price)
                favorable = max(Decimal("0.0"), entry_price - low)

            mae_r = max(mae_r, adverse / r_unit)
            mfe_r = max(mfe_r, favorable / r_unit)

            # Check SL and TP triggers
            if direction == "BULLISH":
                sl_hit = low <= stop_loss
                tp_hit = high >= take_profit
            else:
                sl_hit = high >= stop_loss
                tp_hit = low <= take_profit

            # INTRABAR AMBIGUITY CHECK
            if sl_hit and tp_hit:
                trade.exit_time = c_ts
                trade.exit_price = close
                trade.result = TradeResult.AMBIGUOUS
                trade.status = TradeStatus.CLOSED
                trade.ambiguity_reason = "Intrabar ambiguity: both TP and SL breached in single candle"
                trade.r_multiple = None
                trade.mae_r = mae_r
                trade.mfe_r = mfe_r
                return trade

            if tp_hit:
                exit_price = take_profit
                if self.config.slippage_pips > Decimal("0"):
                    exit_price = exit_price - self.config.slippage_pips if direction == "BULLISH" else exit_price + self.config.slippage_pips
                
                trade.exit_time = c_ts
                trade.exit_price = exit_price
                trade.result = TradeResult.TP
                trade.status = TradeStatus.CLOSED
                trade.r_multiple = self.config.target_r - self._calculate_commission_in_r(r_unit)
                trade.mae_r = mae_r
                trade.mfe_r = mfe_r
                return trade

            if sl_hit:
                exit_price = stop_loss
                if self.config.slippage_pips > Decimal("0"):
                    exit_price = exit_price - self.config.slippage_pips if direction == "BULLISH" else exit_price + self.config.slippage_pips

                trade.exit_time = c_ts
                trade.exit_price = exit_price
                trade.result = TradeResult.SL
                trade.status = TradeStatus.CLOSED
                trade.r_multiple = Decimal("-1.0") - self._calculate_commission_in_r(r_unit)
                trade.mae_r = mae_r
                trade.mfe_r = mfe_r
                return trade

            # TIMEOUT CHECK
            if bars_held >= self.config.timeout_bars:
                exit_price = close
                if self.config.slippage_pips > Decimal("0"):
                    exit_price = exit_price - self.config.slippage_pips if direction == "BULLISH" else exit_price + self.config.slippage_pips

                realized_pnl = (exit_price - entry_price) if direction == "BULLISH" else (entry_price - exit_price)
                realized_r = (realized_pnl / r_unit) - self._calculate_commission_in_r(r_unit)

                trade.exit_time = c_ts
                trade.exit_price = exit_price
                trade.result = TradeResult.TIMEOUT
                trade.status = TradeStatus.CLOSED
                trade.r_multiple = realized_r.quantize(Decimal("0.0001"))
                trade.mae_r = mae_r
                trade.mfe_r = mfe_r
                return trade

        # End of dataset before trade exit reached: close at latest available candle
        if subsequent_candles:
            last_c = subsequent_candles[-1]
            last_ts = ensure_utc(get_val(last_c, "timestamp"))
            last_close = Decimal(str(get_val(last_c, "close")))
            realized_pnl = (last_close - entry_price) if direction == "BULLISH" else (entry_price - last_close)
            realized_r = (realized_pnl / r_unit) - self._calculate_commission_in_r(r_unit)

            trade.exit_time = last_ts
            trade.exit_price = last_close
            trade.result = TradeResult.TIMEOUT
            trade.status = TradeStatus.CLOSED
            trade.r_multiple = realized_r.quantize(Decimal("0.0001"))
            trade.mae_r = mae_r
            trade.mfe_r = mfe_r
        else:
            trade.result = TradeResult.DATA_ERROR
            trade.status = TradeStatus.INVALID
            trade.ambiguity_reason = "No subsequent candles provided for simulation"

        return trade

    def _calculate_commission_in_r(self, r_unit: Decimal) -> Decimal:
        """Translates fixed monetary/pip commission into R units."""
        if self.config.commission_per_trade <= Decimal("0") or r_unit <= Decimal("0"):
            return Decimal("0.0")
        return self.config.commission_per_trade / r_unit
