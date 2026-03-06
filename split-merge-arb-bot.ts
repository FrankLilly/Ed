/**
 * Split/Merge Arbitrage Bot for Alpha Arcade
 *
 * Scans all live prediction markets for mispricing between YES and NO tokens.
 * When YES_ask + NO_ask < $1.00 (minus fees): buys both, merges for profit.
 * When YES_bid + NO_bid > $1.00 (plus fees): splits USDC, sells both for profit.
 *
 * Zero directional risk — you never bet on an outcome.
 */

import algosdk from "algosdk";
import { AlphaClient } from "@alpha-arcade/sdk";
import type {
  Market,
  Orderbook,
  OrderbookEntry,
} from "@alpha-arcade/sdk";

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------

const ALGOD_URL = "https://mainnet-api.algonode.cloud";
const INDEXER_URL = "https://mainnet-idx.algonode.cloud";
const MATCHER_APP_ID = 741347297;
const USDC_ASSET_ID = 31566704;
const MICROUNITS = 1_000_000; // $1.00 = 1,000,000 microunits

// How often to scan (milliseconds)
const POLL_INTERVAL_MS = 4_000; // ~1 Algorand block

// Minimum profit per share (in microunits) after fees to execute
const MIN_PROFIT_THRESHOLD = 5_000; // $0.005 — half a cent per share

// Maximum shares to trade per arb opportunity
const MAX_QUANTITY = 10_000_000; // 10 shares

// Set true to actually execute trades; false = log-only dry run
const DRY_RUN = true;

// ---------------------------------------------------------------------------
// Setup
// ---------------------------------------------------------------------------

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
    apiKey: process.env.ALPHA_API_KEY,
  });
}

// ---------------------------------------------------------------------------
// Fee math (mirrors src/utils/fees.ts)
// ---------------------------------------------------------------------------

function calculateFee(
  quantity: number,
  price: number,
  feeBase: number,
): number {
  // fee = feeBase * quantity * price * (1 - price)
  // all values in microunits; feeBase, price divided by 1,000,000
  const q = quantity / MICROUNITS;
  const p = price / MICROUNITS;
  const fb = feeBase / MICROUNITS;
  return Math.ceil(fb * q * p * (1 - p) * MICROUNITS);
}

// ---------------------------------------------------------------------------
// Core arb detection
// ---------------------------------------------------------------------------

type ArbOpportunity = {
  market: Market;
  type: "BUY_MERGE" | "SPLIT_SELL";
  yesPrice: number;
  noPrice: number;
  quantity: number; // shares we can fill (limited by thinnest side)
  grossProfit: number; // before fees, in microunits
  totalFees: number;
  netProfit: number; // after fees, in microunits
};

function bestAsk(entries: OrderbookEntry[]): OrderbookEntry | null {
  if (entries.length === 0) return null;
  // asks sorted ascending by price — best ask is lowest
  return entries.reduce((best, e) => (e.price < best.price ? e : best));
}

function bestBid(entries: OrderbookEntry[]): OrderbookEntry | null {
  if (entries.length === 0) return null;
  // bids sorted descending by price — best bid is highest
  return entries.reduce((best, e) => (e.price > best.price ? e : best));
}

function detectBuyMergeArb(
  market: Market,
  orderbook: Orderbook,
  feeBase: number,
): ArbOpportunity | null {
  // Can we buy YES + NO for less than $1.00?
  const yesAsk = bestAsk(orderbook.yes.asks);
  const noAsk = bestAsk(orderbook.no.asks);
  if (!yesAsk || !noAsk) return null;

  const combinedCost = yesAsk.price + noAsk.price;
  if (combinedCost >= MICROUNITS) return null; // no arb

  // Quantity limited by the thinner side and our max
  const quantity = Math.min(yesAsk.quantity, noAsk.quantity, MAX_QUANTITY);

  const grossProfit = (MICROUNITS - combinedCost) * (quantity / MICROUNITS);
  const yesFee = calculateFee(quantity, yesAsk.price, feeBase);
  const noFee = calculateFee(quantity, noAsk.price, feeBase);
  const totalFees = yesFee + noFee;
  const netProfit = grossProfit - totalFees;

  if (netProfit < MIN_PROFIT_THRESHOLD * (quantity / MICROUNITS)) return null;

  return {
    market,
    type: "BUY_MERGE",
    yesPrice: yesAsk.price,
    noPrice: noAsk.price,
    quantity,
    grossProfit,
    totalFees,
    netProfit,
  };
}

function detectSplitSellArb(
  market: Market,
  orderbook: Orderbook,
  feeBase: number,
): ArbOpportunity | null {
  // Can we sell YES + NO for more than $1.00?
  const yesBid = bestBid(orderbook.yes.bids);
  const noBid = bestBid(orderbook.no.bids);
  if (!yesBid || !noBid) return null;

  const combinedValue = yesBid.price + noBid.price;
  if (combinedValue <= MICROUNITS) return null; // no arb

  const quantity = Math.min(yesBid.quantity, noBid.quantity, MAX_QUANTITY);

  const grossProfit = (combinedValue - MICROUNITS) * (quantity / MICROUNITS);
  const yesFee = calculateFee(quantity, yesBid.price, feeBase);
  const noFee = calculateFee(quantity, noBid.price, feeBase);
  const totalFees = yesFee + noFee;
  const netProfit = grossProfit - totalFees;

  if (netProfit < MIN_PROFIT_THRESHOLD * (quantity / MICROUNITS)) return null;

  return {
    market,
    type: "SPLIT_SELL",
    yesPrice: yesBid.price,
    noPrice: noBid.price,
    quantity,
    grossProfit,
    totalFees,
    netProfit,
  };
}

