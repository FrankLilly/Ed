# Options Trading Bot — AI Agent Skills

## The Edge

This bot makes money through **variance risk premium (VRP)** — the
statistically proven tendency for implied volatility to overstate
realized volatility ~83% of the time on major indices. We sell
overpriced premium and let mean reversion do the work.

Secondary edges:
- **IV rank mean reversion** — high IV rank reverts, sell premium when rich
- **Put skew richness** — OTM puts are chronically overpriced (crash demand)
- **Earnings IV crush** — IV spikes before earnings, collapses after
- **Term structure** — backwardation signals fear = sell front-month
- **Unusual flow** — piggyback institutional conviction

## Architecture

```
Signal Layer (what to trade)
├── EdgeSignalGenerator   — VRP, IV rank, skew, term structure, vol regime
├── FlowScanner           — unusual options activity, put/call ratio
├── EarningsCalendar      — pre/post earnings signals, event avoidance
└── Signal combination    — confluence detection, strength boosting

Strategy Layer (how to trade)
├── Iron Condor / Butterfly — neutral premium selling (primary)
├── Bull Put / Bear Call    — directional credit spreads
├── Straddle / Strangle     — volatility plays (long or short)
└── Single legs             — directional (calls/puts)

Risk Layer (how much to trade)
├── Per-trade risk caps     — max 5% portfolio per trade
├── Total exposure limits   — max 20% total portfolio risk
├── Daily loss breaker      — stop at 3% daily loss
├── Defined-risk only       — no naked options by default
└── Liquidity filters       — bid-ask spread, volume, OI checks

Execution Layer (when to act)
├── Position Manager        — take profit 50%, stop loss 2x, DTE exit
├── Roll engine             — roll tested positions for more premium
├── Broker (Alpaca/Paper)   — paper or live order submission
└── Portfolio Tracker       — P&L, Sharpe, drawdown, equity curve

Validation Layer (prove it works)
├── Backtesting engine      — GBM + jump diffusion price paths
├── Monte Carlo simulation  — distribution of outcomes across N paths
└── Vol surface modeling    — SVI fit, mispricing detection
```

## Quick Start

### Paper Trading (no API keys needed)
```bash
# Single scan cycle
python -m options_bot --once --auto --capital 10000

# Continuous paper trading
python -m options_bot --auto --capital 25000 --symbols SPY QQQ AAPL

# Generate config file
python -m options_bot --generate-config bot_config.json
```

### Backtest First (always do this)
```bash
# Monte Carlo: 100 simulations of iron condor over 1 year
python -m options_bot.run_backtest -s iron_condor --paths 100

# Detailed single-path backtest
python -m options_bot.run_backtest -s iron_condor --single

# Test with VRP edge: IV=25%, RV=18% (realistic)
python -m options_bot.run_backtest -s iron_condor --iv 0.25 --vol 0.18

# Compare strategies
python -m options_bot.run_backtest -s bull_put_spread --paths 200
python -m options_bot.run_backtest -s short_strangle --paths 200
```

### Live Trading (requires Alpaca)
```bash
export ALPACA_API_KEY=your_key
export ALPACA_SECRET_KEY=your_secret

# Paper first
python -m options_bot --auto --capital 10000

# Then live (requires typing CONFIRM)
python -m options_bot --live --auto --capital 10000
```

## Agent Operation Mode

### Autonomous Loop
```python
from options_bot.bot import OptionsBot
from options_bot.config import BotConfig

config = BotConfig.from_file("bot_config.json")
config.auto_trade = True
bot = OptionsBot(config)

while True:
    orders = bot.run_once()

    # Monitor performance
    perf = bot.portfolio.get_performance()
    if perf.max_drawdown > 0.10:
        bot.config.auto_trade = False  # circuit breaker

    time.sleep(config.scan_interval)
```

### Signal Analysis (read-only)
```python
from options_bot.signals.edge_signals import EdgeSignalGenerator
from options_bot.data.market_data import SimulatedMarketData

data = SimulatedMarketData()
signals = EdgeSignalGenerator(data)

for symbol in ["SPY", "QQQ", "AAPL"]:
    signal = signals.get_best_signal(symbol)
    if signal:
        print(f"{symbol}: {signal.signal_type.value} "
              f"(strength={signal.strength:.2f}) — {signal.reason}")
```

### Backtest Validation
```python
from options_bot.backtesting.engine import BacktestEngine
from options_bot.strategies.multi_leg import IronCondor

engine = BacktestEngine(initial_capital=100_000)
mc = engine.run_monte_carlo(
    strategy=IronCondor(),
    num_simulations=500,
    iv=0.25,        # what we sell
    annual_vol=0.18, # what actually happens (VRP = 7%)
)
print(f"Profitable paths: {mc['profitable_paths_pct']:.0%}")
print(f"Avg return: {mc['avg_return']:.1%}")
```

## Configuration

### Risk Limits (defaults)
| Parameter | Default | Description |
|---|---|---|
| `max_portfolio_risk_pct` | 5% | Max risk per trade |
| `max_total_risk_pct` | 20% | Max total portfolio risk |
| `max_positions` | 10 | Max concurrent positions |
| `max_daily_trades` | 5 | Daily trade limit |
| `max_daily_loss` | 3% | Daily loss circuit breaker |
| `require_defined_risk` | True | Block naked options |
| `min_days_to_expiry` | 7 | Don't trade near expiry |
| `max_days_to_expiry` | 60 | Don't buy far-dated |

### Position Management
| Parameter | Default | Why |
|---|---|---|
| Take profit | 50% of max | Captures most premium, avoids gamma risk |
| Stop loss | 2x credit | Limits tail losses |
| Min DTE close | 7 days | Gamma risk accelerates |
| Roll threshold | 14 DTE | Roll for new premium before decay |
| Delta defense | 0.30 | Adjust when tested |

## File Structure

```
options_bot/
├── __init__.py
├── __main__.py              # CLI entry point
├── bot.py                   # Main orchestrator (edge-based)
├── config.py                # Configuration
├── models.py                # Data models
├── run_backtest.py          # Backtest runner
├── pricing/
│   ├── black_scholes.py     # BS pricing + IV solver
│   ├── greeks.py            # Greeks calculations
│   └── vol_surface.py       # SVI vol surface + VRP analyzer
├── strategies/
│   ├── base.py              # Strategy base class
│   ├── single_leg.py        # Long/short calls and puts
│   ├── spreads.py           # Vertical spreads
│   ├── multi_leg.py         # Iron condors, straddles, strangles
│   └── position_mgmt.py     # Rolling, adjustments, exits
├── risk/
│   └── manager.py           # Risk management engine
├── signals/
│   ├── generator.py         # Basic TA signals (legacy)
│   ├── edge_signals.py      # VRP, IV rank, skew, regime signals
│   ├── earnings.py          # Earnings calendar + IV crush
│   └── flow.py              # Unusual options flow scanner
├── portfolio/
│   └── tracker.py           # P&L, Sharpe, drawdown tracking
├── backtesting/
│   └── engine.py            # GBM backtest + Monte Carlo
└── data/
    ├── market_data.py       # Market data providers
    └── broker.py            # Broker integrations
```
