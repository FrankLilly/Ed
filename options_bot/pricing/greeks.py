"""Options Greeks calculations."""

from __future__ import annotations

import math

from options_bot.models import GreeksResult, OptionContract, OptionLeg, OptionType
from options_bot.pricing.black_scholes import BlackScholes


class Greeks:
    """Calculate option Greeks using the Black-Scholes model."""

    @classmethod
    def calculate(
        cls,
        option_type: OptionType,
        s: float,
        k: float,
        t: float,
        r: float = 0.05,
        sigma: float = 0.2,
    ) -> GreeksResult:
        """
        Calculate all Greeks for an option.

        Args:
            option_type: CALL or PUT
            s: Underlying price
            k: Strike price
            t: Time to expiration in years
            r: Risk-free rate
            sigma: Volatility

        Returns:
            GreeksResult with all Greeks
        """
        if t <= 0 or sigma <= 0:
            return GreeksResult()

        d1 = BlackScholes._d1(s, k, t, r, sigma)
        d2 = BlackScholes._d2(s, k, t, r, sigma)
        sqrt_t = math.sqrt(t)
        norm_pdf_d1 = BlackScholes._norm_pdf(d1)
        norm_cdf_d1 = BlackScholes._norm_cdf(d1)
        norm_cdf_d2 = BlackScholes._norm_cdf(d2)
        discount = math.exp(-r * t)

        # Delta
        if option_type == OptionType.CALL:
            delta = norm_cdf_d1
        else:
            delta = norm_cdf_d1 - 1.0

        # Gamma (same for calls and puts)
        gamma = norm_pdf_d1 / (s * sigma * sqrt_t)

        # Theta (per calendar day)
        theta_common = -(s * norm_pdf_d1 * sigma) / (2.0 * sqrt_t)
        if option_type == OptionType.CALL:
            theta = theta_common - r * k * discount * norm_cdf_d2
        else:
            theta = theta_common + r * k * discount * BlackScholes._norm_cdf(-d2)
        theta /= 365.0  # convert to per-day

        # Vega (per 1% move in vol)
        vega = s * norm_pdf_d1 * sqrt_t / 100.0

        # Rho (per 1% move in rate)
        if option_type == OptionType.CALL:
            rho = k * t * discount * norm_cdf_d2 / 100.0
        else:
            rho = -k * t * discount * BlackScholes._norm_cdf(-d2) / 100.0

        return GreeksResult(
            delta=delta,
            gamma=gamma,
            theta=theta,
            vega=vega,
            rho=rho,
        )

    @classmethod
    def for_contract(
        cls,
        contract: OptionContract,
        t: float,
        r: float = 0.05,
    ) -> GreeksResult:
        """Calculate Greeks for an OptionContract."""
        sigma = contract.implied_volatility if contract.implied_volatility > 0 else 0.2
        return cls.calculate(
            option_type=contract.option_type,
            s=contract.underlying_price,
            k=contract.strike,
            t=t,
            r=r,
            sigma=sigma,
        )

    @classmethod
    def portfolio_greeks(
        cls,
        legs: list[OptionLeg],
        t: float,
        r: float = 0.05,
    ) -> GreeksResult:
        """Calculate net Greeks for a multi-leg position."""
        net = GreeksResult()
        for leg in legs:
            g = cls.for_contract(leg.contract, t, r)
            sign = 1.0 if leg.side.value == "long" else -1.0
            qty = leg.quantity * sign
            net.delta += g.delta * qty
            net.gamma += g.gamma * qty
            net.theta += g.theta * qty
            net.vega += g.vega * qty
            net.rho += g.rho * qty
        return net
