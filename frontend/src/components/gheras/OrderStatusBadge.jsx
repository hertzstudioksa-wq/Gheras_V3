import React from "react";

const STATUS_MAP = {
  draft:                 { label: "مسودة", bg: "bg-[#F8F1E7]", fg: "text-[#8A9AB0]", dot: "bg-[#8A9AB0]" },
  pending:               { label: "بانتظار البدء", bg: "bg-[#F8F1E7]", fg: "text-[#8B5A2B]", dot: "bg-[#D4A373]" },
  in_review:             { label: "قيد المراجعة", bg: "bg-[#FCE6D4]", fg: "text-[#B8612F]", dot: "bg-[#E07A5F]" },
  scenarios_generating:  { label: "جاري توليد السيناريوهات", bg: "bg-[#E8F0E1]", fg: "text-[#4F6B3B]", dot: "bg-[#87A96B] animate-pulse" },
  scenarios_ready:       { label: "السيناريوهات جاهزة", bg: "bg-[#DEEBCF]", fg: "text-[#3F5B2E]", dot: "bg-[#4F6B3B]" },
  scenario_selected:     { label: "تم اختيار سيناريو", bg: "bg-[#DEEBCF]", fg: "text-[#3F5B2E]", dot: "bg-[#4F6B3B]" },
  awaiting_payment:      { label: "بانتظار الدفع", bg: "bg-[#FBEFD5]", fg: "text-[#8B5A2B]", dot: "bg-[#D4A373]" },
  ready_for_ai:          { label: "جاهز للتوليد", bg: "bg-[#E8F0E1]", fg: "text-[#4F6B3B]", dot: "bg-[#87A96B]" },
  production_planning:   { label: "جاري إعداد خطة الإنتاج", bg: "bg-[#E8F0E1]", fg: "text-[#4F6B3B]", dot: "bg-[#87A96B] animate-pulse" },
  production_ready:      { label: "الخطة جاهزة", bg: "bg-[#DEEBCF]", fg: "text-[#3F5B2E]", dot: "bg-[#4F6B3B]" },
  production_approved:   { label: "الخطة معتمدة", bg: "bg-[#DEEBCF]", fg: "text-[#3F5B2E]", dot: "bg-[#4F6B3B]" },
  assets_generating:     { label: "جاري توليد الوسائط", bg: "bg-[#E8F0E1]", fg: "text-[#4F6B3B]", dot: "bg-[#87A96B] animate-pulse" },
  pictures_review:       { label: "الصور بانتظار ولي الأمر", bg: "bg-[#FBEFD5]", fg: "text-[#8B5A2B]", dot: "bg-[#D4A373]" },
  assets_ready:          { label: "الوسائط جاهزة", bg: "bg-[#DEEBCF]", fg: "text-[#3F5B2E]", dot: "bg-[#4F6B3B]" },
  assembling:            { label: "جاري التجميع", bg: "bg-[#E8F0E1]", fg: "text-[#4F6B3B]", dot: "bg-[#87A96B] animate-pulse" },
  delivered:             { label: "تم التسليم", bg: "bg-[#DEEBCF]", fg: "text-[#3F5B2E]", dot: "bg-[#4F6B3B]" },
  media_failed:          { label: "فشل إنتاج الوسائط", bg: "bg-[#FCE6D4]", fg: "text-[#B8612F]", dot: "bg-[#E07A5F]" },
  generating:            { label: "جاري التوليد", bg: "bg-[#E8F0E1]", fg: "text-[#4F6B3B]", dot: "bg-[#87A96B] animate-pulse" },
  completed:             { label: "مكتمل", bg: "bg-[#DEEBCF]", fg: "text-[#3F5B2E]", dot: "bg-[#4F6B3B]" },
  failed:                { label: "فشل", bg: "bg-[#FCE6D4]", fg: "text-[#B8612F]", dot: "bg-[#E07A5F]" },
};

// What a parent reads: where their story is, in their words (the admin keeps
// the exact pipeline status above). A failed order is "paused" for the parent:
// it is resumed or retried, never left as a bare "فشل".
const WORKING = { bg: "bg-[#E8F0E1]", fg: "text-[#4F6B3B]", dot: "bg-[#87A96B] animate-pulse" };
const WAITING = { bg: "bg-[#FBEFD5]", fg: "text-[#8B5A2B]", dot: "bg-[#D4A373]" };
const READY = { bg: "bg-[#DEEBCF]", fg: "text-[#3F5B2E]", dot: "bg-[#4F6B3B]" };
const PAUSED = { bg: "bg-[#F8F1E7]", fg: "text-[#8B5A2B]", dot: "bg-[#D4A373]" };
const PARENT_MAP = {
  draft: { label: "مسودة", ...PAUSED },
  pending: { label: "نكتب الحكايات", ...WORKING },
  in_review: { label: "قيد المراجعة", ...WAITING },
  scenarios_generating: { label: "نكتب الحكايات", ...WORKING },
  scenarios_ready: { label: "اختر حكايتك", ...WAITING },
  scenario_selected: { label: "اختر حكايتك", ...WAITING },
  awaiting_payment: { label: "بانتظار الدفع", ...WAITING },
  ready_for_ai: { label: "نجهّز المشاهد", ...WORKING },
  production_planning: { label: "نجهّز المشاهد", ...WORKING },
  production_ready: { label: "الخطة بانتظار اعتمادك", ...WAITING },
  production_approved: { label: "نرسم ونحرّك القصة", ...WORKING },
  assets_generating: { label: "نرسم ونحرّك القصة", ...WORKING },
  pictures_review: { label: "الصور بانتظار مراجعتك", ...WAITING },
  assets_ready: { label: "نرسم ونحرّك القصة", ...WORKING },
  generating: { label: "نرسم ونحرّك القصة", ...WORKING },
  assembling: { label: "اللمسات الأخيرة", ...WORKING },
  delivered: { label: "جاهزة للمشاهدة", ...READY },
  completed: { label: "جاهزة للمشاهدة", ...READY },
  media_failed: { label: "متوقفة — افتحها لنكمل", ...PAUSED },
  failed: { label: "متوقفة — افتحها لنكمل", ...PAUSED },
};

export default function OrderStatusBadge({ status, audience = "admin", paused = false }) {
  const parent = audience === "parent";
  const s = parent && paused && ["failed", "media_failed"].includes(status)
    ? { label: "سنكملها قريباً", ...PAUSED }
    : (parent ? PARENT_MAP : STATUS_MAP)[status] || STATUS_MAP.pending;
  return (
    <span
      className={`inline-flex items-center gap-2 rounded-full ${s.bg} ${s.fg} px-3 py-1 text-xs font-bold font-body whitespace-nowrap`}
      data-testid={`status-badge-${status}`}
    >
      <span className={`w-2 h-2 rounded-full ${s.dot}`} />
      {s.label}
    </span>
  );
}
