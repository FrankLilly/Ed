/**
 * ╔═══════════════════════════════════════════════════════════════════════════╗
 * ║                     THE LIFECYCLE PREDATOR                               ║
 * ║                                                                          ║
 * ║  An original strategy that treats every prediction market as having a    ║
 * ║  lifecycle — and applies the optimal strategy for each phase.            ║
 * ║                                                                          ║
 * ║  Phase 1: NEWBORN    → First-mover market making (widest spread)         ║
 * ║  Phase 2: REWARDED   → Reward-farming MM (quote within reward distance)  ║
 * ║  Phase 3: MATURE     → Tight MM + inventory management                  ║
 * ║  Phase 4: CONVERGENT → Resolution sniper (buy known outcomes cheaply)    ║
 * ║  Phase 5: DEAD       → Skip (don't waste capital)                       ║
 * ║                                                                          ║
 * ║  The bot dynamically allocates a $100 bankroll to whichever markets     ║
 * ║  are in the most profitable phase, maximizing capital efficiency.        ║
 * ╚═══════════════════════════════════════════════════════════════════════════╝
 */

import algosdk from "algosdk";
import { AlphaClient } from "@alpha-arcade/sdk";
import type { Market, Orderbook, OrderbookEntry } from "@alpha-arcade/sdk";

// ==========================================================================
// Configuration
// ==========================================================================

const ALGOD_URL = "https://mainnet-api.algonode.cloud";
const INDEXER_URL = "https://mainnet-idx.algonode.cloud";
const MATCHER_APP_ID = 741347297;
const USDC_ASSET_ID = 31566704;
const MICRO = 1_000_000; // $1.00 = 1,000,000 microunits

// --- Bankroll ---
const TOTAL_BANKROLL = 100 * MICRO; // $100 in microunits
const MAX_PER_MARKET = 25 * MICRO; // Max $25 per market (diversification)
const MIN_ORDER_SIZE = 1 * MICRO; // Minimum $1 order

// --- Timing ---
const POLL_INTERVAL_MS = 4_000; // ~1 Algorand block
const ORDER_REFRESH_MS = 30_000; // Refresh quotes every 30s
const CONVERGENCE_WINDOW_S = 3600 * 24; // 24h before resolution = convergence phase

// --- Strategy Thresholds ---
const NEWBORN_MAX_VOLUME = 50 * MICRO; // Market with < $50 volume = newborn
const NEWBORN_SPREAD = 120_000; // 12¢ spread on each side for newborns
const REWARD_SPREAD_BUFFER = 5_000; // Stay 0.5¢ inside reward distance
const MATURE_SPREAD = 50_000; // 5¢ spread for mature markets
const CONVERGENCE_THRESHOLD = 900_000; // Buy YES if > 90¢ implied but trading < 90¢
const CONVERGENCE_MIN_DISCOUNT = 30_000; // Need at least 3¢ discount to snipe
const DEAD_VOLUME_THRESHOLD = 5 * MICRO; // < $5 volume AND far from resolution = dead

// --- Risk ---
const MAX_INVENTORY_SKEW = 10 * MICRO; // Max 10 shares net long/short any position
const INVENTORY_BIAS_FACTOR = 0.3; // How aggressively to skew quotes on inventory

// --- Mode ---
const DRY_RUN = true; // Set to false for live trading

// ==========================================================================
// Types
// ==========================================================================

type LifecyclePhase = "NEWBORN" | "REWARDED" | "MATURE" | "CONVERGENT" | "DEAD";

type MarketState = {
  market: Market;
  phase: LifecyclePhase;
  orderbook: Orderbook;
  midPrice: number; // microunits
  spread: number; // current market spread
  optimalSpread: number; // what we'd quote
  capitalAllocation: number; // how much $ to deploy here
  priority: number; // higher = allocate first
  activeOrders: ActiveOrder[];
  inventory: { yes: number; no: number }; // current position
};

type ActiveOrder = {
  escrowAppId: number;
  marketAppId: number;
  position: 0 | 1;
  price: number;
  quantity: number;
  isBuying: boolean;
  placedAt: number; // timestamp
};

