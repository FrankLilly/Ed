"""Tests for the options trading bot core components."""

from __future__ import annotations

import math
from datetime import datetime, timedelta

import pytest

from options_bot.models import (
    GreeksResult,
    MarketSnapshot,
    OptionContract,
    OptionLeg,
    OptionType,
    Position,
    PositionSide,
    Signal,
    SignalType,
    TradeOrder,
    OrderAction,
)
from options_bot.pricing.black_scholes import BlackScholes
from options_bot.pricing.greeks import Greeks
from options_bot.strategies.single_leg import LongCall, LongPut, ShortCall, ShortPut
from options_bot.strategies.spreads import BullCallSpread, BearPutSpread, BullPutSpread, BearCallSpread
from options_bot.strategies.multi_leg import IronCondor, IronButterfly, Straddle, Strangle
from options_bot.risk.manager import RiskManager, RiskLimits
from options_bot.portfolio.tracker import PortfolioTracker
from options_bot.data.market_data import SimulatedMarketData
from options_bot.data.broker import PaperBroker
from options_bot.signals.generator import SignalGenerator
from options_bot.config import BotConfig
from options_bot.bot import OptionsBot


# === Fixtures ===

EXP = datetime.now() + timedelta(days=30)
SYMBOL = "SPY"
PRICE = 450.0


def _make_signal(sig_type: SignalType = SignalType.BULLISH, strength: float = 0.7) -> Signal:
    return Signal(
        signal_type=sig_type,
        symbol=SYMBOL,
        strength=strength,
        timestamp=datetime.now(),
        reason="test signal",
    )


def _make_snapshot(iv_rank: float = 50.0) -> MarketSnapshot:
    return MarketSnapshot(
        symbol=SYMBOL,
        price=PRICE,
        timestamp=datetime.now(),
        iv_rank=iv_rank,
    )


# === Black-Scholes Tests ===


class TestBlackScholes:
    def test_call_price_positive(self) -> None:
        price = BlackScholes.price(OptionType.CALL, 100, 100, 0.25, 0.05, 0.2)
        assert price > 0

    def test_put_price_positive(self) -> None:
        price = BlackScholes.price(OptionType.PUT, 100, 100, 0.25, 0.05, 0.2)
        assert price > 0

    def test_put_call_parity(self) -> None:
        s, k, t, r, sigma = 100, 100, 0.25, 0.05, 0.2
        call = BlackScholes.price(OptionType.CALL, s, k, t, r, sigma)
        put = BlackScholes.price(OptionType.PUT, s, k, t, r, sigma)
        # C - P = S - K*e^(-rT)
        parity = call - put - (s - k * math.exp(-r * t))
        assert abs(parity) < 1e-10

    def test_deep_itm_call_near_intrinsic(self) -> None:
        price = BlackScholes.price(OptionType.CALL, 200, 100, 0.01, 0.05, 0.2)
        assert price > 99  # should be near intrinsic ~100

    def test_expired_option_returns_intrinsic(self) -> None:
        call = BlackScholes.price(OptionType.CALL, 110, 100, 0.0, 0.05, 0.2)
        assert abs(call - 10.0) < 1e-10
        put = BlackScholes.price(OptionType.PUT, 90, 100, 0.0, 0.05, 0.2)
        assert abs(put - 10.0) < 1e-10

    def test_implied_volatility_recovery(self) -> None:
        true_sigma = 0.25
        price = BlackScholes.price(OptionType.CALL, 100, 100, 0.25, 0.05, true_sigma)
        recovered = BlackScholes.implied_volatility(OptionType.CALL, price, 100, 100, 0.25, 0.05)
        assert abs(recovered - true_sigma) < 0.001

    def test_time_to_expiry(self) -> None:
        now = datetime(2024, 1, 1)
        exp = datetime(2025, 1, 1)
        t = BlackScholes.time_to_expiry(exp, now)
        assert abs(t - 1.0) < 0.01  # ~1 year


# === Greeks Tests ===


