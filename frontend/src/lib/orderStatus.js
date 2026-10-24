// Order statuses grouped into the phases an admin thinks in (mirrors
// backend models.ORDER_STATUS_AR). Used by the order list filters, the order
// page header and the operations home.

export const ORDER_PHASES = [
  { key: "intake", label: "استلام", statuses: ["draft", "pending", "in_review"] },
  { key: "scenarios", label: "السيناريوهات", statuses: ["scenarios_generating", "scenarios_ready", "scenario_selected", "awaiting_payment"] },
  { key: "planning", label: "خطة الإنتاج", statuses: ["ready_for_ai", "production_planning", "production_ready", "production_approved"] },
  { key: "media", label: "إنتاج الوسائط", statuses: ["assets_generating", "assets_ready", "assembling", "generating"] },
  { key: "delivered", label: "تم التسليم", statuses: ["delivered", "completed"] },
  { key: "failed", label: "فشل", statuses: ["media_failed", "failed"] },
];

export const STATUS_LABELS = {
  draft: "مسودة",
  pending: "بانتظار البدء",
  in_review: "قيد المراجعة",
  scenarios_generating: "جاري توليد السيناريوهات",
  scenarios_ready: "السيناريوهات جاهزة",
  scenario_selected: "تم اختيار سيناريو",
  awaiting_payment: "بانتظار الدفع",
  ready_for_ai: "جاهز للتوليد",
  production_planning: "جاري إعداد خطة الإنتاج",
  production_ready: "خطة الإنتاج جاهزة",
  production_approved: "تمت الموافقة على الخطة",
  assets_generating: "جاري توليد الوسائط",
  assets_ready: "الوسائط جاهزة",
  assembling: "جاري التجميع",
  delivered: "تم التسليم",
  media_failed: "فشل إنتاج الوسائط",
  generating: "جاري التوليد",
  completed: "مكتمل",
  failed: "فشل",
};

export function phaseOf(status) {
  return ORDER_PHASES.find((p) => p.statuses.includes(status)) || ORDER_PHASES[0];
}

export function formatDate(iso, withTime = true) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString("ar-EG", {
    year: "numeric", month: "short", day: "numeric",
    ...(withTime ? { hour: "2-digit", minute: "2-digit", hour12: false } : {}),
  });
}

/** "منذ 3 ساعات" style relative time for queues. */
export function timeAgo(iso) {
  if (!iso) return "";
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 60) return "دلوقتي";
  if (diff < 3600) return `من ${Math.round(diff / 60)} دقيقة`;
  if (diff < 86400) return `من ${Math.round(diff / 3600)} ساعة`;
  return `من ${Math.round(diff / 86400)} يوم`;
}
