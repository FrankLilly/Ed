"""Unusual options activity / flow scanner.

Smart money leaves footprints in the options market. Large unusual trades
signal institutional conviction. We piggyback on their research.

Key signals:
- Unusual volume: volume >> open interest on a strike = new positions
- Large sweeps: aggressive multi-exchange fills = urgency
- Put/call ratio extremes: contrarian indicator
- Dark pool prints: block trades at odd sizes
"""

from __future__ import annotations

import logging
from datetime import datetime
from dataclasses import dataclass

from options_bot.data.market_data import MarketDataProvider
from options_bot.models import OptionContract, OptionType, Signal, SignalType

logger = logging.getLogger(__name__)


@dataclass
class UnusualActivity:
    """A detected unusual options activity event."""

    symbol: str
    option_type: OptionType
    strike: float
    expiration: datetime
    volume: int
    open_interest: int
    vol_oi_ratio: float  # volume / open interest
    premium_traded: float  # total $ premium
    side_estimate: str  # "bought" or "sold" based on trade price vs mid
    timestamp: datetime


class FlowScanner:
    """Scan for unusual options activity that signals institutional conviction."""

    def __init__(self, data_provider: MarketDataProvider) -> None:
        self.data = data_provider

    def scan_unusual_activity(
        self,
        symbol: str,
        min_vol_oi_ratio: float = 3.0,
        min_premium: float = 50_000,
    ) -> list[UnusualActivity]:
        """Find contracts with unusual volume relative to open interest.

        Vol/OI > 3 means 3x more contracts traded today than exist —
        new positions being opened aggressively.
        """
        expirations = self.data.get_expirations(symbol)
        unusual: list[UnusualActivity] = []

        for exp in expirations[:4]:  # scan near-term expirations
            chain = self.data.get_option_chain(symbol, exp)
            for contract in chain:
                if contract.open_interest <= 0 or contract.volume <= 0:
                    continue

                vol_oi = contract.volume / contract.open_interest
                premium = contract.volume * contract.mid_price * 100

                if vol_oi >= min_vol_oi_ratio and premium >= min_premium:
                    # Estimate if bought or sold based on price location
                    if contract.bid > 0 and contract.ask > 0:
                        mid = contract.mid_price
                        if contract.premium >= mid:
                            side = "bought"  # paid at/above mid = aggressive buy
                        else:
                            side = "sold"
                    else:
                        side = "unknown"

                    unusual.append(UnusualActivity(
                        symbol=symbol,
                        option_type=contract.option_type,
                        strike=contract.strike,
                        expiration=exp,
                        volume=contract.volume,
                        open_interest=contract.open_interest,
                        vol_oi_ratio=vol_oi,
                        premium_traded=premium,
                        side_estimate=side,
                        timestamp=datetime.now(),
                    ))

        # Sort by premium size (biggest bets first)
        unusual.sort(key=lambda x: x.premium_traded, reverse=True)
        return unusual

    def generate_flow_signal(
        self,
        symbol: str,
        min_vol_oi_ratio: float = 3.0,
        min_premium: float = 50_000,
    ) -> Signal | None:
        """Convert unusual activity into a trading signal.

        Heavy call buying = bullish institutional bet
        Heavy put buying = bearish hedge or directional bet
        Heavy put selling = bullish (selling insurance = expecting calm)
        """
        activities = self.scan_unusual_activity(symbol, min_vol_oi_ratio, min_premium)
        if not activities:
            return None

        # Aggregate the flow
        call_bought = sum(a.premium_traded for a in activities
                         if a.option_type == OptionType.CALL and a.side_estimate == "bought")
        call_sold = sum(a.premium_traded for a in activities
                        if a.option_type == OptionType.CALL and a.side_estimate == "sold")
        put_bought = sum(a.premium_traded for a in activities
                         if a.option_type == OptionType.PUT and a.side_estimate == "bought")
        put_sold = sum(a.premium_traded for a in activities
                        if a.option_type == OptionType.PUT and a.side_estimate == "sold")

        total_flow = call_bought + call_sold + put_bought + put_sold
        if total_flow == 0:
            return None

        net_call_flow = call_bought - call_sold
        net_put_flow = put_bought - put_sold

        # Bullish flow: net call buying or net put selling
        if net_call_flow > 0 and net_call_flow > abs(net_put_flow):
            strength = min(1.0, net_call_flow / 500_000)
            return Signal(
                signal_type=SignalType.BULLISH,
                symbol=symbol,
                strength=max(0.4, strength),
                timestamp=datetime.now(),
                reason=f"Unusual call buying: ${net_call_flow:,.0f} net call flow",
                indicators={
                    "net_call_flow": net_call_flow,
                    "net_put_flow": net_put_flow,
                    "total_flow": total_flow,
                    "num_unusual": len(activities),
                    "edge": "follow_flow",
                },
            )

        # Bearish flow: net put buying
        if net_put_flow > 0 and net_put_flow > abs(net_call_flow):
            strength = min(1.0, net_put_flow / 500_000)
            return Signal(
                signal_type=SignalType.BEARISH,
                symbol=symbol,
                strength=max(0.4, strength),
                timestamp=datetime.now(),
                reason=f"Unusual put buying: ${net_put_flow:,.0f} net put flow",
                indicators={
                    "net_call_flow": net_call_flow,
                    "net_put_flow": net_put_flow,
                    "total_flow": total_flow,
                    "num_unusual": len(activities),
                    "edge": "follow_flow",
                },
            )

        return None

    def put_call_ratio(self, symbol: str) -> float | None:
        """Calculate the put/call ratio from volume across all expirations.

        P/C > 1.2 = bearish sentiment (contrarian bullish)
        P/C < 0.6 = bullish complacency (contrarian bearish)
        """
        expirations = self.data.get_expirations(symbol)
        total_call_vol = 0
        total_put_vol = 0

        for exp in expirations[:4]:
            chain = self.data.get_option_chain(symbol, exp)
            for c in chain:
                if c.option_type == OptionType.CALL:
                    total_call_vol += c.volume
                else:
                    total_put_vol += c.volume

        if total_call_vol == 0:
            return None
        return total_put_vol / total_call_vol
