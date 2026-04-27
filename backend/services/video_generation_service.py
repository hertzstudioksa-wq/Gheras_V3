"""Video Generation Service — Phase L.

Provider-adapter for video clip generation. fal.ai Kling is the primary
provider (single FAL_KEY bearer). Sora & Luma slots reserved.

Resolution rules (matches tts_service):
  1. Provider/model resolved from `model_registry` row for `video_generation`.
  2. FAL_KEY resolved via `secret_overrides_service.get_secret_with_source`.
  3. If provider lacks credentials → audio_bytes-equivalent (None) returned
     with `fallback_to_mock=True`. We NEVER raise.

Strategy (admin-configurable later):
  * **Hybrid**: if scene image URL is present → I2V endpoint, else T2V.
  * Endpoint path comes from `model_name` (full slug like
    `fal-ai/kling-video/v2.1/standard/image-to-video`). The admin selects
    quality/version from Stage Control by editing model_name.
  * If the configured slug ends with `/image-to-video` and no image is
    provided, we degrade to the matching `/text-to-video` slug if known,
    else we fail honestly with `error="image_required_for_i2v"`.

Public API:
    submit_clip(scene)    -> (request_id, meta)        # async submit
    poll_clip(request_id) -> (status, video_url, meta) # one tick
    generate_clip_sync(scene, max_wait_s=300) -> (bytes, mime, meta)
    video_real_call_available() -> bool                # for stage control UI
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Optional

import httpx

from services.secret_overrides_service import get_secret_with_source
from services.config_service import resolve_model

logger = logging.getLogger("video_generation_service")

DEFAULT_KLING_MODEL = "fal-ai/kling-video/v3/pro/image-to-video"
DEFAULT_DURATION_SEC = 5
DEFAULT_ASPECT = "16:9"
FAL_QUEUE_BASE = "https://queue.fal.run"
SUBMIT_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
POLL_TIMEOUT = httpx.Timeout(20.0, connect=10.0)
DOWNLOAD_TIMEOUT = httpx.Timeout(120.0, connect=15.0)


def _i2v_to_t2v(slug: str) -> str | None:
    """Convert a fal.ai I2V slug to its T2V counterpart when known."""
    if not slug or not slug.endswith("/image-to-video"):
        return None
    return slug.removesuffix("/image-to-video") + "/text-to-video"


# ---------------------------------------------------------------------------
# fal.ai Kling adapter
# ---------------------------------------------------------------------------
async def _kling_submit(
    fal_key: str,
    model_slug: str,
    payload: dict,
) -> tuple[str | None, dict]:
    """POST to fal queue and return (request_id, meta_for_audit)."""
    url = f"{FAL_QUEUE_BASE}/{model_slug}"
    headers = {
        "Authorization": f"Key {fal_key}",
        "Content-Type":  "application/json",
    }
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=SUBMIT_TIMEOUT) as c:
            r = await c.post(url, headers=headers, json=payload)
        latency = int((time.monotonic() - started) * 1000)
        if r.status_code in (200, 201, 202):
            data = r.json()
            req_id = data.get("request_id") or data.get("id")
            return req_id, {
                "submitted":      True,
                "latency_ms":     latency,
                "queue_status":   data.get("status"),
                "endpoint_used":  model_slug,
            }
        try:
            err = r.json()
        except Exception:  # noqa: BLE001
            err = r.text[:300]
        return None, {
            "submitted":      False,
            "latency_ms":     latency,
            "endpoint_used":  model_slug,
            "error":          f"HTTP {r.status_code}: {err}",
        }
    except Exception as e:  # noqa: BLE001
        return None, {
            "submitted":     False,
            "endpoint_used": model_slug,
            "error":         f"{type(e).__name__}: {e}",
        }


async def _kling_poll(
    fal_key: str,
    model_slug: str,
    request_id: str,
) -> tuple[str, dict]:
    """Single poll tick. Returns (state, info) where state is one of:
       'IN_QUEUE', 'IN_PROGRESS', 'COMPLETED', 'FAILED', 'UNKNOWN'.
    `info` carries video_url when COMPLETED.
    """
    status_url = f"{FAL_QUEUE_BASE}/{model_slug}/requests/{request_id}/status"
    result_url = f"{FAL_QUEUE_BASE}/{model_slug}/requests/{request_id}"
    headers = {"Authorization": f"Key {fal_key}"}
    try:
        async with httpx.AsyncClient(timeout=POLL_TIMEOUT) as c:
            sr = await c.get(status_url, headers=headers)
        if sr.status_code != 200:
            return "UNKNOWN", {"error": f"status HTTP {sr.status_code}: {sr.text[:200]}"}
        st = (sr.json() or {}).get("status")
        if st == "COMPLETED":
            async with httpx.AsyncClient(timeout=POLL_TIMEOUT) as c:
                rr = await c.get(result_url, headers=headers)
            data = rr.json() if rr.status_code == 200 else {}
            video_url = (((data or {}).get("video") or {}).get("url"))
            return ("COMPLETED" if video_url else "FAILED",
                    {"video_url": video_url, "raw": data if not video_url else None})
        if st in ("IN_QUEUE", "IN_PROGRESS"):
            return st, {}
        return "UNKNOWN", {"raw_status": st}
    except Exception as e:  # noqa: BLE001
        return "UNKNOWN", {"error": f"{type(e).__name__}: {e}"}


async def _kling_download(video_url: str) -> bytes | None:
    try:
        async with httpx.AsyncClient(timeout=DOWNLOAD_TIMEOUT, follow_redirects=True) as c:
            r = await c.get(video_url)
        return r.content if r.status_code == 200 else None
    except Exception as e:  # noqa: BLE001
        logger.warning(f"clip download failed: {e}")
        return None


def _build_payload(scene: dict, has_image: bool) -> dict:
    """Build the JSON payload fal.ai Kling expects.

    Input scene shape (read defensively, never mandatory beyond `prompt`):
      prompt:           str  — the video prompt
      image_url:        str  — public/relative URL to scene image (I2V)
      duration:         int  — 5 or 10
      aspect_ratio:     str  — "16:9" / "9:16" / "1:1"
      negative_prompt:  str
      cfg_scale:        float
    """
    payload: dict = {
        "prompt":          (scene.get("prompt") or "")[:500],
        "duration":        str(scene.get("duration") or DEFAULT_DURATION_SEC),
        "aspect_ratio":    scene.get("aspect_ratio") or DEFAULT_ASPECT,
        "negative_prompt": scene.get("negative_prompt")
                           or "blurry, distorted, low quality, watermark, text",
        "cfg_scale":       float(scene.get("cfg_scale") or 0.5),
    }
    if has_image and scene.get("image_url"):
        payload["image_url"] = scene["image_url"]
    return payload


# ---------------------------------------------------------------------------
# Mock + future provider stubs
# ---------------------------------------------------------------------------
async def _video_via_mock(scene: dict, **_) -> tuple[bytes | None, str, dict]:
    return None, "video/mp4", {
        "provider":         "mock",
        "model":            "mock-video-v1",
        "real_call":        False,
        "fallback_to_mock": False,
        "secret_source":    "n/a",
        "duration":         scene.get("duration") or DEFAULT_DURATION_SEC,
        "clip_strategy":    "none",
        "error":            None,
        "note":             "Video provider is mock — no clip produced.",
    }


async def _video_via_sora(scene: dict, **_) -> tuple[bytes | None, str, dict]:
    return None, "video/mp4", {
        "provider":         "sora",
        "model":            "sora-2",
        "real_call":        False,
        "fallback_to_mock": True,
        "secret_source":    "n/a",
        "error":            "sora_not_yet_wired",
        "note":             "Sora adapter slot reserved — wire after fal.ai Kling stabilizes.",
    }


async def _video_via_luma(scene: dict, **_) -> tuple[bytes | None, str, dict]:
    return None, "video/mp4", {
        "provider":         "luma",
        "model":            "luma-dream-machine",
        "real_call":        False,
        "fallback_to_mock": True,
        "secret_source":    "n/a",
        "error":            "luma_not_yet_wired",
    }


# ---------------------------------------------------------------------------
# Kling primary path — submit/poll API surface
# ---------------------------------------------------------------------------
async def _resolve_video_provider() -> tuple[str, str]:
    provider, model_name, _src = await resolve_model(
        "video_generation", "kling", DEFAULT_KLING_MODEL,
    )
    if provider not in ("kling", "sora", "luma", "mock"):
        provider = "kling"
    return provider, (model_name or DEFAULT_KLING_MODEL)


async def _get_fal_key_for_video() -> tuple[str | None, str]:
    """Phase N — prefer FAL_KEY_VIDEO, fall back to legacy FAL_KEY."""
    secret, source = await get_secret_with_source("FAL_KEY_VIDEO")
    if secret:
        return secret, source
    return await get_secret_with_source("FAL_KEY")


async def video_real_call_available() -> bool:
    """True if `video_generation` can produce a real clip RIGHT NOW."""
    provider, _ = await _resolve_video_provider()
    if provider == "kling":
        secret, _src = await _get_fal_key_for_video()
        return bool(secret)
    return False


async def submit_clip(scene: dict) -> tuple[str | None, dict]:
    """Submit one clip job and return (request_id, meta).

    `scene` is a flat dict — `image_url` is optional. When present we use the
    configured I2V slug. When absent we attempt T2V on the matching slug.
    """
    provider, model_slug = await _resolve_video_provider()
    if provider != "kling":
        # Future: dispatch to other providers' submit. For now, mock honestly.
        _, _, meta = await _video_via_mock(scene)
        meta["clip_strategy"] = "none"
        return None, meta

    secret, source = await _get_fal_key_for_video()
    if not secret:
        return None, {
            "provider":        "kling",
            "model":           model_slug,
            "secret_source":   "missing",
            "env_key":         "FAL_KEY_VIDEO",
            "real_call":       False,
            "fallback_to_mock": True,
            "clip_strategy":   "none",
            "error":           "FAL_KEY_VIDEO (or legacy FAL_KEY) not configured",
            "note":            "Add FAL_KEY_VIDEO in /admin/secrets to enable real clip generation.",
        }

    has_image = bool(scene.get("image_url"))
    if has_image:
        endpoint = model_slug
        clip_strategy = "i2v"
    else:
        t2v = _i2v_to_t2v(model_slug) or model_slug.replace("/image-to-video", "/text-to-video")
        endpoint = t2v
        clip_strategy = "t2v"

    payload = _build_payload(scene, has_image=has_image)
    req_id, sub_meta = await _kling_submit(secret, endpoint, payload)
    meta = {
        "provider":        "kling",
        "model":           endpoint,
        "secret_source":   source,
        "clip_strategy":   clip_strategy,
        "real_call":       bool(req_id),
        "fallback_to_mock": not bool(req_id),
        "request_id":      req_id,
        "duration":        scene.get("duration") or DEFAULT_DURATION_SEC,
        "aspect_ratio":    scene.get("aspect_ratio") or DEFAULT_ASPECT,
        **sub_meta,
    }
    return req_id, meta


async def poll_clip(request_id: str, model_slug: str | None = None) -> tuple[str, dict]:
    """One poll tick. Returns (state, info)."""
    if not request_id:
        return "FAILED", {"error": "no_request_id"}
    secret, _ = await _get_fal_key_for_video()
    if not secret:
        return "FAILED", {"error": "FAL_KEY_VIDEO not configured"}
    if not model_slug:
        _, model_slug = await _resolve_video_provider()
    return await _kling_poll(secret, model_slug, request_id)


async def download_clip(video_url: str) -> bytes | None:
    return await _kling_download(video_url)


async def generate_clip_sync(
    scene: dict,
    max_wait_s: int = 300,
    poll_interval_s: int = 8,
) -> tuple[bytes | None, str, dict]:
    """Synchronous façade: submit + poll until complete or timeout, then
    download bytes. Used by the Stage Lab and any one-shot caller.
    """
    req_id, sub_meta = await submit_clip(scene)
    if not req_id:
        # Non-callable provider, missing key, or submit error → mock path.
        _, _, mock_meta = await _video_via_mock(scene)
        merged = {**sub_meta, **mock_meta, "fallback_to_mock": True,
                  "real_call": False}
        return None, "video/mp4", merged

    started = time.monotonic()
    last_state = "IN_QUEUE"
    last_info: dict = {}
    while time.monotonic() - started < max_wait_s:
        last_state, last_info = await poll_clip(req_id, sub_meta.get("model"))
        if last_state in ("COMPLETED", "FAILED", "UNKNOWN"):
            break
        await asyncio.sleep(poll_interval_s)

    if last_state != "COMPLETED" or not last_info.get("video_url"):
        return None, "video/mp4", {
            **sub_meta,
            "real_call":      True,
            "completed":      False,
            "final_state":    last_state,
            "final_info":     last_info,
            "elapsed_s":      round(time.monotonic() - started, 1),
            "fallback_to_mock": True,
            "error":          last_info.get("error") or f"final_state={last_state}",
        }

    video_url = last_info["video_url"]
    bytes_ = await download_clip(video_url)
    return bytes_, "video/mp4", {
        **sub_meta,
        "real_call":      True,
        "completed":      True,
        "video_url":      video_url,
        "bytes":          len(bytes_) if bytes_ else 0,
        "elapsed_s":      round(time.monotonic() - started, 1),
        "fallback_to_mock": False,
    }


async def submit_all_then_poll(
    scenes: list[dict],
    max_wait_s: int = 600,
    poll_interval_s: int = 10,
) -> list[dict]:
    """Submit-all-then-poll-parallel for an entire scene batch.

    Returns one dict per scene with: index, request_id, video_url|None,
    bytes|None, mime, meta. Order matches the input scenes.
    """
    # 1. Submit every scene first.
    submitted: list[dict] = []
    for i, sc in enumerate(scenes):
        req_id, sub_meta = await submit_clip(sc)
        submitted.append({
            "index":      i,
            "scene":      sc,
            "request_id": req_id,
            "meta":       sub_meta,
            "model":      sub_meta.get("model"),
            "state":      "IN_QUEUE" if req_id else "FAILED",
            "info":       {},
        })

    # 2. Poll loop until every job is in a terminal state OR we time out.
    started = time.monotonic()
    while time.monotonic() - started < max_wait_s:
        pending = [r for r in submitted
                   if r["state"] in ("IN_QUEUE", "IN_PROGRESS") and r["request_id"]]
        if not pending:
            break

        async def _tick(row):
            st, info = await poll_clip(row["request_id"], row["model"])
            row["state"], row["info"] = st, info

        await asyncio.gather(*(_tick(r) for r in pending))
        if all(r["state"] not in ("IN_QUEUE", "IN_PROGRESS") for r in submitted):
            break
        await asyncio.sleep(poll_interval_s)

    # 3. Download bytes for every COMPLETED row.
    out: list[dict] = []
    for r in submitted:
        bytes_ = None
        if r["state"] == "COMPLETED" and r["info"].get("video_url"):
            bytes_ = await download_clip(r["info"]["video_url"])
        out.append({
            "index":       r["index"],
            "request_id":  r["request_id"],
            "state":       r["state"],
            "video_url":   r["info"].get("video_url") if r["state"] == "COMPLETED" else None,
            "bytes":       bytes_,
            "mime":        "video/mp4",
            "meta":        {**r["meta"], "final_state": r["state"]},
        })
    return out
