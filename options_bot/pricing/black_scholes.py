"""Black-Scholes option pricing model."""

from __future__ import annotations

import math
from datetime import datetime

from options_bot.models import GreeksResult, OptionType


class BlackScholes:
    """Black-Scholes pricing model for European options."""

    @staticmethod
    def _d1(s: float, k: float, t: float, r: float, sigma: float) -> float:
        """Calculate d1 parameter."""
        if t <= 0 or sigma <= 0:
            return 0.0
        return (math.log(s / k) + (r + 0.5 * sigma**2) * t) / (sigma * math.sqrt(t))

    @staticmethod
    def _d2(s: float, k: float, t: float, r: float, sigma: float) -> float:
        """Calculate d2 parameter."""
        if t <= 0 or sigma <= 0:
            return 0.0
        return BlackScholes._d1(s, k, t, r, sigma) - sigma * math.sqrt(t)

    @staticmethod
    def _norm_cdf(x: float) -> float:
        """Standard normal cumulative distribution function."""
        return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

    @staticmethod
    def _norm_pdf(x: float) -> float:
        """Standard normal probability density function."""
        return math.exp(-0.5 * x**2) / math.sqrt(2.0 * math.pi)

    @classmethod
    def price(
        cls,
        option_type: OptionType,
        s: float,
        k: float,
        t: float,
        r: float = 0.05,
        sigma: float = 0.2,
    ) -> float:
        """
        Calculate the theoretical option price.

        Args:
            option_type: CALL or PUT
            s: Current underlying price
            k: Strike price
            t: Time to expiration in years
            r: Risk-free interest rate (annualized)
            sigma: Volatility (annualized)

        Returns:
            Theoretical option price
        """
        if t <= 0:
            if option_type == OptionType.CALL:
                return max(0.0, s - k)
            return max(0.0, k - s)

        d1 = cls._d1(s, k, t, r, sigma)
        d2 = cls._d2(s, k, t, r, sigma)

        if option_type == OptionType.CALL:
            return s * cls._norm_cdf(d1) - k * math.exp(-r * t) * cls._norm_cdf(d2)
        else:
            return k * math.exp(-r * t) * cls._norm_cdf(-d2) - s * cls._norm_cdf(-d1)

    @classmethod
    def implied_volatility(
        cls,
        option_type: OptionType,
        market_price: float,
        s: float,
        k: float,
        t: float,
        r: float = 0.05,
        precision: float = 1e-6,
        max_iterations: int = 100,
    ) -> float:
        """
        Calculate implied volatility using Newton-Raphson method.

        Args:
            option_type: CALL or PUT
            market_price: Observed market price
            s: Current underlying price
            k: Strike price
            t: Time to expiration in years
            r: Risk-free interest rate
            precision: Convergence threshold
            max_iterations: Maximum solver iterations

        Returns:
            Implied volatility
        """
        if t <= 0 or market_price <= 0:
            return 0.0

        sigma = 0.3  # initial guess

        for _ in range(max_iterations):
            price = cls.price(option_type, s, k, t, r, sigma)
            vega = cls._vega_raw(s, k, t, r, sigma)

            if vega < 1e-12:
                break

            diff = price - market_price
            if abs(diff) < precision:
                return sigma

            sigma -= diff / vega
            sigma = max(0.001, min(sigma, 5.0))  # clamp

        return sigma

    @classmethod
    def _vega_raw(cls, s: float, k: float, t: float, r: float, sigma: float) -> float:
        """Raw vega for IV solver (not scaled by 100)."""
        if t <= 0 or sigma <= 0:
            return 0.0
        d1 = cls._d1(s, k, t, r, sigma)
        return s * cls._norm_pdf(d1) * math.sqrt(t)

    @classmethod
    def time_to_expiry(cls, expiration: datetime, now: datetime | None = None) -> float:
        """Convert expiration date to time in years."""
        if now is None:
            now = datetime.now()
        delta = expiration - now
        return max(0.0, delta.total_seconds() / (365.25 * 24 * 3600))
