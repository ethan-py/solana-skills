"""Bot crypto identity: local key storage + signing-key lookup.

The Chat XDK does all encryption client-side. Instead of the interactive
passcode/Juicebox backup flow (built for humans on phones), the bot keeps
its exported private-key blob in state/keys.json. Guard that file like a
password: anyone holding it plus the bot token can read the bot's DMs.
"""

import json
import os
from typing import Any, Dict, List

from chat_xdk import Chat, base64_to_bytes, bytes_to_base64
from xdk.chat.models import AddUserPublicKeyRequest

import config


def as_dict(obj: Any) -> Dict[str, Any]:
    """Normalize xdk pydantic models / dicts to plain dicts."""
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    return dict(obj)


def load_or_create(client, bot_user_id: str):
    """Return (chat, key_version), generating + publishing keys on first run."""
    config.STATE_DIR.mkdir(parents=True, exist_ok=True)

    if config.KEYS_FILE.is_file():
        saved = json.loads(config.KEYS_FILE.read_text())
        version = str(saved["version"])
        chat = Chat()
        chat.import_keys(bytes(base64_to_bytes(saved["keys_b64"])), version=version)
        chat.set_identity(str(bot_user_id), version)
        chat.set_cache_keys(True)
        return chat, version

    chat = Chat()
    reg = chat.generate_keypairs()
    pk = reg.public_key
    version = str(reg.version)

    client.chat.add_user_public_key(
        str(bot_user_id),
        AddUserPublicKeyRequest(
            public_key={
                "identity_public_key_signature": pk.identity_public_key_signature,
                "public_key": pk.public_key,
                "public_key_fingerprint": pk.public_key_fingerprint,
                "registration_method": pk.registration_method,
                "signing_public_key": pk.signing_public_key,
                "signing_public_key_signature": pk.signing_public_key_signature,
            },
            version=version,
            generate_version=bool(reg.generate_version),
        ),
    )

    config.KEYS_FILE.write_text(
        json.dumps(
            {
                "keys_b64": bytes_to_base64(bytes(chat.export_keys())),
                "version": version,
                "user_id": str(bot_user_id),
                "fingerprint": pk.public_key_fingerprint,
            },
            indent=2,
        )
    )
    os.chmod(config.KEYS_FILE, 0o600)

    chat.set_identity(str(bot_user_id), version)
    chat.set_cache_keys(True)
    print(f"Registered new public key (version {version}) for bot {bot_user_id}")
    return chat, version


def signing_keys_for(client, user_ids: List[str]) -> List[Dict[str, Any]]:
    """Fetch signing keys for the given users, for signature verification."""
    keys: List[Dict[str, Any]] = []
    for user_id in user_ids:
        try:
            resp = client.users.get_public_key(
                str(user_id),
                public_key_fields=[
                    "public_key_version",
                    "public_key",
                    "signing_public_key",
                    "identity_public_key_signature",
                ],
            )
        except Exception as exc:  # user without registered keys, etc.
            print(f"  ! could not fetch public key for {user_id}: {exc}")
            continue
        data = getattr(resp, "data", None) or []
        if not isinstance(data, list):
            data = [data]
        for record in data:
            r = as_dict(record)
            keys.append(
                {
                    "user_id": str(user_id),
                    "public_key_version": r.get("public_key_version"),
                    "public_key": r.get("signing_public_key"),
                    "identity_public_key": r.get("public_key"),
                    "identity_public_key_signature": r.get(
                        "identity_public_key_signature"
                    ),
                }
            )
    return keys
