# Market Data APIs & Metrics

Fetching price, liquidity, volume, and market cap for Solana memecoins — and interpreting them without being fooled.

## API Landscape

| API | Key needed | Best for | Notes |
|---|---|---|---|
| **DexScreener** | No | Pair data: price, liquidity, volume, txns, age | 300 req/min on pair/token endpoints |
| **Jupiter** | No (lite tier) | Prices, sell quotes, price impact, token metadata | `lite-api.jup.ag` free; `api.jup.ag` keyed/paid |
| **GeckoTerminal** | No | Pools, OHLCV | ~30 req/min free |
| **RugCheck** | No | Safety report (see [token-safety.md](./token-safety.md)) | |
| **Birdeye** | Yes | OHLCV candles, trades, wallet PnL | `public-api.birdeye.so` |
| **Helius** | Yes | DAS asset lookups, holders, parsed history, webhooks | RPC + REST |
| **PumpPortal / Bitquery** | Mixed | Pump.fun real-time streams | See [launchpads.md](./launchpads.md) |

For a screener, DexScreener + Jupiter covers ~90% of needs with no keys.

## DexScreener

```typescript
// All pairs for a token (the same token often trades in several pools):
const { pairs } = await fetch(
    `https://api.dexscreener.com/latest/dex/tokens/${MINT}`
).then((r) => r.json());

// Batch lookup, up to 30 mints in one call:
const arr = await fetch(
    `https://api.dexscreener.com/tokens/v1/solana/${MINT_1},${MINT_2}`
).then((r) => r.json());

// Search by name/symbol (for discovery only — never to resolve identity):
const found = await fetch(
    "https://api.dexscreener.com/latest/dex/search?q=WIF"
).then((r) => r.json());
```

Key fields per pair:

```typescript
{
  dexId: "raydium", pairAddress: "...",
  baseToken: { address, name, symbol },
  priceUsd: "0.0000123", priceNative: "...",
  txns:   { m5: { buys, sells }, h1: {...}, h6: {...}, h24: {...} },
  volume: { m5, h1, h6, h24 },            // USD
  priceChange: { m5, h1, h6, h24 },        // %
  liquidity: { usd, base, quote },
  fdv: 123456, marketCap: 123456,
  pairCreatedAt: 1700000000000,            // ms epoch
  info: { imageUrl, websites, socials },   // self-reported — do not trust
}
```

Aggregate across pairs when a token has several pools: sum `liquidity.usd` and `volume.h24`, take price from the deepest pool.

## Jupiter

```typescript
// Price (USD) for up to 50 mints — v3:
const prices = await fetch(
    `https://lite-api.jup.ag/price/v3?ids=${MINT},So11111111111111111111111111111111111111112`
).then((r) => r.json());
// { "<mint>": { usdPrice, decimals, blockId, priceChange24h } }

// Quote — doubles as executable-price + price-impact oracle:
const quote = await fetch(
    "https://lite-api.jup.ag/swap/v1/quote" +
    `?inputMint=${MINT}&outputMint=So11111111111111111111111111111111111111112` +
    `&amount=${rawAmount}&slippageBps=100`
).then((r) => r.json());
// quote.outAmount, quote.priceImpactPct, quote.routePlan[]
```

The quote API is the most honest price source: it reflects what you'd *actually receive*, including route depth. DexScreener/price APIs show marginal spot price, which overstates the value of any meaningful position in a thin pool.

Jupiter's Token API v2 (`https://lite-api.jup.ag/tokens/v2/search?query=...`) adds metadata, org/community verification flags, and holder counts — the verification flag is a useful (not sufficient) legitimacy signal.

## GeckoTerminal

```typescript
// Pools for a token:
const pools = await fetch(
    `https://api.geckoterminal.com/api/v2/networks/solana/tokens/${MINT}/pools`
).then((r) => r.json());

// OHLCV for a pool (free — Birdeye alternative):
const ohlcv = await fetch(
    `https://api.geckoterminal.com/api/v2/networks/solana/pools/${POOL}/ohlcv/minute` +
    "?aggregate=5&limit=100"
).then((r) => r.json());
// ohlcv.data.attributes.ohlcv_list: [[ts, o, h, l, c, volume], ...]
```

## Birdeye (API key)

```typescript
const headers = { "X-API-KEY": BIRDEYE_KEY, "x-chain": "solana" };

const price = await fetch(
    `https://public-api.birdeye.so/defi/price?address=${MINT}`, { headers }
).then((r) => r.json());

const candles = await fetch(
    "https://public-api.birdeye.so/defi/ohlcv" +
    `?address=${MINT}&type=1m&time_from=${from}&time_to=${to}`, { headers }
).then((r) => r.json());
```

Use when you need per-token (not per-pool) candles, trade feeds, or top-trader breakdowns.

## Helius DAS `getAsset`

Metadata + supply + price in a single call:

```typescript
const asset = await fetch(HELIUS_RPC_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
        jsonrpc: "2.0", id: "1", method: "getAsset",
        params: { id: MINT, displayOptions: { showFungible: true } },
    }),
}).then((r) => r.json());

const t = asset.result.token_info;
// t.supply, t.decimals, t.price_info?.price_per_token, t.price_info?.total_price
// asset.result.content.metadata: name, symbol; .links.image
```

## Interpreting the Numbers

### Market cap vs FDV
- `marketCap` = price × circulating supply; `fdv` = price × total supply.
- For typical memecoins (fixed 1B supply, no vesting) they're equal. A large gap means locked/vesting supply that will eventually hit the market — check the unlock schedule.

### Liquidity quality
- **Liquidity/MC ratio**: healthy young tokens sit very roughly around 5–20%. Extremely low (<1–2%) → exit door is tiny; price is a fiction for any real position size.
- Confirm claimed liquidity with a Jupiter sell quote for a realistic size: `priceImpactPct` > a few percent on a modest sell contradicts a "deep" pool.
- Liquidity can be single-sided or concentrated (CLMM/DLMM) — USD liquidity numbers overstate exit depth if it's mostly the memecoin side.

### Volume authenticity
Wash trading is endemic (bots ping-ponging to trend on screeners). Cross-check:
- `txns.h24.buys` vs `sells` — organic flow is mixed; 50/50 with metronome regularity is bot-like.
- Volume ≫ liquidity (e.g. 50× daily turnover of the pool) with a flat price → wash.
- Unique traders (Birdeye/Helius) ≪ transaction count → few bots generating everything.

### Price
- Use pool-derived prices (DexScreener/Jupiter), never the metadata or self-reported values.
- Sub-cent tokens: keep full precision (strings/bigint math); `priceUsd` like `0.0{5}123` loses meaning through naive float rounding.

## Real-Time Monitoring

One-shot HTTP polling caps out quickly (rate limits, latency). For live tooling:
- `connection.onLogs(poolOrProgramId, cb)` — WebSocket log subscription on a pool or DEX program.
- **Helius webhooks** — push parsed events (swaps on an address list) to your endpoint.
- **Geyser / Yellowstone gRPC** — full-firehose account + transaction streaming; what serious sniping/monitoring infra uses.
- **PumpPortal WebSocket** — prebuilt streams of Pump.fun creates/trades/graduations (see [launchpads.md](./launchpads.md)).
