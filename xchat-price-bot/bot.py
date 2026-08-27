"""XChat Solana price/alert bot.

DM the bot:
    price <ticker|mint>     (or just: BONK, $WIF, a mint address)
    alert <ticker|mint> above|below <price>
    alerts                  list alerts set in this conversation
    clear                   remove this conversation's alerts
    help

Run:  XCHAT_BOT_TOKEN=xcbot_... python3 bot.py

The bot polls its inbox (no public webhook URL needed), decrypts incoming
messages with the Chat XDK, and replies encrypted. On the very first run it
snapshots the inbox and only answers messages that arrive afterwards.
"""

import json
import re
import time
import traceback
from typing import Any, Dict, List, Optional

from xdk import Client
from xdk.chat.models import SendMessageRequest

import config
import identity
import price
from identity import as_dict

HELP = (
    "gm! I quote Solana token prices (data: DexScreener).\n\n"
    "price <ticker|mint> - current price (or just send the ticker)\n"
    "alert <ticker|mint> above|below <price> - DM you when it crosses\n"
    "alerts - list alerts for this chat\n"
    "clear - remove this chat's alerts\n"
    "help - this message"
)

ALERT_RE = re.compile(
    r"^alert\s+(?P<query>\S+)\s+(?P<dir>above|below|over|under|>|<)\s+\$?(?P<price>[\d.,]+)$",
    re.IGNORECASE,
)


# ---------------------------------------------------------------- state

def load_state() -> Dict[str, Any]:
    if config.STATE_FILE.is_file():
        return json.loads(config.STATE_FILE.read_text())
    return {"cursors": {}, "alerts": [], "initialized": False}


def save_state(state: Dict[str, Any]) -> None:
    config.STATE_DIR.mkdir(parents=True, exist_ok=True)
    config.STATE_FILE.write_text(json.dumps(state, indent=2))


# ---------------------------------------------------------------- commands

def handle_command(text: str, conversation_id: str, state: Dict[str, Any]) -> str:
    text = text.strip()
    lowered = text.lower()

    if lowered in ("help", "start", "gm", "hi", "hello"):
        return HELP

    if lowered == "alerts":
        mine = [a for a in state["alerts"] if a["conversation_id"] == conversation_id]
        if not mine:
            return "No alerts set in this chat. Try: alert BONK above 0.00003"
        return "Active alerts:\n" + "\n".join(
            f"- {a['query']} {a['direction']} ${a['threshold']:g}" for a in mine
        )

    if lowered in ("clear", "clear alerts"):
        before = len(state["alerts"])
        state["alerts"] = [
            a for a in state["alerts"] if a["conversation_id"] != conversation_id
        ]
        save_state(state)
        return f"Removed {before - len(state['alerts'])} alert(s)."

    match = ALERT_RE.match(text)
    if match:
        query = match.group("query")
        direction = "above" if match.group("dir").lower() in ("above", "over", ">") else "below"
        threshold = float(match.group("price").replace(",", ""))
        current, reply = price.quote(query)
        if current is None:
            return reply
        state["alerts"].append(
            {
                "conversation_id": conversation_id,
                "query": query.lstrip("$"),
                "direction": direction,
                "threshold": threshold,
                "created_at": time.time(),
            }
        )
        save_state(state)
        return (
            f"Alert set: {query} {direction} ${threshold:g} "
            f"(now {price._fmt_price(current)}). I'll DM you when it crosses."
        )

    if lowered.startswith("alert"):
        return "Usage: alert <ticker|mint> above|below <price>"

    query = text
    if lowered.startswith("price "):
        query = text[6:].strip()
    if not query or len(query.split()) > 1:
        return HELP
    _, reply = price.quote(query)
    return reply


