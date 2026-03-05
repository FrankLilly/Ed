"""Multi-leg volatility strategies: straddles, strangles, iron condors, iron butterflies."""

from __future__ import annotations

from datetime import datetime

from options_bot.models import (
    MarketSnapshot,
    OptionContract,
    OptionLeg,
    OptionType,
    PositionSide,
    Signal,
    SignalType,
)
from options_bot.pricing.black_scholes import BlackScholes
from options_bot.strategies.base import Strategy
from options_bot.strategies.spreads import _make_contract


class Straddle(Strategy):
    """Buy (or sell) a call and put at the same strike — volatility play."""

    name = "long_straddle"
    description = "High volatility: profit from large moves in either direction."

    def __init__(self, short: bool = False) -> None:
        self._short = short
        if short:
            self.name = "short_straddle"
            self.description = "Low volatility: profit when price stays near strike."

    def build_legs(
        self,
        symbol: str,
        underlying_price: float,
        expiration: datetime,
        strike: float = 0.0,
        iv: float = 0.3,
        quantity: int = 1,
        **kwargs: float,
    ) -> list[OptionLeg]:
        if strike == 0.0:
            strike = round(underlying_price, 2)

        call = _make_contract(symbol, OptionType.CALL, strike, expiration, underlying_price, iv)
        put = _make_contract(symbol, OptionType.PUT, strike, expiration, underlying_price, iv)

        side = PositionSide.SHORT if self._short else PositionSide.LONG
        qty = int(quantity)
        return [
            OptionLeg(contract=call, side=side, quantity=qty),
            OptionLeg(contract=put, side=side, quantity=qty),
        ]

    def should_enter(self, signal: Signal, market: MarketSnapshot) -> bool:
        if self._short:
            return signal.signal_type == SignalType.LOW_VOLATILITY and signal.strength >= 0.5
        return signal.signal_type == SignalType.HIGH_VOLATILITY and signal.strength >= 0.6


class Strangle(Strategy):
    """Buy (or sell) OTM call and OTM put — cheaper volatility play."""

    name = "long_strangle"
    description = "High volatility: cheaper than straddle, needs larger move."

    def __init__(self, short: bool = False) -> None:
        self._short = short
        if short:
            self.name = "short_strangle"
            self.description = "Low volatility: wider profit zone than straddle."

    def build_legs(
        self,
        symbol: str,
        underlying_price: float,
        expiration: datetime,
        call_strike: float = 0.0,
        put_strike: float = 0.0,
        iv: float = 0.3,
        quantity: int = 1,
        **kwargs: float,
    ) -> list[OptionLeg]:
        if call_strike == 0.0:
            call_strike = round(underlying_price * 1.05, 2)
        if put_strike == 0.0:
            put_strike = round(underlying_price * 0.95, 2)

        call = _make_contract(symbol, OptionType.CALL, call_strike, expiration, underlying_price, iv)
        put = _make_contract(symbol, OptionType.PUT, put_strike, expiration, underlying_price, iv)

        side = PositionSide.SHORT if self._short else PositionSide.LONG
        qty = int(quantity)
        return [
            OptionLeg(contract=call, side=side, quantity=qty),
            OptionLeg(contract=put, side=side, quantity=qty),
        ]

    def should_enter(self, signal: Signal, market: MarketSnapshot) -> bool:
        if self._short:
            return signal.signal_type == SignalType.LOW_VOLATILITY and signal.strength >= 0.5
        return signal.signal_type == SignalType.HIGH_VOLATILITY and signal.strength >= 0.5