type BotStats = {
  totalPnl: number;
  spreadsCaptured: number;
  rewardsEarned: number; // estimated ALPHA
  resolutionSnipes: number;
  ordersPlaced: number;
  ordersFilled: number;
  cycleCount: number;
};

// ==========================================================================
// Helpers
// ==========================================================================

function fmt(micro: number): string {
  return `$${(micro / MICRO).toFixed(4)}`;
}

function fmtPct(micro: number): string {
  return `${((micro / MICRO) * 100).toFixed(1)}%`;
}

function now(): number {
  return Math.floor(Date.now() / 1000);
}

function bestBid(entries: OrderbookEntry[]): OrderbookEntry | null {
  return entries.length === 0
    ? null
    : entries.reduce((b, e) => (e.price > b.price ? e : b));
}

function bestAsk(entries: OrderbookEntry[]): OrderbookEntry | null {
  return entries.length === 0
    ? null
    : entries.reduce((b, e) => (e.price < b.price ? e : b));
}

function midPrice(orderbook: Orderbook): number {
  const bid = bestBid(orderbook.yes.bids);
  const ask = bestAsk(orderbook.yes.asks);
  if (bid && ask) return Math.floor((bid.price + ask.price) / 2);
  if (bid) return bid.price;
  if (ask) return ask.price;
  return 500_000; // default 50¢ if completely empty
}

function currentSpread(orderbook: Orderbook): number {
  const bid = bestBid(orderbook.yes.bids);
  const ask = bestAsk(orderbook.yes.asks);
  if (bid && ask) return ask.price - bid.price;
  return MICRO; // infinite spread if one side is empty
}

function calculateFee(
  quantity: number,
  price: number,
  feeBase: number,
): number {
  const q = quantity / MICRO;
  const p = price / MICRO;
  const fb = feeBase / MICRO;
  return Math.ceil(fb * q * p * (1 - p) * MICRO);
}

// ==========================================================================
// Phase 1: LIFECYCLE CLASSIFIER
// ==========================================================================

function classifyPhase(market: Market, orderbook: Orderbook): LifecyclePhase {
  const timeToResolution = market.endTs - now();
  const volume = market.volume ?? 0;
  const hasRewards =
    (market.totalRewards ?? 0) > 0 &&
    (market.rewardsPaidOut ?? 0) < (market.totalRewards ?? 0);

  // Already resolved or very close
  if (market.isResolved) return "DEAD";

  // Within 24h of resolution — convergence snipe territory
  if (timeToResolution <= CONVERGENCE_WINDOW_S && timeToResolution > 0) {
    return "CONVERGENT";
  }

  // Dead: low volume, far from resolution, no rewards
  if (
    volume < DEAD_VOLUME_THRESHOLD &&
    timeToResolution > CONVERGENCE_WINDOW_S * 7 &&
    !hasRewards
  ) {
    return "DEAD";
  }

  // Newborn: very low volume, book is thin
  if (volume < NEWBORN_MAX_VOLUME) {
    return "NEWBORN";
  }

  // Has active liquidity rewards
  if (hasRewards) {
    return "REWARDED";
  }

  // Everything else
  return "MATURE";
}

function phasePriority(phase: LifecyclePhase): number {
  // Higher = gets capital first
  switch (phase) {
    case "CONVERGENT":
      return 100; // Near-risk-free, snipe known outcomes
    case "REWARDED":
      return 80; // Earn ALPHA + spread
    case "NEWBORN":
      return 60; // Wide spreads, first-mover
    case "MATURE":
      return 40; // Tighter spreads but steady
    case "DEAD":
      return 0; // Skip
  }
}

// ==========================================================================
// Phase 2: OPTIMAL SPREAD CALCULATOR
// ==========================================================================

