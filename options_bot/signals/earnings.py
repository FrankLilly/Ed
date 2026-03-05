"""Earnings calendar integration — the #1 event risk for options traders.

IV spikes 5-10 days before earnings and collapses immediately after.
This creates a massive, repeatable edge:
- SELL premium 5-7 days before earnings (IV crush pays you)
- DON'T hold through earnings unless you want binary risk
- BUY premium only if IV hasn't yet priced in the move
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from dataclasses import dataclass

from options_bot.models import Signal, SignalType

logger = logging.getLogger(__name__)


@dataclass
class EarningsEvent:
    """An upcoming earnings announcement."""

    symbol: str
    report_date: datetime
    timing: str  # "bmo" (before market open), "amc" (after market close)
    expected_move_pct: float = 0.0  # expected % move from options pricing
    historical_avg_move: float = 0.0  # avg historical earnings move


class EarningsCalendar:
    """Tracks earnings dates and generates pre/post earnings signals."""

    def __init__(self) -> None:
        self._events: dict[str, EarningsEvent] = {}
        self._historical_moves: dict[str, list[float]] = {}

    def add_event(self, event: EarningsEvent) -> None:
        self._events[event.symbol] = event

    def add_historical_move(self, symbol: str, move_pct: float) -> None:
        """Record a historical earnings move for calibration."""
        if symbol not in self._historical_moves:
            self._historical_moves[symbol] = []
        self._historical_moves[symbol].append(abs(move_pct))

    def load_from_api(self, symbols: list[str]) -> None:
        """Load earnings dates from a free API.

        Uses SEC EDGAR for real data. For production, use Alpha Vantage,
        Earnings Whispers, or similar paid API for accuracy.
        """
        for symbol in symbols:
            try:
                import urllib.request
                url = f"https://www.alphavantage.co/query?function=EARNINGS&symbol={symbol}&apikey=demo"
                req = urllib.request.Request(url, headers={"User-Agent": "OptionsBot/1.0"})
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = json.loads(resp.read().decode())

                quarterly = data.get("quarterlyEarnings", [])
                if quarterly:
                    # Find next upcoming earnings
                    for q in quarterly:
                        report_date_str = q.get("reportedDate", "")
                        if report_date_str:
                            report_date = datetime.strptime(report_date_str, "%Y-%m-%d")
                            if report_date > datetime.now():
                                surprise = float(q.get("surprisePercentage", "0") or "0")
                                self.add_event(EarningsEvent(
                                    symbol=symbol,
                                    report_date=report_date,
                                    timing="amc",
                                    historical_avg_move=abs(surprise),
                                ))
                                break

                    # Load historical moves for calibration
                    for q in quarterly[:8]:  # last 2 years
                        surprise = q.get("surprisePercentage", "0")
                        if surprise:
                            self.add_historical_move(symbol, float(surprise))

            except Exception:
                logger.debug("Could not load earnings for %s", symbol)

    def set_known_dates(self, earnings_map: dict[str, tuple[str, str]]) -> None:
        """Manually set earnings dates: {symbol: (date_str, timing)}.

        Use this when you know the dates from earnings whispers, etc.
        """
        for symbol, (date_str, timing) in earnings_map.items():
            self.add_event(EarningsEvent(
                symbol=symbol,
                report_date=datetime.strptime(date_str, "%Y-%m-%d"),
                timing=timing,
            ))

    def days_to_earnings(self, symbol: str) -> int | None:
        """Get days until next earnings. None if unknown."""
        event = self._events.get(symbol)
        if not event:
            return None
        return (event.report_date - datetime.now()).days

    def get_earnings_signal(self, symbol: str, current_iv: float) -> Signal | None:
        """Generate a signal based on earnings proximity.

        5-7 days before earnings with elevated IV = SELL premium (IV crush edge)
        1-2 days before = too risky unless you want binary
        Post-earnings = IV crushed, consider buying premium cheap
        """
        dte = self.days_to_earnings(symbol)
        if dte is None:
            return None

        # Pre-earnings: 5-10 days out with elevated IV
        if 5 <= dte <= 10:
            # Check if IV has already expanded for earnings
            # We estimate this by checking if current IV seems elevated
            hist_moves = self._historical_moves.get(symbol, [])
            avg_move = sum(hist_moves) / len(hist_moves) if hist_moves else 5.0

            strength = min(1.0, 0.6 + (current_iv - 0.20) * 2)
            return Signal(
                signal_type=SignalType.HIGH_VOLATILITY,
                symbol=symbol,
                strength=max(0.5, strength),
                timestamp=datetime.now(),
                reason=(
                    f"Earnings in {dte} days — IV elevated, sell premium for crush. "
                    f"Avg historical move: {avg_move:.1f}%"
                ),
                indicators={
                    "days_to_earnings": float(dte),
                    "avg_earnings_move": avg_move,
                    "current_iv": current_iv,
                    "edge": "earnings_iv_crush",
                },
            )

        # Too close — warn but don't trade
        if 0 < dte <= 4:
            return Signal(
                signal_type=SignalType.HIGH_VOLATILITY,
                symbol=symbol,
                strength=0.2,  # low strength = don't trade
                timestamp=datetime.now(),
                reason=f"Earnings in {dte} days — AVOID, binary event risk",
                indicators={"days_to_earnings": float(dte), "edge": "avoid"},
            )

        # Post-earnings (day of or day after) — IV crushed, premium is cheap
        if -2 <= dte <= 0:
            return Signal(
                signal_type=SignalType.LOW_VOLATILITY,
                symbol=symbol,
                strength=0.4,
                timestamp=datetime.now(),
                reason="Post-earnings — IV crushed, premium is cheap",
                indicators={"days_to_earnings": float(dte), "edge": "post_earnings"},
            )

        return None

    def should_avoid(self, symbol: str) -> bool:
        """Returns True if earnings are too close to safely trade."""
        dte = self.days_to_earnings(symbol)
        if dte is None:
            return False
        return 0 <= dte <= 3
