# On-Chain Analysis Patterns

Reading token state directly from RPC: mint data, metadata, holders, token age, and wallet forensics. Everything here works against any RPC; sections marked **Helius** need their DAS/enhanced APIs.

## Reading the Mint Account

```typescript
import { Connection, PublicKey } from "@solana/web3.js";
import { getMint, TOKEN_PROGRAM_ID, TOKEN_2022_PROGRAM_ID } from "@solana/spl-token";

const connection = new Connection(RPC_URL, "confirmed");
const mint = new PublicKey(MINT_ADDRESS);

// The owner program tells you SPL Token vs Token-2022:
const acctInfo = await connection.getAccountInfo(mint);
const tokenProgram = acctInfo!.owner.equals(TOKEN_2022_PROGRAM_ID)
    ? TOKEN_2022_PROGRAM_ID
    : TOKEN_PROGRAM_ID;

const info = await getMint(connection, mint, "confirmed", tokenProgram);
// info.supply (bigint, raw), info.decimals, info.mintAuthority, info.freezeAuthority

const uiSupply = Number(info.supply) / 10 ** info.decimals;
```

Almost all memecoins use 6 decimals and a fixed 1,000,000,000 supply (the Pump.fun convention). A weird supply/decimals combo is itself a signal to look closer.

## Metaplex Metadata

The metadata account is a PDA of the Token Metadata program (`metaqbxxUerdq28cj1RbAWkYQm3ybzjb6a8bt518x1s`), seeds `["metadata", program_id, mint]`.

```typescript
// With Umi (@metaplex-foundation/mpl-token-metadata v3):
import { createUmi } from "@metaplex-foundation/umi-bundle-defaults";
import { publicKey } from "@metaplex-foundation/umi";
import { fetchMetadataFromSeeds } from "@metaplex-foundation/mpl-token-metadata";

const umi = createUmi(RPC_URL);
const md = await fetchMetadataFromSeeds(umi, { mint: publicKey(MINT_ADDRESS) });
// md.name, md.symbol, md.uri, md.isMutable, md.updateAuthority

// The URI points to off-chain JSON (image, description, socials):
const offchain = await fetch(md.uri).then((r) => r.json());
```

Token-2022 mints may instead embed metadata via the `MetadataPointer`/`TokenMetadata` extensions — read with `getTokenMetadata(connection, mint)` from `@solana/spl-token`.

**Cheapest path:** if you have Helius, `getAsset` returns metadata + supply + price in one call (see [market-data.md](./market-data.md)).

## Holder Analysis

### Top 20 holders — any RPC

```typescript
const { value: largest } = await connection.getTokenLargestAccounts(mint);
// [{ address, amount, decimals, uiAmount }] — token ACCOUNTS, not owners

// Resolve token accounts → owner wallets:
const accounts = await connection.getMultipleParsedAccounts(
    largest.map((a) => a.address)
);
const owners = accounts.value.map(
    (a) => (a?.data as any).parsed.info.owner as string
);
```

