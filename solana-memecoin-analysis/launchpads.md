# Launchpads, Bonding Curves & DEX Pools

Where Solana memecoins come from, how bonding curves work, and how to read launchpad/pool state on-chain. Mechanics (fees, thresholds) change often — treat numbers as "as of early 2026" and verify.

## Lifecycle of a Typical Memecoin

1. **Launch** on a bonding-curve launchpad (Pump.fun et al.) — no LP needed; the curve is the market.
2. **Curve phase** — price follows a constant-product formula against virtual reserves; buys push price up deterministically.
3. **Graduation** — when the curve sells out, the raised SOL + reserved tokens migrate into a real AMM pool (PumpSwap, Raydium, Meteora — depends on launchpad).
4. **AMM phase** — normal DEX trading; analysis shifts to LP status, holders, volume (see the other reference files).

Knowing which phase a token is in dictates which accounts to read: bonding curve state vs pool state.

### Which launchpad did it come from?
- Pump.fun mints are vanity-ground to end in `pump`; LetsBonk mints end in `bonk` (heuristic, not proof).
- Definitive: the mint's first transaction invokes the launchpad's program (see token age in [onchain-analysis.md](./onchain-analysis.md)).

## Pump.fun In Depth

Program: `6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P`

Fixed parameters per token: 1B total supply, 6 decimals, 793.1M sold on the curve, ~206.9M reserved for the graduation LP. The curve starts with **virtual** reserves of 30 SOL and 1.073B tokens and completes after collecting ~85 SOL (so the USD market cap at graduation floats with SOL price). Swap fee on the curve: 1%.

### Reading Bonding Curve State

```typescript
import { Connection, PublicKey } from "@solana/web3.js";

const PUMP_FUN = new PublicKey("6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P");

const [bondingCurve] = PublicKey.findProgramAddressSync(
    [Buffer.from("bonding-curve"), mint.toBuffer()],
    PUMP_FUN
);

const acct = await connection.getAccountInfo(bondingCurve);
if (!acct) throw new Error("Not a Pump.fun token (no bonding curve PDA)");

// Layout: 8-byte discriminator, then u64 LE fields, then flags
const v = new DataView(acct.data.buffer, acct.data.byteOffset, acct.data.byteLength);
const curve = {
    virtualTokenReserves: v.getBigUint64(8, true),
    virtualSolReserves:   v.getBigUint64(16, true),
    realTokenReserves:    v.getBigUint64(24, true),
    realSolReserves:      v.getBigUint64(32, true),
    tokenTotalSupply:     v.getBigUint64(40, true),
    complete:             acct.data[48] === 1,
    // Program updates have appended more fields after the flag (creator, etc.) —
    // the account is 150 bytes as of mid-2026 — but this leading layout is stable.
};
```

### Price, Market Cap, Graduation Progress

```typescript
// Spot price in SOL per token (SOL is 9 decimals, pump tokens are 6):
const priceSol =
    Number(curve.virtualSolReserves) / 1e9 /
    (Number(curve.virtualTokenReserves) / 1e6);

const marketCapSol = priceSol * 1e9; // 1B fixed supply

// Progress toward graduation (793.1M curve tokens, 6 decimals):
const INITIAL_REAL_TOKEN_RESERVES = 793_100_000_000_000n;
const progressPct =
    100 * (1 - Number(curve.realTokenReserves) / Number(INITIAL_REAL_TOKEN_RESERVES));

// complete === true → graduated; trading has moved to the AMM pool
```

After graduation the reserve fields read **0** (verified on mainnet against a graduated token) — detect graduation with `complete`, and don't run the price/progress math on a completed curve.