function calculateOptimalSpread(
  state: MarketState,
): { bidPrice: number; askPrice: number; quantity: number } {
  const { market, phase, orderbook, midPrice: mid, inventory } = state;

  let halfSpread: number;
  let quantity = Math.min(state.capitalAllocation, MAX_PER_MARKET);

  switch (phase) {
    case "NEWBORN":
      // Wide spread — we're the only game in town. Capture maximum edge.
      halfSpread = NEWBORN_SPREAD;
      // Smaller size on newborns (less liquid, harder to exit)
      quantity = Math.min(quantity, 5 * MICRO);
      break;

    case "REWARDED": {
      // Quote just inside the reward spread distance to qualify for ALPHA rewards
      const rewardDist = market.rewardsSpreadDistance ?? 50_000; // default 5¢
      halfSpread = Math.max(rewardDist - REWARD_SPREAD_BUFFER, 10_000);
      // Size at minimum required for rewards
      const minContracts = market.rewardsMinContracts ?? 1 * MICRO;
      quantity = Math.max(quantity, minContracts);
      break;
    }

    case "MATURE":
      // Tight spread — compete for fills
      halfSpread = MATURE_SPREAD;
      break;

    case "CONVERGENT":
      // Not market-making — we're sniping. Handled separately.
      halfSpread = 0;
      quantity = 0;
      break;

    case "DEAD":
      halfSpread = 0;
      quantity = 0;
      break;
  }

  // --- Inventory skew ---
  // If we're long YES, push our YES ask lower (more eager to sell)
  // and our YES bid lower (less eager to buy more)
  const netYes = inventory.yes - inventory.no;
  const skew = Math.floor(netYes * INVENTORY_BIAS_FACTOR);

  let bidPrice = Math.max(mid - halfSpread - skew, 10_000); // floor at 1¢
  let askPrice = Math.min(mid + halfSpread - skew, 990_000); // cap at 99¢

  // Ensure bid < ask
  if (bidPrice >= askPrice) {
    bidPrice = mid - 10_000;
    askPrice = mid + 10_000;
  }

  // Clamp quantity
  quantity = Math.max(Math.min(quantity, MAX_PER_MARKET), 0);

  return { bidPrice, askPrice, quantity };
}

// ==========================================================================
// Phase 3: CONVERGENCE SNIPER
// ==========================================================================

type SnipeOpportunity = {
  market: Market;
  position: 0 | 1; // which side to buy
  currentPrice: number; // what it's trading at
  impliedValue: number; // what we think it's worth (near $1 or $0)
  discount: number; // how much cheaper than implied
  quantity: number;
};

function detectSnipeOpportunity(
  market: Market,
  orderbook: Orderbook,
  budget: number,
): SnipeOpportunity | null {
  // Look at the YES probability from the API (if available)
  const yesProb = market.yesProb ?? midPrice(orderbook) / MICRO;

  // Is this market basically decided?
  if (yesProb > CONVERGENCE_THRESHOLD / MICRO) {
    // YES is very likely — buy YES at a discount
    const ask = bestAsk(orderbook.yes.asks);
    if (!ask) return null;

    const discount = MICRO - ask.price; // How far below $1 the YES token trades
    if (discount < CONVERGENCE_MIN_DISCOUNT) return null; // Not enough discount

    return {
      market,
      position: 1,
      currentPrice: ask.price,
      impliedValue: MICRO,
      discount,
      quantity: Math.min(ask.quantity, budget),
    };
  }

  if (yesProb < (MICRO - CONVERGENCE_THRESHOLD) / MICRO) {
    // NO is very likely — buy NO at a discount
    const ask = bestAsk(orderbook.no.asks);
    if (!ask) return null;

    const discount = MICRO - ask.price;
    if (discount < CONVERGENCE_MIN_DISCOUNT) return null;

    return {
      market,
      position: 0,
      currentPrice: ask.price,
      impliedValue: MICRO,
      discount,
      quantity: Math.min(ask.quantity, budget),
    };
  }

  return null;
}

// ==========================================================================
// Phase 4: CAPITAL ALLOCATOR
// ==========================================================================

