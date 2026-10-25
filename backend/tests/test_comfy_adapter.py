"""Comfy Cloud adapter (services/ai/comfy.py): templates, references, errors,
the balance lock, the concurrency gate and resuming — no network, no database."""
import asyncio
import json
import os
import sys

import httpx
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
os.environ.setdefault("MONGO_URL", "mongodb://127.0.0.1:27017")
os.environ.setdefault("DB_NAME", "gheras_comfy_unit")
os.environ.pop("GHERAS_FAKE_PROVIDERS", None)

from services import engine_health  # noqa: E402
from services.ai import AIConfigError, AIError, AIPermanentError, comfy  # noqa: E402

KEY = "comfyui-test-key"
KEYFRAME_FILLS = {"scene_prompt": 'A "new" scene,\nline two', "seed": 7}
CLIP_FILLS = {"start_image": "kf.png", "motion_prompt": "The child waves.", "seed": 9, "duration_seconds": 5}


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    """Key, settings and health calls answered in memory; every call recorded."""
    calls = {"errors": [], "successes": []}

    async def key():
        return KEY

    async def note_error(stage, message, provider="fal", status=None, raw=None):
        calls["errors"].append({"stage": stage, "message": str(message), "provider": provider, "status": status,
                                "raw": raw, "lock": engine_health.is_lock_error(message, provider, status)})

    async def note_success(provider="fal"):
        calls["successes"].append(provider)

    async def limit():
        return calls.get("limit", 1)

    monkeypatch.setattr(comfy, "_key", key)
    monkeypatch.setattr(comfy, "_max_concurrent", limit)
    monkeypatch.setattr(engine_health, "note_error", note_error)
    monkeypatch.setattr(engine_health, "note_success", note_success)
    monkeypatch.setattr(comfy, "_gate", comfy._Gate())
    monkeypatch.setattr(comfy, "_transport", None)
    return calls


def mock(monkeypatch, handler):
    seen = []

    def wrapped(request):
        seen.append(request)
        return handler(request)

    monkeypatch.setattr(comfy, "_transport", httpx.MockTransport(wrapped))
    return seen


def run(coro):
    return asyncio.run(coro)


def loaders(workflow):
    return {k: v for k, v in workflow.items() if v["class_type"] == "LoadImage"}


# ---------------------------------------------------------------- templates
def test_templates_have_the_documented_placeholders():
    assert comfy.placeholders(comfy.load_workflow("keyframe_qwen21")) == \
        {"ref_1", "ref_2", "ref_3", "ref_4", "scene_prompt", "seed", "output_prefix"}
    assert comfy.placeholders(comfy.load_workflow("clip_wan22")) == \
        {"start_image", "motion_prompt", "seed", "duration_seconds", "output_prefix"}
    for name, spec in comfy.WORKFLOWS.items():
        wf = comfy.load_workflow(name)
        assert spec["output_node"] in wf
        for pair in ("prompt_input", "start_input", "duration_input"):
            if pair in spec:
                node, field = spec[pair]
                assert field in wf[node]["inputs"], (name, pair)


def test_fill_types_and_text():
    wf = comfy.fill_workflow("clip_wan22", CLIP_FILLS)
    assert wf["129:86"]["inputs"]["noise_seed"] == 9 and type(wf["129:86"]["inputs"]["noise_seed"]) is int
    assert wf["129:161"]["inputs"]["value"] == 5 and type(wf["129:161"]["inputs"]["value"]) is int
    assert wf["97"]["inputs"]["image"] == "kf.png"
    assert wf["108"]["inputs"]["filename_prefix"] == comfy.DEFAULT_PREFIX
    kf = comfy.fill_workflow("keyframe_qwen21", KEYFRAME_FILLS, ["a.png"])
    assert kf["459:474"]["inputs"]["prompt"] == 'A "new" scene,\nline two'
    assert kf["459:458"]["inputs"]["seed"] == 7
    assert "{{" not in json.dumps(wf) and "{{" not in json.dumps(kf)
    # a fresh copy every time: filling never edits the template
    assert "{{seed}}" in json.dumps(comfy.load_workflow("clip_wan22"))