class TestGreeks:
    def test_call_delta_between_0_and_1(self) -> None:
        g = Greeks.calculate(OptionType.CALL, 100, 100, 0.25, 0.05, 0.2)
        assert 0 < g.delta < 1

    def test_put_delta_between_neg1_and_0(self) -> None:
        g = Greeks.calculate(OptionType.PUT, 100, 100, 0.25, 0.05, 0.2)
        assert -1 < g.delta < 0

    def test_gamma_positive(self) -> None:
        g = Greeks.calculate(OptionType.CALL, 100, 100, 0.25, 0.05, 0.2)
        assert g.gamma > 0

    def test_theta_negative_for_long(self) -> None:
        g = Greeks.calculate(OptionType.CALL, 100, 100, 0.25, 0.05, 0.2)
        assert g.theta < 0  # time decay hurts long positions

    def test_vega_positive(self) -> None:
        g = Greeks.calculate(OptionType.CALL, 100, 100, 0.25, 0.05, 0.2)
        assert g.vega > 0

    def test_portfolio_greeks_net_out(self) -> None:
        """Long call + short call at same strike should net to ~zero delta."""
        contract = OptionContract(
            symbol="SPY", option_type=OptionType.CALL, strike=100,
            expiration=EXP, premium=5.0, underlying_price=100.0,
            implied_volatility=0.2,
        )
        legs = [
            OptionLeg(contract=contract, side=PositionSide.LONG),
            OptionLeg(contract=contract, side=PositionSide.SHORT),
        ]
        net = Greeks.portfolio_greeks(legs, 0.08)
        assert abs(net.delta) < 1e-10


# === Strategy Tests ===


class TestStrategies:
    def test_long_call_builds_one_leg(self) -> None:
        strategy = LongCall()
        legs = strategy.build_legs(SYMBOL, PRICE, EXP)
        assert len(legs) == 1
        assert legs[0].side == PositionSide.LONG
        assert legs[0].contract.option_type == OptionType.CALL

    def test_long_put_builds_one_leg(self) -> None:
        strategy = LongPut()
        legs = strategy.build_legs(SYMBOL, PRICE, EXP)
        assert len(legs) == 1
        assert legs[0].side == PositionSide.LONG
        assert legs[0].contract.option_type == OptionType.PUT

    def test_bull_call_spread_two_legs(self) -> None:
        strategy = BullCallSpread()
        legs = strategy.build_legs(SYMBOL, PRICE, EXP)
        assert len(legs) == 2
        long_legs = [l for l in legs if l.side == PositionSide.LONG]
        short_legs = [l for l in legs if l.side == PositionSide.SHORT]
        assert len(long_legs) == 1
        assert len(short_legs) == 1
        assert long_legs[0].contract.strike < short_legs[0].contract.strike

    def test_bear_put_spread_two_legs(self) -> None:
        strategy = BearPutSpread()
        legs = strategy.build_legs(SYMBOL, PRICE, EXP)
        assert len(legs) == 2

    def test_iron_condor_four_legs(self) -> None:
        strategy = IronCondor()
        legs = strategy.build_legs(SYMBOL, PRICE, EXP)
        assert len(legs) == 4
        calls = [l for l in legs if l.contract.option_type == OptionType.CALL]
        puts = [l for l in legs if l.contract.option_type == OptionType.PUT]
        assert len(calls) == 2
        assert len(puts) == 2

    def test_iron_butterfly_four_legs(self) -> None:
        strategy = IronButterfly()
        legs = strategy.build_legs(SYMBOL, PRICE, EXP)
        assert len(legs) == 4

    def test_straddle_two_legs_same_strike(self) -> None:
        strategy = Straddle()
        legs = strategy.build_legs(SYMBOL, PRICE, EXP)
        assert len(legs) == 2
        assert legs[0].contract.strike == legs[1].contract.strike
        types = {l.contract.option_type for l in legs}
        assert types == {OptionType.CALL, OptionType.PUT}

    def test_strangle_two_legs_different_strikes(self) -> None:
        strategy = Strangle()
        legs = strategy.build_legs(SYMBOL, PRICE, EXP)
        assert len(legs) == 2
        assert legs[0].contract.strike != legs[1].contract.strike

    def test_breakeven_calculation(self) -> None:
        strategy = LongCall()
        legs = strategy.build_legs(SYMBOL, PRICE, EXP, strike=450.0)
        breakevens = strategy.breakeven_prices(legs)
        assert len(breakevens) >= 1

    def test_should_enter_respects_signal(self) -> None:
        strategy = LongCall()
        bullish = _make_signal(SignalType.BULLISH, 0.8)
        bearish = _make_signal(SignalType.BEARISH, 0.8)
        snapshot = _make_snapshot()
        assert strategy.should_enter(bullish, snapshot) is True
        assert strategy.should_enter(bearish, snapshot) is False


