"""Entry point — run the options trading bot."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from options_bot.bot import OptionsBot
from options_bot.config import BotConfig


def main() -> None:
    parser = argparse.ArgumentParser(description="Options Trading Bot")
    parser.add_argument(
        "--config", "-c",
        type=str,
        default=None,
        help="Path to config JSON file",
    )
    parser.add_argument(
        "--paper",
        action="store_true",
        default=True,
        help="Use paper trading (default: True)",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        default=False,
        help="Use live trading (overrides --paper)",
    )
    parser.add_argument(
        "--capital",
        type=float,
        default=10_000.0,
        help="Starting capital (default: 10000)",
    )
    parser.add_argument(
        "--auto",
        action="store_true",
        default=False,
        help="Enable auto-trading (default: manual confirmation)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        default=False,
        help="Run a single scan cycle and exit",
    )
    parser.add_argument(
        "--generate-config",
        type=str,
        default=None,
        help="Generate a default config file at the given path",
    )
    parser.add_argument(
        "--symbols",
        type=str,
        nargs="+",
        default=None,
        help="Symbols to watch (e.g., SPY QQQ AAPL)",
    )

    args = parser.parse_args()

    # Generate config mode
    if args.generate_config:
        config = BotConfig()
        config.to_file(args.generate_config)
        print(f"Default config written to {args.generate_config}")
        return

    # Load or create config
    if args.config:
        config = BotConfig.from_file(args.config)
    else:
        config = BotConfig()

    # CLI overrides
    config.initial_capital = args.capital
    config.auto_trade = args.auto

    if args.live:
        config.broker.paper = False
    if args.symbols:
        config.watchlist = args.symbols

    # Safety check for live trading
    if not config.broker.paper:
        print("=" * 50)
        print("WARNING: LIVE TRADING MODE")
        print(f"Capital: ${config.initial_capital:,.2f}")
        print(f"Auto-trade: {config.auto_trade}")
        print("=" * 50)
        confirm = input("Type 'CONFIRM' to proceed with live trading: ")
        if confirm != "CONFIRM":
            print("Aborted.")
            sys.exit(1)

    # Start bot
    bot = OptionsBot(config)

    if args.once:
        orders = bot.run_once()
        print(f"\nScan complete. {len(orders)} orders executed.")
        print(bot.portfolio.summary())
    else:
        bot.run()


if __name__ == "__main__":
    main()