@pytest.mark.parametrize("fills", [
    {k: v for k, v in CLIP_FILLS.items() if k != "seed"},          # missing
    {**CLIP_FILLS, "steps": 4},                                    # unknown
    {**CLIP_FILLS, "duration_seconds": "5"},                       # text for a number
    {**CLIP_FILLS, "duration_seconds": 5.5},                       # not whole
    {**CLIP_FILLS, "seed": True},                                  # bool is not a number here
    {**CLIP_FILLS, "motion_prompt": 3},                            # number for text
])
def test_bad_fills_are_refused(fills):
    with pytest.raises(AIPermanentError):
        comfy.fill_workflow("clip_wan22", fills)


def test_unknown_workflow():
    with pytest.raises(AIConfigError):
        comfy.fill_workflow("nope", {})


@pytest.mark.parametrize("n", [1, 4, 7, 10])
def test_dynamic_references(n):
    names = [f"ref{i}.png" for i in range(1, n + 1)]
    wf = comfy.fill_workflow("keyframe_qwen21", KEYFRAME_FILLS, names)
    enc = wf["459:474"]["inputs"]
    keys = sorted((k for k in enc if k.startswith("images.image_")), key=lambda k: int(k.rsplit("_", 1)[1]))
    assert keys == [f"images.image_{i}" for i in range(1, n + 1)]
    assert len(loaders(wf)) == n
    # <imageN> order: image_i is wired to the loader holding the i-th name
    assert [wf[enc[k][0]]["inputs"]["image"] for k in keys] == names
    assert all(wf[enc[k][0]]["class_type"] == "LoadImage" for k in keys)
    assert "{{" not in json.dumps(wf)
    # every link points at a node that exists
    for node in wf.values():
        for v in node["inputs"].values():
            if isinstance(v, list) and len(v) == 2 and isinstance(v[0], str):
                assert v[0] in wf


@pytest.mark.parametrize("names", [[], [f"r{i}" for i in range(11)]])
def test_reference_count_limits(names):
    with pytest.raises(AIPermanentError):
        comfy.fill_workflow("keyframe_qwen21", KEYFRAME_FILLS, names)


def test_clip_takes_no_references():
    with pytest.raises(AIPermanentError):
        comfy.fill_workflow("clip_wan22", CLIP_FILLS, ["x.png"])


def test_output_files_and_gpu_seconds():
    job = {"outputs": {"108": {"animated": [True], "images": [{"filename": "c.mp4", "subfolder": "gheras"}]},
                       "461": {"images": [{"filename": "k.png"}]}},
           "execution_start_time": 1792941176039, "execution_end_time": 1792941192964}
    assert [f["filename"] for f in comfy.output_files(job, "clip_wan22")] == ["c.mp4"]
    assert [f["filename"] for f in comfy.output_files(job, "keyframe_qwen21")] == ["k.png"]
    assert comfy.gpu_seconds(job) == 16.925
    assert comfy.gpu_seconds({"execution_start_time": 100, "execution_end_time": 180}) == 80
    assert comfy.gpu_seconds({}) is None
    assert comfy.gpu_seconds({"execution_start_time": 5, "execution_end_time": 1}) is None


# ---------------------------------------------------------------- HTTP
def test_submit_sends_the_filled_workflow_with_the_key(monkeypatch, offline):
    def handler(request):
        assert request.url.path == "/api/prompt"
        assert request.headers["x-api-key"] == KEY
        body = json.loads(request.content)
        assert body["prompt"]["459:474"]["inputs"]["images.image_1"]
        return httpx.Response(200, json={"prompt_id": "p-1", "number": 1, "node_errors": {}})

    seen = mock(monkeypatch, handler)
    assert run(comfy.submit(stage="t", workflow="keyframe_qwen21", fills=KEYFRAME_FILLS, refs=["a.png"])) == "p-1"
    assert len(seen) == 1 and offline["successes"] == ["comfy"]


