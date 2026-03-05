"""Base strategy class and common types."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from options_bot.models import (
    GreeksResult,
    MarketSnapshot,
    OptionContract,
    OptionLeg,
    OptionType,
    PositionSide,
    Signal,
    TradeOrder,
    OrderAction,
)
from options_bot.pricing.greeks import Greeks

# Re-export for convenience
__all__ = ["Strategy", "OptionLeg", "OptionType", "PositionSide"]


class Strategy(ABC):
    """Abstract base class for all options strategies."""

    name: str = "base"
    description: str = ""

    @abstractmethod
    def build_legs(
        self,
        symbol: str,
        underlying_price: float,
        expiration: datetime,
        **kwargs: float,
    ) -> list[OptionLeg]:
        """Construct the option legs for this strategy."""

    def should_enter(self, signal: Signal, market: MarketSnapshot) -> bool:
        """Determine if this strategy should be entered given a signal."""
        return signal.strength >= 0.5

    def create_order(
        self,
        symbol: str,
        underlying_price: float,
        expiration: datetime,
        signal: Signal | None = None,
        **kwargs: float,
    ) -> TradeOrder:
        """Create a trade order for this strategy."""
        legs = self.build_legs(symbol, underlying_price, expiration, **kwargs)
        has_long = any(l.side == PositionSide.LONG for l in legs)
        action = OrderAction.BUY_TO_OPEN if has_long else OrderAction.SELL_TO_OPEN
        return TradeOrder(
            legs=legs,
            action=action,
            strategy_name=self.name,
            signal=signal,
        )

    def net_greeks(self, legs: list[OptionLeg], t: float, r: float = 0.05) -> GreeksResult:
        """Calculate net Greeks for the strategy's legs."""
        return Greeks.portfolio_greeks(legs, t, r)

    def payoff_at_expiry(self, legs: list[OptionLeg], price: float) -> float:
        """Calculate total P&L at expiry for a given underlying price."""
        return sum(leg.pnl_at_expiry(price) for leg in legs)

    def breakeven_prices(self, legs: list[OptionLeg]) -> list[float]:
        """Find approximate breakeven prices by scanning a price range."""
        if not legs:
            return []
        strikes = [leg.contract.strike for leg in legs]
        low = min(strikes) * 0.5
        high = max(strikes) * 1.5
        step = (high - low) / 1000.0

        breakevens: list[float] = []
        prev_pnl = self.payoff_at_expiry(legs, low)

        price = low + step
        while price <= high:
            current_pnl = self.payoff_at_expiry(legs, price)
            if prev_pnl * current_pnl < 0:  # sign change
                # Linear interpolation
                ratio = abs(prev_pnl) / (abs(prev_pnl) + abs(current_pnl))
                breakevens.append(round(price - step + step * ratio, 2))
            prev_pnl = current_pnl
            price += step

        return breakevens

    def __repr__(self) -> str:
        return f"<Strategy: {self.name}>"