function allocateCapital(states: MarketState[]): MarketState[] {
  // Sort by priority (highest first)
  const active = states
    .filter((s) => s.phase !== "DEAD")
    .sort((a, b) => b.priority - a.priority);

  let remaining = TOTAL_BANKROLL;

  for (const state of active) {
    if (remaining <= MIN_ORDER_SIZE) {
      state.capitalAllocation = 0;
      continue;
    }

    // Allocate proportional to priority, capped per market
    const allocation = Math.min(
      MAX_PER_MARKET,
      remaining,
      // Give convergent plays more capital (they're near risk-free)
      state.phase === "CONVERGENT" ? MAX_PER_MARKET : MAX_PER_MARKET / 2,
    );

    state.capitalAllocation = allocation;
    remaining -= allocation;
  }

  return states;
}

// ==========================================================================
// Phase 5: ORDER MANAGER
// ==========================================================================

// In-memory order tracking (production would persist this)
const activeOrdersByMarket = new Map<number, ActiveOrder[]>();
const inventoryByMarket = new Map<number, { yes: number; no: number }>();

async function cancelStaleOrders(
  client: AlphaClient,
  marketAppId: number,
  orders: ActiveOrder[],
): Promise<void> {
  const stale = orders.filter((o) => now() - o.placedAt > ORDER_REFRESH_MS / 1000);

  for (const order of stale) {
    try {
      if (!DRY_RUN) {
        await client.cancelOrder({
          marketAppId: order.marketAppId,
          escrowAppId: order.escrowAppId,
          orderOwner: "", // filled by SDK from activeAddress
        });
      }
      console.log(
        `  [CANCEL] ${order.isBuying ? "BUY" : "SELL"} ${order.position === 1 ? "YES" : "NO"} @ ${fmt(order.price)}`,
      );
    } catch (err) {
      console.error(`  [CANCEL ERROR]`, err);
    }
  }
}

async function placeMMOrders(
  client: AlphaClient,
  state: MarketState,
): Promise<ActiveOrder[]> {
  const { bidPrice, askPrice, quantity } = calculateOptimalSpread(state);
  if (quantity <= 0) return [];

  const newOrders: ActiveOrder[] = [];
  const feeBase = state.market.feeBase ?? 70_000;

  // --- YES side: post bid (buy YES) and ask (sell YES) ---
  const yesBidQty = Math.min(quantity, MAX_PER_MARKET);
  const yesAskQty = Math.min(quantity, state.inventory.yes); // can only sell what we hold

  if (yesBidQty >= MIN_ORDER_SIZE) {
    const fee = calculateFee(yesBidQty, bidPrice, feeBase);
    console.log(
      `  [${state.phase}] BID YES @ ${fmt(bidPrice)} x${(yesBidQty / MICRO).toFixed(1)} (fee: ${fmt(fee)})`,
    );

    if (!DRY_RUN) {
      try {
        const result = await client.createLimitOrder({
          marketAppId: state.market.marketAppId,
          position: 1,
          price: bidPrice,
          quantity: yesBidQty,
          isBuying: true,
        });
        newOrders.push({
          escrowAppId: result.escrowAppId,
          marketAppId: state.market.marketAppId,
          position: 1,
          price: bidPrice,
          quantity: yesBidQty,
          isBuying: true,
          placedAt: now(),
        });
      } catch (err) {
        console.error(`  [ORDER ERROR] YES bid:`, err);
      }
    }
  }

  // --- NO side: post bid (buy NO at complementary price) ---
  const noBidPrice = MICRO - askPrice; // complementary: if YES ask is 60¢, NO bid is 40¢
  const noBidQty = Math.min(quantity, MAX_PER_MARKET);

  if (noBidQty >= MIN_ORDER_SIZE && noBidPrice > 10_000) {
    const fee = calculateFee(noBidQty, noBidPrice, feeBase);
    console.log(
      `  [${state.phase}] BID NO  @ ${fmt(noBidPrice)} x${(noBidQty / MICRO).toFixed(1)} (fee: ${fmt(fee)})`,
    );

    if (!DRY_RUN) {
      try {
        const result = await client.createLimitOrder({
          marketAppId: state.market.marketAppId,
          position: 0,
          price: noBidPrice,
          quantity: noBidQty,
          isBuying: true,
        });
        newOrders.push({
          escrowAppId: result.escrowAppId,
          marketAppId: state.market.marketAppId,
          position: 0,
          price: noBidPrice,
          quantity: noBidQty,
          isBuying: true,
          placedAt: now(),
        });
      } catch (err) {
        console.error(`  [ORDER ERROR] NO bid:`, err);
      }
    }
  }

  return newOrders;
}

