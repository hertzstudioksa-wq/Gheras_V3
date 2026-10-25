"""The shot engine's Comfy branches end to end in rehearsal mode (GHERAS_FAKE_PROVIDERS=1):
keyframes with their references, Wan clips, the review takes, failed jobs, resuming,
and the actual cost. Needs the local MongoDB; uses its own throwaway database."""
import asyncio
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
os.environ.setdefault("MONGO_URL", "mongodb://127.0.0.1:27017")
os.environ.setdefault("DB_NAME", "gheras_comfy_unit")

import storage  # noqa: E402
from db import client, db  # noqa: E402
from services import shot_pipeline as sp  # noqa: E402
from services.ai import comfy, fake_providers  # noqa: E402

KLING = "fal-ai/kling-video/v3/pro/image-to-video"
LOOP = asyncio.new_event_loop()  # motor and the Comfy gate stay on one loop


def run(coro):
    return LOOP.run_until_complete(coro)


async def _mongo_up() -> bool:
    try:
        await asyncio.wait_for(client.admin.command("ping"), 3)
        return True
    except Exception:  # noqa: BLE001
        return False


@pytest.fixture(autouse=True)
def rehearsal(monkeypatch, tmp_path):
    if not run(_mongo_up()):
        pytest.skip("local MongoDB is not running")
    assert db.name not in ("gheras", "gheras_prod")
    for k, v in {"GHERAS_FAKE_PROVIDERS": "1", "GHERAS_FAKE_SPEED": "0.002", "COMFY_API_KEY": "fake",
                 "FAL_KEY": "fake"}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(storage, "STORAGE_DIR", tmp_path)
    monkeypatch.setattr(comfy, "_gate", comfy._Gate())
    run(client.drop_database(db.name))

    async def seed():
        from services import model_catalog

        await model_catalog.seed_catalog()
        for stage, provider, model in (("scene_image_generation", "comfy_image", "comfy/keyframe_qwen21"),
                                       ("video_generation", "comfy_video", "comfy/clip_wan22")):
            await db.model_registry.insert_one({"stage_key": stage, "active": True, "provider": provider,
                                                "model_name": model})
    run(seed())
    yield
    run(client.drop_database(db.name))


async def _file(file_id: str, prompt: str, size: str) -> str:
    path = f"t/{file_id}.png"
    storage.put_object(path, fake_providers.picture(prompt, size), "image/png")
    await db.files.insert_one({"id": file_id, "storage_path": path, "content_type": "image/png", "is_deleted": False})
    return f"/api/uploads/file/{file_id}"


async def _story(oid: str, narration=(2.4, 4.6, 7.9)):
    """Lina (sheet), her father (sheet), her toy; scene 1 = two shots, scene 2 = one shot with nobody."""
    order = {"id": oid, "user_id": "u", "production_plan_id": f"p-{oid}",
             "data": {"child": {"name": "Lina"}, "characters": [], "delivery": {"output_type": "both"},
                      "personalization": {"toy_image_url": await _file(f"{oid}-toy", "toy", "1024x1024"),
                                          "toy_description_auto": "a blue knitted rabbit plush",
                                          "favorites": {"toy": {"name": "Bunbun", "selected": True}}}}}
    plan = {"id": f"p-{oid}", "order_id": oid, "title": "x", "cover_prompt": "Lina holds Bunbun."}
    await db.orders.insert_one(dict(order))
    await db.child_character_assets.insert_one({"order_id": oid, "status": "completed", "created_at": "1",
                                               "generated_image_url": await _file(f"{oid}-c", "child", "896x1344")})
    await db.extra_character_assets.insert_one({"order_id": oid, "status": "completed", "character_type": "father",
                                               "generated_image_url": await _file(f"{oid}-f", "father", "896x1344")})
    await db.character_profiles.insert_many([
        {"production_plan_id": plan["id"], "type": "child", "name_en": "Lina", "key_features": "two short braids"},
        {"production_plan_id": plan["id"], "type": "father", "name_en": "Omar"}])
    base = {"order_id": oid, "production_plan_id": plan["id"], "is_archived": False}
    await db.scene_plans.insert_many([
        {**base, "id": f"{oid}-s1", "scene_index": 1, "key_objects": ["Bunbun the blue rabbit plush"], "shots": [
            {"shot_index": 1, "characters": ["child", "father"], "narration_line": "a",
             "keyframe_prompt": "Lina and her father walk into the garden.", "motion_prompt": "They walk."},
            {"shot_index": 2, "characters": ["child"], "narration_line": "b",
             "keyframe_prompt": "Lina hugs Bunbun the blue rabbit plush.", "motion_prompt": "She hugs it."}]},
        {**base, "id": f"{oid}-s2", "scene_index": 2, "shots": [
            {"shot_index": 1, "characters": [], "narration_line": "c",
             "keyframe_prompt": "The quiet garden at dusk.", "motion_prompt": "Leaves sway."}]}])
    for s in (1, 2):
        await sp.execute_scene_keyframes({"id": f"{oid}-j{s}", "target_id": f"{oid}-s{s}"}, order, plan)
    for (s, i), secs in zip(((1, 1), (1, 2), (2, 1)), narration):
        await db.shot_assets.update_one({"order_id": oid, "scene_index": s, "shot_index": i},
                                        {"$set": {"narration_seconds": secs, "narration_url": "x"}})
    return order, plan


