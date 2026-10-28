"""The parent checks the pictures before any is animated (rehearsal mode, local MongoDB): the order
waits, a picture sent back is drawn again alone, the approval resumes the story, and a review
nobody answers is approved after a while. Uses the shot rehearsal's throwaway database."""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from tests.test_comfy_pipeline_rehearsal import _row, _story, db, rehearsal, run  # noqa: F401 (fixture)
from services import picture_review as pr


def _trigger(monkeypatch) -> list[str]:
    monkeypatch.setenv("JWT_SECRET", "test")  # the routes module reads it on import
    from routes import media_routes

    started = []

    async def trigger(order_id, background):
        started.append(order_id)
        return "run"

    monkeypatch.setattr(media_routes, "trigger_asset_generation", trigger)
    return started


async def _order(oid):
    return await db.orders.find_one({"id": oid}, {"_id": 0})


async def _settled(oid):
    for _ in range(400):
        if (await _order(oid))["picture_review"]["state"] == "waiting":
            return
        await asyncio.sleep(0.05)
    raise AssertionError("the redraw never finished")


def test_the_parent_sends_one_picture_back_then_approves(monkeypatch):
    async def go():
        _, plan = await _story("o1")
        await db.production_plans.insert_one(dict(plan))
        await db.orders.update_one({"id": "o1"}, {"$set": {"status": "assets_generating", "production_approved": True}})
        assert await pr.waits(await _order("o1"))
        assert await pr.open_review("o1")
        o = await _order("o1")
        assert o["status"] == "pictures_review" and o["picture_review"]["redraws_left"] == 3
        seen = await pr.pictures(o)
        assert [(s["scene_index"], s["shot_index"]) for s in seen["shots"]] == [(1, 1), (1, 2), (2, 1)]
        assert all(s["picture_url"] for s in seen["shots"]) and seen["shots"][0]["narration_line"] == "a"
        assert "prompt" not in str(seen)  # nothing internal reaches the parent

        old, other = (await _row("o1", 1, 2))["keyframe_url"], (await _row("o1", 1, 1))["keyframe_url"]
        assert (await pr.redraw(o, [(1, 2)], "likeness", "u"))["redraws_left"] == 2
        assert (await _order("o1"))["picture_review"]["state"] == "redrawing"
        with pytest.raises(pr.ReviewError):  # one redraw at a time
            await pr.redraw(await _order("o1"), [(1, 1)], "other", "u")
        await _settled("o1")
        new = await _row("o1", 1, 2)
        assert new["keyframe_url"] and new["keyframe_url"] != old and new["parent_redraw"]["reason"] == "likeness"
        assert (await _row("o1", 1, 1))["keyframe_url"] == other  # the rest stays as approved
        assert pr.REASONS["likeness"] and not (await _order("o1"))["picture_review"]["redrawing"]
        with pytest.raises(pr.ReviewError):  # three asked, two left
            await pr.redraw(await _order("o1"), [(1, 1), (1, 2), (2, 1)], "other", "u")

        started = _trigger(monkeypatch)
        assert await pr.approve("o1", "user", "u")
        o = await _order("o1")
        assert o["status"] == "production_approved" and o["picture_review"]["approved_at"] and started == ["o1"]
        assert not await pr.waits(o)  # the resumed run animates them
        assert not await pr.approve("o1", "user", "u")  # once
    run(go())


def test_the_review_can_be_turned_off_and_a_waiting_story_holds_no_slot():
    from services import limits, recovery_service

    async def go():
        assert await pr.waits({"id": "x"})
        await db.settings.insert_one({"key": pr.ENABLED_KEY, "value": False})
        assert not await pr.waits({"id": "x"})
        assert "pictures_review" not in limits.GENERATING  # waiting for a parent frees the generation slot
        assert "pictures_review" not in recovery_service.STEP_OF_STATUS  # and isn't "resumed" after a restart
    run(go())


def test_an_unanswered_review_is_approved_after_the_hours_and_a_cut_redraw_is_freed(monkeypatch):
    async def go():
        now = datetime.now(timezone.utc)
        old = (now - timedelta(hours=25)).isoformat()
        await db.orders.insert_many([
            {"id": "a", "status": "pictures_review", "picture_review": {"state": "waiting", "waiting_since": old}},
            {"id": "b", "status": "pictures_review", "picture_review": {"state": "waiting",
                                                                        "waiting_since": now.isoformat()}},
            {"id": "c", "status": "pictures_review", "picture_review": {"state": "redrawing", "redraw_started_at": old,
                                                                        "redrawing": [[1, 1]]}}])
        started = _trigger(monkeypatch)
        assert await pr.sweep() == {"approved": ["a"], "freed": ["c"]}
        assert started == ["a"] and (await _order("a"))["picture_review"]["approved_by"] == "system"
        assert (await _order("c"))["picture_review"]["state"] == "waiting"
        await db.settings.insert_one({"key": pr.AUTO_HOURS_KEY, "value": 0})  # 0 = wait for the parent
        await db.orders.update_one({"id": "b"}, {"$set": {"picture_review.waiting_since": old}})
        assert (await pr.sweep())["approved"] == []
    run(go())


def test_the_progress_and_the_email_say_the_pictures_wait_for_the_parent():
    from services import notify_service
    from services.progress_service import compute_pipeline_progress

    async def go():
        p = await compute_pipeline_progress({"id": "x", "status": "pictures_review",
                                             "picture_review": {"state": "waiting"}})
        assert p["stage"] == "review" and p["review"] and "راجعها" in p["message_ar"]
        p = await compute_pipeline_progress({"id": "x", "status": "pictures_review",
                                             "picture_review": {"state": "redrawing"}})
        assert "نعيد رسم" in p["message_ar"]
        assert notify_service.CUSTOMER_EVENTS["pictures_review"] == "pictures_ready"
        subject, lines, button = notify_service._compose("pictures_ready", {"id": "x", "data": {"child": {"name": "لينا"}}})
        assert "لينا" in subject and button == "راجع الصور"
    run(go())
