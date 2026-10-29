"""Comfy Cloud calls: shot keyframes (Qwen Image 2.1) and shot clips (Wan 2.2).

The app stays the orchestrator; Comfy only runs the workflows exported to
backend/comfy_workflows/ (the README there lists the placeholders, the calls and
the prompt template). What the API answered when this was written:

  upload    POST /api/upload/image   multipart "image" -> {"name"}; content-addressed, free
  submit    POST /api/prompt         {"prompt": <workflow>} -> {"prompt_id", "node_errors"}
  wait      GET  /api/jobs/{id}      status pending | in_progress | completed | failed | cancelled;
                                     times in ms; files under outputs[<node>].images (clips too)
  download  GET  /api/view           302 to a signed storage URL — fetched without our key
  balance   GET  /api/billing/usage/timeseries   summary.balance.amount_cents (free)

Credits running out: 402 at submit, 429 "User has not paid", or a job failed
with InsufficientFundsError / InactiveSubscriptionError. Each locks the engine
like fal's exhausted balance (engine_health); every error answer is logged in
full and the latest is kept on the engine_health doc, so its wording is known.
"""
from __future__ import annotations

import asyncio
import contextlib
import functools
import heapq
import itertools
import json
import logging
import os
import re
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

from services import engine_health
from services.ai import AIConfigError, AIError, AIPermanentError, classify_http_error, fake_providers

logger = logging.getLogger("ai.comfy")

DEFAULT_BASE_URL = "https://cloud.comfy.org"
WORKFLOW_DIR = Path(__file__).resolve().parents[2] / "comfy_workflows"
DEFAULT_PREFIX = "gheras/app"
MAX_REFS = 10
MAX_POLL_ERRORS = 5
SETTING_MAX_CONCURRENT = "comfy.max_concurrent"
SETTING_USD_PER_GPU_SECOND = "comfy.usd_per_gpu_second"
# Plan credits: 0.39 credits per GPU-second at ~211 credits per USD (an API
# deployment bills about half: $3.49/h ≈ $0.00097/s).
DEFAULT_USD_PER_GPU_SECOND = 0.0019
LIMIT_CACHE_SECONDS = 15
LOCK_EXCEPTIONS = ("InsufficientFundsError", "InactiveSubscriptionError")
PERMANENT_EXCEPTIONS = ("ValidationError",)

# Node ids come from the exported files. `refs_node` takes images.image_1..N;
# the *_input pairs (node, input) are what the rehearsal fakes read back.
WORKFLOWS = {
    "keyframe_qwen21": {"output_node": "461", "ints": {"seed"}, "refs_node": "459:474",
                        "prompt_input": ("459:474", "prompt")},
    # The same at the sheet's portrait 1024x1536: a drawn sheet's head made the right
    # size for the age (services/sheet_proportions.py).
    "sheet_qwen21": {"output_node": "461", "ints": {"seed"}, "refs_node": "459:474",
                     "prompt_input": ("459:474", "prompt")},
    # A grown-up's real face edited into a finished shot picture (services/face_fix.py).
    "face_id": {"output_node": "60", "ints": {"seed"}, "floats": {"denoise"}, "prompt_input": ("6", "text")},
    "clip_wan22": {"output_node": "108", "ints": {"seed", "duration_seconds"},
                   "prompt_input": ("129:93", "text"), "start_input": ("97", "image"),
                   "duration_input": ("129:161", "value")},
    # The same clip pinned at both ends (WanFirstLastFrameToVideo): the shot's checked
    # end picture is its last frame, so Wan can't end on a face turned to the camera.
    "clip_wan22_flf": {"output_node": "108", "ints": {"seed", "duration_seconds"},
                       "prompt_input": ("129:93", "text"), "start_input": ("97", "image"),
                       "end_input": ("98", "image"), "duration_input": ("129:161", "value")},
}
_PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")
_REF_KEY = re.compile(r"images\.image_(\d+)$")

