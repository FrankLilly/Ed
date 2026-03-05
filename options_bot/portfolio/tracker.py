"""Portfolio tracking — positions, P&L, and performance metrics."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime

from options_bot.models import Position, TradeOrder


@dataclass
class PerformanceMetrics:
    """Portfolio performance statistics."""

    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    total_pnl: float = 0.0
    max_drawdown: float = 0.0
    win_rate: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    profit_factor: float = 0.0
    sharpe_ratio: float = 0.0


class PortfolioTracker:
    """Tracks all positions and calculates portfolio-level metrics."""

    def __init__(self, initial_capital: float) -> None:
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.positions: list[Position] = []
        self.trade_history: list[Position] = []
        self._equity_curve: list[tuple[datetime, float]] = [
            (datetime.now(), initial_capital)
        ]

    @property
    def open_positions(self) -> list[Position]:
        return [p for p in self.positions if not p.is_closed]

    @property
    def closed_positions(self) -> list[Position]:
        return [p for p in self.positions if p.is_closed]

    @property
    def total_value(self) -> float:
        return self.cash + sum(p.current_value for p in self.open_positions)

    @property
    def unrealized_pnl(self) -> float:
        return sum(p.unrealized_pnl for p in self.open_positions)

    @property
    def realized_pnl(self) -> float:
        return sum(p.realized_pnl for p in self.positions)

    @property
    def total_pnl(self) -> float:
        return self.total_value - self.initial_capital

    @property
    def return_pct(self) -> float:
        if self.initial_capital <= 0:
            return 0.0
        return (self.total_value - self.initial_capital) / self.initial_capital

    def open_position(self, order: TradeOrder) -> Position:
        """Open a new position from a trade order."""
        position = Position(
            position_id=str(uuid.uuid4())[:8],
            legs=order.legs,
            strategy_name=order.strategy_name,
            entry_time=datetime.now(),
            entry_premium=order.net_premium,
            current_value=order.net_premium,
        )
        self.positions.append(position)
        self.cash += order.net_premium  # credit = positive, debit = negative
        self._record_equity()
        return position

    def close_position(self, position_id: str, close_value: float) -> Position | None:
        """Close a position and realize P&L."""
        for pos in self.positions:
            if pos.position_id == position_id and not pos.is_closed:
                pos.realized_pnl = close_value - pos.entry_premium
                pos.current_value = 0.0
                pos.is_closed = True
                pos.close_time = datetime.now()
                self.cash += close_value
                self._record_equity()
                return pos
        return None

    def update_position_value(self, position_id: str, current_value: float) -> None:
        """Update the mark-to-market value of a position."""
        for pos in self.positions:
            if pos.position_id == position_id and not pos.is_closed:
                pos.current_value = current_value
                break
        self._record_equity()

    def get_performance(self) -> PerformanceMetrics:
        """Calculate performance metrics from trade history."""
        closed = self.closed_positions
        if not closed:
            return PerformanceMetrics()

        wins = [p for p in closed if p.realized_pnl > 0]
        losses = [p for p in closed if p.realized_pnl <= 0]

        total_wins = sum(p.realized_pnl for p in wins)
        total_losses = abs(sum(p.realized_pnl for p in losses))

        # Max drawdown from equity curve
        max_dd = 0.0
        peak = self.initial_capital
        for _, equity in self._equity_curve:
            if equity > peak:
                peak = equity
            dd = (peak - equity) / peak if peak > 0 else 0
            if dd > max_dd:
                max_dd = dd

        # Sharpe ratio (simplified — daily returns)
        sharpe = 0.0
        if len(self._equity_curve) > 2:
            returns = []
            for i in range(1, len(self._equity_curve)):
                prev = self._equity_curve[i - 1][1]
                curr = self._equity_curve[i][1]
                if prev > 0:
                    returns.append((curr - prev) / prev)
            if returns:
                avg_ret = sum(returns) / len(returns)
                std_ret = (sum((r - avg_ret) ** 2 for r in returns) / len(returns)) ** 0.5
                if std_ret > 0:
                    sharpe = (avg_ret / std_ret) * (252**0.5)

        return PerformanceMetrics(
            total_trades=len(closed),
            winning_trades=len(wins),
            losing_trades=len(losses),
            total_pnl=self.total_pnl,
            max_drawdown=max_dd,
            win_rate=len(wins) / len(closed) if closed else 0,
            avg_win=total_wins / len(wins) if wins else 0,
            avg_loss=total_losses / len(losses) if losses else 0,
            profit_factor=total_wins / total_losses if total_losses > 0 else float("inf"),
            sharpe_ratio=sharpe,
        )

    def summary(self) -> str:
        """Human-readable portfolio summary."""
        perf = self.get_performance()
        lines = [
            "=" * 50,
            "PORTFOLIO SUMMARY",
            "=" * 50,
            f"Initial Capital:   ${self.initial_capital:>12,.2f}",
            f"Current Value:     ${self.total_value:>12,.2f}",
            f"Cash:              ${self.cash:>12,.2f}",
            f"Total P&L:         ${self.total_pnl:>12,.2f} ({self.return_pct:+.2%})",
            f"Unrealized P&L:    ${self.unrealized_pnl:>12,.2f}",
            f"Realized P&L:      ${self.realized_pnl:>12,.2f}",
            "-" * 50,
            f"Open Positions:    {len(self.open_positions)}",
            f"Total Trades:      {perf.total_trades}",
            f"Win Rate:          {perf.win_rate:.1%}",
            f"Avg Win:           ${perf.avg_win:>12,.2f}",
            f"Avg Loss:          ${perf.avg_loss:>12,.2f}",
            f"Profit Factor:     {perf.profit_factor:.2f}",
            f"Max Drawdown:      {perf.max_drawdown:.2%}",
            f"Sharpe Ratio:      {perf.sharpe_ratio:.2f}",
            "=" * 50,
        ]
        return "\n".join(lines)

    def _record_equity(self) -> None:
        self._equity_curve.append((datetime.now(), self.total_value))
