"""A grown-up drawn from a parent's photo gets the parent's face back in each shot picture (FaceID on
Comfy), only when it can't land on someone else; anything that goes wrong keeps the picture."""
import asyncio
import io

import pytest
from PIL import Image

from test_comfy_pipeline_rehearsal import _row, _story, db, rehearsal, run  # noqa: F401 (fixture)
from services import face_fix, shot_pipeline
from services.ai import AIError, comfy, fake_providers

PHOTO = {"from_photo": True, "photo_url": "/api/uploads/file/p"}


def _png(color, size=(1536, 864)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


def test_only_a_grown_up_who_cant_be_confused_is_fixed():
    sheets = {"child": PHOTO, "father": PHOTO, "mother": PHOTO, "grandfather": PHOTO, "teacher": PHOTO,
              "uncle": {"from_photo": False}, "aunt": {"from_photo": True, "photo_url": None}}
    t = face_fix.targets
    assert t({"characters": ["child", "father"]}, sheets) == ["father"]
    assert t({"characters": ["father", "mother", "child"]}, sheets) == ["father", "mother"]
    assert t({"characters": ["father", "grandfather"]}, sheets) == []  # two men: whose head is whose?
    assert t({"characters": ["father", "teacher"]}, sheets) == []  # a teacher could be a man
    assert t({"characters": ["father", "shopkeeper"]}, sheets) == []  # someone the plan made up
    assert t({"characters": ["uncle", "aunt"]}, sheets) == []  # drawn from the plan / photo deleted
    assert t({"characters": ["child", "friend"]}, sheets) == []
    assert face_fix.gender_of("mother_2") == "woman" and face_fix.gender_of("grandfather") == "man"


def test_the_workflow_takes_the_strength_as_a_number():
    w = comfy.fill_workflow("face_id", {"scene_image": "s.png", "face_mask": "m.png", "ref_1": "p.png",
                                        "scene_prompt": "x", "seed": 7, "denoise": face_fix.DENOISE})
    sampler = next(n for n in w.values() if n["class_type"] == "KSampler")
    assert sampler["inputs"]["denoise"] == 0.5 and sampler["inputs"]["seed"] == 7
    assert "{{" not in str(w)
    with pytest.raises(Exception):
        comfy.fill_workflow("face_id", {"scene_image": "s", "face_mask": "m", "ref_1": "p", "scene_prompt": "x",
                                        "seed": 7, "denoise": "0.5"})


def _patched(monkeypatch, run_result=None, box=(600, 100, 200, 250), photo=(b"photo", "image/jpeg")):
    calls = []

    async def on():
        return True

    async def fetch(url, owner_id=None):
        return photo

    async def face_box(picture, who, child_in_shot):
        calls.append(("box", who))
        return box

    async def upload(data, name, stage="x"):
        calls.append(("upload", name))
        return name

    async def run_(**k):
        calls.append(("run", k["workflow"], k["fills"]))
        if isinstance(run_result, Exception):
            raise run_result
        return run_result, "image/png", {"execution_start_time": 1_800_000_000_000, "execution_end_time": 1_800_000_004_000}

    monkeypatch.setattr(fake_providers, "enabled", lambda: False)
    monkeypatch.setattr(face_fix, "on", on)
    monkeypatch.setattr(shot_pipeline, "_fetch_source_bytes", fetch)
    monkeypatch.setattr(face_fix, "_face_box", face_box)
    monkeypatch.setattr(comfy, "upload", upload)
    monkeypatch.setattr(comfy, "run", run_)
    return calls


def test_the_face_is_redrawn_from_the_parents_photo(monkeypatch):
    fixed = _png("blue")
    calls = _patched(monkeypatch, run_result=fixed)
    out, mime, gpu, who = run(face_fix.fix_faces({"user_id": "u"}, {"characters": ["child", "father"]},
                                                         _png("red"), "image/png", {"father": PHOTO}))
    assert out == fixed and who == ["father"] and gpu == 4.0
    run_call = next(c for c in calls if c[0] == "run")
    assert run_call[1] == "face_id" and run_call[2]["denoise"] == 0.5 and "man's face" in run_call[2]["scene_prompt"]
    assert ("box", "man") in calls


def test_anything_wrong_keeps_the_picture(monkeypatch):
    shot, sheets, red = {"characters": ["father"]}, {"father": PHOTO}, _png("red")
    _patched(monkeypatch, run_result=_png("blue", (1024, 1024)))  # a picture of another size
    assert run(face_fix.fix_faces({}, shot, red, "image/png", sheets))[0] == red
    _patched(monkeypatch, run_result=AIError("comfy job failed: InsightFace found no face"))
    assert run(face_fix.fix_faces({}, shot, red, "image/png", sheets))[0] == red
    _patched(monkeypatch, run_result=_png("blue"), box=None)  # no head found
    assert run(face_fix.fix_faces({}, shot, red, "image/png", sheets))[3] == []
    _patched(monkeypatch, run_result=_png("blue"), photo=None)  # the photo was deleted after delivery
    assert run(face_fix.fix_faces({}, shot, red, "image/png", sheets))[0] == red
    _patched(monkeypatch, run_result=AIError("comfy: InsufficientFundsError: not enough credits"))
    from services import engine_health
    monkeypatch.setattr(engine_health, "is_balance_message", lambda e: "InsufficientFunds" in str(e))
    with pytest.raises(AIError):  # an empty balance pauses the order like any other step
        run(face_fix.fix_faces({}, shot, red, "image/png", sheets))


def test_the_start_and_end_pictures_of_a_shot_with_the_father_get_his_face(monkeypatch):
    seen = []

    async def fix(order, sh, picture, mime, sheets, queue_key=""):
        who = [t for t in sh.get("characters") or [] if face_fix.gender_of(t)]  # the rehearsal sheets have no photo url
        seen.append((sh["shot_index"], tuple(who)))
        return picture, mime, (4.0 if who else 0.0), who

    monkeypatch.setattr(face_fix, "fix_faces", fix)

    async def go():
        await _story("ff")  # scene 1: shot 1 = Lina and her father (both from photos), shot 2 = Lina alone
        r1, r2 = await _row("ff", 1, 1), await _row("ff", 1, 2)
        assert r1["faces_fixed"] == ["father"] and r2["faces_fixed"] == []
        assert r1["face_fix_gpu_seconds"] == 8.0  # the start picture and the end picture
        assert not r2.get("face_fix_gpu_seconds")
        assert (1, ("father",)) in seen and seen.count((1, ("father",))) == 2
    run(go())


def test_only_a_box_shaped_like_a_face_and_not_the_childs_is_used(monkeypatch):
    # what Florence answered on the kitchen and swing pictures (1536x864)
    size = (1536, 864)
    assert face_fix.plausible((827, 123, 247, 226), size) and face_fix.plausible((881, 62, 141, 162), size)
    assert not face_fix.plausible((1, 0, 178, 373), size)  # "a man's head" = a window corner
    assert not face_fix.plausible((253, 673, 372, 189), size)  # ... and the child's legs
    answers = {}

    async def detect(picture, words):
        return answers.get(words, [])

    monkeypatch.setattr(face_fix, "_detect", detect)
    pic = _png("red")
    answers["man's face"] = [(1, 0, 178, 373), (827, 123, 247, 226)]
    assert run(face_fix._face_box(pic, "man", child_in_shot=True)) == (827, 123, 247, 226)
    answers["child's face"] = [(840, 130, 200, 200)]  # the same face: it may be the child's
    assert run(face_fix._face_box(pic, "man", child_in_shot=True)) is None
    answers["man's face"] = [(1, 0, 178, 373)]
    assert run(face_fix._face_box(pic, "man", child_in_shot=False)) is None


def test_the_face_step_is_off_unless_the_owner_turns_it_on():
    # side by side with Qwen's own face (from the head-fitted sheet), the owner preferred Qwen's
    async def go():
        assert not await face_fix.on()
        await db.settings.insert_one({"key": face_fix.SETTING, "value": True})
        assert await face_fix.on()
    run(go())