# Tests swap in an httpx.MockTransport.
_transport: httpx.AsyncBaseTransport | None = None


# ---------------------------------------------------------------- workflows
@functools.lru_cache(maxsize=None)
def _template_text(name: str) -> str:
    return (WORKFLOW_DIR / f"{name}_api.json").read_text(encoding="utf-8")


def load_workflow(name: str) -> dict:
    if name not in WORKFLOWS:
        raise AIConfigError(f"unknown Comfy workflow '{name}'")
    return json.loads(_template_text(name))


def placeholders(workflow: dict) -> set[str]:
    return {m for node in workflow.values() for v in (node.get("inputs") or {}).values()
            if isinstance(v, str) for m in _PLACEHOLDER.findall(v)}


def _set_references(workflow: dict, target: str, names: list[str]) -> None:
    """One LoadImage node per reference, wired to images.image_1..N of the text
    encoder in order (N = the <imageN> numbering the prompt uses)."""
    if not 1 <= len(names) <= MAX_REFS:
        raise AIPermanentError(f"Comfy keyframes take 1 to {MAX_REFS} reference images, got {len(names)}")
    inputs = workflow[target]["inputs"]
    loaders: dict[int, str] = {}
    for key in [k for k in inputs if _REF_KEY.match(k)]:
        n, node_id = int(_REF_KEY.match(key).group(1)), inputs[key][0]
        if n > len(names):
            del inputs[key]
            workflow.pop(node_id, None)
        else:
            loaders[n] = node_id
    next_id = max(int(k) for k in workflow if k.isdigit()) + 1
    for n, name in enumerate(names, 1):
        if n not in loaders:
            loaders[n] = str(next_id)
            next_id += 1
            workflow[loaders[n]] = {"inputs": {}, "class_type": "LoadImage", "_meta": {"title": f"ref_{n}"}}
            inputs[f"images.image_{n}"] = [loaders[n], 0]
        workflow[loaders[n]]["inputs"]["image"] = name


def _typed(workflow: str, key: str, value):
    if key in WORKFLOWS[workflow].get("floats", ()):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise AIPermanentError(f"Comfy {workflow}: '{key}' must be a number, got {value!r}")
        return float(value)
    if key in WORKFLOWS[workflow]["ints"]:
        if isinstance(value, bool) or not isinstance(value, int):
            raise AIPermanentError(f"Comfy {workflow}: '{key}' must be a whole number, got {value!r}")
        return value
    if not isinstance(value, str):
        raise AIPermanentError(f"Comfy {workflow}: '{key}' must be text, got {type(value).__name__}")
    return value


def fill_workflow(name: str, fills: dict, refs: list[str] | None = None) -> dict:
    """A copy of the workflow with every {{placeholder}} filled with the right
    type, and the reference images set (keyframes only)."""
    workflow = load_workflow(name)
    spec = WORKFLOWS[name]
    if spec.get("refs_node"):
        _set_references(workflow, spec["refs_node"], list(refs or []))
    elif refs:
        raise AIPermanentError(f"Comfy {name} takes no reference images")
    fills = {"output_prefix": DEFAULT_PREFIX, **fills}
    wanted = placeholders(workflow)
    missing, extra = wanted - set(fills), set(fills) - wanted
    if missing or extra:
        raise AIPermanentError(f"Comfy {name}: missing {sorted(missing)}, unknown {sorted(extra)}")
    values = {k: _typed(name, k, v) for k, v in fills.items()}
    for node in workflow.values():
        inputs = node.get("inputs") or {}
        for key, value in inputs.items():
            if not isinstance(value, str) or "{{" not in value:
                continue
            whole = _PLACEHOLDER.fullmatch(value)
            inputs[key] = values[whole.group(1)] if whole else \
                _PLACEHOLDER.sub(lambda m: str(values[m.group(1)]), value)
    return workflow


def new_seed() -> int:
    return secrets.randbelow(2**31 - 1) + 1