`getTokenLargestAccounts` returns token accounts; two entries can belong to one owner. Always resolve to owners before computing concentration, and exclude pool vaults (see [token-safety.md](./token-safety.md#5-holder-concentration)).

### Full holder list / count — Helius DAS

`getProgramAccounts` on the token program is disabled or heavily limited on most public RPCs. Use Helius `getTokenAccounts` (paginated, works for millions of holders):

```typescript
async function getAllHolders(mintAddr: string): Promise<Map<string, bigint>> {
    const holders = new Map<string, bigint>();
    let page = 1;
    while (true) {
        const res = await fetch(HELIUS_RPC_URL, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                jsonrpc: "2.0", id: "1", method: "getTokenAccounts",
                params: { mint: mintAddr, page, limit: 1000 },
            }),
        }).then((r) => r.json());

        const accts = res.result?.token_accounts ?? [];
        if (accts.length === 0) break;
        for (const a of accts) {
            const prev = holders.get(a.owner) ?? 0n;
            holders.set(a.owner, prev + BigInt(a.amount));
        }
        page++;
    }
    return holders; // holders.size = holder count (incl. zero-balance unless filtered)
}
```

**Fallback** (RPC that allows `getProgramAccounts`): filter token accounts by mint —

```typescript
const accounts = await connection.getProgramAccounts(TOKEN_PROGRAM_ID, {
    filters: [
        { dataSize: 165 },                                  // classic token account
        { memcmp: { offset: 0, bytes: mint.toBase58() } },  // mint is the first field
    ],
});
```

**Interpretation caveats:** holder counts are inflated by dust airdrops (thousands of 1-token holders created by the deployer to fake adoption). Weight by balance, not count.

## Token Age & Launch Transactions

Age ≈ time of the oldest signature on the mint (or on the pool for "trading age").

```typescript
async function getOldestSignature(connection: Connection, addr: PublicKey) {
    let before: string | undefined;
    let oldest;
    while (true) {
        const sigs = await connection.getSignaturesForAddress(addr, { before, limit: 1000 });
        if (sigs.length === 0) break;
        oldest = sigs[sigs.length - 1];
        if (sigs.length < 1000) break;
        before = oldest.signature;
    }
    return oldest; // { signature, slot, blockTime }
}
```

This walks the full history — fine for young tokens, expensive for active ones (1000 sigs/call). Shortcuts:
- DexScreener `pairCreatedAt` gives pool age with zero RPC calls.
- Pump.fun tokens: the mint's *first* transaction is the `create` instruction; the fee payer of that transaction **is the deployer**.

Fetch and parse the launch transaction to identify the creator:

```typescript
const tx = await connection.getTransaction(oldest.signature, {
    maxSupportedTransactionVersion: 0,
});
const deployer = tx?.transaction.message.staticAccountKeys[0].toBase58(); // fee payer
```

## Dev Wallet Forensics

Once you have the deployer wallet:

1. **Funding source** — its first incoming SOL transfer. Deployers funded straight from a CEX hot wallet are weak signals either way; deployers funded by a wallet that funded *previous rug deployers* are a strong red flag.
2. **Prior launches** — scan the wallet's history for other `create`/`initializeMint` calls. Serial deployers with dozens of dead tokens → assume this one is disposable too.
3. **Current position** — does the deployer (or wallets it funded) still hold a large share? Cross-reference with the holder list.

**Helius Enhanced Transactions** does the parsing for you (typed `events` instead of raw instructions):

```typescript
const txs = await fetch(
    `https://api.helius.xyz/v0/addresses/${WALLET}/transactions?api-key=${KEY}&limit=100`
).then((r) => r.json());
// Each tx has .type (e.g. "SWAP", "TRANSFER", "CREATE"), .tokenTransfers, .nativeTransfers
```

Wallet-graph analysis (clusters of funded-by relationships) is what most "insider %" dashboards compute; you can approximate it with 1–2 hops of `getSignaturesForAddress` + parsed SOL transfers from the deployer.

## Known Addresses Worth Hardcoding

| Address | What |
|---|---|
| `TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA` | SPL Token program |
| `TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb` | Token-2022 program |
| `metaqbxxUerdq28cj1RbAWkYQm3ybzjb6a8bt518x1s` | Metaplex Token Metadata |
| `1nc1nerator11111111111111111111111111111111` | Burn address (burned LP/tokens sit here) |
| `5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1` | Raydium AMM v4 authority (owns pool vaults) |
| `TSLvdd1pWpHVjahSpsvCXUbgwsL3JAcvokwaKt1eokM` | Pump.fun mint authority PDA |
| `So11111111111111111111111111111111111111112` | Wrapped SOL mint |

Launchpad and DEX program IDs live in [launchpads.md](./launchpads.md#program-id-reference).