async def _row(oid, s, i):
    return await db.shot_assets.find_one({"order_id": oid, "scene_index": s, "shot_index": i}, {"_id": 0})


def test_keyframes_references_toy_previous_and_cost_fields():
    async def go():
        await _story("k")
        r11, r12, r21 = await _row("k", 1, 1), await _row("k", 1, 2), await _row("k", 2, 1)
        assert r11["keyframe_refs"] == ["<image1> Lina's sheet", "<image2> Omar (the child's father)'s sheet"]
        assert r12["keyframe_refs"] == ["<image1> Lina's sheet", "<image2> the child's toy"]
        assert r21["keyframe_refs"] == ["<image1> the previous scene's last shot"]
        assert "<image2> shows only the child's Bunbun" in r12["keyframe_prompt_used"]
        assert sp.COMFY_NOBODY in r21["keyframe_prompt_used"]
        for r in (r11, r12, r21):
            assert r["keyframe_prompt_used"].startswith(sp.COMFY_INTRO)
            assert r["image_model"] == "comfy/keyframe_qwen21" and r["keyframe_gpu_seconds"] == 20
            assert r["paid_keyframes"] == 1 and r.get("keyframe_prompt_id") is None
    run(go())


def test_keyframe_resume_waits_on_the_saved_job():
    async def go():
        order, plan = await _story("r")
        pid = await comfy.submit(stage="scene_image_generation", workflow="keyframe_qwen21",
                                 fills={"scene_prompt": "resumed", "seed": 1}, refs=["x.png"])
        await db.shot_assets.update_one({"order_id": "r", "scene_index": 2, "shot_index": 1},
                                        {"$set": {"keyframe_url": None, "keyframe_prompt_id": pid,
                                                  "keyframe_prompt_attempt": 1}})
        jobs = await db.fake_requests.count_documents({"kind": "comfy"})
        await sp.execute_scene_keyframes({"id": "r-j3", "target_id": "r-s2"}, order, plan)
        assert await db.fake_requests.count_documents({"kind": "comfy"}) == jobs
        assert (await _row("r", 2, 1))["keyframe_url"]
    run(go())


def test_wan_clips_lengths_takes_and_failures():
    async def go():
        order, plan = await _story("c")
        await fake_providers.simulate(flag_times={"1_2": 3}, flag_counts={}, comfy_fail_clips=["2_1"])
        res = await sp.run_shot_clips(order, plan, "run-c")
        r11, r12, r21 = await _row("c", 1, 1), await _row("c", 1, 2), await _row("c", 2, 1)
        assert r11["clip_engine"] == "comfy_video" and r11["clip_seconds"] == 3 and r11["clip_gpu_seconds"] == 80
        assert "@Element" not in r11["clip_prompt_used"] and sp.WAN_STILL in r11["clip_prompt_used"]
        # flagged three times: calm redo, a new seed, then the best take — still Wan
        assert r12["clip_engine"] == "comfy_video" and r12["clip_review"].get("best_of_takes")
        assert r12["comfy_clip_seconds"] == 3 * r12["clip_seconds"] == 18
        # failing on Wan: no clip, its GPU time still counted, and no Kling by default
        assert r21["clip_state"] == "failed" and r21["clip_gpu_seconds"] == 60 and not r21.get("clip_rescue")
        assert res["kling_rescues"] == []
    run(go())


def test_kling_rescue_when_the_owner_turns_it_on():
    async def go():
        await db.settings.insert_one({"key": "comfy.kling_rescue", "value": True})
        order, plan = await _story("k2")
        await fake_providers.simulate(flag_times={"1_2": 2}, flag_counts={}, comfy_fail_clips=[])
        res = await sp.run_shot_clips(order, plan, "run-k2")
        r12 = await _row("k2", 1, 2)
        assert res["kling_rescues"] == ["1_2"]
        assert r12["clip_engine"] == "kling" and r12["clip_model"] == KLING and r12["clip_rescue"]["from"] == "comfy/clip_wan22"
    run(go())


def test_actual_cost_uses_gpu_time():
    async def go():
        from services.order_costs import actual_cost

        await db.settings.insert_one({"key": "comfy.usd_per_gpu_second", "value": 0.002})
        await _story("$")
        cost = await actual_cost(await db.orders.find_one({"id": "$"}, {"_id": 0}))
        kf = next(i for i in cost["items"] if i["label_ar"] == "صور اللقطات (Comfy)")
        assert kf["quantity"] == 60 and kf["unit"] == "ثانية GPU" and abs(kf["cost_usd"] - 0.12) < 1e-9
        # all keyframes on Comfy: the old one-picture-per-scene count must not add GPT images
        assert not any(i["key"] == "keyframes" and i["unit"] == "صورة" for i in cost["items"])
    run(go())


