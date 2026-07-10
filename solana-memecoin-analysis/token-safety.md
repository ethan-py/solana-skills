# Token Safety & Rug-Pull Checks

Checks that detect the common ways Solana memecoin holders get scammed: supply inflation, frozen accounts, honeypots, LP pulls, and insider dumps.

## Red-Flag Checklist

| Check | Red flag | Severity |
|---|---|---|
| Mint authority | Not revoked (supply can be inflated) | 🔴 Critical |
| Freeze authority | Present (your account can be frozen → honeypot) | 🔴 Critical |
| Token-2022 permanent delegate | Set (delegate can seize/burn anyone's tokens) | 🔴 Critical |
| Token-2022 transfer hook | Custom program can block sells | 🔴 Critical |
| Token-2022 default account state | `Frozen` (new accounts can't transfer until thawed) | 🔴 Critical |
| Sell quote | No route / sell reverts in simulation | 🔴 Critical |
| LP tokens | Held by deployer, not burned/locked | 🔴 High |
| Top 10 holders (ex-pools) | > 25–30% of supply | 🟠 High |
| Token-2022 transfer fee | > a few % (100% = honeypot) | 🟠 High |
| Metadata | Mutable + update authority is a wallet (can rebrand/impersonate) | 🟡 Medium |
| Liquidity | < ~$10k (trivially manipulated, high impact) | 🟡 Medium |
| Bundled snipers | Many fresh wallets buying in the creation slot | 🟡 Medium |
| Dev wallet | Funded by wallet linked to prior rugs | 🟠 High |

A token passing every check can still dump; these only filter *mechanical* scams.

## 1. Mint & Freeze Authority

The single most important check. If `mintAuthority` exists, supply can be inflated at will. If `freezeAuthority` exists, the holder's token account can be frozen — the classic "you can buy but not sell" honeypot on classic SPL tokens.

```typescript
import { Connection, PublicKey } from "@solana/web3.js";
import { getMint, TOKEN_PROGRAM_ID, TOKEN_2022_PROGRAM_ID } from "@solana/spl-token";

async function checkAuthorities(connection: Connection, mintAddr: string) {
    const mint = new PublicKey(mintAddr);
    const acct = await connection.getAccountInfo(mint);
    if (!acct) throw new Error("Mint account not found");

    const tokenProgram = acct.owner.equals(TOKEN_2022_PROGRAM_ID)
        ? TOKEN_2022_PROGRAM_ID
        : TOKEN_PROGRAM_ID;

    const info = await getMint(connection, mint, "confirmed", tokenProgram);
    return {
        isToken2022: tokenProgram.equals(TOKEN_2022_PROGRAM_ID),
        mintAuthority: info.mintAuthority?.toBase58() ?? null,   // null = revoked ✅
        freezeAuthority: info.freezeAuthority?.toBase58() ?? null, // null = none ✅
        supply: info.supply,
        decimals: info.decimals,
    };
}
```

**Exceptions that are OK:**
- Pump.fun tokens show the Pump.fun mint-authority PDA (`TSLvdd1pWpHVjahSpsvCXUbgwsL3JAcvokwaKt1eokM`) — program logic never mints beyond the curve allocation.
- Stablecoins and wrapped assets legitimately keep freeze authority (USDC, USDT). For a *memecoin* there is no legitimate reason.

## 2. Token-2022 Extension Risks

If the mint is owned by Token-2022 (`TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb`), enumerate its extensions — several are rug primitives when attached to a memecoin:

| Extension | Risk |
|---|---|
| `PermanentDelegate` | Delegate can transfer or burn tokens **from any holder** at any time |
| `TransferHook` | Every transfer calls an arbitrary program — it can reject sells (honeypot) |
| `TransferFeeConfig` | Tax on transfers; fee is changeable up to the max — 100% max fee = latent honeypot |
| `DefaultAccountState` | New token accounts start `Frozen`; only the freeze authority can thaw |
| `MintCloseAuthority` | Mint can be closed and later re-created at the same address |
| `Pausable` | Authority can pause all transfers |
| `NonTransferable` | Tokens can never be sold (soulbound) |

```typescript
import {
    getMint, getExtensionTypes, ExtensionType,
    getTransferFeeConfig, getPermanentDelegate, getTransferHook,
    getDefaultAccountState, TOKEN_2022_PROGRAM_ID,
} from "@solana/spl-token";
import { AccountState } from "@solana/spl-token";

async function checkToken2022(connection: Connection, mint: PublicKey) {
    const info = await getMint(connection, mint, "confirmed", TOKEN_2022_PROGRAM_ID);
    const extensions = getExtensionTypes(info.tlvData);

    const flags: string[] = [];
    if (extensions.includes(ExtensionType.PermanentDelegate)) {
        const d = getPermanentDelegate(info);
        flags.push(`PERMANENT DELEGATE: ${d?.delegate.toBase58()}`);
    }
    if (extensions.includes(ExtensionType.TransferHook)) {
        const h = getTransferHook(info);
        flags.push(`TRANSFER HOOK program: ${h?.programId.toBase58()}`);
    }
    if (extensions.includes(ExtensionType.TransferFeeConfig)) {
        const f = getTransferFeeConfig(info);
        const bps = f?.newerTransferFee.transferFeeBasisPoints ?? 0;
        flags.push(`TRANSFER FEE: ${bps / 100}% (max ${f?.newerTransferFee.maximumFee})`);
    }
    if (extensions.includes(ExtensionType.DefaultAccountState)) {
        const s = getDefaultAccountState(info);
        if (s?.state === AccountState.Frozen) flags.push("DEFAULT STATE: Frozen");
    }
    return { extensions: extensions.map((e) => ExtensionType[e]), flags };
}
```

## 3. Metadata Checks

Fetch Metaplex metadata (see [onchain-analysis.md](./onchain-analysis.md#metaplex-metadata)) and inspect:

- **`isMutable: true` + wallet update authority** — name, symbol, and image can be swapped later (impersonation/rebrand rugs). Launchpad-owned update authorities (PDAs) are lower risk.
- **Impersonation** — a token named "USDC"/"Trump"/etc. proves nothing. Compare the *mint address* against the project's official channels.
- **URI content** — the JSON at `metadata.uri` may claim websites/socials that don't reference the mint back. Fabricated socials are the norm on scam tokens.

## 4. LP Status: Burned or Locked?

If the deployer holds the LP tokens, they can withdraw both sides of the pool at any time ("liquidity pull").

**Fast path — Raydium API (includes burn percentage):**
```typescript
const res = await fetch(
    "https://api-v3.raydium.io/pools/info/mint" +
    `?mint1=${MINT}&poolType=all&poolSortField=liquidity&sortType=desc&pageSize=5&page=1`
);
const { data } = await res.json();
for (const pool of data.data) {
    console.log(pool.type, pool.id, "LP burned:", pool.burnPercent, "%");
}
```

**Manual path — check who holds the LP mint:**
```typescript
// 1. Get the pool's lpMint (from Raydium API above, or decoded pool state)
// 2. See where LP supply sits:
const largest = await connection.getTokenLargestAccounts(new PublicKey(LP_MINT));
const supply = await connection.getTokenSupply(new PublicKey(LP_MINT));
// Burned if supply ≈ 0 (burned via spl-token burn) or the top holder is the
// incinerator: 1nc1nerator11111111111111111111111111111111
```

**Notes:**
- Pump.fun graduations migrate liquidity to PumpSwap where the LP is program-owned — no LP-pull risk, which is a big reason the flow is popular.
- "Locked" LP (Streamflow, Jupiter Lock, Raydium's burn-and-earn) is weaker than burned — check the unlock date.
- CLMM/DLMM (concentrated liquidity) positions are NFTs, not fungible LP tokens; deployer-owned positions can be withdrawn anytime, so treat unlocked concentrated liquidity as pullable.

## 5. Holder Concentration

```typescript
const { value: top } = await connection.getTokenLargestAccounts(mint); // top 20
const supply = Number((await connection.getTokenSupply(mint)).value.amount);

// Exclude liquidity pools & known program vaults before judging concentration —
// the largest holder of a healthy new token is usually the pool itself.
// Common excludes: the pool's token vaults (from DexScreener `pairAddress` /
// Raydium pool keys), Pump.fun bonding curve ATA, burn/incinerator addresses.
const EXCLUDE = new Set([...poolVaultAddresses]);

let insiderPct = 0;
for (const acct of top) {
    if (EXCLUDE.has(acct.address.toBase58())) continue;
    insiderPct += (Number(acct.amount) / supply) * 100;
}
console.log(`Top holders (ex-pools): ${insiderPct.toFixed(1)}%`);
```

Rules of thumb: single non-pool wallet > 5–10%, or top 10 non-pool wallets > 25–30% → high dump risk. Also watch for **many wallets holding identical amounts** — one insider split across wallets to look distributed.

## 6. Can You Actually Sell? (Honeypot Test)

The definitive functional test: ask Jupiter for a *sell* quote and simulate it.

```typescript
const SOL = "So11111111111111111111111111111111111111112";
const amount = 1_000_000; // raw units of the token to sell

const quote = await fetch(
    "https://lite-api.jup.ag/swap/v1/quote" +
    `?inputMint=${MINT}&outputMint=${SOL}&amount=${amount}&slippageBps=100`
).then((r) => r.json());

if (quote.error) {
    console.log("🔴 No sell route — possible honeypot or zero liquidity");
} else {
    console.log("Sell OK. Price impact:", quote.priceImpactPct, "%");
}
```

For high confidence, build the swap transaction and `simulateTransaction` — transfer-hook and frozen-account honeypots fail only at execution, not at quoting.

## 7. Sniper & Bundle Detection

Insiders often buy their own launch across many fresh wallets in the first slot(s) (frequently via Jito bundles), then dump on organic buyers. Heuristics:

1. Get the pool/curve creation transaction and its slot (first signature on the pair address).
2. Pull all buys in the first ~5–10 slots (`getSignaturesForAddress` on the pool, then parse).
3. For each early buyer: wallet age (first-ever signature), funding source (`SOL` transfer in), and whether multiple buyers share one funder.
4. Red flags: buyers created minutes before launch, common funding wallet, near-identical buy sizes, buys landing in the same slot as pool creation.

RugCheck (below) and most trading terminals surface a precomputed "snipers/bundlers" figure if you don't want to build this.

## 8. RugCheck API (Aggregated Report)

Free, keyless summary of most checks above:

```typescript
const report = await fetch(
    `https://api.rugcheck.xyz/v1/tokens/${MINT}/report/summary`
).then((r) => r.json());

// { score, risks: [{ name, description, level, score }] }
// Higher score = more risk factors. Treat as a triage signal, not a verdict.
for (const risk of report.risks) console.log(`[${risk.level}] ${risk.name}`);
```

The full report (`/v1/tokens/{mint}/report`) adds top holders, markets, LP lockers, and insider graph data. Always spot-check critical findings on-chain yourself — third-party scores can lag or be gamed.
