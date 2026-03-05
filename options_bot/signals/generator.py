"""Signal generation engine — technical analysis and volatility signals."""

from __future__ import annotations

import math
from datetime import datetime

from options_bot.data.market_data import MarketDataProvider
from options_bot.models import MarketSnapshot, Signal, SignalType


class SignalGenerator:
    """Generates trading signals from market data and technical indicators."""

    def __init__(self, data_provider: MarketDataProvider) -> None:
        self.data = data_provider

    def generate_signals(self, symbol: str) -> list[Signal]:
        """Run all signal generators for a symbol."""
        snapshot = self.data.get_snapshot(symbol)
        history = self.data.get_historical_prices(symbol, days=50)
        prices = [p for _, p in history]

        if len(prices) < 20:
            return []

        signals: list[Signal] = []

        trend_signal = self._trend_signal(symbol, prices, snapshot)
        if trend_signal:
            signals.append(trend_signal)

        momentum_signal = self._momentum_signal(symbol, prices, snapshot)
        if momentum_signal:
            signals.append(momentum_signal)

        vol_signal = self._volatility_signal(symbol, prices, snapshot)
        if vol_signal:
            signals.append(vol_signal)

        mean_rev_signal = self._mean_reversion_signal(symbol, prices, snapshot)
        if mean_rev_signal:
            signals.append(mean_rev_signal)

        return signals

    def get_best_signal(self, symbol: str) -> Signal | None:
        """Get the strongest signal for a symbol."""
        signals = self.generate_signals(symbol)
        if not signals:
            return None
        return max(signals, key=lambda s: s.strength)

    def _trend_signal(
        self, symbol: str, prices: list[float], snapshot: MarketSnapshot,
    ) -> Signal | None:
        """Moving average crossover signal."""
        sma_10 = sum(prices[-10:]) / 10
        sma_20 = sum(prices[-20:]) / 20
        sma_50 = sum(prices[-50:]) / 50 if len(prices) >= 50 else sma_20

        price = snapshot.price

        # Bullish: price > SMA10 > SMA20 > SMA50
        if price > sma_10 > sma_20:
            strength = min(1.0, (price - sma_20) / sma_20 * 10)
            return Signal(
                signal_type=SignalType.BULLISH,
                symbol=symbol,
                strength=strength,
                timestamp=datetime.now(),
                reason=f"Bullish trend: price ${price:.2f} > SMA10 ${sma_10:.2f} > SMA20 ${sma_20:.2f}",
                indicators={"sma_10": sma_10, "sma_20": sma_20, "sma_50": sma_50},
            )

        # Bearish: price < SMA10 < SMA20
        if price < sma_10 < sma_20:
            strength = min(1.0, (sma_20 - price) / sma_20 * 10)
            return Signal(
                signal_type=SignalType.BEARISH,
                symbol=symbol,
                strength=strength,
                timestamp=datetime.now(),
                reason=f"Bearish trend: price ${price:.2f} < SMA10 ${sma_10:.2f} < SMA20 ${sma_20:.2f}",
                indicators={"sma_10": sma_10, "sma_20": sma_20, "sma_50": sma_50},
            )

        return None

    def _momentum_signal(
        self, symbol: str, prices: list[float], snapshot: MarketSnapshot,
    ) -> Signal | None:
        """RSI-based momentum signal."""
        rsi = self._calculate_rsi(prices, period=14)
        if rsi is None:
            return None

        if rsi < 30:
            strength = min(1.0, (30 - rsi) / 30)
            return Signal(
                signal_type=SignalType.BULLISH,
                symbol=symbol,
                strength=strength,
                timestamp=datetime.now(),
                reason=f"Oversold: RSI {rsi:.1f}",
                indicators={"rsi": rsi},
            )

        if rsi > 70:
            strength = min(1.0, (rsi - 70) / 30)
            return Signal(
                signal_type=SignalType.BEARISH,
                symbol=symbol,
                strength=strength,
                timestamp=datetime.now(),
                reason=f"Overbought: RSI {rsi:.1f}",
                indicators={"rsi": rsi},
            )

        return None

    def _volatility_signal(
        self, symbol: str, prices: list[float], snapshot: MarketSnapshot,
    ) -> Signal | None:
        """Historical vs implied volatility signal."""
        returns = [(prices[i] - prices[i - 1]) / prices[i - 1] for i in range(1, len(prices))]
        if len(returns) < 10:
            return None

        hv = math.sqrt(252) * (sum(r**2 for r in returns[-20:]) / len(returns[-20:])) ** 0.5
        iv_rank = snapshot.iv_rank

        if iv_rank > 60:
            strength = min(1.0, (iv_rank - 50) / 50)
            return Signal(
                signal_type=SignalType.HIGH_VOLATILITY,
                symbol=symbol,
                strength=strength,
                timestamp=datetime.now(),
                reason=f"Elevated IV: rank {iv_rank:.0f}, HV {hv:.2%}",
                indicators={"iv_rank": iv_rank, "hv_20": hv},
            )

        if iv_rank < 30:
            strength = min(1.0, (40 - iv_rank) / 40)
            return Signal(
                signal_type=SignalType.LOW_VOLATILITY,
                symbol=symbol,
                strength=strength,
                timestamp=datetime.now(),
                reason=f"Low IV: rank {iv_rank:.0f}, HV {hv:.2%}",
                indicators={"iv_rank": iv_rank, "hv_20": hv},
            )

        return None

    def _mean_reversion_signal(
        self, symbol: str, prices: list[float], snapshot: MarketSnapshot,
    ) -> Signal | None:
        """Bollinger Band mean reversion signal."""
        sma_20 = sum(prices[-20:]) / 20
        std_20 = (sum((p - sma_20) ** 2 for p in prices[-20:]) / 20) ** 0.5
        upper_band = sma_20 + 2 * std_20
        lower_band = sma_20 - 2 * std_20
        price = snapshot.price

        if price < lower_band:
            distance = (lower_band - price) / std_20 if std_20 > 0 else 0
            strength = min(1.0, distance * 0.4)
            return Signal(
                signal_type=SignalType.BULLISH,
                symbol=symbol,
                strength=strength,
                timestamp=datetime.now(),
                reason=f"Below lower Bollinger Band: ${price:.2f} < ${lower_band:.2f}",
                indicators={"bb_upper": upper_band, "bb_lower": lower_band, "bb_sma": sma_20},
            )

        if price > upper_band:
            distance = (price - upper_band) / std_20 if std_20 > 0 else 0
            strength = min(1.0, distance * 0.4)
            return Signal(
                signal_type=SignalType.BEARISH,
                symbol=symbol,
                strength=strength,
                timestamp=datetime.now(),
                reason=f"Above upper Bollinger Band: ${price:.2f} > ${upper_band:.2f}",
                indicators={"bb_upper": upper_band, "bb_lower": lower_band, "bb_sma": sma_20},
            )

        return None

    @staticmethod
    def _calculate_rsi(prices: list[float], period: int = 14) -> float | None:
        """Calculate RSI."""
        if len(prices) < period + 1:
            return None

        changes = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
        recent = changes[-period:]

        gains = [c for c in recent if c > 0]
        losses = [-c for c in recent if c < 0]

        avg_gain = sum(gains) / period if gains else 0.0
        avg_loss = sum(losses) / period if losses else 0.0001

        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))
