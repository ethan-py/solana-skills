"""Offline-ish sanity checks: no X credentials required.

Covers DexScreener lookups (live public API), command parsing, and the
Chat XDK keypair export/import round trip.
"""

from chat_xdk import Chat, base64_to_bytes, bytes_to_base64

import bot
import price


def test_crypto_roundtrip():
    chat = Chat()
    reg = chat.generate_keypairs()
    blob = bytes_to_base64(bytes(chat.export_keys()))
    restored = Chat()
    restored.import_keys(bytes(base64_to_bytes(blob)), version=str(reg.version))
    assert restored.has_identity_key()
    restored.set_identity("1", str(reg.version))
    assert restored.is_unlocked()
    print("crypto round trip     OK  (fingerprint "
          f"{restored.get_public_key_fingerprint()[:12]}...)")


def test_price_lookup():
    for query in ["SOL", "BONK", "So11111111111111111111111111111111111111112"]:
        value, reply = price.quote(query)
        assert value is not None and value > 0, f"no price for {query}: {reply}"
        print(f"price {query[:12]:<14} OK  ${value:,.6f}")


def test_command_parsing():
    state = {"cursors": {}, "alerts": [], "initialized": True}
    assert "price" in bot.handle_command("help", "c1", state).lower()
    reply = bot.handle_command("alert SOL above 1", "c1", state)
    assert state["alerts"] and state["alerts"][0]["direction"] == "above", reply
    assert "SOL" in bot.handle_command("alerts", "c1", state)
    fired = bot.check_alerts(state)  # SOL > $1, so this must fire
    assert fired and not state["alerts"], "alert should have fired"
    assert "ALERT" in fired[0]["text"]
    assert "Removed" in bot.handle_command("clear", "c1", state)
    assert "Usage" in bot.handle_command("alert nonsense", "c1", state)
    print("command parsing       OK  (alert set + fired + cleared)")


if __name__ == "__main__":
    import config  # noqa: F401  (loads .env if present; harmless without)
    test_crypto_roundtrip()
    test_command_parsing()
    test_price_lookup()
    print("\nAll smoke tests passed.")
