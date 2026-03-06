# Alpha-SDK Bot Techniques Analysis & Edge Hypotheses

## What alpha-sdk Does

**@alpha-arcade/sdk** is a TypeScript SDK for trading on Alpha Arcade, a decentralized
prediction market on Algorand. It provides primitives for placing limit/market orders,
reading on-chain orderbooks, managing positions (split/merge/claim), and building
automated trading bots.

---

## Techniques Used in the SDK

### 1. Polling Loop Architecture
- `setInterval()` at 60-second intervals
- Scans first 10 live markets per cycle
- Calls `getOrderbook()` on each market

### 2. Static Threshold Signal
- Hardcoded `PRICE_THRESHOLD` ($0.20) triggers buys on YES tokens priced below it
- No probabilistic model, no external data, no adaptation

### 3. Complementary Order Matching
- Exploits the binary invariant: `YES_price + NO_price = $1.00`
- A YES buy at $0.60 can match a NO buy at $0.40 (hidden liquidity)
- Greedy best-price-first fill with partial fills

### 4. Atomic Transactions
- Algorand `AtomicTransactionComposer` for all-or-nothing execution
- Escrow-based non-custodial order model

### 5. Parimutuel Fee Structure
- `fee = feeBase * quantity * price * (1 - price)`
- Fees peak at p=0.50, approach zero at extremes (0 or 1)

### 6. Dual Data Source
- On-chain state decoding (no API key needed) vs REST API (richer data)
- Automatic fallback

---

## What's Weak / Where the SDK Bot Leaves Money on the Table

| Weakness | Detail |
|----------|--------|
| **No real signal** | A static $0.20 threshold is not alpha. It's a demo, not a strategy. |
| **No external data** | The bot never looks outside the chain. Prediction markets are priced by information -- ignoring the world is the biggest gap. |
| **Slow polling** | 60-second intervals on a 3.3-second block time chain. You're always late. |
| **No position management** | No stop-loss, no take-profit, no portfolio-level risk. Buys and holds until resolution. |
| **No market making** | Only takes liquidity (market orders). Never provides it. |
| **No cross-market logic** | Markets are treated independently. Correlated markets aren't exploited. |
| **No fee optimization** | Doesn't consider the `p*(1-p)` fee curve when sizing or timing trades. |

---

## Hypotheses: What We Could Do Differently for Real Edge

### Hypothesis 1: Information-Driven Pricing Model
**The single biggest edge opportunity.**

The SDK bot has zero external information. Build a system that:
- Ingests real-time news feeds, social sentiment, sports data, election polls, weather APIs -- whatever is relevant to the market category
- Runs a lightweight Bayesian updater or LLM-based probability estimator to produce a "fair value" probability for each market
- Compares fair value to current orderbook mid-price
- Only trades when `|fair_value - market_price| > threshold + fees`

**Why this works:** Prediction markets are information markets. Everyone using the SDK's demo bot is blind to the world. Even a mediocre external signal dominates a price-only strategy.

### Hypothesis 2: Latency Advantage via WebSocket/Subscription Model
**Replace polling with event-driven execution.**

- Subscribe to Algorand node events or use an indexer WebSocket to detect new blocks and orderbook changes in near-real-time
- React within 1-2 blocks (~4-7 seconds) instead of 60 seconds
- Priority: detect when a large order hits the book or gets cancelled -- these are the moments where mispricing appears and vanishes

**Why this works:** On a 3.3s block time, a 60s poller misses ~18 blocks of opportunity. Being event-driven means you see and act on orderbook changes before other pollers do.

### Hypothesis 3: Automated Market Making with Dynamic Spread
**Flip from taker to maker.**

- Post limit orders on both sides of each market: bid at `mid - spread/2`, ask at `mid + spread/2`
- Dynamically adjust spread based on:
  - Volatility (wider spread when uncertainty is high)
  - Inventory skew (bias quotes away from accumulated position)
  - Time to resolution (tighten as expiry approaches and outcomes become clearer)
  - Fee curve: `p*(1-p)` means fees are lowest at extremes -- MM is most profitable there

**Why this works:** Most participants are directional (they have opinions). Market makers profit from the bid-ask spread regardless of direction. The fee structure actually rewards this at extreme prices.

