"""Token price lookup via the public DexScreener API (no key required).

Accepts either a Solana mint address or a ticker like BONK / $BONK.
Prefers the highest-liquidity Solana pair so thin copycat pools don't win.
"""

import re
from typing import Any, Dict, List, Optional, Tuple

import requests

DEXSCREENER = "https://api.dexscreener.com"
_BASE58_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")

# Canonical mints for common tickers — DexScreener search is polluted with
# scam pools that spoof symbol and liquidity, so majors resolve directly.
WELL_KNOWN = {
    "SOL": "So11111111111111111111111111111111111111112",
    "WSOL": "So11111111111111111111111111111111111111112",
    "USDC": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
    "USDT": "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",
    "BONK": "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263",
    "WIF": "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm",
    "JUP": "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN",
    "RAY": "4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R",
    "PYTH": "HZ1JovNiVvGrGNiiYvEozEVgZ58xaU3RKwX8eACQBCt3",
    "JTO": "jtojtomepa8beP8AuQc6eXt5FriJwfFMwQx2v2f9mCL",
}

# Real pools quote against these; scam pools usually quote against junk
# whose fake USD value inflates the pool's reported liquidity.
TRUSTED_QUOTES = {
    WELL_KNOWN["SOL"],
    WELL_KNOWN["USDC"],
    WELL_KNOWN["USDT"],
}


def looks_like_mint(query: str) -> bool:
    return bool(_BASE58_RE.match(query))


def _liquidity(pair: Dict[str, Any]) -> float:
    return (pair.get("liquidity") or {}).get("usd") or 0


def _best_solana_pair(pairs: List[Dict[str, Any]], symbol: Optional[str] = None):
    solana = [p for p in pairs if p.get("chainId") == "solana"]
    if symbol:
        exact = [
            p
            for p in solana
            if p.get("baseToken", {}).get("symbol", "").lower() == symbol.lower()
        ]
        if exact:
            solana = exact
    trusted = [
        p
        for p in solana
        if p.get("quoteToken", {}).get("address") in TRUSTED_QUOTES
    ]
    if trusted:
        solana = trusted
    if not solana:
        return None
    return max(solana, key=_liquidity)


def lookup(query: str) -> Optional[Dict[str, Any]]:
    """Return the best Solana pair dict for a mint address or ticker."""
    query = query.strip().lstrip("$")
    if not query:
        return None
    mint = WELL_KNOWN.get(query.upper()) or (query if looks_like_mint(query) else None)
    if mint:
        resp = requests.get(f"{DEXSCREENER}/latest/dex/tokens/{mint}", timeout=15)
        resp.raise_for_status()
        return _best_solana_pair(resp.json().get("pairs") or [])
    resp = requests.get(
        f"{DEXSCREENER}/latest/dex/search", params={"q": query}, timeout=15
    )
    resp.raise_for_status()
    return _best_solana_pair(resp.json().get("pairs") or [], symbol=query)


def _fmt_usd(value: Optional[float]) -> str:
    if value is None:
        return "?"
    if value >= 1_000_000_000:
        return f"${value / 1_000_000_000:.2f}B"
    if value >= 1_000_000:
        return f"${value / 1_000_000:.2f}M"
    if value >= 1_000:
        return f"${value / 1_000:.1f}K"
    return f"${value:,.2f}"


def _fmt_price(value: float) -> str:
    if value >= 1:
        return f"${value:,.4f}".rstrip("0").rstrip(".")
    return f"${value:.10f}".rstrip("0")


def price_of(pair: Dict[str, Any]) -> Optional[float]:
    try:
        return float(pair.get("priceUsd"))
    except (TypeError, ValueError):
        return None


def format_pair(pair: Dict[str, Any]) -> str:
    base = pair.get("baseToken", {})
    price = price_of(pair)
    change = (pair.get("priceChange") or {}).get("h24")
    volume = (pair.get("volume") or {}).get("h24")
    liquidity = (pair.get("liquidity") or {}).get("usd")
    fdv = pair.get("fdv") or pair.get("marketCap")

    symbol = str(base.get("symbol", "?")).lstrip("$")
    lines = [
        f"{base.get('name', '?')} (${symbol})",
        f"Price: {_fmt_price(price) if price is not None else '?'}"
        + (f"  ({change:+.1f}% 24h)" if isinstance(change, (int, float)) else ""),
        f"Liquidity: {_fmt_usd(liquidity)}  |  Vol 24h: {_fmt_usd(volume)}"
        + (f"  |  FDV: {_fmt_usd(fdv)}" if fdv else ""),
        f"Mint: {base.get('address', '?')}",
    ]
    if pair.get("url"):
        lines.append(pair["url"])
    return "\n".join(lines)


def quote(query: str) -> Tuple[Optional[float], str]:
    """Return (price, human-readable reply) for a query."""
    try:
        pair = lookup(query)
    except requests.RequestException as exc:
        return None, f"Price lookup failed ({exc.__class__.__name__}). Try again in a bit."
    if pair is None:
        return None, f"Couldn't find a Solana pair for '{query}'. Try the mint address."
    return price_of(pair), format_pair(pair)
