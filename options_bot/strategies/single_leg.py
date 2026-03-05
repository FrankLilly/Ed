"""Single-leg option strategies: long/short calls and puts."""

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


class LongCall(Strategy):
    """Buy a call option — bullish directional bet."""

    name = "long_call"
    description = "Bullish: unlimited upside, risk limited to premium paid."

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
            strike = round(underlying_price * 1.02, 2)  # slightly OTM
        as_of = kwargs.get("as_of")  # type: ignore[arg-type]
        t = BlackScholes.time_to_expiry(expiration, now=as_of)
        premium = BlackScholes.price(OptionType.CALL, underlying_price, strike, t, sigma=iv)
        contract = OptionContract(
            symbol=symbol,
            option_type=OptionType.CALL,
            strike=strike,
            expiration=expiration,
            premium=premium,
            underlying_price=underlying_price,
            implied_volatility=iv,
        )
        return [OptionLeg(contract=contract, side=PositionSide.LONG, quantity=int(quantity))]

    def should_enter(self, signal: Signal, market: MarketSnapshot) -> bool:
        return signal.signal_type == SignalType.BULLISH and signal.strength >= 0.6


class LongPut(Strategy):
    """Buy a put option — bearish directional bet."""

    name = "long_put"
    description = "Bearish: profits when underlying drops, risk limited to premium paid."

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
            strike = round(underlying_price * 0.98, 2)  # slightly OTM
        as_of = kwargs.get("as_of")  # type: ignore[arg-type]
        t = BlackScholes.time_to_expiry(expiration, now=as_of)
        premium = BlackScholes.price(OptionType.PUT, underlying_price, strike, t, sigma=iv)
        contract = OptionContract(
            symbol=symbol,
            option_type=OptionType.PUT,
            strike=strike,
            expiration=expiration,
            premium=premium,
            underlying_price=underlying_price,
            implied_volatility=iv,
        )
        return [OptionLeg(contract=contract, side=PositionSide.LONG, quantity=int(quantity))]

    def should_enter(self, signal: Signal, market: MarketSnapshot) -> bool:
        return signal.signal_type == SignalType.BEARISH and signal.strength >= 0.6


class ShortCall(Strategy):
    """Sell a naked call — collect premium, bearish/neutral bias."""

    name = "short_call"
    description = "Neutral/bearish: collect premium, unlimited risk if underlying rises."

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
            strike = round(underlying_price * 1.05, 2)  # OTM
        as_of = kwargs.get("as_of")  # type: ignore[arg-type]
        t = BlackScholes.time_to_expiry(expiration, now=as_of)
        premium = BlackScholes.price(OptionType.CALL, underlying_price, strike, t, sigma=iv)
        contract = OptionContract(
            symbol=symbol,
            option_type=OptionType.CALL,
            strike=strike,
            expiration=expiration,
            premium=premium,
            underlying_price=underlying_price,
            implied_volatility=iv,
        )
        return [OptionLeg(contract=contract, side=PositionSide.SHORT, quantity=int(quantity))]

    def should_enter(self, signal: Signal, market: MarketSnapshot) -> bool:
        return signal.signal_type in (SignalType.BEARISH, SignalType.NEUTRAL) and signal.strength >= 0.5


class ShortPut(Strategy):
    """Sell a naked put — collect premium, bullish/neutral bias."""

    name = "short_put"
    description = "Neutral/bullish: collect premium, risk if underlying drops."

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
            strike = round(underlying_price * 0.95, 2)  # OTM
        as_of = kwargs.get("as_of")  # type: ignore[arg-type]
        t = BlackScholes.time_to_expiry(expiration, now=as_of)
        premium = BlackScholes.price(OptionType.PUT, underlying_price, strike, t, sigma=iv)
        contract = OptionContract(
            symbol=symbol,
            option_type=OptionType.PUT,
            strike=strike,
            expiration=expiration,
            premium=premium,
            underlying_price=underlying_price,
            implied_volatility=iv,
        )
        return [OptionLeg(contract=contract, side=PositionSide.SHORT, quantity=int(quantity))]

    def should_enter(self, signal: Signal, market: MarketSnapshot) -> bool:
        return signal.signal_type in (SignalType.BULLISH, SignalType.NEUTRAL) and signal.strength >= 0.5