def output_files(job: dict, workflow: str) -> list[dict]:
    """Files the workflow's save node wrote (a video is listed under "images" too)."""
    node = (job.get("outputs") or {}).get(WORKFLOWS[workflow]["output_node"]) or {}
    return [f for v in node.values() if isinstance(v, list) for f in v if isinstance(f, dict) and f.get("filename")]


def gpu_seconds(job: dict) -> float | None:
    """Execution time of a finished job. The API sends ms (its docs say seconds)."""
    start, end = job.get("execution_start_time"), job.get("execution_end_time")
    if not all(isinstance(t, (int, float)) and not isinstance(t, bool) for t in (start, end)) or end < start:
        return None
    return round((end - start) / (1000.0 if end > 1e11 else 1.0), 3)


# ---------------------------------------------------------------- concurrency
async def _max_concurrent() -> int:
    from db import db

    try:
        doc = await db.settings.find_one({"key": SETTING_MAX_CONCURRENT}, {"_id": 0, "value": 1})
        return max(1, int((doc or {}).get("value") or 1))
    except Exception:  # noqa: BLE001 — a settings hiccup must not stop the engine
        return 1


async def usd_per_gpu_second() -> float:
    """What a GPU-second costs us (setting comfy.usd_per_gpu_second)."""
    from db import db

    try:
        doc = await db.settings.find_one({"key": SETTING_USD_PER_GPU_SECOND}, {"_id": 0, "value": 1})
        value = float((doc or {}).get("value") or DEFAULT_USD_PER_GPU_SECOND)
        return value if value > 0 else DEFAULT_USD_PER_GPU_SECOND
    except Exception:  # noqa: BLE001
        return DEFAULT_USD_PER_GPU_SECOND


_order_keys: dict[str, str] = {}


async def order_priority(order_id: str | None) -> str:
    """Queue key of a job: its order's approval time, so the oldest story gets
    the next free slot. Jobs without an order (lab, previews) queue by arrival."""
    now = datetime.now(timezone.utc).isoformat()
    if not order_id:
        return now
    if order_id not in _order_keys:
        from db import db

        try:
            o = await db.orders.find_one({"id": order_id}, {"_id": 0, "production_approved_at": 1, "created_at": 1})
            _order_keys[order_id] = (o or {}).get("production_approved_at") or (o or {}).get("created_at") or now
        except Exception:  # noqa: BLE001
            return now
        if len(_order_keys) > 2000:
            _order_keys.pop(next(iter(_order_keys)))
    return _order_keys[order_id]


class _Gate:
    """Jobs in flight across the whole process (the Standard plan runs one at a
    time). The limit is re-read every few seconds, so a change needs no restart.

    A free slot goes to the waiting job of the OLDEST order (first approved,
    first served), not to whoever wakes first: with one slot, two interleaved
    stories both finished at ~50 min; in order the first is ready at ~25 min and
    the second right after."""

    def __init__(self):
        self._busy = 0
        self._waiting: list[tuple[str, int, asyncio.Future]] = []  # heap of (priority, arrival, grant)
        self._arrivals = itertools.count()
        self._limit, self._at = 1, -1e9

    async def _current_limit(self) -> int:
        if time.monotonic() - self._at > LIMIT_CACHE_SECONDS:
            self._limit, self._at = await _max_concurrent(), time.monotonic()
        return self._limit

    def _grant(self) -> None:
        while self._waiting and self._busy < self._limit:
            _, _, grant = heapq.heappop(self._waiting)
            if grant.done():  # the waiter gave up
                continue
            self._busy += 1
            grant.set_result(True)

    @contextlib.asynccontextmanager
    async def slot(self, priority: str | None = None):
        limit = await self._current_limit()
        if self._busy < limit and not self._waiting:
            self._busy += 1
        else:
            grant = asyncio.get_running_loop().create_future()
            heapq.heappush(self._waiting, (priority or datetime.now(timezone.utc).isoformat(),
                                           next(self._arrivals), grant))
            try:
                while not grant.done():
                    with contextlib.suppress(asyncio.TimeoutError):
                        await asyncio.wait_for(asyncio.shield(grant), LIMIT_CACHE_SECONDS)
                    if not grant.done():  # the admin may have raised the limit
                        await self._current_limit()
                        self._grant()
            except BaseException:
                if grant.done() and not grant.cancelled():
                    self._busy -= 1  # granted while being cancelled: hand it on
                    self._grant()
                else:
                    grant.cancel()
                raise
        try:
            yield
        finally:
            self._busy -= 1
            self._grant()

    def waiting(self) -> int:
        return sum(1 for _, _, g in self._waiting if not g.done())


