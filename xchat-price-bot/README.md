# XChat Solana Price/Alert Bot

An [XChat bot](https://docs.x.com/xchat/bots) that answers encrypted DMs on X
with Solana token prices and fires price alerts. Data comes from the public
DexScreener API; encryption is handled client-side by the
[Chat XDK](https://docs.x.com/xchat/xchat-xdk), so X never sees plaintext.

## Commands (DM the bot)

```
BONK                          just a ticker (or $BONK, or a mint address)
price WIF                     same thing, explicit
alert BONK above 0.00003      DM me when BONK crosses $0.00003
alert <mint> below 0.5        works with mint addresses too
alerts                        list alerts set in this chat
clear                         remove this chat's alerts
help
```

## Setup

Requires Python 3.10+ and an X developer account with a project + app.

```bash
cd xchat-price-bot
pip install -r requirements.txt
cp .env.example .env
```

**1. Register the bot** (one time). Put your app's bearer token in `.env` as
`X_APP_BEARER_TOKEN`, then:

```bash
python3 register_bot.py my_price_bot "Solana Price Bot"
```

This calls `POST /2/bots`. The response includes the bot's user id and an
`xcbot_...` token that is shown **once** — the script prints the exact lines
to paste into `.env` (`XCHAT_BOT_TOKEN`, `XCHAT_BOT_ID`). Re-running with the
same handle returns the same bot with a fresh token (revoking the old one).
Default plan allowance is 1 bot per project.

**2. Run the bot:**

```bash
python3 bot.py
```

On first run it:

- generates identity + signing keypairs and publishes the public halves via
  `POST /2/users/:id/keys` (private keys are kept locally in
  `state/keys.json`, chmod 600 — guard that file);
- snapshots the inbox so it only replies to messages that arrive after it
  started.

Then it polls the inbox every `XCHAT_POLL_INTERVAL` seconds (default 5),
decrypts new events, verifies sender signatures, replies encrypted, and
checks active alerts every `XCHAT_ALERT_INTERVAL` seconds (default 30).

**3. Talk to it:** open XChat on X, start a conversation with the bot's
handle, and send `help`. The first message from a new user also delivers the
conversation key (an encrypted copy for each participant), which the bot
caches automatically.

## Sanity check without credentials

```bash
python3 smoke_test.py
```

Exercises the DexScreener lookup, command parsing, and the Chat XDK
keypair generate/export/import round trip — no X API access needed.

## Files

| File | Purpose |
|------|---------|
| `register_bot.py` | `POST /2/bots` — create bot, mint `xcbot_` token |
| `bot.py` | main polling loop: decrypt → command → encrypted reply |
| `identity.py` | keypair generation, local key storage, signing-key lookup |
| `price.py` | DexScreener lookup + formatting |
| `config.py` | env/.env config, paths |
| `state/` | (gitignored) private keys, inbox cursors, alerts |

## Notes

- The bot token is the only way to act as the bot; rotate with
  `POST /2/bots/:id/token` (re-running `register_bot.py` does this too).
- Polling is used instead of webhooks so the bot runs anywhere (no public
  HTTPS endpoint required). Webhooks/activity streams are the
  lower-latency production option.
- If you delete `state/keys.json`, the bot mints and publishes a fresh
  keypair on next start; conversation keys will be re-established on the
  next message in each conversation.
