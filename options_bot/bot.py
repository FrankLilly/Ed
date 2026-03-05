"""Main bot orchestrator — the autonomous trading loop."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta

from options_bot.config import BotConfig
from options_bot.data.broker import AlpacaBroker, Broker, PaperBroker
from options_bot.data.market_data import (
    AlpacaMarketData,
    MarketDataProvider,
    SimulatedMarketData,
)
from options_bot.models import MarketSnapshot, Signal, SignalType, TradeOrder
from options_bot.portfolio.tracker import PortfolioTracker
from options_bot.pricing.black_scholes import BlackScholes
from options_bot.risk.manager import RiskManager
from options_bot.signals.generator import SignalGenerator
from options_bot.strategies.base import Strategy
from options_bot.strategies.multi_leg import IronButterfly, IronCondor, Straddle, Strangle
from options_bot.strategies.single_leg import LongCall, LongPut, ShortCall, ShortPut
from options_bot.strategies.spreads import (
    BearCallSpread,
    BearPutSpread,
    BullCallSpread,
    BullPutSpread,
)

logger = logging.getLogger(__name__)

STRATEGY_MAP: dict[str, Strategy] = {
    "long_call": LongCall(),
    "long_put": LongPut(),
    "short_call": ShortCall(),
    "short_put": ShortPut(),
    "bull_call_spread": BullCallSpread(),
    "bear_put_spread": BearPutSpread(),
    "bull_put_spread": BullPutSpread(),
    "bear_call_spread": BearCallSpread(),
    "iron_condor": IronCondor(),
    "iron_butterfly": IronButterfly(),
    "long_straddle": Straddle(short=False),
    "short_straddle": Straddle(short=True),
    "long_strangle": Strangle(short=False),
    "short_strangle": Strangle(short=True),
}

# Map signal types to preferred strategies
SIGNAL_STRATEGY_MAP: dict[SignalType, list[str]] = {
    SignalType.BULLISH: ["bull_call_spread", "bull_put_spread", "long_call"],
    SignalType.BEARISH: ["bear_put_spread", "bear_call_spread", "long_put"],
    SignalType.NEUTRAL: ["iron_condor", "iron_butterfly", "short_strangle"],
    SignalType.HIGH_VOLATILITY: ["long_straddle", "long_strangle"],
    SignalType.LOW_VOLATILITY: ["iron_condor", "short_straddle", "short_strangle"],
}


class OptionsBot:
    """Autonomous options trading bot."""

    def __init__(self, config: BotConfig) -> None:
        self.config = config
        self._setup_logging()

        # Initialize components
        self.broker: Broker
        self.market_data: MarketDataProvider

        if config.broker.provider == "paper" or not config.broker.api_key:
            logger.info("Using paper broker (no API keys or paper mode)")
            self.broker = PaperBroker(config.initial_capital)
            self.market_data = SimulatedMarketData()
        else:
            logger.info("Using Alpaca broker (paper=%s)", config.broker.paper)
            self.broker = AlpacaBroker(
                config.broker.api_key, config.broker.secret_key, config.broker.paper,
            )
            self.market_data = AlpacaMarketData(
                config.broker.api_key, config.broker.secret_key, config.broker.paper,
            )

        self.signals = SignalGenerator(self.market_data)
        self.portfolio = PortfolioTracker(config.initial_capital)
        self.risk = RiskManager(config.initial_capital, config.risk_limits)

        # Active strategies
        self.strategies: dict[str, Strategy] = {
            name: STRATEGY_MAP[name]
            for name in config.enabled_strategies
            if name in STRATEGY_MAP
        }

        self._running = False
        self._auto_trades_today = 0
        self._last_reset_date: str = ""

    def run(self) -> None:
        """Main bot loop — scan, signal, decide, execute, repeat."""
        self._running = True
        logger.info("=" * 60)
        logger.info("OPTIONS TRADING BOT STARTED")
        logger.info("Capital: $%.2f | Watchlist: %s", self.config.initial_capital, self.config.watchlist)
        logger.info("Strategies: %s", list(self.strategies.keys()))
        logger.info("Auto-trade: %s | Paper: %s", self.config.auto_trade, self.config.broker.paper)
        logger.info("=" * 60)

        try:
            while self._running:
                self._check_daily_reset()
                self._scan_cycle()
                self._manage_positions()

                logger.info("Next scan in %d seconds...", self.config.scan_interval)
                time.sleep(self.config.scan_interval)
        except KeyboardInterrupt:
            logger.info("Bot stopped by user")
        finally:
            self._shutdown()

    def run_once(self) -> list[TradeOrder]:
        """Run a single scan cycle (useful for testing / AI agent triggering)."""
        self._check_daily_reset()
        orders = self._scan_cycle()
        self._manage_positions()
        return orders

    def stop(self) -> None:
        self._running = False

    def _scan_cycle(self) -> list[TradeOrder]:
        """Scan all watchlist symbols for opportunities."""
        logger.info("-" * 40)
        logger.info("SCAN CYCLE: %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

        executed_orders: list[TradeOrder] = []

        for symbol in self.config.watchlist:
            try:
                signal = self.signals.get_best_signal(symbol)
                if signal is None:
                    logger.debug("No signal for %s", symbol)
                    continue

                logger.info(
                    "SIGNAL: %s %s (strength=%.2f) — %s",
                    symbol, signal.signal_type.value, signal.strength, signal.reason,
                )

                order = self._select_and_build_trade(symbol, signal)
                if order is None:
                    continue

                # Risk check
                allowed, reason = self.risk.check_order(order, self.portfolio.open_positions)
                if not allowed:
                    logger.warning("RISK REJECTED: %s — %s", symbol, reason)
                    continue

                # Execute
                if self.config.auto_trade and self._auto_trades_today < self.config.max_auto_trades_per_day:
                    self._execute_order(order)
                    executed_orders.append(order)
                    self._auto_trades_today += 1
                else:
                    logger.info(
                        "TRADE OPPORTUNITY: %s %s | Max P&L: $%.2f / $%.2f | Net Premium: $%.2f",
                        order.strategy_name, symbol,
                        order.max_profit, order.max_loss, order.net_premium,
                    )

            except Exception:
                logger.exception("Error scanning %s", symbol)

        logger.info("Scan complete. Portfolio: %s", self.portfolio.summary())
        return executed_orders

    def _select_and_build_trade(self, symbol: str, signal: Signal) -> TradeOrder | None:
        """Select the best strategy for a signal and build the trade."""
        snapshot = self.market_data.get_snapshot(symbol)
        candidate_names = SIGNAL_STRATEGY_MAP.get(signal.signal_type, [])

        for name in candidate_names:
            strategy = self.strategies.get(name)
            if strategy is None:
                continue

            if not strategy.should_enter(signal, snapshot):
                continue

            # Pick expiration
            expirations = self.market_data.get_expirations(symbol)
            target_exp = self._select_expiration(expirations)
            if target_exp is None:
                continue

            try:
                order = strategy.create_order(
                    symbol=symbol,
                    underlying_price=snapshot.price,
                    expiration=target_exp,
                    signal=signal,
                    iv=snapshot.historical_volatility or 0.3,
                )

                # Check risk/reward is acceptable
                if order.max_loss != 0:
                    rr_ratio = order.max_profit / abs(order.max_loss) if order.max_loss != 0 else 0
                    if rr_ratio < 0.5:
                        logger.debug("Skipping %s: poor risk/reward (%.2f)", name, rr_ratio)
                        continue

                return order

            except Exception:
                logger.exception("Error building %s for %s", name, symbol)

        return None

    def _select_expiration(self, expirations: list[datetime]) -> datetime | None:
        """Pick the best expiration date within DTE range."""
        now = datetime.now()
        target_dte = (self.config.min_dte + self.config.max_dte) // 2

        valid = []
        for exp in expirations:
            dte = (exp - now).days
            if self.config.min_dte <= dte <= self.config.max_dte:
                valid.append((abs(dte - target_dte), exp))

        if not valid:
            return None
        valid.sort()
        return valid[0][1]

    def _execute_order(self, order: TradeOrder) -> None:
        """Execute an order through the broker."""
        try:
            order_id = self.broker.submit_order(order)
            position = self.portfolio.open_position(order)
            self.risk.update_portfolio_value(self.portfolio.total_value)

            logger.info(
                "EXECUTED: %s | Order: %s | Position: %s | Premium: $%.2f",
                order.strategy_name, order_id, position.position_id, order.net_premium,
            )

        except Exception:
            logger.exception("Failed to execute order: %s", order.strategy_name)

    def _manage_positions(self) -> None:
        """Monitor open positions for exit conditions."""
        for pos in self.portfolio.open_positions:
            try:
                # Check P&L thresholds
                if pos.entry_premium != 0:
                    pnl_pct = pos.unrealized_pnl / abs(pos.entry_premium)
                else:
                    pnl_pct = 0.0

                # Take profit at 50% of max
                if pnl_pct >= 0.5:
                    logger.info(
                        "TAKE PROFIT: %s (%.1f%% gain)", pos.position_id, pnl_pct * 100,
                    )
                    if self.config.auto_trade:
                        self.portfolio.close_position(pos.position_id, pos.current_value)

                # Stop loss at -100% of entry
                elif pnl_pct <= -1.0:
                    logger.info(
                        "STOP LOSS: %s (%.1f%% loss)", pos.position_id, pnl_pct * 100,
                    )
                    if self.config.auto_trade:
                        self.portfolio.close_position(pos.position_id, pos.current_value)

                # Check DTE — close if < 7 days to expiry
                for leg in pos.legs:
                    dte = (leg.contract.expiration - datetime.now()).days
                    if dte <= 5:
                        logger.info(
                            "DTE EXIT: %s (%d DTE remaining)", pos.position_id, dte,
                        )
                        if self.config.auto_trade:
                            self.portfolio.close_position(pos.position_id, pos.current_value)
                        break

            except Exception:
                logger.exception("Error managing position %s", pos.position_id)

    def _check_daily_reset(self) -> None:
        """Reset daily counters at market open."""
        today = datetime.now().strftime("%Y-%m-%d")
        if today != self._last_reset_date:
            self._last_reset_date = today
            self._auto_trades_today = 0
            self.risk.reset_daily_stats()
            logger.info("Daily stats reset for %s", today)

    def _setup_logging(self) -> None:
        logging.basicConfig(
            level=getattr(logging, self.config.log_level),
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            handlers=[
                logging.StreamHandler(),
                logging.FileHandler(self.config.log_file),
            ],
        )

    def _shutdown(self) -> None:
        logger.info("Shutting down bot...")
        logger.info(self.portfolio.summary())
        logger.info("Final equity: $%.2f", self.portfolio.total_value)
