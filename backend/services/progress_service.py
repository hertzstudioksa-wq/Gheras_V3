"""Unified pipeline progress — single source of truth for user-facing progress.

Maps the full journey (Plan → Assets → Assembly → Delivered) into 4 stages
with a weighted 0..100 percent and a human Arabic label. All admin/internal
details (job ids, prompts, snapshots) are intentionally kept out.

Stage weights (sum = 100):
    plan         0 .. 20
    assets      20 .. 80
    assembly    80 .. 100
    delivered        100
"""
from db import db
from models import OrderStatus


STAGE_LABELS_AR = {
    "plan": "إعداد خطة القصة",
    "assets": "توليد الصور والسرد",
    "assembly": "تجميع الفيديو والكتاب",
    "delivered": "جاهز",
    "failed": "تعذّر الإنشاء",
}


def _bounded(v: float) -> int:
    return max(0, min(100, int(round(v))))


async def compute_pipeline_progress(order: dict) -> dict:
    """Return {stage, stage_ar, percent, message_ar} for a user-facing progress bar."""
    status = order.get("status")

    # --- Terminal states ---
    if status == OrderStatus.DELIVERED.value:
        return {
            "stage": "delivered",
            "stage_ar": STAGE_LABELS_AR["delivered"],
            "percent": 100,
            "message_ar": "قصّتك جاهزة",
        }

    if status in (OrderStatus.FAILED.value, OrderStatus.MEDIA_FAILED.value):
        return {
            "stage": "failed",
            "stage_ar": STAGE_LABELS_AR["failed"],
            "percent": 0,
            "message_ar": "تعذّر إكمال بعض الخطوات",
        }

    # --- Planning range (0..20) ---
    plan_statuses = (
        OrderStatus.PENDING.value,
        OrderStatus.SCENARIOS_GENERATING.value,
        OrderStatus.SCENARIOS_READY.value,
        OrderStatus.SCENARIO_SELECTED.value,
        OrderStatus.READY_FOR_AI.value,
        OrderStatus.PRODUCTION_PLANNING.value,
    )
    if status in plan_statuses:
        bumps = {
            OrderStatus.PENDING.value: 3,
            OrderStatus.SCENARIOS_GENERATING.value: 5,
            OrderStatus.SCENARIOS_READY.value: 10,
            OrderStatus.SCENARIO_SELECTED.value: 12,
            OrderStatus.READY_FOR_AI.value: 14,
            OrderStatus.PRODUCTION_PLANNING.value: 17,
        }
        return {
            "stage": "plan",
            "stage_ar": STAGE_LABELS_AR["plan"],
            "percent": bumps.get(status, 10),
            "message_ar": "نُعِدّ خطة القصة لطفلك...",
        }

    if status in (OrderStatus.PRODUCTION_READY.value, OrderStatus.PRODUCTION_APPROVED.value):
        # Plan ready. We still show 20% until assets begin; the UI treats
        # production_ready as its own state (approval waiting), no bar flicker.
        return {
            "stage": "plan",
            "stage_ar": STAGE_LABELS_AR["plan"],
            "percent": 20,
            "message_ar": (
                "الخطة جاهزة لاعتمادك"
                if status == OrderStatus.PRODUCTION_READY.value
                else "بدأنا تحضير القصة..."
            ),
        }

    # --- Assets range (20..80) ---
    if status == OrderStatus.ASSETS_GENERATING.value:
        summary = order.get("asset_generation_summary") or {}
        total = int(summary.get("total") or 0)
        completed = int(summary.get("completed") or 0)
        ratio = (completed / total) if total else 0
        return {
            "stage": "assets",
            "stage_ar": STAGE_LABELS_AR["assets"],
            "percent": _bounded(20 + 60 * ratio),
            "message_ar": f"اكتمل {completed} من {total}" if total else "جاري توليد الوسائط...",
        }

    if status == OrderStatus.ASSETS_READY.value:
        return {
            "stage": "assets",
            "stage_ar": STAGE_LABELS_AR["assets"],
            "percent": 80,
            "message_ar": "الوسائط جاهزة، سنبدأ التجميع النهائي...",
        }

    # --- Assembly range (80..100) ---
    if status == OrderStatus.ASSEMBLING.value:
        summary = order.get("final_assembly_summary") or {}
        total = int(summary.get("total") or 2)
        completed = int(summary.get("completed") or 0)
        ratio = (completed / total) if total else 0
        return {
            "stage": "assembly",
            "stage_ar": STAGE_LABELS_AR["assembly"],
            "percent": _bounded(80 + 18 * ratio),
            "message_ar": "نجمع الصور والسرد في فيديو وكتاب...",
        }

    # Fallback
    return {
        "stage": "plan",
        "stage_ar": STAGE_LABELS_AR["plan"],
        "percent": 5,
        "message_ar": "بدء العمل على قصّتك...",
    }


async def fetch_progress_for_user(order_id: str, user_id: str) -> dict | None:
    order = await db.orders.find_one({"id": order_id, "user_id": user_id}, {"_id": 0})
    if not order:
        return None
    return await compute_pipeline_progress(order)