_gate = _Gate()


# ---------------------------------------------------------------- HTTP
def base_url() -> str:
    return (os.environ.get("COMFY_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")


async def _key() -> str:
    from services.secret_overrides_service import get_secret

    value = await get_secret("COMFY_API_KEY")
    if not value:
        raise AIConfigError("COMFY_API_KEY is not configured")
    return value


def _client(key: str, timeout: float) -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=base_url(), headers={"X-API-Key": key}, timeout=timeout,
                             transport=_transport)


async def _request(stage: str, method: str, path: str, timeout: float = 60.0, **kwargs) -> httpx.Response:
    key = await _key()
    try:
        async with _client(key, timeout) as c:
            return await c.request(method, path, **kwargs)
    except httpx.HTTPError as e:
        raise AIError(f"Comfy {method} {path} failed ({stage}): {type(e).__name__}: {e}") from e


def _message(body: str) -> str:
    """The readable part of an error body ({"code","message"}, {"error": {...}}, or text)."""
    try:
        data = json.loads(body)
    except (ValueError, TypeError):
        return (body or "").strip()[:500]
    if not isinstance(data, dict):
        return str(data)[:500]
    err = data.get("error")
    parts = [data.get("code"), data.get("message"), data.get("detail")]
    if isinstance(err, dict):
        parts += [err.get("type"), err.get("message"), err.get("details")]
    elif err:
        parts.append(err)
    return " — ".join(str(p) for p in parts if p)[:500] or body[:500]


async def _http_error(stage: str, status: int | None, body: str) -> AIError:
    """Log the answer in full, keep it for the admin, lock on a credits answer."""
    logger.warning(f"[ai.comfy] stage={stage} HTTP {status}: {(body or '')[:2000]}")
    message = _message(body)
    await engine_health.note_error(stage, message, provider="comfy", status=status, raw=body)
    if status == 429:
        if engine_health.is_lock_error(message, "comfy", status):
            return AIConfigError(f"Comfy call failed ({stage}): HTTP 429: {message}")
        return AIError(f"Comfy call failed ({stage}): HTTP 429: {message}")  # busy: worth retrying
    return classify_http_error(stage, "Comfy", status, message)


async def _job_error(stage: str, prompt_id: str, job: dict) -> AIError:
    err = job.get("execution_error") or {}
    kind, detail = err.get("exception_type") or "", (err.get("exception_message") or "").strip()
    text = (f"Comfy job {prompt_id} {job.get('status')} ({stage}): {kind or 'no error type'} "
            f"in {err.get('node_type') or '-'}: {detail}")[:600]
    logger.warning(f"[ai.comfy] {text}")
    raw = json.dumps({k: err.get(k) for k in ("exception_type", "exception_message", "node_type", "node_id")},
                     ensure_ascii=False)
    await engine_health.note_error(stage, f"{kind}: {detail}", provider="comfy", raw=raw)
    error = (AIConfigError if kind in LOCK_EXCEPTIONS else AIPermanentError if kind in PERMANENT_EXCEPTIONS
             else AIError)(text)  # AIError: out of memory, a worker crash, a cancelled job — worth one retry
    # A failed job still ran on the GPU: callers count it as paid.
    error.gpu_seconds = gpu_seconds(job)
    error.prompt_id = prompt_id
    return error


