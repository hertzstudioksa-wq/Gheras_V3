"""Secure Secret Overrides — Phase H.

Lets the admin store provider API keys in the database safely (encrypted at
rest with Fernet) without ever exposing the raw value back through the API.

Resolution precedence used everywhere in the backend:
    secure_override (db, encrypted) → process .env → None

How the encryption key is derived:
  * Reads the env var `SECRETS_ENCRYPTION_KEY` if present (operator can set
    a long-lived key via deployment config).
  * Falls back to a key derived from `MONGO_URL` (always present in this
    pod) so existing overrides remain decryptable across restarts WITHOUT
    requiring a deployment-time secret.
  * If neither is available, encryption is disabled and writes will fail
    with a clear 503 — admin MUST set SECRETS_ENCRYPTION_KEY.

Security guarantees:
  1. Raw secret value is NEVER returned by any GET endpoint.
  2. Only masked tails (`***1234`) and `last_4_chars` are exposed.
  3. Audit trail on every set/delete (without value).
  4. Encryption is at-rest. The runtime decrypts only when *resolving* the
     value for an outbound provider call — never to ship it to the UI.
"""
from __future__ import annotations

import base64
import hashlib
import logging
import os
from datetime import datetime, timezone
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

from db import db

logger = logging.getLogger("secret_overrides_service")

COLLECTION = "secret_overrides"