// ---------------------------------------------------------------------------
// Execution
// ---------------------------------------------------------------------------

async function executeBuyMerge(
  client: AlphaClient,
  arb: ArbOpportunity,
): Promise<void> {
  console.log(`  [EXECUTE] Buying YES @ ${fmt(arb.yesPrice)}...`);
  await client.createMarketOrder({
    marketAppId: arb.market.marketAppId,
    position: 1, // YES
    price: arb.yesPrice,
    quantity: arb.quantity,
    isBuying: true,
    slippage: 10_000, // $0.01 max slippage
  });

  console.log(`  [EXECUTE] Buying NO @ ${fmt(arb.noPrice)}...`);
  await client.createMarketOrder({
    marketAppId: arb.market.marketAppId,
    position: 0, // NO
    price: arb.noPrice,
    quantity: arb.quantity,
    isBuying: true,
    slippage: 10_000,
  });

  console.log(`  [EXECUTE] Merging ${arb.quantity / MICROUNITS} shares...`);
  await client.mergeShares({
    marketAppId: arb.market.marketAppId,
    amount: arb.quantity,
  });

  console.log(`  [DONE] Net profit: ${fmt(arb.netProfit)}`);
}

async function executeSplitSell(
  client: AlphaClient,
  arb: ArbOpportunity,
): Promise<void> {
  console.log(`  [EXECUTE] Splitting ${arb.quantity / MICROUNITS} USDC...`);
  await client.splitShares({
    marketAppId: arb.market.marketAppId,
    amount: arb.quantity,
  });

  console.log(`  [EXECUTE] Selling YES @ ${fmt(arb.yesPrice)}...`);
  await client.createMarketOrder({
    marketAppId: arb.market.marketAppId,
    position: 1, // YES
    price: arb.yesPrice,
    quantity: arb.quantity,
    isBuying: false,
    slippage: 10_000,
  });

  console.log(`  [EXECUTE] Selling NO @ ${fmt(arb.noPrice)}...`);
  await client.createMarketOrder({
    marketAppId: arb.market.marketAppId,
    position: 0, // NO
    price: arb.noPrice,
    quantity: arb.quantity,
    isBuying: false,
    slippage: 10_000,
  });

  console.log(`  [DONE] Net profit: ${fmt(arb.netProfit)}`);
}

// ---------------------------------------------------------------------------
// Main loop
// ---------------------------------------------------------------------------

function fmt(microunits: number): string {
  return `$${(microunits / MICROUNITS).toFixed(4)}`;
}

async function scan(client: AlphaClient): Promise<void> {
  const markets = await client.getLiveMarkets();
  console.log(`\n[${new Date().toISOString()}] Scanning ${markets.length} markets...`);

  for (const market of markets) {
    let orderbook: Orderbook;
    try {
      orderbook = await client.getOrderbook(market.marketAppId);
    } catch {
      continue; // skip markets we can't read
    }

    const feeBase = market.feeBase ?? 70_000; // default 7% if not specified

    // Check both arb directions
    const buyMerge = detectBuyMergeArb(market, orderbook, feeBase);
    const splitSell = detectSplitSellArb(market, orderbook, feeBase);

    if (buyMerge) {
      console.log(
        `\n  ARB FOUND (BUY+MERGE) on "${market.title}"`,
        `\n    YES ask: ${fmt(buyMerge.yesPrice)}  NO ask: ${fmt(buyMerge.noPrice)}`,
        `\n    Sum: ${fmt(buyMerge.yesPrice + buyMerge.noPrice)} < $1.00`,
        `\n    Qty: ${buyMerge.quantity / MICROUNITS} shares`,
        `\n    Gross: ${fmt(buyMerge.grossProfit)}  Fees: ${fmt(buyMerge.totalFees)}  Net: ${fmt(buyMerge.netProfit)}`,
      );
      if (!DRY_RUN) {
        try {
          await executeBuyMerge(client, buyMerge);
        } catch (err) {
          console.error("  [ERROR] Buy+Merge failed:", err);
        }
      }
    }

    if (splitSell) {
      console.log(
        `\n  ARB FOUND (SPLIT+SELL) on "${market.title}"`,
        `\n    YES bid: ${fmt(splitSell.yesPrice)}  NO bid: ${fmt(splitSell.noPrice)}`,
        `\n    Sum: ${fmt(splitSell.yesPrice + splitSell.noPrice)} > $1.00`,
        `\n    Qty: ${splitSell.quantity / MICROUNITS} shares`,
        `\n    Gross: ${fmt(splitSell.grossProfit)}  Fees: ${fmt(splitSell.totalFees)}  Net: ${fmt(splitSell.netProfit)}`,
      );
      if (!DRY_RUN) {
        try {
          await executeSplitSell(client, splitSell);
        } catch (err) {
          console.error("  [ERROR] Split+Sell failed:", err);
        }
      }
    }
  }
}

async function main(): Promise<void> {
  console.log("=== Split/Merge Arbitrage Bot ===");
  console.log(`Mode: ${DRY_RUN ? "DRY RUN (logging only)" : "LIVE TRADING"}`);
  console.log(`Min profit threshold: ${fmt(MIN_PROFIT_THRESHOLD)}/share`);
  console.log(`Max quantity: ${MAX_QUANTITY / MICROUNITS} shares`);
  console.log(`Poll interval: ${POLL_INTERVAL_MS}ms\n`);

  const client = createClient();

  // Run immediately, then on interval
  await scan(client);
  setInterval(() => scan(client), POLL_INTERVAL_MS);
}

main().catch(console.error);