def _mime(data: bytes) -> str:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[4:8] == b"ftyp":
        return "video/mp4"
    return "application/octet-stream"


# ---------------------------------------------------------------- calls
async def upload(data: bytes, name: str, *, stage: str = "upload") -> str:
    """Upload an input image; returns the name a LoadImage node takes."""
    if fake_providers.enabled():
        return await fake_providers.comfy_upload(data, name)
    r = await _request(stage, "POST", "/api/upload/image", timeout=120.0,
                       files={"image": (name, data, _mime(data))})
    if r.status_code != 200:
        raise await _http_error(stage, r.status_code, r.text)
    got = (r.json() or {}).get("name")
    if not got:
        raise AIError(f"Comfy upload returned no name ({stage}): {r.text[:200]}")
    # No note_success here: uploads are free, so they work with no credits too.
    return got


async def submit(*, stage: str, workflow: str, fills: dict, refs: list[str] | None = None) -> str:
    """Queue a filled workflow and return its prompt_id (persist it to resume later)."""
    prompt = fill_workflow(workflow, fills, refs)
    if fake_providers.enabled():
        prompt_id = await fake_providers.comfy_submit(stage, workflow, prompt)
    else:
        r = await _request(stage, "POST", "/api/prompt", json={"prompt": prompt})
        if r.status_code != 200:
            raise await _http_error(stage, r.status_code, r.text)
        body = r.json() or {}
        if body.get("node_errors"):
            logger.warning(f"[ai.comfy] stage={stage} node_errors: {json.dumps(body['node_errors'])[:2000]}")
            raise AIPermanentError(f"Comfy rejected {workflow} ({stage}): {json.dumps(body['node_errors'])[:400]}")
        prompt_id = body.get("prompt_id")
        if not prompt_id:
            raise AIError(f"Comfy returned no prompt_id ({stage}): {r.text[:200]}")
    logger.info(f"[ai.comfy] stage={stage} workflow={workflow} submitted prompt_id={prompt_id}")
    await engine_health.note_success("comfy")
    return prompt_id


async def _fetch_job(prompt_id: str, client: httpx.AsyncClient | None) -> tuple[int, dict | None, str]:
    if fake_providers.enabled():
        return 200, await fake_providers.comfy_job(prompt_id), ""
    r = await client.get(f"/api/jobs/{prompt_id}")
    if r.status_code != 200:
        return r.status_code, None, r.text
    try:
        return 200, r.json(), ""
    except ValueError:
        return 200, None, r.text[:300]


