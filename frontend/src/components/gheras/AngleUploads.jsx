import { useState } from "react";
import { ChevronDown, ScanFace } from "lucide-react";
import ImageUploader from "./ImageUploader";

// More sides of the face. The cartoon character is drawn from the front photo, while the
// story's scenes show people turned half-way or side-on: with these two photos the
// drawing keeps the real face from every side. Optional — the front photo alone still
// makes the story. `value` holds two slots: [half-side, side].
const SLOTS = [
  { label: "نصف جانب", hint: "الوجه ملتفت قليلاً" },
  { label: "من الجانب", hint: "الوجه من الجنب" },
];

export default function AngleUploads({ value, onChange, scope, testId }) {
  const slots = [value?.[0] || "", value?.[1] || ""];
  const [open, setOpen] = useState(slots.some(Boolean));
  const set = (i, url) => {
    const next = [...slots];
    next[i] = url || "";
    onChange(next);
  };

  return (
    <div className="mt-3" data-testid={testId}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="w-full inline-flex items-center justify-between gap-2 rounded-2xl border border-dashed border-[#87A96B] bg-[#F4F8EF] px-3 py-2 text-sm font-body font-bold text-[#4F6B3B] hover:bg-[#E8F0E1]"
        aria-expanded={open}
        data-testid={`${testId}-toggle`}
      >
        <span className="inline-flex items-center gap-2">
          <ScanFace className="w-4 h-4" /> صور من زوايا أخرى لشبه أدق (اختياري)
        </span>
        <ChevronDown className={`w-4 h-4 transition-transform ${open ? "rotate-180" : ""}`} />
      </button>
      {open && (
        <div className="mt-2 rounded-2xl border border-[#E2D8C9] bg-white p-3">
          <img src="/angle-guide.webp" alt="الوجه من الأمام ومن نصف جانب ومن الجانب" width="900" height="325"
               className="w-full h-auto rounded-xl bg-white" loading="lazy" />
          <div className="grid grid-cols-3 text-center text-[11px] font-body text-[#5A677D] mt-1" dir="ltr">
            <span dir="rtl">من الأمام<br />(الصورة الأساسية)</span>
            <span dir="rtl">نصف جانب</span>
            <span dir="rtl">من الجانب</span>
          </div>
          <p className="mt-2 font-body text-xs leading-relaxed text-[#2D3748]">
            الشخصية تظهر في المشاهد ملتفتة أو من الجانب، فصورتان إضافيتان تجعلان رسمها يشبهها من كل زاوية.
            صوّر الوجه نفسه بإضاءة جيدة، بدون نظارة شمسية أو فلاتر، وبدون أشخاص آخرين.
          </p>
          <div className="mt-3 flex flex-wrap gap-4 justify-center">
            {SLOTS.map((s, i) => (
              <div key={s.label} className="flex flex-col items-center gap-1">
                <ImageUploader
                  value={slots[i]}
                  onChange={(url) => set(i, url)}
                  scope={scope}
                  label={s.label}
                  size="sm"
                  testId={`${testId}-${i}`}
                />
                <span className="text-[11px] text-[#8A9AB0] font-body">{s.hint}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
