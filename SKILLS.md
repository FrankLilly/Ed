# Options Trading Bot — AI Agent Skills

## Overview

This is an autonomous options trading bot that scans markets, generates signals
using technical analysis, selects optimal strategies (calls, puts, spreads,
iron condors, straddles, strangles), enforces risk management, and executes
trades through a broker. It is designed to be operated by an AI agent.

## Agent Skills

### 1. Market Scanning & Signal Generation

**Trigger:** Periodic (every `scan_interval` seconds) or on-demand.

**What the agent does:**
- Iterates through the watchlist symbols
- Pulls market snapshots and 50-day price history
- Runs technical analysis: moving average crossover, RSI momentum,
  Bollinger Band mean reversion, and IV rank volatility signals
- Returns the strongest signal per symbol with type (bullish, bearish,
  neutral, high_vol, low_vol), strength (0–1), and reasoning

**How to invoke:**
```python
from options_bot.bot import OptionsBot
from options_bot.config import BotConfig

config = BotConfig(watchlist=["SPY", "QQQ", "AAPL"])
bot = OptionsBot(config)
orders = bot.run_once()  # single scan cycle
```

### 2. Strategy Selection & Trade Construction

**Trigger:** When a signal is generated with sufficient strength.

**What the agent does:**
- Maps the signal type to candidate strategies:
  - Bullish → bull call spread, bull put spread, long call
  - Bearish → bear put spread, bear call spread, long put
  - High volatility → long straddle, long strangle
  - Low volatility / neutral → iron condor, iron butterfly, short strangle
- Validates each candidate with `should_enter(signal, market)`
- Selects optimal expiration (within configured DTE range)
- Builds the multi-leg order with Black-Scholes pricing
- Checks risk/reward ratio (rejects < 0.5)

**Available strategies:**
| Strategy | Legs | Bias | Risk |
|---|---|---|---|
| `long_call` | 1 | Bullish | Defined (premium) |
| `long_put` | 1 | Bearish | Defined (premium) |
| `short_call` | 1 | Bearish/Neutral | Undefined |
| `short_put` | 1 | Bullish/Neutral | Undefined |
| `bull_call_spread` | 2 | Bullish | Defined |
| `bear_put_spread` | 2 | Bearish | Defined |
| `bull_put_spread` | 2 | Bullish | Defined |
| `bear_call_spread` | 2 | Bearish | Defined |
| `iron_condor` | 4 | Neutral | Defined |
| `iron_butterfly` | 4 | Neutral | Defined |
| `long_straddle` | 2 | Volatility | Defined |
| `short_straddle` | 2 | Low Vol | Undefined |
| `long_strangle` | 2 | Volatility | Defined |
| `short_strangle` | 2 | Low Vol | Undefined |

### 3. Risk Management

**Trigger:** Before every trade execution.

**What the agent enforces:**
- Max 5% portfolio risk per trade
- Max 20% total portfolio risk
- Max 10 open positions
- Max 5 trades per day
- 3% daily loss circuit breaker
- DTE range: 7–60 days
- Bid-ask spread < 10%
- Minimum open interest (100) and volume (50)
- Defined-risk-only mode (blocks naked options by default)

**Configurable via `RiskLimits` dataclass or config JSON.**

### 4. Order Execution

**Trigger:** After risk approval, if `auto_trade=True`.

**What the agent does:**
- Submits the order to the broker (Alpaca or paper)
- For multi-leg orders, uses multi-leg order class
- Tracks order ID and maps to portfolio position
- Logs all execution details

**Brokers supported:**
- `PaperBroker` — in-memory simulation, no API needed
- `AlpacaBroker` — real paper/live trading via Alpaca API

### 5. Position Management

**Trigger:** Every scan cycle, after new trade evaluation.

**What the agent does:**
- Monitors all open positions
- Take profit at 50% of max gain
- Stop loss at 100% of entry premium
- Auto-close positions with < 5 DTE
- Updates portfolio tracker and equity curve

### 6. Portfolio Analytics

**Trigger:** On-demand or after each cycle.

**What the agent reports:**
- Total value, cash, unrealized/realized P&L
- Win rate, average win/loss, profit factor
- Max drawdown, Sharpe ratio
- Full equity curve

```python
print(bot.portfolio.summary())
perf = bot.portfolio.get_performance()
```

## Configuration

### Environment Variables
```
ALPACA_API_KEY=your_key_here
ALPACA_SECRET_KEY=your_secret_here
```

### Config File (JSON)
Generate a default config:
```bash
python -m options_bot --generate-config bot_config.json
```

Key settings:
```json
{
  "watchlist": ["SPY", "QQQ", "AAPL", "TSLA"],
  "initial_capital": 10000,
  "scan_interval": 300,
  "auto_trade": false,
  "broker": {"provider": "paper", "paper": true},
  "risk_limits": {
    "max_portfolio_risk_pct": 0.05,
    "max_daily_trades": 5,
    "require_defined_risk": true
  }
}
```

### CLI Usage
```bash
# Paper trading, manual mode (default)
python -m options_bot --capital 10000

# Auto-trade with paper broker
python -m options_bot --auto --capital 25000 --symbols SPY QQQ AAPL

# Single scan (useful for cron/agent triggers)
python -m options_bot --once --auto

# Live trading (requires confirmation)
python -m options_bot --live --capital 50000

# Load from config file
python -m options_bot -c bot_config.json
```

## Agent Operation Mode

For AI agent autonomous operation:

1. **Set `auto_trade: true`** and configure `max_auto_trades_per_day`
2. **Use paper mode first** to validate strategy before going live
3. **Call `bot.run_once()`** from your agent loop for controlled execution
4. **Monitor `bot.portfolio.summary()`** after each cycle
5. **Check `bot.portfolio.get_performance()`** to evaluate strategy effectiveness
6. **Adjust `config.enabled_strategies`** based on market regime

### Agent Decision Loop
```python
config = BotConfig.from_file("bot_config.json")
config.auto_trade = True
bot = OptionsBot(config)

while agent_is_running:
    orders = bot.run_once()

    perf = bot.portfolio.get_performance()
    if perf.max_drawdown > 0.10:
        bot.config.auto_trade = False  # pause trading

    if perf.win_rate < 0.30 and perf.total_trades > 20:
        # re-evaluate strategy mix
        pass

    time.sleep(config.scan_interval)
```

## File Structure

```
options_bot/
├── __init__.py          # Package init
├── __main__.py          # CLI entry point
├── bot.py               # Main orchestrator
├── config.py            # Configuration management
├── models.py            # Core data models
├── pricing/
│   ├── black_scholes.py # Black-Scholes pricing
│   └── greeks.py        # Greeks calculations
├── strategies/
│   ├── base.py          # Strategy base class
│   ├── single_leg.py    # Long/short calls and puts
│   ├── spreads.py       # Vertical spreads
│   └── multi_leg.py     # Straddles, strangles, iron condors
├── risk/
│   └── manager.py       # Risk management engine
├── signals/
│   └── generator.py     # Technical analysis signals
├── portfolio/
│   └── tracker.py       # Portfolio tracking and P&L
└── data/
    ├── market_data.py   # Market data providers
    └── broker.py        # Broker integrations
```
