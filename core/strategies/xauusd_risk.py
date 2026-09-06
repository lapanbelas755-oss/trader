"""
Trader Machine — XAUUSD Institutional Risk Engine V1.
Strict mathematical risk firewall and position sizing engine for Gold (XAUUSD).

Adheres to Master Instruction (AGENTS.MD Law #10) & User Specification (Section K):
1. Lot size is strictly calculated from account risk %, SL distance, and contract specs.
   NEVER from confidence score or arbitrary heuristics.
2. Hard firewall vetoes:
   - Max risk per trade %
   - Max daily loss %
   - Max consecutive losses
   - Max open positions
   - Max portfolio exposure
   - Trading session filter
   - High-impact news protection
"""

from dataclasses import dataclass, field
from datetime import datetime, time as dt_time, timezone
from decimal import Decimal
import logging
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class XAUUSDRiskConfig:
    """Configurable risk management parameters for XAU/USD."""
    symbol: str = "XAUUSD"
    contract_size: float = 100.0          # 100 troy ounces per 1.00 standard lot
    tick_size: float = 0.01               # $0.01 minimum price increment
    min_lot: float = 0.01
    max_lot: float = 50.0
    step_lot: float = 0.01
    
    # Risk Limits
    risk_per_trade_pct: float = 1.0       # Default 1.0% of account balance
    max_risk_per_trade_pct: float = 2.0   # Hard ceiling
    max_daily_loss_pct: float = 3.0       # Daily stop-loss firewall
    max_consecutive_losses: int = 3       # Cooldown after consecutive losses
    max_open_positions: int = 1           # Sniper single position discipline
    max_exposure_lots: float = 5.0        # Max aggregate exposure
    
    # Session & News Restrictions
    allowed_sessions: Tuple[str, ...] = ("NEW YORK", "NEW YORK (OVERLAP)", "LONDON")
    news_protection_active: bool = False
    min_sl_distance_dollars: float = 1.00 # Minimum $1.00 SL distance on gold ($10/pip)


@dataclass
class AccountRiskState:
    """Current account financial and drawdown state."""
    balance: float
    equity: float
    daily_starting_balance: float
    realized_daily_loss: float = 0.0
    consecutive_losses: int = 0
    open_positions: int = 0
    open_lots: float = 0.0
    is_news_event: bool = False
    current_session: str = "NEW YORK"


@dataclass
class RiskDecision:
    """Approval status, calculated lot size, and explanation."""
    approved: bool
    lot_size: float = 0.0
    risk_dollars: float = 0.0
    risk_pct: float = 0.0
    sl_distance: float = 0.0
    veto_reasons: List[str] = field(default_factory=list)
    notes: str = ""


