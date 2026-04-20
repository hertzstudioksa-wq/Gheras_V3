import React from "react";

const STATUS_MAP = {
  draft:                 { label: "مسودة", bg: "bg-[#F8F1E7]", fg: "text-[#8A9AB0]", dot: "bg-[#8A9AB0]" },
  pending:               { label: "بانتظار البدء", bg: "bg-[#F8F1E7]", fg: "text-[#8B5A2B]", dot: "bg-[#D4A373]" },
  in_review:             { label: "قيد المراجعة", bg: "bg-[#FCE6D4]", fg: "text-[#B8612F]", dot: "bg-[#E07A5F]" },
  scenarios_generating:  { label: "جاري توليد السيناريوهات", bg: "bg-[#E8F0E1]", fg: "text-[#4F6B3B]", dot: "bg-[#87A96B] animate-pulse" },
  scenarios_ready:       { label: "السيناريوهات جاهزة", bg: "bg-[#DEEBCF]", fg: "text-[#3F5B2E]", dot: "bg-[#4F6B3B]" },
  scenario_selected:     { label: "تم اختيار سيناريو", bg: "bg-[#DEEBCF]", fg: "text-[#3F5B2E]", dot: "bg-[#4F6B3B]" },
  ready_for_ai:          { label: "جاهز للتوليد", bg: "bg-[#E8F0E1]", fg: "text-[#4F6B3B]", dot: "bg-[#87A96B]" },
  generating:            { label: "جاري التوليد", bg: "bg-[#E8F0E1]", fg: "text-[#4F6B3B]", dot: "bg-[#87A96B] animate-pulse" },
  completed:             { label: "مكتمل", bg: "bg-[#DEEBCF]", fg: "text-[#3F5B2E]", dot: "bg-[#4F6B3B]" },
  failed:                { label: "فشل", bg: "bg-[#FCE6D4]", fg: "text-[#B8612F]", dot: "bg-[#E07A5F]" },
};

export default function OrderStatusBadge({ status }) {
  const s = STATUS_MAP[status] || STATUS_MAP.pending;
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
