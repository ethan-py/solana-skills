# Solana Memecoin Analysis

## Description
Guides due-diligence and analysis of memecoins on Solana: rug-pull safety checks, holder distribution, market data (price/liquidity/volume), and launchpad mechanics (Pump.fun bonding curves, Raydium, Meteora). Focused on reading and interpreting on-chain + API data — not trading strategy or financial advice.

## When to Use
- Evaluating whether a Solana token is a likely scam/rug before interacting with it
- Fetching price, liquidity, volume, market cap, or holder counts for a token
- Checking mint/freeze authority, Token-2022 extensions, metadata mutability, or LP burn status
- Reading Pump.fun bonding curve state (price, graduation progress)
- Detecting sniper wallets, bundled buys, or insider concentration
- Building token screeners, safety scanners, or the analysis layer of a bot

## Instructions

### Analysis Workflow
Run checks in this order — each step can disqualify a token early:

1. **Identity** — Resolve the exact mint address. Never trust name/symbol/logo; anyone can copy them. Verify via the community's official links, not search results.
2. **Safety** — Check mint & freeze authority, Token-2022 extensions (permanent delegate, transfer hooks, fees), and metadata mutability. See [token-safety.md](./token-safety.md).
3. **Liquidity** — Where does it trade? Is LP burned/locked? Can you actually sell (simulate a sell quote)? See [token-safety.md](./token-safety.md) and [market-data.md](./market-data.md).
4. **Distribution** — Top-holder concentration, dev/insider wallets, sniper activity in the first blocks. See [onchain-analysis.md](./onchain-analysis.md).
5. **Market** — Price, real volume vs wash trading, market cap vs FDV, price impact. See [market-data.md](./market-data.md).
6. **Context** — Token age, dev wallet history (prior launches), launchpad provenance. See [launchpads.md](./launchpads.md).

### Key Decisions
- **Free vs paid data:** DexScreener, GeckoTerminal, Jupiter lite endpoints, and RugCheck are keyless. Birdeye and Helius need API keys but add OHLCV, full holder lists, and parsed history.
- **RPC-only vs indexed:** Authorities, top-20 holders, and bonding curve state need only an RPC. Full holder counts and wallet history need an indexer (Helius DAS) or `getProgramAccounts` on a provider that allows it.
- **Point-in-time vs monitoring:** One-shot checks use HTTP APIs; live monitoring needs WebSocket subscriptions, Geyser/Yellowstone gRPC, or Helius webhooks.

## Reference Files
- [token-safety.md](./token-safety.md) — Rug-pull checks: authorities, Token-2022 extensions, LP status, honeypots
- [onchain-analysis.md](./onchain-analysis.md) — Reading mints, metadata, holders, token age, wallet forensics
- [market-data.md](./market-data.md) — DexScreener, Jupiter, Birdeye, GeckoTerminal, Helius APIs and key metrics
- [launchpads.md](./launchpads.md) — Pump.fun bonding curve math, Raydium/Meteora pools, program ID reference

## Common Patterns

### Quick Safety Check (authorities)
```typescript
import { Connection, PublicKey } from "@solana/web3.js";
import { getMint, TOKEN_PROGRAM_ID, TOKEN_2022_PROGRAM_ID } from "@solana/spl-token";

const connection = new Connection(RPC_URL, "confirmed");
const mint = new PublicKey(MINT_ADDRESS);

const acct = await connection.getAccountInfo(mint);
const program = acct!.owner.equals(TOKEN_2022_PROGRAM_ID)
    ? TOKEN_2022_PROGRAM_ID : TOKEN_PROGRAM_ID;
const info = await getMint(connection, mint, "confirmed", program);

// Both should be null for a token that can't be inflated or frozen:
console.log("mintAuthority:", info.mintAuthority?.toBase58() ?? "revoked ✅");
console.log("freezeAuthority:", info.freezeAuthority?.toBase58() ?? "none ✅");
```

### Quick Market Snapshot (DexScreener, no API key)
```typescript
const res = await fetch(
    `https://api.dexscreener.com/latest/dex/tokens/${MINT_ADDRESS}`
);
const { pairs } = await res.json();
const best = pairs?.sort((a, b) => (b.liquidity?.usd ?? 0) - (a.liquidity?.usd ?? 0))[0];
console.log({
    dex: best.dexId,
    priceUsd: best.priceUsd,
    liquidityUsd: best.liquidity?.usd,
    volume24h: best.volume?.h24,
    marketCap: best.marketCap,
    ageMs: Date.now() - best.pairCreatedAt,
});
```

## Important Caveats
- **Nothing here is financial advice.** Memecoins are extremely high risk; most go to zero. These checks reduce — never eliminate — the chance of interacting with an outright scam.
- **Passing all checks ≠ safe.** Revoked authorities and burned LP don't prevent insiders dumping a large supply share.
- **This ecosystem changes fast.** Program IDs, API endpoints, rate limits, and launchpad mechanics (fees, graduation thresholds) change frequently — verify against official docs before relying on them in production.
- **Handle user funds conservatively.** If code derived from this skill signs transactions, simulate first, bound slippage, and hard-cap spend per transaction.
