"""Backtesting engine — validate strategies against historical data before risking capital.

This is the difference between gambling and trading. You MUST know your edge
is real before putting money on it.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from options_bot.models import (
    MarketSnapshot,
    OptionContract,
    OptionLeg,
    OptionType,
    PositionSide,
    TradeOrder,
    OrderAction,
)
from options_bot.pricing.black_scholes import BlackScholes
from options_bot.pricing.vol_surface import VolAnalyzer
from options_bot.strategies.base import Strategy


@dataclass
class BacktestTrade:
    """Record of a single trade in the backtest."""

    entry_date: datetime
    exit_date: datetime
    strategy_name: str
    symbol: str
    entry_price: float  # underlying at entry
    exit_price: float   # underlying at exit
    entry_premium: float
    exit_premium: float
    pnl: float
    max_drawdown: float = 0.0
    days_held: int = 0


@dataclass
class BacktestResult:
    """Complete backtest results with statistics."""

    trades: list[BacktestTrade] = field(default_factory=list)
    initial_capital: float = 100_000.0
    final_capital: float = 100_000.0
    equity_curve: list[tuple[datetime, float]] = field(default_factory=list)

    @property
    def total_trades(self) -> int:
        return len(self.trades)

    @property
    def winners(self) -> list[BacktestTrade]:
        return [t for t in self.trades if t.pnl > 0]

    @property
    def losers(self) -> list[BacktestTrade]:
        return [t for t in self.trades if t.pnl <= 0]

    @property
    def win_rate(self) -> float:
        if not self.trades:
            return 0.0
        return len(self.winners) / len(self.trades)

    @property
    def total_pnl(self) -> float:
        return sum(t.pnl for t in self.trades)

    @property
    def avg_win(self) -> float:
        if not self.winners:
            return 0.0
        return sum(t.pnl for t in self.winners) / len(self.winners)

    @property
    def avg_loss(self) -> float:
        if not self.losers:
            return 0.0
        return sum(abs(t.pnl) for t in self.losers) / len(self.losers)

    @property
    def profit_factor(self) -> float:
        gross_profit = sum(t.pnl for t in self.winners)
        gross_loss = sum(abs(t.pnl) for t in self.losers)
        if gross_loss == 0:
            return float("inf") if gross_profit > 0 else 0.0
        return gross_profit / gross_loss

    @property
    def max_drawdown(self) -> float:
        if not self.equity_curve:
            return 0.0
        peak = self.initial_capital
        max_dd = 0.0
        for _, equity in self.equity_curve:
            if equity > peak:
                peak = equity
            dd = (peak - equity) / peak if peak > 0 else 0
            if dd > max_dd:
                max_dd = dd
        return max_dd

    @property
    def sharpe_ratio(self) -> float:
        if len(self.equity_curve) < 3:
            return 0.0
        returns = []
        for i in range(1, len(self.equity_curve)):
            prev = self.equity_curve[i - 1][1]
            curr = self.equity_curve[i][1]
            if prev > 0:
                returns.append((curr - prev) / prev)
        if not returns:
            return 0.0
        avg = sum(returns) / len(returns)
        std = math.sqrt(sum((r - avg) ** 2 for r in returns) / len(returns))
        if std == 0:
            return 0.0
        return (avg / std) * math.sqrt(252)

    @property
    def cagr(self) -> float:
        if not self.equity_curve or len(self.equity_curve) < 2:
            return 0.0
        days = (self.equity_curve[-1][0] - self.equity_curve[0][0]).days
        if days <= 0:
            return 0.0
        years = days / 365.25
        ratio = self.final_capital / self.initial_capital
        if ratio <= 0:
            return -1.0
        return ratio ** (1 / years) - 1

    def summary(self) -> str:
        lines = [
            "=" * 60,
            "BACKTEST RESULTS",
            "=" * 60,
            f"Period:            {self.equity_curve[0][0].strftime('%Y-%m-%d') if self.equity_curve else 'N/A'}"
            f" to {self.equity_curve[-1][0].strftime('%Y-%m-%d') if self.equity_curve else 'N/A'}",
            f"Initial Capital:   ${self.initial_capital:>12,.2f}",
            f"Final Capital:     ${self.final_capital:>12,.2f}",
            f"Total P&L:         ${self.total_pnl:>12,.2f} ({self.total_pnl / self.initial_capital:+.2%})",
            f"CAGR:              {self.cagr:.2%}",
            "-" * 60,
            f"Total Trades:      {self.total_trades}",
            f"Win Rate:          {self.win_rate:.1%}",
            f"Avg Win:           ${self.avg_win:>12,.2f}",
            f"Avg Loss:          ${self.avg_loss:>12,.2f}",
            f"Profit Factor:     {self.profit_factor:.2f}",
            f"Max Drawdown:      {self.max_drawdown:.2%}",
            f"Sharpe Ratio:      {self.sharpe_ratio:.2f}",
            "=" * 60,
        ]
        return "\n".join(lines)


class BacktestEngine:
    """Backtest options strategies against historical/synthetic price paths.

    Uses geometric Brownian motion (GBM) to generate realistic price paths
    with configurable drift, volatility, and jump diffusion for tail events.
    """

    def __init__(
        self,
        initial_capital: float = 100_000.0,
        slippage_pct: float = 0.005,  # 0.5% slippage per leg
        commission_per_contract: float = 0.65,
    ) -> None:
        self.initial_capital = initial_capital
        self.slippage_pct = slippage_pct
        self.commission = commission_per_contract

    def generate_price_path(
        self,
        start_price: float,
        days: int,
        annual_drift: float = 0.08,
        annual_vol: float = 0.20,
        jump_probability: float = 0.02,  # 2% chance of jump per day
        jump_magnitude: float = 0.03,    # 3% jump size
        seed: int | None = None,
    ) -> list[tuple[datetime, float]]:
        """Generate a realistic GBM price path with jump diffusion.

        Jump diffusion captures the fat tails that destroy naive vol sellers.
        """
        if seed is not None:
            random.seed(seed)

        dt = 1 / 252
        drift = (annual_drift - 0.5 * annual_vol ** 2) * dt
        vol = annual_vol * math.sqrt(dt)

        prices: list[tuple[datetime, float]] = []
        price = start_price
        date = datetime.now() - timedelta(days=days)

        for day in range(days):
            z = random.gauss(0, 1)
            daily_return = drift + vol * z

            # Jump component (Merton jump diffusion)
            if random.random() < jump_probability:
                jump = random.gauss(0, jump_magnitude)
                daily_return += jump

            price *= math.exp(daily_return)
            date += timedelta(days=1)
            prices.append((date, round(price, 2)))

        return prices

    def run(
        self,
        strategy: Strategy,
        symbol: str = "SPY",
        start_price: float = 450.0,
        days: int = 252,
        trade_interval: int = 7,  # new trade every N days
        dte: int = 30,            # days to expiry for each trade
        iv: float = 0.25,
        annual_drift: float = 0.08,
        annual_vol: float = 0.18,
        take_profit_pct: float = 0.50,
        stop_loss_pct: float = 2.0,
        num_paths: int = 1,
        seed: int | None = None,
    ) -> BacktestResult:
        """Run a full backtest of a strategy.

        Simulates entering trades periodically, monitoring daily, and
        exiting at take-profit, stop-loss, or expiration.
        """
        all_trades: list[BacktestTrade] = []
        all_equity: list[tuple[datetime, float]] = []

        for path_idx in range(num_paths):
            path_seed = (seed + path_idx) if seed is not None else None
            path = self.generate_price_path(
                start_price, days, annual_drift, annual_vol, seed=path_seed,
            )

            capital = self.initial_capital
            open_trades: list[dict] = []
            equity_curve: list[tuple[datetime, float]] = [(path[0][0], capital)]

            for i, (date, price) in enumerate(path):
                # Check open trades for exit
                still_open: list[dict] = []
                for trade in open_trades:
                    days_held = (date - trade["entry_date"]).days
                    current_pnl = self._mark_to_market(
                        trade["legs"], price, trade["entry_price"],
                        trade["t_remaining"] - days_held / 365.0, iv,
                        t_at_entry=trade["t_remaining"],
                    )

                    # Track max drawdown within trade
                    if current_pnl < trade["max_dd"]:
                        trade["max_dd"] = current_pnl

                    entry_risk = abs(trade["entry_premium"]) if trade["entry_premium"] != 0 else 1
                    pnl_ratio = current_pnl / entry_risk if entry_risk > 0 else 0

                    # Exit conditions
                    exit_trade = False
                    if days_held >= dte:  # expiration
                        current_pnl = self._pnl_at_expiry(trade["legs"], price)
                        exit_trade = True
                    elif pnl_ratio >= take_profit_pct:
                        exit_trade = True
                    elif pnl_ratio <= -stop_loss_pct:
                        exit_trade = True

                    if exit_trade:
                        # Apply slippage and commissions
                        num_legs = len(trade["legs"])
                        slippage = abs(current_pnl) * self.slippage_pct
                        commissions = num_legs * trade["quantity"] * self.commission
                        net_pnl = current_pnl - slippage - commissions

                        capital += net_pnl
                        all_trades.append(BacktestTrade(
                            entry_date=trade["entry_date"],
                            exit_date=date,
                            strategy_name=strategy.name,
                            symbol=symbol,
                            entry_price=trade["entry_price"],
                            exit_price=price,
                            entry_premium=trade["entry_premium"],
                            exit_premium=current_pnl,
                            pnl=net_pnl,
                            max_drawdown=trade["max_dd"],
                            days_held=days_held,
                        ))
                    else:
                        still_open.append(trade)

                open_trades = still_open

                # Open new trade at interval
                if i % trade_interval == 0 and i + dte < len(path):
                    expiration = date + timedelta(days=dte)
                    legs = strategy.build_legs(symbol, price, expiration, iv=iv, as_of=date)
                    if legs:
                        entry_premium = sum(leg.net_premium for leg in legs)
                        quantity = max(1, int(capital * 0.03 / max(abs(entry_premium), 100)))

                        open_trades.append({
                            "legs": legs,
                            "entry_date": date,
                            "entry_price": price,
                            "entry_premium": entry_premium,
                            "t_remaining": dte / 365.0,
                            "quantity": quantity,
                            "max_dd": 0.0,
                        })

                equity_curve.append((date, capital))

            all_equity.extend(equity_curve)

        result = BacktestResult(
            trades=all_trades,
            initial_capital=self.initial_capital,
            final_capital=capital if num_paths == 1 else all_equity[-1][1],
            equity_curve=all_equity,
        )
        return result

    def _mark_to_market(
        self,
        legs: list[OptionLeg],
        current_price: float,
        entry_price: float,
        t_remaining: float,
        iv: float,
        t_at_entry: float = 0.0,
    ) -> float:
        """Estimate current P&L using Black-Scholes repricing.

        Compares option values at entry (entry_price, t_at_entry) vs
        now (current_price, t_remaining). The difference captures both
        directional moves AND theta decay.
        """
        total = 0.0
        t_now = max(0.001, t_remaining)
        t_entry = t_at_entry if t_at_entry > 0 else t_now + 0.01

        for leg in legs:
            entry_val = BlackScholes.price(
                leg.contract.option_type, entry_price, leg.contract.strike, t_entry, sigma=iv,
            )
            current_val = BlackScholes.price(
                leg.contract.option_type, current_price, leg.contract.strike, t_now, sigma=iv,
            )

            if leg.side == PositionSide.LONG:
                total += (current_val - entry_val) * leg.quantity * 100
            else:
                total += (entry_val - current_val) * leg.quantity * 100

        return total

    def _pnl_at_expiry(self, legs: list[OptionLeg], price: float) -> float:
        """Calculate P&L at expiration."""
        return sum(leg.pnl_at_expiry(price) for leg in legs)

    def run_monte_carlo(
        self,
        strategy: Strategy,
        num_simulations: int = 100,
        symbol: str = "SPY",
        start_price: float = 450.0,
        days: int = 252,
        trade_interval: int = 7,
        dte: int = 30,
        iv: float = 0.25,
        annual_drift: float = 0.08,
        annual_vol: float = 0.18,
    ) -> dict[str, float]:
        """Run Monte Carlo simulation across many price paths.

        This tells you the DISTRIBUTION of outcomes, not just one path.
        """
        results: list[BacktestResult] = []

        for i in range(num_simulations):
            result = self.run(
                strategy=strategy,
                symbol=symbol,
                start_price=start_price,
                days=days,
                trade_interval=trade_interval,
                dte=dte,
                iv=iv,
                annual_drift=annual_drift,
                annual_vol=annual_vol,
                seed=i * 42,
            )
            results.append(result)

        returns = [(r.final_capital - r.initial_capital) / r.initial_capital for r in results]
        win_rates = [r.win_rate for r in results]
        drawdowns = [r.max_drawdown for r in results]

        returns.sort()
        percentile_5 = returns[int(0.05 * len(returns))]
        percentile_50 = returns[int(0.50 * len(returns))]
        percentile_95 = returns[int(0.95 * len(returns))]

        avg_return = sum(returns) / len(returns)
        profitable_paths = sum(1 for r in returns if r > 0) / len(returns)

        return {
            "avg_return": avg_return,
            "median_return": percentile_50,
            "percentile_5": percentile_5,
            "percentile_95": percentile_95,
            "profitable_paths_pct": profitable_paths,
            "avg_win_rate": sum(win_rates) / len(win_rates),
            "avg_max_drawdown": sum(drawdowns) / len(drawdowns),
            "worst_drawdown": max(drawdowns),
            "num_simulations": num_simulations,
        }
