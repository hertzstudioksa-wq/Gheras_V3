"""Unified pipeline progress — single source of truth for user-facing progress.

Maps the full journey (Plan → Assets → Assembly → Delivered) into a weighted
0..100 percent with a human Arabic label. All admin/internal details (job ids,
prompts, snapshots) are intentionally kept out.

    plan         0 .. 20
    assets      20 .. 92   (shot plans: from the real work done, see below)
    assembly    92 .. 99
    delivered        100

The first full test order showed "اكتمل 0 من 13" for minutes and then sat at
80% for ten more while Kling animated the shots: the old bar only counted
finished jobs. For shot plans the bar now follows what is actually done
(character sheets, start frames, narration, music, animated clips) and how long
each piece usually takes, so it moves the whole time, and the parent gets the
elapsed time, a countdown, a checklist and previews of the pictures as they're
drawn.
"""
from __future__ import annotations

from datetime import datetime, timezone

from db import db
from models import OrderStatus, get_order_output_type


STAGE_LABELS_AR = {
    "plan": "إعداد خطة القصة",
    "assets": "توليد الصور والسرد",
    "assembly": "تجميع الفيديو والكتاب",
    "delivered": "جاهز",
    "failed": "تعذّر الإنشاء",
    "paused": "تأخير بسيط عندنا",
}

# Real-world seconds per unit, measured on the first full test order.
EXPECT = {"planning": 115, "sheet": 45, "cover": 45, "keyframe": 50, "narration": 10, "music": 60,
          "clip": 270, "review": 5, "assembly": 80}
CLIP_CONCURRENCY = 4
PLANNING_MESSAGES = [
    "بنكتب حكاية {name} مشهد مشهد ✍️",
    "بنختار أماكن المشاهد والإضاءة 🌄",
    "بنظبط كلام الراوي باللهجة 🎙️",
    "بنراجع القصة عشان تناسب سن {name} 💚",
]
MAX_PREVIEWS = 16
# How the parent sees the rest of the cast in the previews (sheet labels are English).
CAST_AR = {"father": "بابا", "mother": "ماما", "sibling": "الأخ/الأخت", "grandparent": "الجد/الجدة",
           "friend": "الصاحب", "teacher": "المعلّم/ة", "other": "شخصية من القصة"}


def _bounded(v: float, lo: int = 0, hi: int = 100) -> int:
    return max(lo, min(hi, int(round(v))))


def _seconds(unit: str) -> float:
    from services.ai import fake_providers

    return EXPECT[unit] * (fake_providers.speed() if fake_providers.enabled() else 1.0)


