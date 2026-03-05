"""Run backtests to validate strategies before risking real money.

Usage:
    python -m options_bot.run_backtest
    python -m options_bot.run_backtest --strategy iron_condor --days 504 --paths 200
"""

from __future__ import annotations

import argparse
import sys

from options_bot.backtesting.engine import BacktestEngine
from options_bot.strategies.multi_leg import IronCondor, IronButterfly, Straddle, Strangle
from options_bot.strategies.single_leg import LongCall, LongPut
from options_bot.strategies.spreads import BullCallSpread, BearPutSpread, BullPutSpread, BearCallSpread


STRATEGIES = {
    "iron_condor": IronCondor(),
    "iron_butterfly": IronButterfly(),
    "bull_call_spread": BullCallSpread(),
    "bear_put_spread": BearPutSpread(),
    "bull_put_spread": BullPutSpread(),
    "bear_call_spread": BearCallSpread(),
    "long_call": LongCall(),
    "long_put": LongPut(),
    "long_straddle": Straddle(short=False),
    "short_straddle": Straddle(short=True),
    "long_strangle": Strangle(short=False),
    "short_strangle": Strangle(short=True),
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Backtest options strategies")
    parser.add_argument("--strategy", "-s", type=str, default="iron_condor",
                        choices=list(STRATEGIES.keys()), help="Strategy to test")
    parser.add_argument("--capital", type=float, default=100_000, help="Starting capital")
    parser.add_argument("--days", type=int, default=252, help="Trading days to simulate")
    parser.add_argument("--paths", type=int, default=100, help="Monte Carlo paths")
    parser.add_argument("--price", type=float, default=450.0, help="Starting price")
    parser.add_argument("--vol", type=float, default=0.20, help="Annual volatility")
    parser.add_argument("--drift", type=float, default=0.08, help="Annual drift")
    parser.add_argument("--iv", type=float, default=0.25, help="Implied volatility (should be > vol for VRP)")
    parser.add_argument("--dte", type=int, default=30, help="Days to expiry per trade")
    parser.add_argument("--interval", type=int, default=7, help="Days between trades")
    parser.add_argument("--single", action="store_true", help="Run single path (detailed output)")

    args = parser.parse_args()
    strategy = STRATEGIES[args.strategy]
    engine = BacktestEngine(initial_capital=args.capital)

    print(f"{'=' * 60}")
    print(f"BACKTESTING: {args.strategy.upper()}")
    print(f"Capital: ${args.capital:,.0f} | Days: {args.days} | DTE: {args.dte}")
    print(f"RV: {args.vol:.0%} | IV: {args.iv:.0%} | VRP: {args.iv - args.vol:.0%}")
    print(f"{'=' * 60}")

    if args.single:
        result = engine.run(
            strategy=strategy,
            start_price=args.price,
            days=args.days,
            trade_interval=args.interval,
            dte=args.dte,
            iv=args.iv,
            annual_drift=args.drift,
            annual_vol=args.vol,
            seed=42,
        )
        print(result.summary())

        # Show trade detail
        print("\nTRADE LOG:")
        print(f"{'Date':<12} {'Strategy':<20} {'Entry':>8} {'Exit':>8} {'P&L':>10} {'Days':>5}")
        print("-" * 65)
        for t in result.trades:
            print(f"{t.entry_date.strftime('%Y-%m-%d'):<12} "
                  f"{t.strategy_name:<20} "
                  f"${t.entry_price:>7.2f} "
                  f"${t.exit_price:>7.2f} "
                  f"${t.pnl:>9.2f} "
                  f"{t.days_held:>5}")
    else:
        print(f"\nRunning {args.paths} Monte Carlo simulations...")
        mc = engine.run_monte_carlo(
            strategy=strategy,
            num_simulations=args.paths,
            start_price=args.price,
            days=args.days,
            trade_interval=args.interval,
            dte=args.dte,
            iv=args.iv,
            annual_drift=args.drift,
            annual_vol=args.vol,
        )

        print(f"\n{'=' * 60}")
        print(f"MONTE CARLO RESULTS ({mc['num_simulations']} simulations)")
        print(f"{'=' * 60}")
        print(f"Avg Return:          {mc['avg_return']:>8.2%}")
        print(f"Median Return:       {mc['median_return']:>8.2%}")
        print(f"5th Percentile:      {mc['percentile_5']:>8.2%}  (worst case)")
        print(f"95th Percentile:     {mc['percentile_95']:>8.2%}  (best case)")
        print(f"% Profitable Paths:  {mc['profitable_paths_pct']:>8.1%}")
        print(f"Avg Win Rate:        {mc['avg_win_rate']:>8.1%}")
        print(f"Avg Max Drawdown:    {mc['avg_max_drawdown']:>8.2%}")
        print(f"Worst Drawdown:      {mc['worst_drawdown']:>8.2%}")
        print(f"{'=' * 60}")

        if mc['profitable_paths_pct'] >= 0.7 and mc['avg_return'] > 0:
            print("\nVERDICT: Strategy shows positive edge. Consider paper trading.")
        elif mc['profitable_paths_pct'] >= 0.5:
            print("\nVERDICT: Marginal edge. Needs more refinement or better entry filters.")
        else:
            print("\nVERDICT: No edge detected. Do NOT trade this strategy live.")


if __name__ == "__main__":
    main()