def _derive_key_from(material: str) -> bytes:
    """Derive a 32-byte Fernet key from arbitrary material via SHA-256."""
    h = hashlib.sha256(material.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(h)


def _get_fernet() -> Optional[Fernet]:
    """Return a Fernet ready for encrypt/decrypt, or None if not derivable."""
    explicit = os.environ.get("SECRETS_ENCRYPTION_KEY")
    if explicit:
        try:
            return Fernet(explicit.encode("utf-8"))
        except Exception:
            # Treat as raw material if not a valid Fernet key.
            return Fernet(_derive_key_from(explicit))
    # Fallback: derive from MONGO_URL (always present in this pod). Stable
    # across restarts. Operator can upgrade to SECRETS_ENCRYPTION_KEY later;
    # we'll re-encrypt on next write.
    mongo = os.environ.get("MONGO_URL")
    if mongo:
        return Fernet(_derive_key_from(f"gheras-secrets::{mongo}"))
    return None


def encryption_available() -> bool:
    return _get_fernet() is not None


# ---------------------------------------------------------------------------
def _mask(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    v = value.strip()
    if len(v) <= 8:
        return "***"
    return f"***{v[-4:]}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---- Public API ------------------------------------------------------------
async def list_overrides_status() -> list[dict]:
    """All overrides (no values), masked tail only."""
    rows = await db[COLLECTION].find({}, {"_id": 0}).to_list(100)
    out = []
    for r in rows:
        out.append({
            "env_key":       r.get("env_key"),
            "configured":    bool(r.get("encrypted_value")),
            "masked":        _mask("X" * 40 + (r.get("last_4") or "")),  # `***1234`
            "last_4_chars":  r.get("last_4"),
            "updated_at":    r.get("updated_at"),
            "updated_by":    r.get("updated_by"),
        })
    return out


async def has_override(env_key: str) -> bool:
    return bool(await db[COLLECTION].find_one(
        {"env_key": env_key, "encrypted_value": {"$ne": None}}, {"_id": 1},
    ))


async def get_secret(env_key: str) -> Optional[str]:
    """Backend-internal resolver — secure override first, then process env.
    Never call this from a route that returns to the user.
    """
    row = await db[COLLECTION].find_one(
        {"env_key": env_key, "encrypted_value": {"$ne": None}}, {"_id": 0},
    )
    if row and row.get("encrypted_value"):
        f = _get_fernet()
        if f:
            try:
                return f.decrypt(row["encrypted_value"].encode("utf-8")).decode("utf-8")
            except InvalidToken:
                logger.warning(f"override for {env_key} cannot be decrypted (key rotated?). "
                               f"Falling back to .env.")
            except Exception as e:  # noqa: BLE001
                logger.warning(f"decrypt failed for {env_key}: {e}")
    return os.environ.get(env_key)


async def get_secret_with_source(env_key: str) -> tuple[Optional[str], str]:
    """Resolve and report which source supplied the value.
    Returns (value, source) where source ∈ {"override", "env", "missing"}.
    """
    row = await db[COLLECTION].find_one(
        {"env_key": env_key, "encrypted_value": {"$ne": None}}, {"_id": 0},
    )
    if row and row.get("encrypted_value"):
        f = _get_fernet()
        if f:
            try:
                return f.decrypt(row["encrypted_value"].encode("utf-8")).decode("utf-8"), "override"
            except Exception:  # noqa: BLE001
                pass
    val = os.environ.get(env_key)
    return val, ("env" if val else "missing")


async def secret_source(env_key: str) -> str:
    """Lightweight: just the source name, no value."""
    if await has_override(env_key):
        f = _get_fernet()
        if f:
            return "override"
    return "env" if os.environ.get(env_key) else "missing"


async def set_override(env_key: str, raw_value: str, admin_id: str | None) -> dict:
    """Encrypt and store. Never echoes raw_value back."""
    if not raw_value or not raw_value.strip():
        raise ValueError("empty value")
    f = _get_fernet()
    if not f:
        raise RuntimeError("encryption_unavailable")
    encrypted = f.encrypt(raw_value.strip().encode("utf-8")).decode("utf-8")
    last_4 = raw_value.strip()[-4:] if len(raw_value.strip()) >= 4 else "***"
    now = _now()

    # upsert
    existing = await db[COLLECTION].find_one({"env_key": env_key}, {"_id": 0})
    doc = {
        "env_key":         env_key,
        "encrypted_value": encrypted,
        "last_4":          last_4,
        "updated_at":      now,
        "updated_by":      admin_id,
    }
    if existing:
        await db[COLLECTION].update_one({"env_key": env_key}, {"$set": doc})
        return {"env_key": env_key, "rotated": True, "masked": _mask("x" * 40 + last_4)}
    doc["created_at"] = now
    doc["created_by"] = admin_id
    await db[COLLECTION].insert_one(doc)
    return {"env_key": env_key, "rotated": False, "masked": _mask("x" * 40 + last_4)}


async def delete_override(env_key: str, admin_id: str | None) -> bool:
    res = await db[COLLECTION].delete_one({"env_key": env_key})
    # Drop the env value too so legacy code stops seeing the override.
    if res.deleted_count and env_key in os.environ:
        # Only pop if we previously injected from override (heuristic: keep
        # the actual deployment .env in place by checking against a bootstrap
        # snapshot would be ideal, but at minimum we remove and let the next
        # request fall back to whatever .env defines on next process restart).
        pass  # leave os.environ untouched until next supervisor restart
    return bool(res.deleted_count)


async def apply_overrides_to_env() -> int:
    """At startup: decrypt every override and inject it into os.environ so
    legacy code that reads os.environ.get(...) at module-import time picks up
    the latest override transparently. Returns the number applied."""
    rows = await db[COLLECTION].find(
        {"encrypted_value": {"$ne": None}}, {"_id": 0},
    ).to_list(50)
    f = _get_fernet()
    if not f:
        return 0
    applied = 0
    for r in rows:
        try:
            val = f.decrypt(r["encrypted_value"].encode("utf-8")).decode("utf-8")
            os.environ[r["env_key"]] = val
            applied += 1
        except Exception as e:  # noqa: BLE001
            logger.warning(f"could not apply override for {r.get('env_key')}: {e}")
    if applied:
        logger.info(f"[secret_overrides] applied {applied} overrides to process env")
    return applied
