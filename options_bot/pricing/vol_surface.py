"""Volatility surface modeling — SVI parameterization and skew analysis.

Real options aren't priced at flat vol. OTM puts are expensive (crash protection),
OTM calls are cheap. This module models the actual vol surface so we can find
mispriced contracts and exploit the variance risk premium.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from options_bot.models import OptionContract, OptionType
from options_bot.pricing.black_scholes import BlackScholes


@dataclass
class SVIParams:
    """SVI (Stochastic Volatility Inspired) parameterization.

    Total variance w(k) = a + b * (rho * (k - m) + sqrt((k - m)^2 + sigma^2))
    where k = log(K/F) is log-moneyness.
    """

    a: float = 0.04
    b: float = 0.1
    rho: float = -0.3    # negative = put skew (normal for equities)
    m: float = 0.0
    sigma: float = 0.1


class VolSurface:
    """Volatility surface for realistic pricing and edge detection."""

    def __init__(self) -> None:
        self._slices: dict[float, SVIParams] = {}

    def fit_slice(
        self,
        contracts: list[OptionContract],
        underlying_price: float,
        t: float,
        r: float = 0.05,
    ) -> SVIParams:
        """Fit SVI parameters from market-observed option prices."""
        if not contracts or t <= 0:
            return SVIParams()

        points: list[tuple[float, float]] = []
        forward = underlying_price * math.exp(r * t)

        for c in contracts:
            if c.premium <= 0 or c.strike <= 0:
                continue
            iv = BlackScholes.implied_volatility(
                c.option_type, c.premium, underlying_price, c.strike, t, r,
            )
            if 0.01 < iv < 3.0:
                k = math.log(c.strike / forward)
                total_var = iv * iv * t
                points.append((k, total_var))

        if len(points) < 3:
            params = SVIParams()
            self._slices[t] = params
            return params

        best_params = SVIParams()
        best_error = float("inf")

        for a in [0.01, 0.02, 0.04, 0.06, 0.08]:
            for b in [0.05, 0.1, 0.15, 0.2, 0.3]:
                for rho in [-0.5, -0.3, -0.1, 0.0]:
                    for sig in [0.05, 0.1, 0.2]:
                        params = SVIParams(a=a, b=b, rho=rho, m=0.0, sigma=sig)
                        error = self._svi_error(params, points)
                        if error < best_error:
                            best_error = error
                            best_params = params

        self._slices[t] = best_params
        return best_params

    def get_iv(self, strike: float, underlying: float, t: float, r: float = 0.05) -> float:
        """Get interpolated IV from the fitted surface."""
        if t <= 0:
            return 0.2
        params = self._get_nearest_slice(t)
        forward = underlying * math.exp(r * t)
        k = math.log(strike / forward)
        total_var = self._svi_total_variance(params, k)
        if total_var <= 0:
            return 0.2
        return math.sqrt(total_var / t)

    def get_skew(self, underlying: float, t: float, r: float = 0.05) -> float:
        """Measure put-call skew: IV(90%) - IV(110%). Positive = puts expensive."""
        iv_90 = self.get_iv(underlying * 0.90, underlying, t, r)
        iv_110 = self.get_iv(underlying * 1.10, underlying, t, r)
        return iv_90 - iv_110

    def find_mispriced(
        self,
        contracts: list[OptionContract],
        underlying: float,
        t: float,
        r: float = 0.05,
        threshold: float = 0.02,
    ) -> list[tuple[OptionContract, float]]:
        """Find contracts where market IV deviates from the surface.

        Positive diff = overpriced = sell candidate.
        Negative diff = underpriced = buy candidate.
        """
        mispriced: list[tuple[OptionContract, float]] = []
        for c in contracts:
            if c.premium <= 0:
                continue
            market_iv = BlackScholes.implied_volatility(
                c.option_type, c.premium, underlying, c.strike, t, r,
            )
            model_iv = self.get_iv(c.strike, underlying, t, r)
            diff = market_iv - model_iv
            if abs(diff) > threshold:
                mispriced.append((c, diff))
        mispriced.sort(key=lambda x: abs(x[1]), reverse=True)
        return mispriced

    def _svi_total_variance(self, params: SVIParams, k: float) -> float:
        inner = math.sqrt((k - params.m) ** 2 + params.sigma ** 2)
        return params.a + params.b * (params.rho * (k - params.m) + inner)

    def _svi_error(self, params: SVIParams, points: list[tuple[float, float]]) -> float:
        total = 0.0
        for k, observed_var in points:
            model_var = self._svi_total_variance(params, k)
            total += (observed_var - model_var) ** 2
        return total

    def _get_nearest_slice(self, t: float) -> SVIParams:
        if not self._slices:
            return SVIParams()
        nearest_t = min(self._slices.keys(), key=lambda x: abs(x - t))
        return self._slices[nearest_t]


class VolAnalyzer:
    """Volatility analysis — the statistical edges that make money."""

    @staticmethod
    def variance_risk_premium(prices: list[float], current_iv: float, window: int = 20) -> float:
        """THE core edge: IV - RV. Positive means IV overestimates reality.

        This is positive ~83% of the time on SPX. Selling premium captures this.
        """
        if len(prices) < window + 1 or current_iv <= 0:
            return 0.0
        returns = [math.log(prices[i] / prices[i - 1]) for i in range(len(prices) - window, len(prices))]
        rv = math.sqrt(sum(r ** 2 for r in returns) / len(returns)) * math.sqrt(252)
        return current_iv - rv

    @staticmethod
    def iv_rank(current_iv: float, iv_history: list[float]) -> float:
        """Where current IV sits in its 52-week range (0-100)."""
        if len(iv_history) < 5:
            return 50.0
        iv_min, iv_max = min(iv_history), max(iv_history)
        if iv_max == iv_min:
            return 50.0
        return ((current_iv - iv_min) / (iv_max - iv_min)) * 100

    @staticmethod
    def iv_percentile(current_iv: float, iv_history: list[float]) -> float:
        """% of days IV was lower than current (0-100)."""
        if not iv_history:
            return 50.0
        below = sum(1 for iv in iv_history if iv < current_iv)
        return (below / len(iv_history)) * 100

    @staticmethod
    def expected_move(iv: float, price: float, days: int) -> float:
        """1-sigma expected move over N days."""
        return price * iv * math.sqrt(days / 365.0)

    @staticmethod
    def prob_otm(iv: float, price: float, strike: float, days: int, opt_type: OptionType) -> float:
        """Probability of option expiring OTM — key metric for sellers."""
        if days <= 0 or iv <= 0:
            return 0.5
        t = days / 365.0
        d2 = (math.log(price / strike) + (-0.5 * iv ** 2) * t) / (iv * math.sqrt(t))
        if opt_type == OptionType.CALL:
            return BlackScholes._norm_cdf(-d2)
        return BlackScholes._norm_cdf(d2)

    @staticmethod
    def vol_regime(prices: list[float]) -> tuple[str, float, float]:
        """Detect vol regime: low_stable, low_rising, high_falling, high_unstable.

        Returns (regime, rv_10, rv_30).
        """
        if len(prices) < 31:
            return "unknown", 0.0, 0.0
        returns = [math.log(prices[i] / prices[i - 1]) for i in range(1, len(prices))]
        rv_10 = math.sqrt(252 * sum(r ** 2 for r in returns[-10:]) / 10)
        rv_30 = math.sqrt(252 * sum(r ** 2 for r in returns[-30:]) / 30)

        if rv_10 < 0.15 and rv_30 < 0.15:
            return "low_stable", rv_10, rv_30
        elif rv_10 < 0.15 and rv_30 >= 0.15:
            return "high_falling", rv_10, rv_30
        elif rv_10 >= 0.15 and rv_30 < 0.15:
            return "low_rising", rv_10, rv_30
        else:
            return "high_unstable", rv_10, rv_30