def test_node_errors_are_permanent(monkeypatch):
    mock(monkeypatch, lambda r: httpx.Response(200, json={"prompt_id": "p", "node_errors": {"97": {"errors": ["x"]}}}))
    with pytest.raises(AIPermanentError):
        run(comfy.submit(stage="t", workflow="clip_wan22", fills=CLIP_FILLS))


@pytest.mark.parametrize("status,body,exc,locks", [
    (402, {"code": "PAYMENT_REQUIRED", "message": "Payment required - Insufficient credits"}, AIConfigError, True),
    (429, {"message": "Payment required - User has not paid"}, AIConfigError, True),
    (429, {"message": "Too many requests"}, AIError, False),
    (401, {"code": "UNAUTHORIZED", "message": "Unauthorized"}, AIConfigError, False),
    (400, {"error": {"type": "invalid_prompt", "message": "bad"}}, AIPermanentError, False),
    (503, {"message": "Service unavailable"}, AIError, False),
])
def test_submit_errors(monkeypatch, offline, status, body, exc, locks):
    mock(monkeypatch, lambda r: httpx.Response(status, json=body))
    with pytest.raises(exc) as e:
        run(comfy.submit(stage="video_generation", workflow="clip_wan22", fills=CLIP_FILLS))
    if exc is AIError:
        assert not isinstance(e.value, AIPermanentError)  # retryable
    err = offline["errors"][-1]
    assert err["provider"] == "comfy" and err["status"] == status and err["lock"] is locks
    assert json.loads(err["raw"]) == body  # the full answer is kept for the admin


def test_wait_polls_until_completed(monkeypatch, offline):
    answers = iter([httpx.Response(200, json={"id": "p", "status": "pending"}),
                    httpx.Response(502, text="bad gateway"),  # one passing fault is tolerated
                    httpx.Response(200, json={"id": "p", "status": "in_progress"}),
                    httpx.Response(200, json={"id": "p", "status": "completed", "outputs": {}})])
    seen = mock(monkeypatch, lambda r: next(answers))
    job = run(comfy.wait(stage="t", prompt_id="p", poll_interval=0))
    assert job["status"] == "completed" and len(seen) == 4
    assert all(r.url.path == "/api/jobs/p" for r in seen)
    assert offline["successes"] == ["comfy"]


@pytest.mark.parametrize("etype,exc,locks", [
    ("InsufficientFundsError", AIConfigError, True),
    ("InactiveSubscriptionError", AIConfigError, True),
    ("ValidationError", AIPermanentError, False),
    ("OOMError", AIError, False),
])
def test_failed_jobs(monkeypatch, offline, etype, exc, locks):
    failed = {"id": "p", "status": "failed", "execution_error": {
        "exception_type": etype, "exception_message": "boom", "node_type": "KSampler", "node_id": "3",
        "traceback": [], "current_inputs": {}, "current_outputs": {}}}
    mock(monkeypatch, lambda r: httpx.Response(200, json=failed))
    with pytest.raises(exc):
        run(comfy.wait(stage="t", prompt_id="p", poll_interval=0))
    assert offline["errors"][-1]["lock"] is locks
    assert not offline["successes"]


def test_wait_gives_up_after_repeated_poll_failures(monkeypatch):
    mock(monkeypatch, lambda r: httpx.Response(500, text="down"))
    with pytest.raises(AIError):
        run(comfy.wait(stage="t", prompt_id="p", poll_interval=0))


def test_cancelled_job_is_retryable(monkeypatch):
    mock(monkeypatch, lambda r: httpx.Response(200, json={"id": "p", "status": "cancelled"}))
    with pytest.raises(AIError) as e:
        run(comfy.wait(stage="t", prompt_id="p", poll_interval=0))
    assert not isinstance(e.value, AIPermanentError)


def test_download_follows_the_redirect_without_the_key(monkeypatch):
    def handler(request):
        if request.url.host == "cloud.comfy.org":
            assert request.url.path == "/api/view" and request.url.params["type"] == "output"
            return httpx.Response(302, headers={"location": "https://storage.example/obj.png?sig=1"})
        assert "x-api-key" not in request.headers
        return httpx.Response(200, content=b"\x89PNG\r\n\x1a\nDATA")

    seen = mock(monkeypatch, handler)
    assert run(comfy.download("obj.png", "gheras")) == b"\x89PNG\r\n\x1a\nDATA"
    assert [r.url.host for r in seen] == ["cloud.comfy.org", "storage.example"]