Buy math is constant-product on the *virtual* reserves: for `solIn` (after the 1% fee), `tokensOut = vToken - (vSol * vToken) / (vSol + solIn)`. Early buys get dramatically more tokens — which is exactly why snipers bundle into the creation slot (see [token-safety.md](./token-safety.md#7-sniper--bundle-detection)).

### Graduation → PumpSwap

Since March 2025 graduated tokens migrate to **PumpSwap** (`pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA`), Pump.fun's own AMM, with no migration fee (earlier tokens migrated to Raydium AMM v4 for a 6 SOL fee). PumpSwap LP is program-owned — deployers can't pull it — and a slice of the swap fee goes to the token creator ("creator revenue sharing"). For graduated tokens, analyze the PumpSwap pool like any AMM pool: DexScreener reports it with `dexId: "pumpswap"`.

### Real-Time Pump.fun Data

- **PumpPortal** — free WebSocket: `wss://pumpportal.fun/api/data`, methods `subscribeNewToken`, `subscribeTokenTrade`, `subscribeMigration`.
- **Bitquery** — GraphQL streams over Pump.fun program events (historical + live).
- Raw: `connection.onLogs(PUMP_FUN, cb)` and decode `Create`/`Trade` events yourself.

## Other Launchpads (early 2026)

| Launchpad | Program | Graduates to |
|---|---|---|
| Pump.fun | `6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P` | PumpSwap |
| LetsBonk (Raydium LaunchLab) | `LanMV9sAd7wArD4vJFi2qDdfnVhFxYSUg6eADduJ3uj` | Raydium CPMM |
| Moonshot (DexScreener) | `MoonCVVNZFSYkqNXP6bxHLPL6QQJiMagDL3qcqUQTrG` | Meteora |
| Meteora DBC (white-label: Believe, etc.) | `dbcij3LWUppWqq96dh6gJWwBifmcGfLSB5D4DuSMaqN` | Meteora DAMM v2 |

All follow the same shape (bonding curve → AMM), so the Pump.fun analysis pattern transfers: find the curve account from the program + mint, decode reserves, compute price/progress. New launchpads appear (and die) monthly — the durable skill is identifying the program from the mint's first transaction and reading its curve account.

## Raydium Pools

Three pool types — LP-ownership analysis differs per type (see [token-safety.md](./token-safety.md#4-lp-status-burned-or-locked)):

| Type | Program | LP form |
|---|---|---|
| AMM v4 (legacy, OpenBook) | `675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8` | Fungible LP tokens |
| CPMM (no OpenBook) | `CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C` | Fungible LP tokens |
| CLMM (concentrated) | `CAMMCzo5YL8w4VFF8KVHrK22GGUsp5VTaW7grrKgrWqK` | Position NFTs |

Pool discovery + state without decoding layouts: Raydium's v3 API (`https://api-v3.raydium.io/pools/info/mint?mint1=<mint>&poolType=all&...`) returns pool IDs, LP mints, TVL, and `burnPercent`. For on-chain decoding use `@raydium-io/raydium-sdk-v2` (`liquidity`/`clmm` modules) rather than hand-rolled layouts — they change.

## Meteora

- **DLMM** (`LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo`) — bin-based concentrated liquidity; common for memecoin "launch pools" with dynamic fees that punish snipers early.
- **DAMM v2** (`cpamdpZCGKUy5JxQXB4dcpGPiikHawvSWAd6mEn1sGG`) and legacy Dynamic AMM (`Eo7WjKq67rjJQSZxS6z3YkapzY3eMj6Xy8X5EQVn5UaB`) — constant-product pools; DBC graduations land here.
- API: `https://dlmm-api.meteora.ag` (DLMM pairs/positions); SDKs `@meteora-ag/dlmm`, `@meteora-ag/cp-amm-sdk`.

Concentrated liquidity caveat: "liquidity USD" can sit entirely in bins far from the current price — always sanity-check exit depth with a Jupiter sell quote.

## Program ID Reference

| Program | Address |
|---|---|
| Pump.fun (bonding curve) | `6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P` |
| PumpSwap (AMM) | `pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA` |
| Raydium LaunchLab | `LanMV9sAd7wArD4vJFi2qDdfnVhFxYSUg6eADduJ3uj` |
| Raydium AMM v4 | `675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8` |
| Raydium CPMM | `CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C` |
| Raydium CLMM | `CAMMCzo5YL8w4VFF8KVHrK22GGUsp5VTaW7grrKgrWqK` |
| Meteora DLMM | `LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo` |
| Meteora DAMM v2 | `cpamdpZCGKUy5JxQXB4dcpGPiikHawvSWAd6mEn1sGG` |
| Meteora DBC | `dbcij3LWUppWqq96dh6gJWwBifmcGfLSB5D4DuSMaqN` |
| Moonshot | `MoonCVVNZFSYkqNXP6bxHLPL6QQJiMagDL3qcqUQTrG` |
| Orca Whirlpool | `whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc` |
| Jupiter Lock | `LocpQgucEQHbqNABEYvBvwoxCPsSbG91A1QaQhQQqjn` |
| Streamflow (vesting/locks) | `strmRqUCoQUgGUan5YhzUZa6KqdzwX5L6FpUxfmKg5m` |
