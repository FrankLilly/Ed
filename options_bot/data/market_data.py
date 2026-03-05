"""Market data provider — abstract interface with implementations."""

from __future__ import annotations

import json
import math
import random
from abc import ABC, abstractmethod
from datetime import datetime, timedelta

from options_bot.models import MarketSnapshot, OptionContract, OptionType


class MarketDataProvider(ABC):
    """Abstract market data interface."""

    @abstractmethod
    def get_snapshot(self, symbol: str) -> MarketSnapshot:
        """Get current market snapshot for a symbol."""

    @abstractmethod
    def get_option_chain(
        self,
        symbol: str,
        expiration: datetime,
        option_type: OptionType | None = None,
    ) -> list[OptionContract]:
        """Get available option contracts."""

    @abstractmethod
    def get_expirations(self, symbol: str) -> list[datetime]:
        """Get available expiration dates."""

    @abstractmethod
    def get_historical_prices(
        self,
        symbol: str,
        days: int = 30,
    ) -> list[tuple[datetime, float]]:
        """Get historical daily closing prices."""


class AlpacaMarketData(MarketDataProvider):
    """Market data from Alpaca API (supports paper and live)."""

    def __init__(self, api_key: str, secret_key: str, paper: bool = True) -> None:
        self.api_key = api_key
        self.secret_key = secret_key
        self.base_url = (
            "https://paper-api.alpaca.markets" if paper
            else "https://api.alpaca.markets"
        )
        self.data_url = "https://data.alpaca.markets"
        self._session = None

    def _get_session(self):  # noqa: ANN202
        """Lazy-init HTTP session."""
        if self._session is None:
            import urllib.request
            self._session = True  # placeholder — real impl uses requests
        return self._session

    def _headers(self) -> dict[str, str]:
        return {
            "APCA-API-KEY-ID": self.api_key,
            "APCA-API-SECRET-KEY": self.secret_key,
        }

    def get_snapshot(self, symbol: str) -> MarketSnapshot:
        """Get real-time snapshot via Alpaca data API."""
        import urllib.request

        url = f"{self.data_url}/v2/stocks/{symbol}/snapshot"
        req = urllib.request.Request(url, headers=self._headers())
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode())

        bar = data.get("dailyBar", {})
        trade = data.get("latestTrade", {})
        return MarketSnapshot(
            symbol=symbol,
            price=trade.get("p", 0.0),
            timestamp=datetime.now(),
            high=bar.get("h", 0.0),
            low=bar.get("l", 0.0),
            open=bar.get("o", 0.0),
            close=bar.get("c", 0.0),
            volume=bar.get("v", 0),
        )

    def get_option_chain(
        self,
        symbol: str,
        expiration: datetime,
        option_type: OptionType | None = None,
    ) -> list[OptionContract]:
        """Get options chain from Alpaca."""
        import urllib.request

        exp_str = expiration.strftime("%Y-%m-%d")
        url = f"{self.data_url}/v1beta1/options/snapshots/{symbol}?expiration_date={exp_str}"
        if option_type:
            url += f"&type={option_type.value}"

        req = urllib.request.Request(url, headers=self._headers())
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode())

        contracts: list[OptionContract] = []
        for snapshot in data.get("snapshots", {}).values():
            greeks = snapshot.get("greeks", {})
            quote = snapshot.get("latestQuote", {})
            trade = snapshot.get("latestTrade", {})

            opt_type_str = snapshot.get("details", {}).get("type", "call")
            contracts.append(OptionContract(
                symbol=symbol,
                option_type=OptionType.CALL if opt_type_str == "call" else OptionType.PUT,
                strike=float(snapshot.get("details", {}).get("strike_price", 0)),
                expiration=expiration,
                premium=float(trade.get("p", 0)),
                underlying_price=0.0,  # filled by caller
                implied_volatility=float(greeks.get("implied_volatility", 0)),
                open_interest=int(snapshot.get("openInterest", 0)),
                volume=int(trade.get("s", 0)),
                bid=float(quote.get("bp", 0)),
                ask=float(quote.get("ap", 0)),
            ))
        return contracts

    def get_expirations(self, symbol: str) -> list[datetime]:
        """Get available expirations — Alpaca provides this in options chain."""
        # Alpaca doesn't have a dedicated expirations endpoint;
        # generate standard monthly/weekly expirations as fallback
        expirations: list[datetime] = []
        today = datetime.now()
        for weeks in range(1, 9):
            exp = today + timedelta(weeks=weeks)
            # Align to Friday
            days_until_friday = (4 - exp.weekday()) % 7
            exp += timedelta(days=days_until_friday)
            expirations.append(exp.replace(hour=16, minute=0, second=0, microsecond=0))
        return expirations

    def get_historical_prices(
        self,
        symbol: str,
        days: int = 30,
    ) -> list[tuple[datetime, float]]:
        """Get historical bars from Alpaca."""
        import urllib.request

        end = datetime.now()
        start = end - timedelta(days=days)
        url = (
            f"{self.data_url}/v2/stocks/{symbol}/bars"
            f"?start={start.strftime('%Y-%m-%d')}"
            f"&end={end.strftime('%Y-%m-%d')}"
            f"&timeframe=1Day"
        )
        req = urllib.request.Request(url, headers=self._headers())
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode())

        prices: list[tuple[datetime, float]] = []
        for bar in data.get("bars", []):
            ts = datetime.fromisoformat(bar["t"].replace("Z", "+00:00"))
            prices.append((ts, bar["c"]))
        return prices