class XAUUSDRiskEngine:
    """
    Independent Risk Firewall for XAU/USD Breakout Trading.
    Completely isolated from strategy signal generation.
    Has absolute authority to veto any signal (AGENTS.MD Law #10).
    """

    def __init__(self, config: Optional[XAUUSDRiskConfig] = None):
        self.cfg = config or XAUUSDRiskConfig()

    def calculate_lot_size(
        self,
        account_balance: float,
        sl_distance_dollars: float,
        risk_pct: Optional[float] = None,
    ) -> Tuple[float, float, float]:
        """
        Calculates exact position size in standard lots for XAU/USD.
        Formula:
            Risk Dollars = Balance * (Risk% / 100)
            Loss Per Standard Lot = SL Distance * Contract Size (100 oz)
            Lot Size = Risk Dollars / Loss Per Standard Lot
        Returns: (lot_size, risk_dollars, effective_risk_pct)
        """
        if account_balance <= 0 or sl_distance_dollars <= 0:
            return 0.0, 0.0, 0.0

        target_risk_pct = risk_pct if risk_pct is not None else self.cfg.risk_per_trade_pct
        target_risk_pct = min(target_risk_pct, self.cfg.max_risk_per_trade_pct)
        target_risk_pct = max(0.1, target_risk_pct)

        risk_dollars = account_balance * (target_risk_pct / 100.0)
        dollar_loss_per_lot = sl_distance_dollars * self.cfg.contract_size

        if dollar_loss_per_lot <= 0:
            return 0.0, 0.0, 0.0

        raw_lot = risk_dollars / dollar_loss_per_lot

        # Round down to nearest step_lot (0.01) to never exceed designated risk
        step = self.cfg.step_lot
        stepped_lot = int(raw_lot / step) * step
        stepped_lot = round(stepped_lot, 2)

        # Enforce bounds
        bounded_lot = max(self.cfg.min_lot, min(self.cfg.max_lot, stepped_lot))
        if stepped_lot < self.cfg.min_lot:
            # If minimum lot exceeds target risk dollars by > 25%, reject
            min_lot_risk = self.cfg.min_lot * dollar_loss_per_lot
            if min_lot_risk > risk_dollars * 1.25:
                return 0.0, 0.0, 0.0
            bounded_lot = self.cfg.min_lot

        actual_risk_dollars = bounded_lot * dollar_loss_per_lot
        effective_risk_pct = (actual_risk_dollars / account_balance) * 100.0

        return round(bounded_lot, 2), round(actual_risk_dollars, 2), round(effective_risk_pct, 2)

    def evaluate(
        self,
        account: AccountRiskState,
        signal: str,
        entry: float,
        stop_loss: float,
    ) -> RiskDecision:
        """
        Audits prospective signal against all institutional risk firewall rules.
        Returns approved RiskDecision or vetoed decision with exact reasons.
        """
        vetoes: List[str] = []

        if signal not in ("BUY", "SELL"):
            return RiskDecision(
                approved=False,
                veto_reasons=["No actionable trading signal (Signal is NO_TRADE)"],
                notes="Risk engine dormant",
            )

        sl_distance = abs(entry - stop_loss)
        if sl_distance < self.cfg.min_sl_distance_dollars:
            vetoes.append(
                f"SL distance too small (${sl_distance:.2f} < ${self.cfg.min_sl_distance_dollars:.2f})"
            )

        # 1. Daily Loss Limit Firewall
        starting_bal = account.daily_starting_balance if account.daily_starting_balance > 0 else account.balance
        daily_loss_pct = (account.realized_daily_loss / starting_bal) * 100.0 if starting_bal > 0 else 0.0
        if daily_loss_pct >= self.cfg.max_daily_loss_pct:
            vetoes.append(
                f"Daily loss limit breached ({daily_loss_pct:.1f}% >= max {self.cfg.max_daily_loss_pct:.1f}%)"
            )

        # 2. Consecutive Losses Limit
        if account.consecutive_losses >= self.cfg.max_consecutive_losses:
            vetoes.append(
                f"Consecutive loss limit reached ({account.consecutive_losses} >= max {self.cfg.max_consecutive_losses})"
            )

        # 3. Max Open Positions
        if account.open_positions >= self.cfg.max_open_positions:
            vetoes.append(
                f"Max open positions reached ({account.open_positions} >= max {self.cfg.max_open_positions})"
            )

        # 4. News Protection Guard
        if account.is_news_event or self.cfg.news_protection_active:
            vetoes.append("High-impact economic news embargo active")

        # 5. Session Filter
        if account.current_session not in self.cfg.allowed_sessions:
            vetoes.append(
                f"Session '{account.current_session}' not in approved breakout sessions {self.cfg.allowed_sessions}"
            )

        # 6. Lot Size Computation & Portfolio Exposure
        lot_size, risk_dollars, risk_pct = self.calculate_lot_size(
            account_balance=account.balance,
            sl_distance_dollars=sl_distance,
        )

        if lot_size <= 0:
            vetoes.append("Calculated lot size is zero or exceeds risk bounds for account balance")

        if account.open_lots + lot_size > self.cfg.max_exposure_lots:
            vetoes.append(
                f"Total exposure exceeded ({account.open_lots + lot_size:.2f} > max {self.cfg.max_exposure_lots:.2f} lots)"
            )

        if vetoes:
            logger.warning("🛡️ Risk Firewall VETO for %s: %s", signal, "; ".join(vetoes))
            return RiskDecision(
                approved=False,
                lot_size=0.0,
                risk_dollars=0.0,
                risk_pct=0.0,
                sl_distance=round(sl_distance, 2),
                veto_reasons=vetoes,
                notes="Signal blocked by Risk Firewall",
            )

        logger.info(
            "✅ Risk Firewall APPROVED: %s | Lot: %.2f | Risk: $%.2f (%.2f%%) | SL dist: $%.2f",
            signal, lot_size, risk_dollars, risk_pct, sl_distance,
        )
        return RiskDecision(
            approved=True,
            lot_size=lot_size,
            risk_dollars=risk_dollars,
            risk_pct=risk_pct,
            sl_distance=round(sl_distance, 2),
            veto_reasons=[],
            notes="Risk checks passed. Position approved.",
        )