def test_upload_returns_the_name(monkeypatch, offline):
    def handler(request):
        assert request.url.path == "/api/upload/image"
        assert b'name="image"' in request.content
        return httpx.Response(200, json={"name": "abc.png", "subfolder": "", "type": "input"})

    mock(monkeypatch, handler)
    assert run(comfy.upload(b"\x89PNG\r\n\x1a\n", "sheet.png")) == "abc.png"
    assert not offline["successes"]  # free calls say nothing about the credit


def test_balance_reads_cents(monkeypatch):
    mock(monkeypatch, lambda r: httpx.Response(200, json={"summary": {"balance": {"amount_cents": 1952.46}}}))
    assert run(comfy.balance_usd()) == 19.52
    mock(monkeypatch, lambda r: httpx.Response(500, text="x"))
    assert run(comfy.balance_usd()) is None


# ---------------------------------------------------------------- run(): gate + resume
def _fake_service(state):
    """A tiny Comfy: a job completes on its second poll."""
    def handler(request):
        path = request.url.path
        if path == "/api/prompt":
            state["submits"] += 1
            return httpx.Response(200, json={"prompt_id": f"p{state['submits']}", "node_errors": {}})
        if path.startswith("/api/jobs/"):
            pid = path.rsplit("/", 1)[1]
            state["polls"][pid] = state["polls"].get(pid, 0) + 1
            done = state["polls"][pid] >= 2
            return httpx.Response(200, json={
                "id": pid, "status": "completed" if done else "in_progress",
                "execution_start_time": 1_000_000_000_000, "execution_end_time": 1_000_000_020_000,
                "outputs": {"461": {"images": [{"filename": f"{pid}.png", "subfolder": "gheras", "type": "output",
                                                "mime_type": "image/png"}]}}})
        if path == "/api/view":
            return httpx.Response(200, content=b"\x89PNG\r\n\x1a\n" + request.url.params["filename"].encode())
        return httpx.Response(404)
    return handler


def test_run_saves_the_id_before_waiting_and_resumes(monkeypatch):
    state = {"submits": 0, "polls": {}}
    mock(monkeypatch, _fake_service(state))
    saved = []

    async def on_submitted(pid):
        assert state["polls"].get(pid) is None  # before the first poll
        saved.append(pid)

    data, mime, job = run(comfy.run(stage="t", workflow="keyframe_qwen21", fills=KEYFRAME_FILLS, refs=["a.png"],
                                    on_submitted=on_submitted, poll_interval=0))
    assert saved == ["p1"] and data.endswith(b"p1.png") and mime == "image/png"
    assert job["prompt_id"] == "p1" and comfy.gpu_seconds(job) == 20
    # after a "crash": the saved id is waited on, nothing is paid twice
    data, _, job = run(comfy.run(stage="t", workflow="keyframe_qwen21", fills=KEYFRAME_FILLS, refs=["a.png"],
                                 prompt_id="p1", poll_interval=0))
    assert state["submits"] == 1 and job["prompt_id"] == "p1"


@pytest.mark.parametrize("limit", [1, 2])
def test_gate_limits_jobs_in_flight(monkeypatch, offline, limit):
    offline["limit"] = limit
    state = {"submits": 0, "polls": {}}
    mock(monkeypatch, _fake_service(state))
    flight = {"now": 0, "max": 0}
    real_wait = comfy.wait

    async def tracked_wait(**kw):
        flight["now"] += 1
        flight["max"] = max(flight["max"], flight["now"])
        try:
            await asyncio.sleep(0.02)
            return await real_wait(**kw)
        finally:
            flight["now"] -= 1

    monkeypatch.setattr(comfy, "wait", tracked_wait)

    async def many():
        return await asyncio.gather(*(comfy.run(stage="t", workflow="keyframe_qwen21", fills=KEYFRAME_FILLS,
                                                refs=["a.png"], poll_interval=0) for _ in range(4)))

    assert len(run(many())) == 4
    assert flight["max"] == limit and state["submits"] == 4


