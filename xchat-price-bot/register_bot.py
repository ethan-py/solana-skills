"""Register (or re-mint the token for) an XChat bot.

Usage:
    X_APP_BEARER_TOKEN=... python3 register_bot.py <handle> [display name]

Calls POST /2/bots with your app's bearer token. The response contains the
bot's user id and its xcbot_ token. The token is shown ONCE — copy it into
your .env as XCHAT_BOT_TOKEN immediately. Re-running with the same handle
is idempotent: it returns the same bot with a freshly minted token (and
revokes the old one).
"""

import json
import sys

import requests

import config


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    handle = sys.argv[1]
    display_name = " ".join(sys.argv[2:]) or handle

    resp = requests.post(
        f"{config.API_BASE}/2/bots",
        headers={
            "Authorization": f"Bearer {config.app_bearer_token()}",
            "Content-Type": "application/json",
        },
        json={"handle": handle, "display_name": display_name},
        timeout=30,
    )
    if resp.status_code not in (200, 201):
        raise SystemExit(
            f"Bot creation failed ({resp.status_code}):\n{resp.text}"
        )

    data = resp.json().get("data", {})
    print(json.dumps({k: v for k, v in data.items() if k != "token"}, indent=2))
    print()
    print("Bot user id :", data.get("id"))
    print("Handle      :", data.get("username"))
    print("Token (shown ONCE — save it now):")
    print()
    print("   ", data.get("token"))
    print()
    print("Add to xchat-price-bot/.env:")
    print(f"    XCHAT_BOT_TOKEN={data.get('token')}")
    print(f"    XCHAT_BOT_ID={data.get('id')}")


if __name__ == "__main__":
    main()
