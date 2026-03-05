"""Options trading strategies."""

from options_bot.strategies.base import Strategy, OptionLeg, OptionType, PositionSide
from options_bot.strategies.single_leg import LongCall, LongPut, ShortCall, ShortPut
from options_bot.strategies.spreads import BullCallSpread, BearPutSpread, BullPutSpread, BearCallSpread
from options_bot.strategies.multi_leg import Straddle, Strangle, IronCondor, IronButterfly

__all__ = [
    "Strategy", "OptionLeg", "OptionType", "PositionSide",
    "LongCall", "LongPut", "ShortCall", "ShortPut",
    "BullCallSpread", "BearPutSpread", "BullPutSpread", "BearCallSpread",
    "Straddle", "Strangle", "IronCondor", "IronButterfly",
]