def test_gate_serves_the_oldest_order_first(monkeypatch):
    async def one():
        return 1

    monkeypatch.setattr(comfy, "_max_concurrent", one)
    gate = comfy._Gate()
    order = []

    async def job(name, priority, hold=0.01):
        async with gate.slot(priority):
            order.append(name)
            await asyncio.sleep(hold)

    async def scenario():
        first = asyncio.create_task(job("running", "2026-01-05", hold=0.05))
        await asyncio.sleep(0.01)  # it holds the only slot
        waiting = [asyncio.create_task(job(n, p)) for n, p in
                   (("newest", "2026-01-04"), ("oldest", "2026-01-01"), ("middle", "2026-01-02"))]
        await asyncio.gather(first, *waiting)

    run(scenario())
    assert order == ["running", "oldest", "middle", "newest"]


def test_gate_cancelled_waiter_does_not_leak_a_slot(monkeypatch):
    async def one():
        return 1

    monkeypatch.setattr(comfy, "_max_concurrent", one)
    gate = comfy._Gate()
    done = []

    async def job(name, hold=0.02):
        async with gate.slot("2026-01-01"):
            done.append(name)
            await asyncio.sleep(hold)

    async def scenario():
        holder = asyncio.create_task(job("a"))
        await asyncio.sleep(0.005)
        quitter = asyncio.create_task(job("quits"))
        await asyncio.sleep(0.005)
        quitter.cancel()
        await asyncio.gather(holder, job("b"), return_exceptions=True)

    run(scenario())
    assert done == ["a", "b"] and gate._busy == 0 and gate.waiting() == 0


# ---------------------------------------------------------------- lock rules
@pytest.mark.parametrize("message,provider,status,locks", [
    ("User is locked. Exhausted balance.", "fal", 403, True),
    ("Payment required - Insufficient credits", "comfy", 402, True),
    ("anything", "comfy", 402, True),
    ("Payment required - User has not paid", "comfy", 429, True),
    ("Too many requests", "comfy", 429, False),
    ("InsufficientFundsError: Account balance too low", "comfy", None, True),
    ("OOMError: out of memory", "comfy", None, False),
    ("anything", "fal", 402, False),  # fal's lock stays on its own wording
])
def test_lock_rules(message, provider, status, locks):
    assert engine_health.is_lock_error(message, provider, status) is locks


def test_a_failed_job_carries_its_gpu_time(monkeypatch):
    failed = {"id": "p", "status": "failed", "execution_start_time": 1_000_000_000_000,
              "execution_end_time": 1_000_000_030_000, "execution_error": {
                  "exception_type": "OOMError", "exception_message": "boom", "node_type": "KSampler", "node_id": "3",
                  "traceback": [], "current_inputs": {}, "current_outputs": {}}}
    mock(monkeypatch, lambda r: httpx.Response(200, json=failed))
    with pytest.raises(AIError) as e:
        run(comfy.wait(stage="t", prompt_id="p", poll_interval=0))
    assert e.value.gpu_seconds == 30 and e.value.prompt_id == "p"  # still billed: callers count it



def test_keyframes_go_before_clips_of_the_same_order(offline):
    """With one slot busy, a clip queued first still waits for a keyframe of the same order."""
    gate, order = comfy._Gate(), []

    async def job(priority, name, hold=0.0):
        async with gate.slot(priority):
            order.append(name)
            await asyncio.sleep(hold)

    async def go():
        first = asyncio.ensure_future(job("2026-10-25T10:00|0", "running", 0.05))
        await asyncio.sleep(0.01)
        clip = asyncio.ensure_future(job("2026-10-25T10:00|1", "clip"))
        await asyncio.sleep(0.005)
        keyframe = asyncio.ensure_future(job("2026-10-25T10:00|0", "keyframe"))
        await asyncio.gather(first, clip, keyframe)

    run(go())
    assert order == ["running", "keyframe", "clip"]
