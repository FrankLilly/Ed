"""Risk management engine — capital protection and position sizing."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from options_bot.models import OptionLeg, Position, TradeOrder


@dataclass
class RiskLimits:
    """Configurable risk parameters."""

    max_portfolio_risk_pct: float = 0.05  # max 5% of portfolio at risk per trade
    max_total_risk_pct: float = 0.20  # max 20% of portfolio at risk total
    max_single_position_pct: float = 0.10  # max 10% of portfolio in one position
    max_positions: int = 10
    max_daily_trades: int = 5
    max_daily_loss: float = 0.03  # stop trading if down 3% in a day
    min_days_to_expiry: int = 7  # don't open positions expiring in < 7 days
    max_days_to_expiry: int = 60  # don't buy options > 60 DTE
    max_bid_ask_spread_pct: float = 0.10  # skip illiquid options
    min_open_interest: int = 100
    min_volume: int = 50
    max_iv_percentile: float = 90.0  # don't buy options with IV > 90th percentile
    require_defined_risk: bool = True  # only allow defined-risk strategies


@dataclass
class DailyStats:
    """Track daily trading statistics."""

    date: datetime = field(default_factory=datetime.now)
    trades_today: int = 0
    daily_pnl: float = 0.0
    starting_balance: float = 0.0


class RiskManager:
    """Enforces risk limits and calculates position sizes."""

    def __init__(self, portfolio_value: float, limits: RiskLimits | None = None) -> None:
        self.portfolio_value = portfolio_value
        self.limits = limits or RiskLimits()
        self.daily_stats = DailyStats(starting_balance=portfolio_value)

    def update_portfolio_value(self, value: float) -> None:
        self.portfolio_value = value

    def update_daily_pnl(self, pnl: float) -> None:
        self.daily_stats.daily_pnl = pnl

    def reset_daily_stats(self) -> None:
        self.daily_stats = DailyStats(starting_balance=self.portfolio_value)

    def check_order(
        self,
        order: TradeOrder,
        open_positions: list[Position],
    ) -> tuple[bool, str]:
        """
        Validate an order against all risk limits.

        Returns:
            (allowed, reason) — allowed=True if trade passes all checks
        """
        # Daily trade limit
        if self.daily_stats.trades_today >= self.limits.max_daily_trades:
            return False, f"Daily trade limit reached ({self.limits.max_daily_trades})"

        # Daily loss limit
        daily_loss_pct = abs(self.daily_stats.daily_pnl) / self.portfolio_value if self.portfolio_value > 0 else 0
        if self.daily_stats.daily_pnl < 0 and daily_loss_pct >= self.limits.max_daily_loss:
            return False, f"Daily loss limit reached ({daily_loss_pct:.1%} >= {self.limits.max_daily_loss:.1%})"

        # Max positions
        active_positions = [p for p in open_positions if not p.is_closed]
        if len(active_positions) >= self.limits.max_positions:
            return False, f"Max positions reached ({self.limits.max_positions})"

        # Single position size
        max_loss = abs(order.max_loss) if order.max_loss < 0 else 0
        if max_loss == 0:
            # Credit strategy — risk is (width - credit) or undefined
            max_loss = abs(order.net_premium) * 5  # conservative estimate

        position_risk_pct = max_loss / self.portfolio_value if self.portfolio_value > 0 else 1.0
        if position_risk_pct > self.limits.max_single_position_pct:
            return False, (
                f"Position risk too high ({position_risk_pct:.1%} > "
                f"{self.limits.max_single_position_pct:.1%})"
            )

        if position_risk_pct > self.limits.max_portfolio_risk_pct:
            return False, (
                f"Per-trade risk limit exceeded ({position_risk_pct:.1%} > "
                f"{self.limits.max_portfolio_risk_pct:.1%})"
            )

        # Total portfolio risk
        total_risk = sum(
            abs(p.entry_premium) for p in active_positions if not p.is_closed
        ) + max_loss
        total_risk_pct = total_risk / self.portfolio_value if self.portfolio_value > 0 else 1.0
        if total_risk_pct > self.limits.max_total_risk_pct:
            return False, (
                f"Total portfolio risk limit exceeded ({total_risk_pct:.1%} > "
                f"{self.limits.max_total_risk_pct:.1%})"
            )

        # DTE checks
        for leg in order.legs:
            dte = (leg.contract.expiration - datetime.now()).days
            if dte < self.limits.min_days_to_expiry:
                return False, f"Expiration too soon ({dte} < {self.limits.min_days_to_expiry} DTE)"
            if dte > self.limits.max_days_to_expiry:
                return False, f"Expiration too far out ({dte} > {self.limits.max_days_to_expiry} DTE)"

        # Liquidity checks
        for leg in order.legs:
            c = leg.contract
            if c.open_interest > 0 and c.open_interest < self.limits.min_open_interest:
                return False, f"Low open interest on {c.strike} {c.option_type.value} ({c.open_interest})"
            if c.volume > 0 and c.volume < self.limits.min_volume:
                return False, f"Low volume on {c.strike} {c.option_type.value} ({c.volume})"
            if c.ask > 0 and c.bid > 0:
                spread_pct = (c.ask - c.bid) / c.mid_price if c.mid_price > 0 else 1.0
                if spread_pct > self.limits.max_bid_ask_spread_pct:
                    return False, f"Bid-ask spread too wide ({spread_pct:.1%})"

        # Defined risk check
        if self.limits.require_defined_risk:
            has_naked = self._has_naked_legs(order.legs)
            if has_naked:
                return False, "Undefined risk not allowed (naked short option detected)"

        self.daily_stats.trades_today += 1
        return True, "Order approved"

    def calculate_position_size(self, max_loss_per_contract: float) -> int:
        """Calculate how many contracts to trade given risk limits."""
        if max_loss_per_contract <= 0 or self.portfolio_value <= 0:
            return 0
        max_risk_amount = self.portfolio_value * self.limits.max_portfolio_risk_pct
        contracts = int(max_risk_amount / abs(max_loss_per_contract))
        return max(1, contracts)

    @staticmethod
    def _has_naked_legs(legs: list[OptionLeg]) -> bool:
        """Check if any short legs are unprotected."""
        from options_bot.models import PositionSide, OptionType

        short_calls = [l for l in legs if l.side == PositionSide.SHORT and l.contract.option_type == OptionType.CALL]
        long_calls = [l for l in legs if l.side == PositionSide.LONG and l.contract.option_type == OptionType.CALL]
        short_puts = [l for l in legs if l.side == PositionSide.SHORT and l.contract.option_type == OptionType.PUT]
        long_puts = [l for l in legs if l.side == PositionSide.LONG and l.contract.option_type == OptionType.PUT]

        # Naked if short calls/puts outnumber long calls/puts
        naked_calls = sum(l.quantity for l in short_calls) > sum(l.quantity for l in long_calls)
        naked_puts = sum(l.quantity for l in short_puts) > sum(l.quantity for l in long_puts)
        return naked_calls or naked_puts
