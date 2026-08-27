"""Configuration for the XChat price bot.

All secrets come from environment variables (a local .env file is loaded
first if present). Nothing secret is ever written to the repo; runtime
state (keys, cursors, alerts) lives under state/ which is gitignored.
"""

import os
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
STATE_DIR = Path(os.environ.get("XCHAT_STATE_DIR", PROJECT_DIR / "state"))

STATE_FILE = STATE_DIR / "state.json"
KEYS_FILE = STATE_DIR / "keys.json"

API_BASE = os.environ.get("X_API_BASE", "https://api.x.com")


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip("'\"")
        os.environ.setdefault(key, value)


_load_dotenv(PROJECT_DIR / ".env")


def app_bearer_token() -> str:
    """App-only bearer token from the X developer portal.

    Only needed by register_bot.py — day-to-day the bot runs on its own
    xcbot_ token.
    """
    token = os.environ.get("X_APP_BEARER_TOKEN", "")
    if not token:
        raise SystemExit(
            "X_APP_BEARER_TOKEN is not set. Get it from your app in the X "
            "developer portal and export it or put it in xchat-price-bot/.env"
        )
    return token


def bot_token() -> str:
    """The bot's own bearer token (xcbot_...), minted by register_bot.py."""
    token = os.environ.get("XCHAT_BOT_TOKEN", "")
    if not token:
        raise SystemExit(
            "XCHAT_BOT_TOKEN is not set. Run register_bot.py first and "
            "export the xcbot_ token it prints (or put it in .env)."
        )
    return token


# Seconds between inbox polls / alert checks.
POLL_INTERVAL = float(os.environ.get("XCHAT_POLL_INTERVAL", "5"))
ALERT_INTERVAL = float(os.environ.get("XCHAT_ALERT_INTERVAL", "30"))
