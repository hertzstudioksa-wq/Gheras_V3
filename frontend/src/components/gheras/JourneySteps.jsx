import React from "react";
import { Check } from "lucide-react";

// Where the order is in the parent's journey (replaces the old "step 8 of 8"
// badge, which never moved after the builder).
const STEPS = ["الحكاية", "الدفع", "خطة المشاهد", "الرسم والتحريك", "الاستلام"];

const STEP_OF_STATUS = {
  draft: 0, pending: 0, in_review: 0, scenarios_generating: 0, scenarios_ready: 0, scenario_selected: 0,
  awaiting_payment: 1,
  ready_for_ai: 2, production_planning: 2, production_ready: 2,
  production_approved: 3, assets_generating: 3, pictures_review: 3, assets_ready: 3, assembling: 3, generating: 3, media_failed: 3,
  delivered: 5, completed: 5,
};

export function journeyStep(status, approved = false) {
  if (status === "failed") return approved ? 3 : 2;
  return STEP_OF_STATUS[status] ?? 0;
}

export default function JourneySteps({ status, approved = false, className = "" }) {
  const current = journeyStep(status, approved);
  return (
    <ol className={`flex items-center gap-1 sm:gap-2 overflow-x-auto no-scrollbar ${className}`} aria-label="مراحل القصة" data-testid="journey-steps">
      {STEPS.map((label, i) => {
        const done = i < current;
        const active = i === current;
        return (
          <li key={label} className="flex items-center gap-1 sm:gap-2 shrink-0" aria-current={active ? "step" : undefined}>
            <span
              className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-bold font-body whitespace-nowrap ${
                active ? "bg-[#729352] text-white shadow-sm"
                  : done ? "bg-white text-[#4F6B3B] border border-[#87A96B]/40"
                    : "bg-white/60 text-[#8A9AB0] border border-[#E2D8C9]"}`}
            >
              {done ? <Check className="w-3 h-3" /> : <span className="tabular-nums">{i + 1}</span>}
              {label}
            </span>
            {i < STEPS.length - 1 && <span className={`w-3 sm:w-5 h-px ${done ? "bg-[#87A96B]" : "bg-[#E2D8C9]"}`} />}
          </li>
        );
      })}
    </ol>
  );
}
