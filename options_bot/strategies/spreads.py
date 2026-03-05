"""Vertical spread strategies: bull/bear call and put spreads."""

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


def _make_contract(
    symbol: str,
    opt_type: OptionType,
    strike: float,
    expiration: datetime,
    underlying_price: float,
    iv: float,
    as_of: datetime | None = None,
) -> OptionContract:
    t = BlackScholes.time_to_expiry(expiration, now=as_of)
    premium = BlackScholes.price(opt_type, underlying_price, strike, t, sigma=iv)
    return OptionContract(
        symbol=symbol,
        option_type=opt_type,
        strike=strike,
        expiration=expiration,
        premium=premium,
        underlying_price=underlying_price,
        implied_volatility=iv,
    )


class BullCallSpread(Strategy):
    """Buy lower strike call, sell higher strike call — debit spread, bullish."""

    name = "bull_call_spread"
    description = "Bullish: capped profit, capped risk. Net debit."

    def build_legs(
        self,
        symbol: str,
        underlying_price: float,
        expiration: datetime,
        long_strike: float = 0.0,
        short_strike: float = 0.0,
        iv: float = 0.3,
        quantity: int = 1,
        **kwargs: float,
    ) -> list[OptionLeg]:
        if long_strike == 0.0:
            long_strike = round(underlying_price * 0.98, 2)
        if short_strike == 0.0:
            short_strike = round(underlying_price * 1.05, 2)

        as_of = kwargs.get("as_of")  # type: ignore[arg-type]
        long_contract = _make_contract(symbol, OptionType.CALL, long_strike, expiration, underlying_price, iv, as_of=as_of)
        short_contract = _make_contract(symbol, OptionType.CALL, short_strike, expiration, underlying_price, iv, as_of=as_of)

        return [
            OptionLeg(contract=long_contract, side=PositionSide.LONG, quantity=int(quantity)),
            OptionLeg(contract=short_contract, side=PositionSide.SHORT, quantity=int(quantity)),
        ]

    def should_enter(self, signal: Signal, market: MarketSnapshot) -> bool:
        return signal.signal_type == SignalType.BULLISH and signal.strength >= 0.5


class BearPutSpread(Strategy):
    """Buy higher strike put, sell lower strike put — debit spread, bearish."""

    name = "bear_put_spread"
    description = "Bearish: capped profit, capped risk. Net debit."

    def build_legs(
        self,
        symbol: str,
        underlying_price: float,
        expiration: datetime,
        long_strike: float = 0.0,
        short_strike: float = 0.0,
        iv: float = 0.3,
        quantity: int = 1,
        **kwargs: float,
    ) -> list[OptionLeg]:
        if long_strike == 0.0:
            long_strike = round(underlying_price * 1.02, 2)
        if short_strike == 0.0:
            short_strike = round(underlying_price * 0.95, 2)

        as_of = kwargs.get("as_of")  # type: ignore[arg-type]
        long_contract = _make_contract(symbol, OptionType.PUT, long_strike, expiration, underlying_price, iv, as_of=as_of)
        short_contract = _make_contract(symbol, OptionType.PUT, short_strike, expiration, underlying_price, iv, as_of=as_of)

        return [
            OptionLeg(contract=long_contract, side=PositionSide.LONG, quantity=int(quantity)),
            OptionLeg(contract=short_contract, side=PositionSide.SHORT, quantity=int(quantity)),
        ]

    def should_enter(self, signal: Signal, market: MarketSnapshot) -> bool:
        return signal.signal_type == SignalType.BEARISH and signal.strength >= 0.5


class BullPutSpread(Strategy):
    """Sell higher strike put, buy lower strike put — credit spread, bullish."""

    name = "bull_put_spread"
    description = "Bullish: collect credit, capped risk. Net credit."

    def build_legs(
        self,
        symbol: str,
        underlying_price: float,
        expiration: datetime,
        short_strike: float = 0.0,
        long_strike: float = 0.0,
        iv: float = 0.3,
        quantity: int = 1,
        **kwargs: float,
    ) -> list[OptionLeg]:
        if short_strike == 0.0:
            short_strike = round(underlying_price * 0.97, 2)
        if long_strike == 0.0:
            long_strike = round(underlying_price * 0.92, 2)

        short_contract = _make_contract(symbol, OptionType.PUT, short_strike, expiration, underlying_price, iv)
        long_contract = _make_contract(symbol, OptionType.PUT, long_strike, expiration, underlying_price, iv)

        return [
            OptionLeg(contract=short_contract, side=PositionSide.SHORT, quantity=int(quantity)),
            OptionLeg(contract=long_contract, side=PositionSide.LONG, quantity=int(quantity)),
        ]

    def should_enter(self, signal: Signal, market: MarketSnapshot) -> bool:
        return signal.signal_type == SignalType.BULLISH and signal.strength >= 0.4


class BearCallSpread(Strategy):
    """Sell lower strike call, buy higher strike call — credit spread, bearish."""

    name = "bear_call_spread"
    description = "Bearish: collect credit, capped risk. Net credit."

    def build_legs(
        self,
        symbol: str,
        underlying_price: float,
        expiration: datetime,
        short_strike: float = 0.0,
        long_strike: float = 0.0,
        iv: float = 0.3,
        quantity: int = 1,
        **kwargs: float,
    ) -> list[OptionLeg]:
        if short_strike == 0.0:
            short_strike = round(underlying_price * 1.03, 2)
        if long_strike == 0.0:
            long_strike = round(underlying_price * 1.08, 2)

        short_contract = _make_contract(symbol, OptionType.CALL, short_strike, expiration, underlying_price, iv)
        long_contract = _make_contract(symbol, OptionType.CALL, long_strike, expiration, underlying_price, iv)

        return [
            OptionLeg(contract=short_contract, side=PositionSide.SHORT, quantity=int(quantity)),
            OptionLeg(contract=long_contract, side=PositionSide.LONG, quantity=int(quantity)),
        ]

    def should_enter(self, signal: Signal, market: MarketSnapshot) -> bool:
        return signal.signal_type == SignalType.BEARISH and signal.strength >= 0.4