async def wait(*, stage: str, prompt_id: str, timeout: float = 900.0, poll_interval: float = 3.0) -> dict:
    """Poll until the job finishes; returns the full job (outputs, execution times)."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    errors = 0
    async with contextlib.AsyncExitStack() as stack:
        client = None
        if not fake_providers.enabled():
            client = await stack.enter_async_context(_client(await _key(), 30.0))
        while True:
            try:
                status, job, body = await _fetch_job(prompt_id, client)
            except httpx.HTTPError as e:
                status, job, body = None, None, f"{type(e).__name__}: {e}"
            if job is not None:
                errors = 0
                if job.get("status") == "completed":
                    break
                if job.get("status") in ("failed", "cancelled"):
                    raise await _job_error(stage, prompt_id, job)
            elif status in (401, 403, 404):
                raise await _http_error(stage, status, body)
            else:
                errors += 1
                logger.warning(f"[ai.comfy] stage={stage} poll {prompt_id} failed ({errors}/{MAX_POLL_ERRORS}): "
                               f"{status} {body[:300]}")
                if errors >= MAX_POLL_ERRORS:
                    raise AIError(f"Comfy job {prompt_id} could not be read ({stage}): {status} {body[:200]}")
            if loop.time() > deadline:
                raise AIError(f"Comfy job timed out after {int(timeout)}s ({stage}, prompt_id={prompt_id})")
            await asyncio.sleep(poll_interval)
    await engine_health.note_success("comfy")
    return job


async def download(filename: str, subfolder: str = "", *, kind: str = "output", stage: str = "download") -> bytes:
    if fake_providers.enabled():
        return fake_providers.comfy_download(filename)
    params = {"filename": filename, "subfolder": subfolder or "", "type": kind}
    r = await _request(stage, "GET", "/api/view", timeout=120.0, params=params)
    if r.is_redirect:
        # A signed storage link: our key must not travel to the storage host.
        try:
            async with httpx.AsyncClient(timeout=180.0, follow_redirects=True, transport=_transport) as c:
                r = await c.get(r.headers["location"])
        except (httpx.HTTPError, KeyError) as e:
            raise AIError(f"Comfy output download failed ({stage}): {type(e).__name__}: {e}") from e
        if r.status_code != 200:
            raise AIError(f"Comfy output download failed ({stage}): storage HTTP {r.status_code}")
    elif r.status_code != 200:
        raise await _http_error(stage, r.status_code, r.text[:2000])
    return r.content


async def run(*, stage: str, workflow: str, fills: dict, refs: list[str] | None = None,
              on_submitted=None, prompt_id: str | None = None, queue_key: str = "",
              timeout: float = 900.0, poll_interval: float = 3.0) -> tuple[bytes, str, dict]:
    """Submit (or resume `prompt_id`), wait and download the first output file.
    `on_submitted(prompt_id)` runs before the wait, so the caller can save the id
    and a crash resumes the paid job instead of paying again. Returns
    (bytes, mime, job); `gpu_seconds(job)` is what the job cost."""
    # Within an order, keyframes go before clips: a keyframe takes ~20 s against a
    # clip's ~110 s, and the scene pictures (the parent's previews, every clip's
    # start frame) waited behind clips for half an hour in the first real story.
    # `queue_key` (scene.shot) then serves them in story order: the parent watched
    # scene 4's picture arrive before scene 1's.
    rank = "1" if workflow.startswith("clip") else "0"
    async with _gate.slot(f"{await order_priority(fake_providers.CURRENT_ORDER.get())}|{rank}|{queue_key}"):
        if not prompt_id:
            prompt_id = await submit(stage=stage, workflow=workflow, fills=fills, refs=refs)
            if on_submitted:
                await on_submitted(prompt_id)
        job = await wait(stage=stage, prompt_id=prompt_id, timeout=timeout, poll_interval=poll_interval)
        files = output_files(job, workflow)
        if not files:
            raise AIError(f"Comfy job {prompt_id} finished without an output file ({stage})")
        f = files[0]
        data = await download(f["filename"], f.get("subfolder") or "", kind=f.get("type") or "output", stage=stage)
    return data, f.get("mime_type") or _mime(data), {**job, "prompt_id": prompt_id}


async def balance_usd(stage: str = "balance") -> float | None:
    """Credit left on the workspace (a free read); None when billing can't tell."""
    if fake_providers.enabled():
        return await fake_providers.comfy_balance()
    r = await _request(stage, "GET", "/api/billing/usage/timeseries", timeout=20.0,
                       params={"months": 1, "granularity": "month"})
    if r.status_code in (401, 403):
        raise await _http_error(stage, r.status_code, r.text)
    if r.status_code != 200:
        logger.warning(f"[ai.comfy] balance read HTTP {r.status_code}: {r.text[:500]}")
        return None
    balance = ((r.json() or {}).get("summary") or {}).get("balance") or {}
    # In cents despite the _micros name (the API docs say so; the live answer agrees).
    cents = balance.get("amount_cents", balance.get("amount_micros"))
    return round(float(cents) / 100, 2) if isinstance(cents, (int, float)) else None


async def ping(stage: str = "ping") -> None:
    """Checks the key with the cheapest read (the latest job)."""
    if fake_providers.enabled():
        return
    r = await _request(stage, "GET", "/api/jobs", timeout=20.0, params={"limit": 1})
    if r.status_code != 200:
        raise await _http_error(stage, r.status_code, r.text)