class IronCondor(Strategy):
    """Sell OTM strangle + buy further OTM strangle — defined risk neutral strategy."""

    name = "iron_condor"
    description = "Neutral/low vol: profit from range-bound price action, defined risk."

    def build_legs(
        self,
        symbol: str,
        underlying_price: float,
        expiration: datetime,
        put_long_strike: float = 0.0,
        put_short_strike: float = 0.0,
        call_short_strike: float = 0.0,
        call_long_strike: float = 0.0,
        iv: float = 0.3,
        quantity: int = 1,
        **kwargs: float,
    ) -> list[OptionLeg]:
        if put_long_strike == 0.0:
            put_long_strike = round(underlying_price * 0.90, 2)
        if put_short_strike == 0.0:
            put_short_strike = round(underlying_price * 0.95, 2)
        if call_short_strike == 0.0:
            call_short_strike = round(underlying_price * 1.05, 2)
        if call_long_strike == 0.0:
            call_long_strike = round(underlying_price * 1.10, 2)

        qty = int(quantity)
        return [
            # Bull put spread (lower wing)
            OptionLeg(
                contract=_make_contract(symbol, OptionType.PUT, put_long_strike, expiration, underlying_price, iv),
                side=PositionSide.LONG,
                quantity=qty,
            ),
            OptionLeg(
                contract=_make_contract(symbol, OptionType.PUT, put_short_strike, expiration, underlying_price, iv),
                side=PositionSide.SHORT,
                quantity=qty,
            ),
            # Bear call spread (upper wing)
            OptionLeg(
                contract=_make_contract(symbol, OptionType.CALL, call_short_strike, expiration, underlying_price, iv),
                side=PositionSide.SHORT,
                quantity=qty,
            ),
            OptionLeg(
                contract=_make_contract(symbol, OptionType.CALL, call_long_strike, expiration, underlying_price, iv),
                side=PositionSide.LONG,
                quantity=qty,
            ),
        ]

    def should_enter(self, signal: Signal, market: MarketSnapshot) -> bool:
        return (
            signal.signal_type in (SignalType.NEUTRAL, SignalType.LOW_VOLATILITY)
            and signal.strength >= 0.5
            and market.iv_rank >= 30  # want elevated IV for better credit
        )


class IronButterfly(Strategy):
    """Sell ATM straddle + buy OTM strangle — tighter iron condor variant."""

    name = "iron_butterfly"
    description = "Neutral: max profit at one price, defined risk. Higher credit than iron condor."

    def build_legs(
        self,
        symbol: str,
        underlying_price: float,
        expiration: datetime,
        center_strike: float = 0.0,
        wing_width: float = 0.0,
        iv: float = 0.3,
        quantity: int = 1,
        **kwargs: float,
    ) -> list[OptionLeg]:
        if center_strike == 0.0:
            center_strike = round(underlying_price, 2)
        if wing_width == 0.0:
            wing_width = round(underlying_price * 0.05, 2)

        put_long_strike = center_strike - wing_width
        call_long_strike = center_strike + wing_width
        qty = int(quantity)

        return [
            # Long OTM put (lower wing)
            OptionLeg(
                contract=_make_contract(symbol, OptionType.PUT, put_long_strike, expiration, underlying_price, iv),
                side=PositionSide.LONG,
                quantity=qty,
            ),
            # Short ATM put
            OptionLeg(
                contract=_make_contract(symbol, OptionType.PUT, center_strike, expiration, underlying_price, iv),
                side=PositionSide.SHORT,
                quantity=qty,
            ),
            # Short ATM call
            OptionLeg(
                contract=_make_contract(symbol, OptionType.CALL, center_strike, expiration, underlying_price, iv),
                side=PositionSide.SHORT,
                quantity=qty,
            ),
            # Long OTM call (upper wing)
            OptionLeg(
                contract=_make_contract(symbol, OptionType.CALL, call_long_strike, expiration, underlying_price, iv),
                side=PositionSide.LONG,
                quantity=qty,
            ),
        ]

    def should_enter(self, signal: Signal, market: MarketSnapshot) -> bool:
        return (
            signal.signal_type in (SignalType.NEUTRAL, SignalType.LOW_VOLATILITY)
            and signal.strength >= 0.6
            and market.iv_rank >= 40
        )
