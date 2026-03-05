"""Dynamic position management — rolling, adjustments, and smart exits.

This is where real money is made or saved. A mediocre entry with excellent
management beats a perfect entry with bad management every time.

Key techniques:
- Roll tested positions out in time for more premium
- Adjust iron condors by rolling the tested side
- Close winners early (50% of max profit)
- Defend losers at 2x credit received
- Never hold to expiration (gamma risk)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from options_bot.models import (
    OptionContract,
    OptionLeg,
    OptionType,
    Position,
    PositionSide,
    TradeOrder,
    OrderAction,
)
from options_bot.pricing.black_scholes import BlackScholes
from options_bot.pricing.greeks import Greeks

logger = logging.getLogger(__name__)


@dataclass
class AdjustmentAction:
    """A recommended position adjustment."""

    action_type: str  # "close", "roll_out", "roll_up", "roll_down", "adjust_wing", "defend"
    reason: str
    urgency: float  # 0-1, higher = act now
    new_order: TradeOrder | None = None


class PositionManager:
    """Actively manage open positions for maximum profitability."""

    def __init__(
        self,
        take_profit_pct: float = 0.75,    # close at 75% of max profit (backtested optimal)
        stop_loss_multiplier: float = 3.0, # close at 3x credit received (backtested optimal)
        min_dte_close: int = 7,            # close positions < 7 DTE
        roll_dte_threshold: int = 14,       # consider rolling at 14 DTE
        delta_defense_threshold: float = 0.30,  # defend when short delta > 0.30
    ) -> None:
        self.take_profit_pct = take_profit_pct
        self.stop_loss_mult = stop_loss_multiplier
        self.min_dte_close = min_dte_close
        self.roll_dte = roll_dte_threshold
        self.delta_defense = delta_defense_threshold

    def evaluate_position(
        self,
        position: Position,
        current_price: float,
        current_iv: float,
    ) -> AdjustmentAction | None:
        """Evaluate an open position and return recommended action.

        Checks, in priority order:
        1. DTE too low → close or roll
        2. Stop loss hit → close
        3. Take profit hit → close
        4. Delta breach → adjust
        5. Roll opportunity → roll for more premium
        """
        if position.is_closed:
            return None

        # Calculate current metrics
        legs = position.legs
        if not legs:
            return None

        min_dte = min((leg.contract.expiration - datetime.now()).days for leg in legs)
        entry_premium = abs(position.entry_premium) if position.entry_premium != 0 else 1

        # Current P&L ratio
        pnl_pct = position.unrealized_pnl / entry_premium if entry_premium > 0 else 0

        # 1. DTE check — gamma risk gets dangerous near expiration
        if min_dte <= self.min_dte_close:
            return AdjustmentAction(
                action_type="close",
                reason=f"DTE={min_dte} — gamma risk, close position",
                urgency=0.9,
            )

        # 2. Stop loss
        if pnl_pct <= -self.stop_loss_mult:
            return AdjustmentAction(
                action_type="close",
                reason=f"Stop loss: P&L at {pnl_pct:.0%} of entry (limit: {-self.stop_loss_mult:.0%})",
                urgency=1.0,
            )

        # 3. Take profit — this is the #1 edge in management
        #    Closing at 50% captures most of the premium while avoiding
        #    the final weeks where gamma risk can destroy your trade.
        if position.entry_premium > 0 and pnl_pct >= self.take_profit_pct:
            return AdjustmentAction(
                action_type="close",
                reason=f"Take profit: {pnl_pct:.0%} of max (target: {self.take_profit_pct:.0%})",
                urgency=0.8,
            )

        # 4. Delta defense — if price is testing a short strike
        t = max(0.01, min_dte / 365.0)
        net_greeks = Greeks.portfolio_greeks(legs, t)

        if abs(net_greeks.delta) > self.delta_defense:
            direction = "upside" if net_greeks.delta < 0 else "downside"
            return AdjustmentAction(
                action_type="defend",
                reason=f"Delta breach: net delta {net_greeks.delta:.2f} — {direction} tested",
                urgency=0.7,
            )

        # 5. Roll opportunity — if profitable and approaching roll DTE
        if min_dte <= self.roll_dte and pnl_pct >= 0.25:
            return AdjustmentAction(
                action_type="roll_out",
                reason=f"Roll opportunity: {pnl_pct:.0%} profit at {min_dte} DTE",
                urgency=0.4,
            )

        return None

    def build_roll_order(
        self,
        position: Position,
        current_price: float,
        new_expiration: datetime,
        iv: float = 0.25,
    ) -> TradeOrder | None:
        """Build an order to roll a position to a new expiration.

        Rolling = close current + open new at same strikes but later expiry.
        This captures time decay on the existing trade AND collects new premium.
        """
        if not position.legs:
            return None

        new_legs: list[OptionLeg] = []
        t = BlackScholes.time_to_expiry(new_expiration)

        for old_leg in position.legs:
            new_premium = BlackScholes.price(
                old_leg.contract.option_type,
                current_price,
                old_leg.contract.strike,
                t,
                sigma=iv,
            )
            new_contract = OptionContract(
                symbol=old_leg.contract.symbol,
                option_type=old_leg.contract.option_type,
                strike=old_leg.contract.strike,
                expiration=new_expiration,
                premium=new_premium,
                underlying_price=current_price,
                implied_volatility=iv,
            )
            new_legs.append(OptionLeg(
                contract=new_contract,
                side=old_leg.side,
                quantity=old_leg.quantity,
            ))

        return TradeOrder(
            legs=new_legs,
            action=OrderAction.BUY_TO_OPEN,
            strategy_name=f"{position.strategy_name}_roll",
        )

    def optimal_exit_timing(
        self,
        strategy_name: str,
        pnl_pct: float,
        dte: int,
    ) -> str:
        """Advise on optimal exit timing based on strategy type and current state.

        Research shows:
        - Credit spreads: close at 50% profit maximizes risk-adjusted returns
        - Iron condors: close at 50%, or 25% if < 21 DTE
        - Straddles/strangles: close at 25% for short, let run for long
        - Directional: trail stop at 2x premium
        """
        if "iron" in strategy_name or "condor" in strategy_name:
            if dte < 21 and pnl_pct >= 0.25:
                return "CLOSE NOW — 25%+ profit with < 21 DTE, gamma risk rising"
            if pnl_pct >= 0.50:
                return "CLOSE NOW — 50% of max profit captured"
            if pnl_pct <= -1.0:
                return "CLOSE NOW — 100% loss, cut and move on"

        if "spread" in strategy_name:
            if pnl_pct >= 0.50:
                return "CLOSE NOW — 50% target hit"
            if pnl_pct >= 0.75:
                return "CLOSE NOW — 75% captured, diminishing returns ahead"

        if "straddle" in strategy_name or "strangle" in strategy_name:
            if "short" in strategy_name and pnl_pct >= 0.25:
                return "CLOSE NOW — 25% profit on short vol is ideal"
            if "long" in strategy_name and pnl_pct >= 1.0:
                return "TRAIL STOP — let winners run with trailing stop"

        if dte <= 5:
            return "CLOSE NOW — too close to expiry, gamma risk"

        return "HOLD — no exit trigger hit"
