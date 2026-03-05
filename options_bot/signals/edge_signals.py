"""Edge-based signal generation — the actual money-making signals.

Core edges in options:
1. IV overstatement: implied vol > realized vol ~83% of the time on SPY
2. Variance risk premium: selling vol is systematically profitable
3. Put skew richness: OTM puts are chronically overpriced
4. IV rank mean reversion: high IV rank reverts → sell premium
5. Earnings IV crush: IV spikes before earnings, collapses after
6. Term structure: backwardation = fear = opportunity
"""

from __future__ import annotations

import math
from datetime import datetime

from options_bot.data.market_data import MarketDataProvider
from options_bot.models import MarketSnapshot, Signal, SignalType
from options_bot.pricing.vol_surface import VolSurface, VolAnalyzer
from options_bot.pricing.black_scholes import BlackScholes


class EdgeSignalGenerator:
    """Signals based on real statistical edges, not textbook indicators."""

    def __init__(self, data_provider: MarketDataProvider) -> None:
        self.data = data_provider
        self.vol_surface = VolSurface()

    def generate_signals(self, symbol: str) -> list[Signal]:
        """Run all edge detectors for a symbol."""
        snapshot = self.data.get_snapshot(symbol)
        history = self.data.get_historical_prices(symbol, days=60)
        prices = [p for _, p in history]

        if len(prices) < 20:
            return []

        signals: list[Signal] = []

        for fn in [
            self._variance_risk_premium,
            self._iv_rank_mean_reversion,
            self._skew_signal,
            self._term_structure_signal,
            self._volatility_regime,
        ]:
            sig = fn(symbol, prices, snapshot)
            if sig:
                signals.append(sig)

        return signals

    def get_best_signal(self, symbol: str) -> Signal | None:
        signals = self.generate_signals(symbol)
        if not signals:
            return None
        return max(signals, key=lambda s: s.strength)

    def _variance_risk_premium(
        self, symbol: str, prices: list[float], snapshot: MarketSnapshot,
    ) -> Signal | None:
        """THE core edge: IV almost always overstates realized vol.

        When IV >> RV, sell premium. Works ~83% of the time on major indices.
        """
        iv = snapshot.historical_volatility if snapshot.historical_volatility > 0 else 0.25
        vrp = VolAnalyzer.variance_risk_premium(prices, iv)

        if vrp > 0.03:
            strength = min(1.0, vrp / 0.15)
            return Signal(
                signal_type=SignalType.HIGH_VOLATILITY,
                symbol=symbol,
                strength=strength,
                timestamp=datetime.now(),
                reason=f"VRP edge: IV overestimates RV by {vrp:.1%} — sell premium",
                indicators={"vrp": vrp, "implied_vol": iv, "edge": "sell_premium"},
            )

        if vrp < -0.05:
            strength = min(1.0, abs(vrp) / 0.15)
            return Signal(
                signal_type=SignalType.LOW_VOLATILITY,
                symbol=symbol,
                strength=strength,
                timestamp=datetime.now(),
                reason=f"Cheap vol: IV underestimates RV by {abs(vrp):.1%} — buy premium",
                indicators={"vrp": vrp, "implied_vol": iv, "edge": "buy_premium"},
            )

        return None

    def _iv_rank_mean_reversion(
        self, symbol: str, prices: list[float], snapshot: MarketSnapshot,
    ) -> Signal | None:
        """IV rank mean reverts. High IV rank = sell premium.

        This is the #1 filter professional vol sellers use.
        """
        iv_rank = snapshot.iv_rank

        if iv_rank >= 50:
            strength = min(1.0, (iv_rank - 40) / 60)
            return Signal(
                signal_type=SignalType.HIGH_VOLATILITY,
                symbol=symbol,
                strength=strength,
                timestamp=datetime.now(),
                reason=f"High IV Rank {iv_rank:.0f} — premium rich, sell vol",
                indicators={"iv_rank": iv_rank, "edge": "sell_premium"},
            )

        if iv_rank <= 20:
            strength = min(1.0, (30 - iv_rank) / 30)
            return Signal(
                signal_type=SignalType.LOW_VOLATILITY,
                symbol=symbol,
                strength=strength,
                timestamp=datetime.now(),
                reason=f"Low IV Rank {iv_rank:.0f} — premium cheap",
                indicators={"iv_rank": iv_rank, "edge": "buy_premium"},
            )

        return None

    def _skew_signal(
        self, symbol: str, prices: list[float], snapshot: MarketSnapshot,
    ) -> Signal | None:
        """When put skew is steep, OTM puts are extra rich — sell put spreads."""
        price = snapshot.price
        expirations = self.data.get_expirations(symbol)
        if not expirations:
            return None

        target_exp = None
        for exp in expirations:
            dte = (exp - datetime.now()).days
            if 25 <= dte <= 40:
                target_exp = exp
                break
        if target_exp is None:
            return None

        chain = self.data.get_option_chain(symbol, target_exp)
        if len(chain) < 5:
            return None

        t = BlackScholes.time_to_expiry(target_exp)
        self.vol_surface.fit_slice(chain, price, t)
        skew = self.vol_surface.get_skew(price, t)

        if skew > 0.05:
            strength = min(1.0, (skew - 0.03) / 0.12)
            return Signal(
                signal_type=SignalType.NEUTRAL,
                symbol=symbol,
                strength=strength,
                timestamp=datetime.now(),
                reason=f"Steep put skew ({skew:.1%}) — OTM puts are rich, sell put spreads",
                indicators={"skew": skew, "edge": "sell_put_spread"},
            )

        return None

    def _term_structure_signal(
        self, symbol: str, prices: list[float], snapshot: MarketSnapshot,
    ) -> Signal | None:
        """IV term structure: backwardation = fear = sell front-month premium."""
        expirations = self.data.get_expirations(symbol)
        if len(expirations) < 2:
            return None

        price = snapshot.price
        front_chain = self.data.get_option_chain(symbol, expirations[0])
        back_chain = self.data.get_option_chain(symbol, expirations[-1])

        front_iv = self._atm_iv(front_chain, price)
        back_iv = self._atm_iv(back_chain, price)

        if front_iv <= 0 or back_iv <= 0:
            return None

        term_spread = front_iv - back_iv

        if term_spread > 0.03:
            strength = min(1.0, term_spread / 0.10)
            return Signal(
                signal_type=SignalType.HIGH_VOLATILITY,
                symbol=symbol,
                strength=strength,
                timestamp=datetime.now(),
                reason=f"IV backwardation: front {front_iv:.1%} > back {back_iv:.1%} — sell front-month",
                indicators={
                    "front_iv": front_iv,
                    "back_iv": back_iv,
                    "term_spread": term_spread,
                    "edge": "sell_front_month",
                },
            )

        return None

    def _volatility_regime(
        self, symbol: str, prices: list[float], snapshot: MarketSnapshot,
    ) -> Signal | None:
        """Detect vol regime for position sizing.

        low_stable = best for selling premium aggressively
        high_falling = sell premium with wider wings
        high_unstable = reduce size or stay out
        """
        regime, rv_10, rv_30 = VolAnalyzer.vol_regime(prices)

        if regime == "low_stable":
            strength = min(1.0, (0.20 - rv_10) / 0.10) if rv_10 < 0.20 else 0.4
            return Signal(
                signal_type=SignalType.NEUTRAL,
                symbol=symbol,
                strength=max(0.5, strength),
                timestamp=datetime.now(),
                reason=f"Stable low vol regime: RV10={rv_10:.1%}, RV30={rv_30:.1%} — sell premium",
                indicators={"rv_10": rv_10, "rv_30": rv_30, "regime": regime, "edge": "sell_premium"},
            )

        if regime == "high_falling":
            return Signal(
                signal_type=SignalType.HIGH_VOLATILITY,
                symbol=symbol,
                strength=0.6,
                timestamp=datetime.now(),
                reason=f"Vol falling: RV10={rv_10:.1%} < RV30={rv_30:.1%} — sell premium (wide wings)",
                indicators={"rv_10": rv_10, "rv_30": rv_30, "regime": regime, "edge": "sell_premium_wide"},
            )

        return None

    @staticmethod
    def _atm_iv(chain: list[OptionContract], price: float) -> float:
        if not chain:
            return 0.0
        atm = min(chain, key=lambda c: abs(c.strike - price))
        return atm.implied_volatility if atm.implied_volatility > 0 else 0.0