def check_alerts(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return fired alerts (already removed from state) with reply text."""
    fired = []
    remaining = []
    for alert in state["alerts"]:
        current, formatted = price.quote(alert["query"])
        if current is None:
            remaining.append(alert)  # lookup failed; keep and retry later
            continue
        crossed = (
            current >= alert["threshold"]
            if alert["direction"] == "above"
            else current <= alert["threshold"]
        )
        if crossed:
            fired.append(
                {
                    "conversation_id": alert["conversation_id"],
                    "text": (
                        f"ALERT: {alert['query']} is {alert['direction']} "
                        f"${alert['threshold']:g}\n\n{formatted}"
                    ),
                }
            )
        else:
            remaining.append(alert)
    if fired:
        state["alerts"] = remaining
        save_state(state)
    return fired


# ---------------------------------------------------------------- messaging

def send_text(client: Client, chat, conversation_id: str, text: str,
              conversation_token: Optional[str] = None) -> None:
    payload = chat.encrypt_message(conversation_id, text)
    body = SendMessageRequest(
        message_id=payload.message_id,
        encoded_message_create_event=payload.encrypted_content,
        encoded_message_event_signature=payload.encoded_event_signature,
        conversation_token=conversation_token,
    )
    client.chat.send_message(conversation_id, body)


def fetch_new_events(client: Client, conversation_id: str,
                     last_seen: Optional[str]) -> List[Dict[str, Any]]:
    """Events newer than last_seen, oldest first."""
    fields = [
        "id",
        "conversation_id",
        "conversation_token",
        "created_at",
        "encoded_event",
        "sender_id",
    ]
    collected: List[Dict[str, Any]] = []
    for page in client.chat.get_conversation_events(
        conversation_id, max_results=50, chat_message_event_fields=fields
    ):
        data = getattr(page, "data", None) or []
        stop = False
        for event in data:  # newest first from the API
            e = as_dict(event)
            if last_seen is not None and str(e.get("id")) == str(last_seen):
                stop = True
                break
            collected.append(e)
        if stop or last_seen is None:
            break  # first page is enough when we have no cursor yet
    collected.reverse()
    return collected


def decrypt_batch(chat, client: Client, events: List[Dict[str, Any]],
                  signing_keys: Dict[str, List]) -> List[Dict[str, Any]]:
    """Decrypt encoded events; returns decrypted message dicts.

    signing_keys accumulates each sender's verification keys across calls
    so we only hit the public-key endpoint once per sender.
    """
    senders = {str(e["sender_id"]) for e in events if e.get("sender_id")}
    new_senders = [s for s in senders if s not in signing_keys]
    if new_senders:
        for sender in new_senders:
            signing_keys[sender] = identity.signing_keys_for(client, [sender])
        chat.set_signing_keys([k for keys in signing_keys.values() for k in keys])

    encoded = [e["encoded_event"] for e in events if e.get("encoded_event")]
    if not encoded:
        return []
    result = chat.decrypt_events(encoded)
    result = result if isinstance(result, dict) else as_dict(result)
    messages = result.get("messages") or []
    for err in result.get("errors") or []:
        print(f"  ! decrypt error: {err}")
    return [as_dict(m) for m in messages]


# ---------------------------------------------------------------- main loop

def main() -> None:
    client = Client(access_token=config.bot_token())

    import os
    bot_id = os.environ.get("XCHAT_BOT_ID", "")
    if not bot_id:
        me = as_dict(client.users.get_me().data)
        bot_id = str(me["id"])
        print(f"Running as @{me.get('username')} (id {bot_id})")
    else:
        print(f"Running as bot id {bot_id}")

    chat, _version = identity.load_or_create(client, bot_id)
    state = load_state()
    known_signers: Dict[str, List] = {}
    last_alert_check = 0.0
    first_run = not state.get("initialized", False)
    if first_run:
        print("First run: snapshotting inbox; only new messages get replies.")

    while True:
        try:
            # -- inbox poll
            conversations = []
            for page in client.chat.get_conversations(
                max_results=50, chat_conversation_fields=["id", "type", "updated_at"]
            ):
                conversations.extend(as_dict(c) for c in (getattr(page, "data", None) or []))
                break  # first page: most recently active conversations

            for conv in conversations:
                conv_id = str(conv["id"])
                cursor = state["cursors"].get(conv_id)
                events = fetch_new_events(client, conv_id, cursor)
                if not events:
                    continue
                state["cursors"][conv_id] = str(events[-1]["id"])
                conv_token = next(
                    (e["conversation_token"] for e in reversed(events)
                     if e.get("conversation_token")),
                    None,
                )

                if first_run or cursor is None:
                    # Just learn keys from the backlog; don't answer old messages.
                    decrypt_batch(chat, client, events, known_signers)
                    save_state(state)
                    continue

                for message in decrypt_batch(chat, client, events, known_signers):
                    event = message.get("event") or message
                    if event.get("type") != "Message":
                        continue
                    if str(event.get("sender_id")) == bot_id:
                        continue
                    content = event.get("content") or {}
                    if content.get("content_type") != "Text":
                        continue
                    text = content.get("text", "")
                    print(f"<- [{conv_id}] {event.get('sender_id')}: {text!r}"
                          f" (verified={event.get('verified')})")
                    reply = handle_command(text, conv_id, state)
                    send_text(client, chat, conv_id, reply, conv_token)
                    print(f"-> [{conv_id}] {reply.splitlines()[0]}")
                save_state(state)

            if first_run:
                state["initialized"] = True
                save_state(state)
                first_run = False
                print("Inbox snapshot complete. Listening for new messages...")

            # -- alert checks
            if state["alerts"] and time.time() - last_alert_check > config.ALERT_INTERVAL:
                last_alert_check = time.time()
                for fired in check_alerts(state):
                    send_text(client, chat, fired["conversation_id"], fired["text"])
                    print(f"-> alert fired in {fired['conversation_id']}")

        except KeyboardInterrupt:
            print("bye")
            return
        except Exception:
            traceback.print_exc()

        time.sleep(config.POLL_INTERVAL)


if __name__ == "__main__":
    main()
