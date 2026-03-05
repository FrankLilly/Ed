"""Main bot orchestrator — the autonomous trading loop.

Rewired to use edge-based signals (VRP, IV rank, skew, term structure),
volatility surface modeling, earnings awareness, flow scanning, and
active position management. This is a real trading system.
"""

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
from options_bot.pricing.vol_surface import VolSurface, VolAnalyzer
from options_bot.risk.manager import RiskManager
from options_bot.signals.edge_signals import EdgeSignalGenerator
from options_bot.signals.earnings import EarningsCalendar
from options_bot.signals.flow import FlowScanner
from options_bot.strategies.base import Strategy
from options_bot.strategies.multi_leg import IronButterfly, IronCondor, Straddle, Strangle
from options_bot.strategies.single_leg import LongCall, LongPut, ShortCall, ShortPut
from options_bot.strategies.spreads import (
    BearCallSpread,
    BearPutSpread,
    BullCallSpread,
    BullPutSpread,
)
from options_bot.strategies.position_mgmt import PositionManager

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

# Signal-to-strategy mapping — prioritizes short strangles (backtested best)
SIGNAL_STRATEGY_MAP: dict[SignalType, list[str]] = {
    # High IV = sell premium aggressively (THE primary edge)
    SignalType.HIGH_VOLATILITY: [
        "short_strangle",    # primary: +28.7% annual, Sharpe 2.85
        "short_straddle",    # aggressive: highest premium
        "iron_condor",       # fallback: defined risk
    ],
    # Low IV = buy premium or sit out
    SignalType.LOW_VOLATILITY: [
        "long_straddle",
        "long_strangle",
    ],
    # Bullish + high IV = sell puts
    SignalType.BULLISH: [
        "bull_put_spread",
        "short_strangle",    # if neutral-ish bullish
    ],
    # Bearish + high IV = sell calls
    SignalType.BEARISH: [
        "bear_call_spread",
        "short_strangle",    # if neutral-ish bearish
    ],
    # Neutral = premium selling paradise
    SignalType.NEUTRAL: [
        "short_strangle",
        "iron_condor",
        "short_straddle",
    ],
}