class SimulatedMarketData(MarketDataProvider):
    """Simulated market data for paper trading and testing."""

    def __init__(self, base_prices: dict[str, float] | None = None) -> None:
        self.base_prices = base_prices or {"SPY": 450.0, "QQQ": 380.0, "AAPL": 175.0, "TSLA": 250.0}

    def get_snapshot(self, symbol: str) -> MarketSnapshot:
        base = self.base_prices.get(symbol, 100.0)
        jitter = base * random.uniform(-0.01, 0.01)
        price = base + jitter
        return MarketSnapshot(
            symbol=symbol,
            price=round(price, 2),
            timestamp=datetime.now(),
            high=round(price * 1.01, 2),
            low=round(price * 0.99, 2),
            open=round(base, 2),
            close=round(price, 2),
            volume=random.randint(1_000_000, 50_000_000),
            historical_volatility=random.uniform(0.15, 0.45),
            iv_rank=random.uniform(20, 80),
            iv_percentile=random.uniform(20, 80),
        )

    def get_option_chain(
        self,
        symbol: str,
        expiration: datetime,
        option_type: OptionType | None = None,
    ) -> list[OptionContract]:
        from options_bot.pricing.black_scholes import BlackScholes

        snapshot = self.get_snapshot(symbol)
        price = snapshot.price
        t = BlackScholes.time_to_expiry(expiration)
        contracts: list[OptionContract] = []

        strikes = [round(price * (0.85 + i * 0.025), 2) for i in range(13)]
        types = [option_type] if option_type else [OptionType.CALL, OptionType.PUT]

        for strike in strikes:
            iv = random.uniform(0.18, 0.50)
            for ot in types:
                premium = BlackScholes.price(ot, price, strike, t, sigma=iv)
                contracts.append(OptionContract(
                    symbol=symbol,
                    option_type=ot,
                    strike=strike,
                    expiration=expiration,
                    premium=round(premium, 2),
                    underlying_price=price,
                    implied_volatility=iv,
                    open_interest=random.randint(100, 10000),
                    volume=random.randint(50, 5000),
                    bid=round(premium * 0.95, 2),
                    ask=round(premium * 1.05, 2),
                ))
        return contracts

    def get_expirations(self, symbol: str) -> list[datetime]:
        expirations: list[datetime] = []
        today = datetime.now()
        for weeks in range(1, 9):
            exp = today + timedelta(weeks=weeks)
            days_until_friday = (4 - exp.weekday()) % 7
            exp += timedelta(days=days_until_friday)
            expirations.append(exp.replace(hour=16, minute=0, second=0, microsecond=0))
        return expirations

    def get_historical_prices(
        self,
        symbol: str,
        days: int = 30,
    ) -> list[tuple[datetime, float]]:
        base = self.base_prices.get(symbol, 100.0)
        prices: list[tuple[datetime, float]] = []
        price = base * 0.95
        for i in range(days):
            price += price * random.gauss(0.0005, 0.015)
            dt = datetime.now() - timedelta(days=days - i)
            prices.append((dt, round(price, 2)))
        return prices