async function executeSnipe(
  client: AlphaClient,
  snipe: SnipeOpportunity,
): Promise<void> {
  console.log(
    `\n  [SNIPE] "${snipe.market.title}"` +
      `\n    Buy ${snipe.position === 1 ? "YES" : "NO"} @ ${fmt(snipe.currentPrice)}` +
      `\n    Implied value: ${fmt(snipe.impliedValue)}` +
      `\n    Discount: ${fmt(snipe.discount)} (${fmtPct(snipe.discount)})` +
      `\n    Qty: ${(snipe.quantity / MICRO).toFixed(1)} shares`,
  );

  if (!DRY_RUN) {
    try {
      await client.createMarketOrder({
        marketAppId: snipe.market.marketAppId,
        position: snipe.position,
        price: snipe.currentPrice,
        quantity: snipe.quantity,
        isBuying: true,
        slippage: 20_000, // 2¢ slippage tolerance
      });
      console.log(`  [SNIPE EXECUTED]`);
    } catch (err) {
      console.error(`  [SNIPE ERROR]`, err);
    }
  }
}

// ==========================================================================
// Main Loop
// ==========================================================================

async function cycle(client: AlphaClient, stats: BotStats): Promise<void> {
  stats.cycleCount++;

  // 1. Fetch all markets (with rewards data if API key provided)
  let markets: Market[];
  try {
    markets = await client.getLiveMarkets();
  } catch (err) {
    console.error("[ERROR] Failed to fetch markets:", err);
    return;
  }

  // Also fetch reward markets for richer data
  let rewardMarkets: Market[] = [];
  try {
    rewardMarkets = await client.getRewardMarkets();
  } catch {
    // API key may not be set — that's ok
  }

  // Merge reward data into main market list
  const rewardMap = new Map(rewardMarkets.map((m) => [m.marketAppId, m]));
  for (const market of markets) {
    const reward = rewardMap.get(market.marketAppId);
    if (reward) {
      market.totalRewards = reward.totalRewards;
      market.rewardsPaidOut = reward.rewardsPaidOut;
      market.rewardsSpreadDistance = reward.rewardsSpreadDistance;
      market.rewardsMinContracts = reward.rewardsMinContracts;
      market.lastRewardAmount = reward.lastRewardAmount;
      market.lastRewardTs = reward.lastRewardTs;
    }
  }

  console.log(
    `\n[${new Date().toISOString()}] Cycle #${stats.cycleCount} — ${markets.length} markets`,
  );

  // 2. Build state for each market
  const states: MarketState[] = [];
  for (const market of markets) {
    let orderbook: Orderbook;
    try {
      orderbook = await client.getOrderbook(market.marketAppId);
    } catch {
      continue;
    }

    const phase = classifyPhase(market, orderbook);
    const mid = midPrice(orderbook);
    const spread = currentSpread(orderbook);
    const inv = inventoryByMarket.get(market.marketAppId) ?? {
      yes: 0,
      no: 0,
    };
    const orders = activeOrdersByMarket.get(market.marketAppId) ?? [];

    states.push({
      market,
      phase,
      orderbook,
      midPrice: mid,
      spread,
      optimalSpread: 0,
      capitalAllocation: 0,
      priority: phasePriority(phase),
      activeOrders: orders,
      inventory: inv,
    });
  }

  // 3. Allocate capital across markets
  allocateCapital(states);

  // 4. Print dashboard
  const phaseCount = { NEWBORN: 0, REWARDED: 0, MATURE: 0, CONVERGENT: 0, DEAD: 0 };
  for (const s of states) phaseCount[s.phase]++;

  console.log(
    `  Phases: ` +
      `NEWBORN=${phaseCount.NEWBORN} ` +
      `REWARDED=${phaseCount.REWARDED} ` +
      `MATURE=${phaseCount.MATURE} ` +
      `CONVERGENT=${phaseCount.CONVERGENT} ` +
      `DEAD=${phaseCount.DEAD}`,
  );

  // 5. Execute strategy per phase
  for (const state of states) {
    if (state.phase === "DEAD" || state.capitalAllocation <= 0) continue;

    console.log(
      `\n  "${state.market.title}" [${state.phase}]` +
        `\n    Mid: ${fmt(state.midPrice)} | Spread: ${fmt(state.spread)} | Budget: ${fmt(state.capitalAllocation)}`,
    );

    // Cancel stale orders before placing new ones
    await cancelStaleOrders(client, state.market.marketAppId, state.activeOrders);

    if (state.phase === "CONVERGENT") {
      // --- Resolution sniper ---
      const snipe = detectSnipeOpportunity(
        state.market,
        state.orderbook,
        state.capitalAllocation,
      );
      if (snipe) {
        await executeSnipe(client, snipe);
        stats.resolutionSnipes++;
      }
    } else {
      // --- Market making (NEWBORN / REWARDED / MATURE) ---
      const newOrders = await placeMMOrders(client, state);
      activeOrdersByMarket.set(state.market.marketAppId, newOrders);
      stats.ordersPlaced += newOrders.length;

      if (state.phase === "REWARDED") {
        const remaining =
          (state.market.totalRewards ?? 0) - (state.market.rewardsPaidOut ?? 0);
        if (remaining > 0) {
          console.log(
            `    Reward pool: ${remaining.toFixed(0)} ALPHA remaining` +
              ` | Spread distance: ${fmt(state.market.rewardsSpreadDistance ?? 0)}` +
              ` | Min contracts: ${((state.market.rewardsMinContracts ?? 0) / MICRO).toFixed(1)}`,
          );
        }
      }
    }
  }

  // 6. Summary
  console.log(
    `\n  --- Cycle Summary ---` +
      `\n  Orders placed: ${stats.ordersPlaced}` +
      `\n  Snipes: ${stats.resolutionSnipes}` +
      `\n  Mode: ${DRY_RUN ? "DRY RUN" : "LIVE"}`,
  );
}