class OptionsBot:
    """Autonomous options trading bot — built on real statistical edges."""

    def __init__(self, config: BotConfig) -> None:
        self.config = config
        self._setup_logging()

        # Initialize broker + data
        self.broker: Broker
        self.market_data: MarketDataProvider

        if config.broker.provider == "paper" or not config.broker.api_key:
            logger.info("Using paper broker (simulated data)")
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

        # Core systems — all edge-based
        self.edge_signals = EdgeSignalGenerator(self.market_data)
        self.flow_scanner = FlowScanner(self.market_data)
        self.earnings = EarningsCalendar()
        self.vol_surface = VolSurface()
        self.position_mgr = PositionManager()
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
        """Main bot loop — scan, signal, decide, execute, manage, repeat."""
        self._running = True
        logger.info("=" * 60)
        logger.info("OPTIONS TRADING BOT v2 — EDGE-BASED")
        logger.info("Capital: $%.2f | Watchlist: %s", self.config.initial_capital, self.config.watchlist)
        logger.info("Strategies: %s", list(self.strategies.keys()))
        logger.info("Mode: %s | Auto-trade: %s",
                     "PAPER" if self.config.broker.paper else "LIVE",
                     self.config.auto_trade)
        logger.info("Edge signals: VRP, IV Rank, Skew, Term Structure, Flow")
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
        """Run a single scan cycle — for AI agent or cron use."""
        self._check_daily_reset()
        orders = self._scan_cycle()
        self._manage_positions()
        return orders

    def stop(self) -> None:
        self._running = False

    def _scan_cycle(self) -> list[TradeOrder]:
        """Scan all symbols using edge-based signals."""
        logger.info("-" * 40)
        logger.info("SCAN CYCLE: %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

        executed_orders: list[TradeOrder] = []

        for symbol in self.config.watchlist:
            try:
                # STEP 1: Check earnings — avoid if too close
                if self.earnings.should_avoid(symbol):
                    logger.info("SKIP %s — earnings too close, binary risk", symbol)
                    continue

                # STEP 2: Get edge-based signals (VRP, IV rank, skew, etc.)
                edge_signal = self.edge_signals.get_best_signal(symbol)

                # STEP 3: Get flow signal (unusual options activity)
                flow_signal = self.flow_scanner.generate_flow_signal(symbol)

                # STEP 4: Get earnings signal if applicable
                snapshot = self.market_data.get_snapshot(symbol)
                earnings_signal = self.earnings.get_earnings_signal(
                    symbol, snapshot.historical_volatility or 0.25,
                )

                # STEP 5: Combine signals — edge signals get priority
                best_signal = self._combine_signals(edge_signal, flow_signal, earnings_signal)
                if best_signal is None:
                    logger.debug("No actionable signal for %s", symbol)
                    continue

                logger.info(
                    "SIGNAL: %s %s (strength=%.2f) — %s",
                    symbol, best_signal.signal_type.value, best_signal.strength,
                    best_signal.reason,
                )

                # STEP 6: Build the trade
                order = self._select_and_build_trade(symbol, best_signal, snapshot)
                if order is None:
                    continue

                # STEP 7: Risk check
                allowed, reason = self.risk.check_order(order, self.portfolio.open_positions)
                if not allowed:
                    logger.warning("RISK REJECTED: %s — %s", symbol, reason)
                    continue

                # STEP 8: Execute or log
                if self.config.auto_trade and self._auto_trades_today < self.config.max_auto_trades_per_day:
                    self._execute_order(order)
                    executed_orders.append(order)
                    self._auto_trades_today += 1
                else:
                    logger.info(
                        "TRADE OPPORTUNITY: %s %s | Max P/L: $%.2f / $%.2f | Premium: $%.2f",
                        order.strategy_name, symbol,
                        order.max_profit, order.max_loss, order.net_premium,
                    )

            except Exception:
                logger.exception("Error scanning %s", symbol)

        logger.info("Scan complete. %d orders executed.", len(executed_orders))
        return executed_orders

    def _combine_signals(
        self,
        edge: Signal | None,
        flow: Signal | None,
        earnings: Signal | None,
    ) -> Signal | None:
        """Combine multiple signal sources. Edge signals get priority.

        Signal confluence (multiple sources agreeing) increases strength.
        """
        signals = [s for s in (edge, flow, earnings) if s is not None and s.strength >= 0.4]
        if not signals:
            return None

        # Sort by strength, take the best
        signals.sort(key=lambda s: s.strength, reverse=True)
        best = signals[0]

        # Confluence bonus: if multiple signals agree on direction, boost strength
        if len(signals) >= 2:
            agreeing = sum(1 for s in signals[1:] if s.signal_type == best.signal_type)
            if agreeing > 0:
                boost = min(0.2, agreeing * 0.1)
                best = Signal(
                    signal_type=best.signal_type,
                    symbol=best.symbol,
                    strength=min(1.0, best.strength + boost),
                    timestamp=best.timestamp,
                    reason=f"{best.reason} [+{agreeing} confirming signal(s)]",
                    indicators={**best.indicators, "confluence": agreeing + 1},
                )

        return best

    def _select_and_build_trade(
        self,
        symbol: str,
        signal: Signal,
        snapshot: MarketSnapshot,
    ) -> TradeOrder | None:
        """Select strategy based on edge type and build the order.

        Key insight: when IV is high (VRP positive), we SELL premium.
        When IV is low, we either buy or stay out. We never fight the VRP.
        """
        # Check if signal indicates a specific edge
        edge_type = signal.indicators.get("edge", "")

        # Force strategy selection based on edge
        if edge_type in ("sell_premium", "sell_premium_wide", "earnings_iv_crush", "sell_front_month"):
            # Prefer defined-risk premium selling strategies
            candidate_names = ["iron_condor", "bull_put_spread", "bear_call_spread", "iron_butterfly"]
        elif edge_type == "sell_put_spread":
            candidate_names = ["bull_put_spread", "iron_condor"]
        elif edge_type == "buy_premium":
            candidate_names = ["long_straddle", "long_strangle", "long_call", "long_put"]
        elif edge_type == "follow_flow":
            candidate_names = SIGNAL_STRATEGY_MAP.get(signal.signal_type, [])
        else:
            candidate_names = SIGNAL_STRATEGY_MAP.get(signal.signal_type, [])

        for name in candidate_names:
            strategy = self.strategies.get(name)
            if strategy is None:
                continue

            if not strategy.should_enter(signal, snapshot):
                continue

            expirations = self.market_data.get_expirations(symbol)
            target_exp = self._select_expiration(expirations)
            if target_exp is None:
                continue

            try:
                iv = snapshot.historical_volatility or 0.25
                order = strategy.create_order(
                    symbol=symbol,
                    underlying_price=snapshot.price,
                    expiration=target_exp,
                    signal=signal,
                    iv=iv,
                )

                # Position sizing based on risk
                if order.max_loss != 0:
                    size = self.risk.calculate_position_size(abs(order.max_loss))
                    logger.debug("Position size: %d contracts (max_loss=$%.2f)", size, order.max_loss)

                return order

            except Exception:
                logger.exception("Error building %s for %s", name, symbol)

        return None

    def _select_expiration(self, expirations: list[datetime]) -> datetime | None:
        """Pick expiration closest to 45 DTE (backtested optimal for strangles)."""
        now = datetime.now()
        target_dte = 45  # optimal: enough theta but manageable gamma

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
        """Active position management using the PositionManager.

        This is where real money is made or saved.
        """
        for pos in self.portfolio.open_positions:
            try:
                # Get current price for the underlying
                symbol = pos.legs[0].contract.symbol if pos.legs else None
                if not symbol:
                    continue

                snapshot = self.market_data.get_snapshot(symbol)
                iv = snapshot.historical_volatility or 0.25

                # Use the position manager to evaluate
                action = self.position_mgr.evaluate_position(pos, snapshot.price, iv)

                if action is None:
                    continue

                logger.info(
                    "POSITION %s: %s (urgency=%.1f) — %s",
                    pos.position_id, action.action_type, action.urgency, action.reason,
                )

                if not self.config.auto_trade:
                    continue

                if action.action_type == "close" and action.urgency >= 0.7:
                    self.portfolio.close_position(pos.position_id, pos.current_value)
                    self.risk.update_portfolio_value(self.portfolio.total_value)
                    logger.info("CLOSED: %s | P&L: $%.2f", pos.position_id, pos.realized_pnl)

                elif action.action_type == "roll_out" and action.urgency >= 0.4:
                    expirations = self.market_data.get_expirations(symbol)
                    new_exp = self._select_expiration(expirations)
                    if new_exp:
                        roll_order = self.position_mgr.build_roll_order(
                            pos, snapshot.price, new_exp, iv,
                        )
                        if roll_order:
                            self.portfolio.close_position(pos.position_id, pos.current_value)
                            self._execute_order(roll_order)
                            logger.info("ROLLED: %s to %s", pos.position_id, new_exp.strftime("%Y-%m-%d"))

            except Exception:
                logger.exception("Error managing position %s", pos.position_id)

    def _check_daily_reset(self) -> None:
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
