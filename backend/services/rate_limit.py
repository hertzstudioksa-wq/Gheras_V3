"""Per-IP / per-user request limits (audit MISS-11, CS-13).

A sliding window kept in memory: the backend runs as one process, so this is
enough to stop password guessing, sign-up farming and loops on endpoints that
start paid work. Limits are deliberately loose for real parents.
"""
from __future__ import annotations

import time
from collections import deque

from fastapi import HTTPException, Request

_TRUSTED_PROXIES = {"127.0.0.1", "::1"}
_hits: dict[str, deque] = {}
_last_sweep = time.monotonic()


def client_ip(request: Request) -> str:
    """The caller's IP; behind our own nginx, the forwarded address."""
    ip = request.client.host if request.client else "unknown"
    if ip in _TRUSTED_PROXIES:
        forwarded = request.headers.get("X-Real-IP") or (request.headers.get("X-Forwarded-For") or "").split(",")[0]
        if forwarded.strip():
            return forwarded.strip()
    return ip


def _sweep(now: float) -> None:
    global _last_sweep
    if now - _last_sweep < 300:
        return
    _last_sweep = now
    for key in [k for k, q in _hits.items() if not q or now - q[-1] > 3600]:
        _hits.pop(key, None)


def count(key: str, window: float) -> int:
    now = time.monotonic()
    q = _hits.get(key)
    if not q:
        return 0
    while q and now - q[0] > window:
        q.popleft()
    return len(q)


def record(key: str) -> None:
    now = time.monotonic()
    _hits.setdefault(key, deque()).append(now)
    _sweep(now)


def check(key: str, limit: int, window: float, message: str = "طلبات كتير ورا بعض — جرّب كمان شوية") -> None:
    """Count this call against `key`; refuse with 429 once over the limit."""
    if count(key, window) >= limit:
        raise HTTPException(status_code=429, detail=message, headers={"Retry-After": str(int(window))})
    record(key)


def per_ip(name: str, limit: int, window: float, message: str | None = None):
    """FastAPI dependency: at most `limit` calls per `window` seconds per IP."""
    async def dependency(request: Request) -> None:
        check(f"{name}:{client_ip(request)}", limit, window, *([message] if message else []))
    return dependency


def reset() -> None:
    _hits.clear()
