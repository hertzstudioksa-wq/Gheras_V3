"""Object storage for uploads and generated media.

Backends (STORAGE_BACKEND):
  * "local"   — default. Files live under STORAGE_DIR (default: <repo>/.media
                in dev; set it outside the deploy folder in production, e.g.
                /var/lib/gheras/media, so deploys never touch customer files).
  * "emergent" — legacy Emergent object store, kept only to read files created
                before the migration. Needs EMERGENT_LLM_KEY.

Every caller uses the same synchronous API (run it in a thread pool from async
code): put_object(path, data, content_type) -> {"path", "size"},
get_object(path) -> (bytes, content_type), delete_object(path) -> bool.
"""
import logging
import mimetypes
import os
from pathlib import Path

import requests

APP_NAME = os.environ.get("APP_NAME", "gheras")
STORAGE_BACKEND = os.environ.get("STORAGE_BACKEND", "local").strip().lower()
STORAGE_DIR = Path(os.environ.get("STORAGE_DIR") or Path(__file__).resolve().parent.parent / ".media")

EMERGENT_STORAGE_URL = "https://integrations.emergentagent.com/objstore/api/v1/storage"

logger = logging.getLogger("storage")
_emergent_storage_key: str | None = None


def init_storage() -> str | None:
    """Prepare the configured backend. Safe to call multiple times."""
    if STORAGE_BACKEND == "local":
        STORAGE_DIR.mkdir(parents=True, exist_ok=True)
        logger.info(f"Local storage ready at {STORAGE_DIR}")
        return str(STORAGE_DIR)
    if STORAGE_BACKEND == "emergent":
        return _emergent_key()
    raise RuntimeError(f"Unknown STORAGE_BACKEND: {STORAGE_BACKEND}")


def put_object(path: str, data: bytes, content_type: str) -> dict:
    if STORAGE_BACKEND == "emergent":
        return _emergent_put(path, data, content_type)
    target = _local_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    # Write then rename so a crash never leaves a half-written file in place.
    tmp = target.with_name(target.name + ".part")
    tmp.write_bytes(data)
    os.replace(tmp, target)
    return {"path": path, "size": len(data)}


def get_object(path: str) -> tuple[bytes, str]:
    if STORAGE_BACKEND == "emergent":
        return _emergent_get(path)
    target = _local_path(path)
    if not target.is_file():
        raise FileNotFoundError(path)
    content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
    return target.read_bytes(), content_type


def delete_object(path: str) -> bool:
    """Remove a stored object. Returns False when it was already gone."""
    if STORAGE_BACKEND == "emergent":
        raise RuntimeError("Emergent object storage has no delete API")
    target = _local_path(path)
    if not target.is_file():
        return False
    target.unlink()
    return True


def _local_path(path: str) -> Path:
    """Map a storage path to a file under STORAGE_DIR, refusing anything that escapes it."""
    rel = Path(path.lstrip("/\\"))
    if not path or rel.is_absolute() or ".." in rel.parts:
        raise ValueError(f"Invalid storage path: {path!r}")
    root = STORAGE_DIR.resolve()
    target = (root / rel).resolve()
    if root not in target.parents:
        raise ValueError(f"Invalid storage path: {path!r}")
    return target


# --- Legacy Emergent backend ---------------------------------------------------
def _emergent_key() -> str | None:
    global _emergent_storage_key
    if _emergent_storage_key:
        return _emergent_storage_key
    emergent_key = os.environ.get("EMERGENT_LLM_KEY", "")
    if not emergent_key:
        logger.warning("STORAGE_BACKEND=emergent but EMERGENT_LLM_KEY is not set — storage disabled")
        return None
    try:
        resp = requests.post(f"{EMERGENT_STORAGE_URL}/init", json={"emergent_key": emergent_key}, timeout=30)
        resp.raise_for_status()
        _emergent_storage_key = resp.json().get("storage_key")
        logger.info("Emergent object storage initialized")
        return _emergent_storage_key
    except Exception as e:
        logger.error(f"Emergent storage init failed: {e}")
        return None


def _emergent_put(path: str, data: bytes, content_type: str) -> dict:
    key = _emergent_key()
    if not key:
        raise RuntimeError("Object storage is not available")
    resp = requests.put(
        f"{EMERGENT_STORAGE_URL}/objects/{path}",
        headers={"X-Storage-Key": key, "Content-Type": content_type},
        data=data,
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()


def _emergent_get(path: str) -> tuple[bytes, str]:
    key = _emergent_key()
    if not key:
        raise RuntimeError("Object storage is not available")
    resp = requests.get(f"{EMERGENT_STORAGE_URL}/objects/{path}", headers={"X-Storage-Key": key}, timeout=60)
    resp.raise_for_status()
    return resp.content, resp.headers.get("Content-Type", "application/octet-stream")


MIME_TYPES = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
    "gif": "image/gif",
}
ALLOWED_EXT = set(MIME_TYPES.keys())
MAX_BYTES = 6 * 1024 * 1024  # 6 MB