### Hypothesis 4: Cross-Market and Split/Merge Arbitrage
**Exploit structural pricing inconsistencies.**

Two concrete strategies:

**A. Split/Merge Arb:**
- Monitor `YES_ask + NO_ask` and `YES_bid + NO_bid` across each market
- If `YES_ask + NO_ask < $1.00 - fees`: buy both, merge for risk-free profit
- If `YES_bid + NO_bid > $1.00 + fees`: split USDC, sell both sides
- This is pure arbitrage -- zero market risk

**B. Correlated Market Arb:**
- Detect markets with logically linked outcomes (e.g., "Team A wins championship" vs "Team A wins semifinal")
- If `P(championship) > P(semifinal)`, that's a logical impossibility -- trade accordingly
- Use the multi-choice market grouping already in the SDK as a starting point

**Why this works:** These are risk-free or near-risk-free. The SDK already has `splitPosition()` and `mergePosition()` built in. Nobody appears to be running this systematically.

### Hypothesis 5: Kelly Criterion Position Sizing
**Size bets optimally instead of fixed quantities.**

- Use Kelly fraction: `f* = (p*b - q) / b` where p = estimated probability, b = payout odds, q = 1-p
- Apply fractional Kelly (e.g., half-Kelly) to reduce variance
- Cap maximum position per market as a percentage of bankroll
- Account for the `p*(1-p)` fee structure in the edge calculation

**Why this works:** The SDK bot uses a fixed quantity with no risk management. Kelly-optimal sizing maximizes long-run growth rate. Even if your signal is only slightly better than the market, correct sizing turns a marginal edge into compounding returns.

### Hypothesis 6: Complementary Liquidity Exploitation Bot
**Specifically target the hidden liquidity the matching algorithm exposes.**

- Scan orderbooks for situations where direct liquidity is thin but complementary liquidity is deep
- Example: YES ask book is empty at $0.55, but NO bid book has large orders at $0.45
  - These are equivalent via the complementary matching
  - Most human traders don't see this liquidity
  - Place orders that specifically exploit the complementary fill path

**Why this works:** The matching engine supports it, but the UI probably doesn't surface complementary depth well. A bot that understands both sides of the book has an informational advantage over manual traders.

### Hypothesis 7: Resolution Timing Plays
**Trade the meta-game of when markets resolve.**

- As market expiry approaches, prices should converge to 0 or 1
- Markets where the outcome is "basically known" but price hasn't fully converged offer near-risk-free returns
- Monitor news/results APIs and be first to trade when an outcome becomes certain but the market hasn't resolved yet
- Target the spread between "outcome is known" and "market officially resolves"

**Why this works:** There's a latency gap between real-world events and on-chain market resolution. During this gap, tokens for known outcomes trade at a discount to their $1.00 redemption value. Automated monitoring + fast execution captures this.

---

## Priority Ranking

| Priority | Hypothesis | Expected Edge | Complexity | Risk |
|----------|-----------|---------------|------------|------|
| **1** | H4: Split/Merge Arb | High (risk-free) | Low | Minimal |
| **2** | H1: Information-Driven Pricing | Highest | Medium-High | Moderate |
| **3** | H2: Latency (Event-Driven) | Medium | Medium | Low |
| **4** | H7: Resolution Timing | Medium-High | Medium | Low |
| **5** | H3: Market Making | Medium | High | Moderate |
| **6** | H5: Kelly Sizing | Medium | Low | Low |
| **7** | H6: Complementary Liquidity | Low-Medium | Medium | Low |

**Recommended starting point:** Implement H4 (Split/Merge Arb) first -- it's closest to risk-free, lowest complexity, and the SDK already has the primitives. Then layer H1 (information model) on top for directional trades, sized with H5 (Kelly).

---

## Implementation Notes

- The local `Ed` repo is an **AlgoKit Beaker template** for Algorand smart contracts -- it provides the scaffolding to build and deploy contracts that could interact with Alpha Arcade's on-chain programs
- The alpha-sdk's contract ABIs (`market_app.ts`, `escrow_app.ts`, `matcher_app.ts`) are the interface to Alpha Arcade's deployed contracts
- A production bot would combine: alpha-sdk for execution + external data APIs for signal + proper risk management for sizing