def _parse(ts: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(ts) if ts else None
    except ValueError:
        return None


def _since(ts: str | None, now: datetime) -> float:
    t = _parse(ts)
    return max(0.0, (now - t).total_seconds()) if t else 0.0


def _status_entered(order: dict, status: str) -> str | None:
    for h in reversed(order.get("status_history") or []):
        if h.get("to") == status:
            return h.get("at")
    return None


def _child_name(order: dict) -> str:
    return ((order.get("data") or {}).get("child") or {}).get("name") or "طفلك"


def _schedule(order: dict, planned: list, rows: dict, sheets_left: int, video: bool, music_done: bool,
              narration_done: bool, now: datetime) -> float:
    """Seconds until the story is ready, by replaying what's left of the run:
    sheets one after another, keyframes one after another, each scene's clips
    as soon as its keyframes exist (four at a time, the ones already at Kling
    counting down from when they were sent), music, then the assembly. A
    finished piece only ever brings the estimate down."""
    S, K, C = _seconds("sheet"), _seconds("keyframe") + _seconds("review"), _seconds("clip") + _seconds("review")
    t = 0.0
    if sheets_left:
        into = _since(order.get("asset_generation_started_at"), now) % S
        t = sheets_left * S - min(into, 0.85 * S)
    done_at = [r.get("keyframe_at") for r in rows.values() if r.get("keyframe_url") and r.get("keyframe_at")]
    since_kf = min((_since(x, now) for x in done_at), default=None)
    kf_ready, first = {}, True
    for k in planned:
        if (rows.get(k) or {}).get("keyframe_url"):
            kf_ready[k] = 0.0
            continue
        into = (since_kf if since_kf is not None else 0.0) if first and not sheets_left else 0.0
        t += max(K - min(into, 0.85 * K), 0.15 * K) if first else K
        first = False
        kf_ready[k] = t
    end = t
    if video:
        scene_ready: dict = {}
        for k, ready in kf_ready.items():
            scene_ready[k[0]] = max(scene_ready.get(k[0], 0.0), ready)
        slots = []
        for k in planned:
            r = rows.get(k) or {}
            if not r.get("clip_url") and r.get("clip_state") in ("submitted", "retrying"):
                slots.append(max(C - _since(r.get("updated_at"), now), 0.1 * C))
        slots = sorted(slots + [0.0] * max(0, CLIP_CONCURRENCY - len(slots)))
        for k in planned:
            r = rows.get(k) or {}
            if r.get("clip_url") or r.get("clip_state") in ("submitted", "retrying"):
                continue
            start = max(scene_ready.get(k[0], 0.0), slots[0])
            slots[0] = start + C
            slots.sort()
        end = max(end, max(slots, default=0.0))
        if not music_done:
            end = max(end, _seconds("music") + (0.0 if narration_done else _seconds("narration") * 4))
    return end + _seconds("assembly")


async def _shot_progress(order: dict, now: datetime) -> dict | None:
    """Steps, ETA and previews of a shot plan in production; None for other plans."""
    from services import shot_pipeline

    plan_id = order.get("production_plan_id")
    if not plan_id:
        return None
    plan = await db.production_plans.find_one({"id": plan_id}, {"_id": 0})
    scenes = await db.scene_plans.find({"order_id": order["id"], "production_plan_id": plan_id, "is_archived": False},
                                       {"_id": 0, "scene_index": 1, "shots": 1}).sort("scene_index", 1).to_list(50)
    if not plan or not shot_pipeline.has_shots(scenes):
        return None
    planned = [(sc["scene_index"], sh["shot_index"]) for sc in scenes for sh in sc.get("shots") or []]
    rows = {(r["scene_index"], r["shot_index"]): r for r in await shot_pipeline.shot_rows(order["id"], plan_id)}
    video = get_order_output_type(order) in ("video", "both")
    cast = sorted({t for sc in scenes for sh in sc.get("shots") or [] for t in (sh.get("characters") or [])})
    sheets = await shot_pipeline.load_character_sheets(order, plan)
    cover = await db.scene_images.find_one({"order_id": order["id"], "production_plan_id": plan_id, "kind": "cover"},
                                           {"_id": 0, "image_url": 1, "created_at": 1})
    music = await db.music_tracks.find_one({"order_id": order["id"], "production_plan_id": plan_id},
                                           {"_id": 0, "created_at": 1}) if video else None

    n = len(planned)
    sheets_total = max(1, len(cast) or 1)
    sheets_done = min(sheets_total, len([t for t in cast if t in sheets]) if cast else len(sheets))
    kf_done = sum(1 for k in planned if (rows.get(k) or {}).get("keyframe_url"))
    narr_done = sum(1 for k in planned if (rows.get(k) or {}).get("narration_url"))
    clips_done = sum(1 for k in planned if (rows.get(k) or {}).get("clip_url")) if video else 0
    in_flight = sum(1 for k in planned if (rows.get(k) or {}).get("clip_state") in ("submitted", "retrying")) if video else 0

    clips_left = (n - clips_done) if video else 0
    remaining = _schedule(order, planned, rows, sheets_total - sheets_done, video, bool(music), narr_done >= n, now)

    name = _child_name(order)
    if sheets_done < sheets_total:
        message = f"بنرسم {name} كرتون 🎨" if "child" not in sheets else "بنرسم باقي العيلة 🎨"
    elif kf_done < n:
        scene_of = planned[kf_done][0]
        message = f"بنرسم المشهد {scene_of} من {len(scenes)} — لقطة {kf_done + 1} من {n} 🖌️"
    elif clips_left:
        message = f"بنحرّك اللقطات: {clips_done} من {n} جاهزة 🎬"
    else:
        message = "اللقطات جاهزة — بنكمّل اللمسات الأخيرة ✨"

    def step(key, label, done, total, active):
        state = "done" if done >= total else "active" if active else "waiting"
        return {"key": key, "label_ar": label, "done": done, "total": total, "state": state}

    # Several of these run at the same time (narration with the sheets, music
    # and clips alongside the keyframes).
    steps = [step("characters", "رسم الشخصيات", sheets_done, sheets_total, True),
             step("scenes", "رسم المشاهد", kf_done, n, sheets_done >= sheets_total),
             step("voice", "تسجيل صوت الراوي", narr_done, n, True)]
    if video:
        steps += [step("music", "تأليف الموسيقى", 1 if music else 0, 1, narr_done >= n),
                  step("animation", "تحريك اللقطات", clips_done, n, in_flight > 0 or clips_done > 0)]
    steps.append(step("assembly", "تجميع الفيديو والكتاب", 0, 1, kf_done >= n and not clips_left))

    previews = []
    if "child" in sheets:
        previews.append({"kind": "character", "url": sheets["child"]["url"], "label_ar": f"شخصية {name}"})
    previews += [{"kind": "character", "url": v["url"], "label_ar": CAST_AR.get(t, "شخصية من القصة")}
                 for t, v in sheets.items() if t != "child"][:3]
    if cover and cover.get("image_url"):
        previews.append({"kind": "cover", "url": cover["image_url"], "label_ar": "الغلاف"})
    previews += [{"kind": "scene", "url": rows[k]["keyframe_url"], "label_ar": f"المشهد {k[0]}"}
                 for k in planned if (rows.get(k) or {}).get("keyframe_url")]
    return {"message": message, "remaining": remaining, "steps": steps, "previews": previews[:MAX_PREVIEWS],
            "highlight": "character" if sheets_done and not kf_done else None}


async def compute_pipeline_progress(order: dict) -> dict:
    """{stage, stage_ar, percent, message_ar} for the progress bar, plus (when
    known) elapsed_seconds, eta_seconds, steps[] and previews[]."""
    status = order.get("status")
    now = datetime.now(timezone.utc)
    name = _child_name(order)

    # --- Terminal states ---
    if status == OrderStatus.DELIVERED.value:
        return {"stage": "delivered", "stage_ar": STAGE_LABELS_AR["delivered"], "percent": 100,
                "message_ar": "قصّتك جاهزة"}

    if status in (OrderStatus.FAILED.value, OrderStatus.MEDIA_FAILED.value):
        if order.get("engine_paused"):
            # Stopped by our engine's balance, not by the story: we resume it.
            return {"stage": "paused", "stage_ar": STAGE_LABELS_AR["paused"], "percent": 0, "paused": True,
                    "message_ar": "حصل تأخير بسيط عندنا — هنكمّل قصتك من نفس المكان أول ما يتحل، "
                                  "ومش محتاج تعمل أي حاجة."}
        return {"stage": "failed", "stage_ar": STAGE_LABELS_AR["failed"], "percent": 0,
                "message_ar": "تعذّر إكمال بعض الخطوات"}

    if status == OrderStatus.AWAITING_PAYMENT.value:
        return {"stage": "plan", "stage_ar": STAGE_LABELS_AR["plan"], "percent": 12,
                "message_ar": "اخترت القصة — ادفع عشان نبدأ نجهّزها"}

    # --- Planning range (0..20) ---
    if status == OrderStatus.PRODUCTION_PLANNING.value:
        started = ((order.get("production_generation") or {}).get("started_at")
                   or _status_entered(order, status))
        elapsed = _since(started, now)
        creep = min(elapsed / _seconds("planning"), 0.95)
        message = PLANNING_MESSAGES[int(elapsed // 25) % len(PLANNING_MESSAGES)].format(name=name)
        return {"stage": "plan", "stage_ar": STAGE_LABELS_AR["plan"], "percent": _bounded(13 + 7 * creep),
                "message_ar": message, "elapsed_seconds": int(elapsed),
                "eta_seconds": int(max(_seconds("planning") - elapsed, 0.1 * _seconds("planning")))}

    plan_statuses = (
        OrderStatus.PENDING.value,
        OrderStatus.SCENARIOS_GENERATING.value,
        OrderStatus.SCENARIOS_READY.value,
        OrderStatus.SCENARIO_SELECTED.value,
        OrderStatus.READY_FOR_AI.value,
    )
    if status in plan_statuses:
        bumps = {
            OrderStatus.PENDING.value: 3,
            OrderStatus.SCENARIOS_GENERATING.value: 5,
            OrderStatus.SCENARIOS_READY.value: 10,
            OrderStatus.SCENARIO_SELECTED.value: 12,
            OrderStatus.READY_FOR_AI.value: 13,
        }
        return {"stage": "plan", "stage_ar": STAGE_LABELS_AR["plan"], "percent": bumps.get(status, 10),
                "message_ar": "نُعِدّ خطة القصة لطفلك..."}

    if status in (OrderStatus.PRODUCTION_READY.value, OrderStatus.PRODUCTION_APPROVED.value):
        # Plan ready. We still show 20% until assets begin; the UI treats
        # production_ready as its own state (approval waiting), no bar flicker.
        return {"stage": "plan", "stage_ar": STAGE_LABELS_AR["plan"], "percent": 20,
                "message_ar": ("الخطة جاهزة لاعتمادك" if status == OrderStatus.PRODUCTION_READY.value
                               else "بدأنا تحضير القصة...")}

    # --- Assets (20..92) and assembly (92..99) ---
    elapsed = _since(order.get("production_approved_at") or order.get("asset_generation_started_at"), now)
    if status in (OrderStatus.ASSETS_GENERATING.value, OrderStatus.ASSETS_READY.value):
        shots = await _shot_progress(order, now) if status == OrderStatus.ASSETS_GENERATING.value else None
        if shots:
            share = elapsed / max(elapsed + shots["remaining"], 1.0)
            return {"stage": "assets", "stage_ar": STAGE_LABELS_AR["assets"],
                    "percent": _bounded(20 + 72 * share, 20, 92), "message_ar": shots["message"],
                    "elapsed_seconds": int(elapsed), "eta_seconds": int(shots["remaining"]),
                    "steps": shots["steps"], "previews": shots["previews"], "highlight": shots["highlight"]}
        if status == OrderStatus.ASSETS_READY.value:
            return {"stage": "assets", "stage_ar": STAGE_LABELS_AR["assets"], "percent": 92,
                    "message_ar": "الوسائط جاهزة، سنبدأ التجميع النهائي...", "elapsed_seconds": int(elapsed),
                    "eta_seconds": int(_seconds("assembly"))}
        summary = order.get("asset_generation_summary") or {}
        total = int(summary.get("total") or 0)
        completed = int(summary.get("completed") or 0)
        ratio = (completed / total) if total else 0
        return {"stage": "assets", "stage_ar": STAGE_LABELS_AR["assets"], "percent": _bounded(20 + 72 * ratio),
                "message_ar": f"اكتمل {completed} من {total}" if total else "جاري توليد الوسائط...",
                "elapsed_seconds": int(elapsed)}

    if status == OrderStatus.ASSEMBLING.value:
        started = _status_entered(order, status)
        into = _since(started, now)
        creep = min(into / _seconds("assembly"), 0.95)
        return {"stage": "assembly", "stage_ar": STAGE_LABELS_AR["assembly"], "percent": _bounded(92 + 7 * creep),
                "message_ar": "بنجمّع الصور والصوت في فيديو وكتاب 📦", "elapsed_seconds": int(elapsed),
                "eta_seconds": int(max(_seconds("assembly") - into, 5))}

    # Fallback
    return {"stage": "plan", "stage_ar": STAGE_LABELS_AR["plan"], "percent": 5,
            "message_ar": "بدء العمل على قصّتك..."}


async def fetch_progress_for_user(order_id: str, user_id: str) -> dict | None:
    order = await db.orders.find_one({"id": order_id, "user_id": user_id}, {"_id": 0})
    if not order:
        return None
    return await compute_pipeline_progress(order)