// ==========================================================================
// Entry Point
// ==========================================================================

function createClient(): AlphaClient {
  const mnemonic = process.env.ALGO_MNEMONIC;
  if (!mnemonic) throw new Error("Set ALGO_MNEMONIC env var");

  const account = algosdk.mnemonicToSecretKey(mnemonic);
  const algodClient = new algosdk.Algodv2("", ALGOD_URL, "");
  const indexerClient = new algosdk.Indexer("", INDEXER_URL, "");

  return new AlphaClient({
    algodClient,
    indexerClient,
    signer: algosdk.makeBasicAccountTransactionSigner(account),
    activeAddress: account.addr,
    matcherAppId: MATCHER_APP_ID,
    usdcAssetId: USDC_ASSET_ID,
    apiKey: process.env.ALPHA_API_KEY, // optional but unlocks reward data
  });
}

async function main(): Promise<void> {
  console.log("╔═══════════════════════════════════════════╗");
  console.log("║         THE LIFECYCLE PREDATOR            ║");
  console.log("╠═══════════════════════════════════════════╣");
  console.log(`║  Bankroll:    ${fmt(TOTAL_BANKROLL).padEnd(28)}║`);
  console.log(`║  Max/market:  ${fmt(MAX_PER_MARKET).padEnd(28)}║`);
  console.log(`║  Mode:        ${(DRY_RUN ? "DRY RUN" : "LIVE TRADING").padEnd(28)}║`);
  console.log(`║  Poll:        ${(POLL_INTERVAL_MS + "ms").padEnd(28)}║`);
  console.log("╚═══════════════════════════════════════════╝\n");

  const client = createClient();

  const stats: BotStats = {
    totalPnl: 0,
    spreadsCaptured: 0,
    rewardsEarned: 0,
    resolutionSnipes: 0,
    ordersPlaced: 0,
    ordersFilled: 0,
    cycleCount: 0,
  };

  // First cycle immediately
  await cycle(client, stats);

  // Then on interval
  setInterval(() => cycle(client, stats).catch(console.error), POLL_INTERVAL_MS);
}

main().catch(console.error);