# === Risk Manager Tests ===


class TestRiskManager:
    def test_approves_valid_order(self) -> None:
        rm = RiskManager(100_000)
        strategy = BullCallSpread()
        order = strategy.create_order(SYMBOL, PRICE, EXP)
        allowed, reason = rm.check_order(order, [])
        assert allowed, reason

    def test_rejects_too_many_positions(self) -> None:
        limits = RiskLimits(max_positions=0)
        rm = RiskManager(100_000, limits)
        strategy = BullCallSpread()
        order = strategy.create_order(SYMBOL, PRICE, EXP)
        allowed, _ = rm.check_order(order, [])
        assert not allowed

    def test_rejects_daily_trade_limit(self) -> None:
        limits = RiskLimits(max_daily_trades=0)
        rm = RiskManager(100_000, limits)
        strategy = BullCallSpread()
        order = strategy.create_order(SYMBOL, PRICE, EXP)
        allowed, _ = rm.check_order(order, [])
        assert not allowed

    def test_position_size_calculation(self) -> None:
        rm = RiskManager(100_000)
        size = rm.calculate_position_size(500)  # $500 max loss per contract
        assert size >= 1
        assert size <= 100_000 * 0.05 / 500 + 1

    def test_naked_detection(self) -> None:
        contract = OptionContract(
            symbol="SPY", option_type=OptionType.CALL, strike=450,
            expiration=EXP, premium=5.0, underlying_price=PRICE,
        )
        naked_legs = [OptionLeg(contract=contract, side=PositionSide.SHORT)]
        assert RiskManager._has_naked_legs(naked_legs) is True

        covered_legs = [
            OptionLeg(contract=contract, side=PositionSide.SHORT),
            OptionLeg(contract=contract, side=PositionSide.LONG),
        ]
        assert RiskManager._has_naked_legs(covered_legs) is False


# === Portfolio Tracker Tests ===


class TestPortfolioTracker:
    def test_initial_state(self) -> None:
        pt = PortfolioTracker(100_000)
        assert pt.total_value == 100_000
        assert pt.cash == 100_000
        assert len(pt.open_positions) == 0

    def test_open_position(self) -> None:
        pt = PortfolioTracker(100_000)
        strategy = BullCallSpread()
        order = strategy.create_order(SYMBOL, PRICE, EXP)
        pos = pt.open_position(order)
        assert pos.is_closed is False
        assert len(pt.open_positions) == 1

    def test_close_position(self) -> None:
        pt = PortfolioTracker(100_000)
        strategy = BullCallSpread()
        order = strategy.create_order(SYMBOL, PRICE, EXP)
        pos = pt.open_position(order)
        closed = pt.close_position(pos.position_id, 500)
        assert closed is not None
        assert closed.is_closed is True
        assert len(pt.open_positions) == 0

    def test_performance_metrics(self) -> None:
        pt = PortfolioTracker(100_000)
        perf = pt.get_performance()
        assert perf.total_trades == 0
        assert perf.win_rate == 0

    def test_summary_output(self) -> None:
        pt = PortfolioTracker(100_000)
        summary = pt.summary()
        assert "PORTFOLIO SUMMARY" in summary
        assert "$100,000.00" in summary