def test_a_flagged_comfy_keyframe_gets_three_takes_and_the_least_broken_is_kept(monkeypatch):
    async def go():
        from services import clip_review

        verdicts = iter([{"ok": False, "problems": ["duplicate"]}, {"ok": False, "problems": ["deformed"]},
                         {"ok": False, "problems": ["text"]}] + [{"ok": True, "problems": []}] * 10)

        async def review(*a, **k):
            return dict(next(verdicts))

        monkeypatch.setattr(clip_review, "review_keyframe", review)
        await _story("t")
        r = await _row("t", 1, 1)
        assert r["paid_keyframes"] == 3 and r["keyframe_gpu_seconds"] == 60
        assert r["keyframe_review"]["problems"] == ["text"] and r["keyframe_review"]["redrawn"]
    run(go())


def _static_first(monkeypatch, times: int):
    """The first `times` keyframe takes come out as coloured static."""
    from services import clip_review

    left = {"n": times}

    def verdict(images):
        if left["n"]:
            left["n"] -= 1
            return {"ok": False, "problems": ["noise"], "note": "static"}
        return None

    monkeypatch.setattr(clip_review, "static_verdict", verdict)


def test_a_static_keyframe_is_drawn_again(monkeypatch):
    async def go():
        _static_first(monkeypatch, 1)
        await _story("n")
        r = await _row("n", 1, 1)
        assert r["paid_keyframes"] == 2 and r["keyframe_gpu_seconds"] == 40
        assert r["keyframe_review"]["ok"] and r["keyframe_review"]["redrawn"]
    run(go())


def test_static_on_every_take_fails_the_shot_instead_of_shipping_it(monkeypatch):
    async def go():
        order, plan = await _story("n3")
        await db.shot_assets.update_one({"order_id": "n3", "scene_index": 2, "shot_index": 1},
                                        {"$set": {"keyframe_url": None}})
        _static_first(monkeypatch, 3)
        with pytest.raises(sp.AIError):
            await sp.execute_scene_keyframes({"id": "n3-j3", "target_id": "n3-s2"}, order, plan)
        r = await _row("n3", 2, 1)
        # the frame isn't stored, and a retry draws fresh instead of waiting on the static job
        assert not r["keyframe_url"] and r["keyframe_prompt_id"] is None and r["paid_keyframes"] == 4
    run(go())


def _locked_once(monkeypatch, name: str):
    """The review hits an exhausted balance once, then works (after the top-up)."""
    from services import clip_review
    from services.ai import AIConfigError

    calls = {"n": 0}
    real = getattr(clip_review, name)

    async def review(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise AIConfigError("fal call failed (upload): HTTP 403: User is locked. Reason: Exhausted balance")
        return await real(*a, **k)

    monkeypatch.setattr(clip_review, name, review)


def test_a_keyframe_review_on_an_empty_balance_pauses_and_resumes_without_paying_twice(monkeypatch):
    async def go():
        from services.ai import AIConfigError

        order, plan = await _story("p")
        await db.shot_assets.update_one({"order_id": "p", "scene_index": 2, "shot_index": 1},
                                        {"$set": {"keyframe_url": None, "paid_keyframes": 0, "keyframe_gpu_seconds": 0,
                                                  "comfy_gpu_seconds": 0}})
        _locked_once(monkeypatch, "review_keyframe")
        with pytest.raises(AIConfigError):
            await sp.execute_scene_keyframes({"id": "p-j3", "target_id": "p-s2"}, order, plan)
        r = await _row("p", 2, 1)
        assert not r["keyframe_url"] and r["keyframe_prompt_id"] and r["paid_keyframes"] == 1
        jobs = await db.fake_requests.count_documents({"kind": "comfy"})
        await sp.execute_scene_keyframes({"id": "p-j4", "target_id": "p-s2"}, order, plan)  # after the top-up
        r = await _row("p", 2, 1)
        assert r["keyframe_url"] and await db.fake_requests.count_documents({"kind": "comfy"}) == jobs
        assert r["paid_keyframes"] == 1 and r["keyframe_gpu_seconds"] == 20
    run(go())


def test_a_clip_review_on_an_empty_balance_pauses_and_resumes_without_paying_twice(monkeypatch):
    async def go():
        order, plan = await _story("q")
        await fake_providers.simulate(flag_times={}, flag_counts={}, comfy_fail_clips=[])
        _locked_once(monkeypatch, "review_clip")
        await sp.run_shot_clips(order, plan, "run-q1")
        paused = [r for r in [await _row("q", 1, 1), await _row("q", 1, 2), await _row("q", 2, 1)]
                  if not r.get("clip_url")]
        assert len(paused) == 1 and paused[0]["clip_state"] == "submitted" and paused[0]["clip_prompt_id"]
        s, i, gpu = paused[0]["scene_index"], paused[0]["shot_index"], paused[0]["clip_gpu_seconds"]
        jobs = await db.fake_requests.count_documents({"kind": "comfy"})
        await sp.run_shot_clips(order, plan, "run-q2")  # after the top-up
        r = await _row("q", s, i)
        assert r["clip_url"] and r["clip_state"] == "completed"
        assert await db.fake_requests.count_documents({"kind": "comfy"}) == jobs and r["clip_gpu_seconds"] == gpu
    run(go())