# === Paper Broker Tests ===


class TestPaperBroker:
    def test_initial_balance(self) -> None:
        broker = PaperBroker(50_000)
        assert broker.get_account_balance() == 50_000

    def test_submit_order(self) -> None:
        broker = PaperBroker(50_000)
        strategy = LongCall()
        order = strategy.create_order(SYMBOL, PRICE, EXP)
        order_id = broker.submit_order(order)
        assert order_id.startswith("paper-")
        assert broker.get_order_status(order_id) == "filled"

    def test_cancel_order(self) -> None:
        broker = PaperBroker(50_000)
        strategy = LongCall()
        order = strategy.create_order(SYMBOL, PRICE, EXP)
        order_id = broker.submit_order(order)
        assert broker.cancel_order(order_id) is True
        assert broker.get_order_status(order_id) == "cancelled"


# === Signal Generator Tests ===


class TestSignalGenerator:
    def test_generates_signals(self) -> None:
        data = SimulatedMarketData()
        gen = SignalGenerator(data)
        signals = gen.generate_signals("SPY")
        # Should generate at least some signals from simulated data
        assert isinstance(signals, list)

    def test_best_signal(self) -> None:
        data = SimulatedMarketData()
        gen = SignalGenerator(data)
        signal = gen.get_best_signal("SPY")
        # May or may not find a signal, but should not error
        if signal:
            assert 0 <= signal.strength <= 1


# === Bot Integration Tests ===


class TestBot:
    def test_bot_creates_with_paper_config(self) -> None:
        config = BotConfig(
            initial_capital=50_000,
            broker=__import__("options_bot.config", fromlist=["BrokerConfig"]).BrokerConfig(
                provider="paper",
            ),
        )
        bot = OptionsBot(config)
        assert bot.portfolio.initial_capital == 50_000

    def test_bot_single_scan(self) -> None:
        config = BotConfig(
            initial_capital=50_000,
            auto_trade=True,
            watchlist=["SPY"],
        )
        config.broker.provider = "paper"
        bot = OptionsBot(config)
        orders = bot.run_once()
        assert isinstance(orders, list)


# === Model Tests ===


class TestModels:
    def test_option_contract_properties(self) -> None:
        c = OptionContract(
            symbol="SPY", option_type=OptionType.CALL, strike=450,
            expiration=EXP, premium=10.0, underlying_price=460.0,
            bid=9.5, ask=10.5,
        )
        assert c.is_itm is True
        assert c.intrinsic_value == 10.0
        assert c.time_value == 0.0
        assert c.mid_price == 10.0
        assert c.spread == 1.0
        assert c.moneyness > 1.0

    def test_option_leg_pnl(self) -> None:
        c = OptionContract(
            symbol="SPY", option_type=OptionType.CALL, strike=450,
            expiration=EXP, premium=10.0, underlying_price=450.0,
        )
        long_leg = OptionLeg(contract=c, side=PositionSide.LONG)
        # At expiry, underlying = 470: profit = (470-450-10)*100 = 1000
        assert long_leg.pnl_at_expiry(470.0) == 1000.0
        # At expiry, underlying = 440: loss = (0-10)*100 = -1000
        assert long_leg.pnl_at_expiry(440.0) == -1000.0

    def test_trade_order_net_premium(self) -> None:
        c1 = OptionContract(
            symbol="SPY", option_type=OptionType.CALL, strike=450,
            expiration=EXP, premium=10.0, underlying_price=450.0,
        )
        c2 = OptionContract(
            symbol="SPY", option_type=OptionType.CALL, strike=460,
            expiration=EXP, premium=5.0, underlying_price=450.0,
        )
        order = TradeOrder(
            legs=[
                OptionLeg(contract=c1, side=PositionSide.LONG),
                OptionLeg(contract=c2, side=PositionSide.SHORT),
            ],
            action=OrderAction.BUY_TO_OPEN,
            strategy_name="test",
        )
        # Net premium: -10*100 + 5*100 = -500 (net debit)
        assert order.net_premium == -500.0
