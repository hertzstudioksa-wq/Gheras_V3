import React, { useState } from "react";
import { toast } from "sonner";
import { BookOpen, Pencil, Save, X, Loader2 } from "lucide-react";
import { api, errorMessage } from "@/lib/api";

const words = (s) => String(s || "").split(/\s+/).filter(Boolean).length;

/**
 * The narrator's lines, scene by scene, on the plan-approval page. Before
 * approval the parent can reword them: one line per shot, within the length a
 * shot can hold (the drawings follow the plan's events, so the meaning stays).
 */
export default function PlanScriptCard({ orderId, summary, editable, onSaved }) {
  const scenes = summary?.scenes || [];
  const maxWords = summary?.max_line_words || 12;
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState({});
  const [saving, setSaving] = useState(false);

  if (!scenes.length) return null;

  const start = () => {
    const d = {};
    scenes.forEach((s) => { d[s.scene_index] = (s.shots || []).map((sh) => sh.narration_line); });
    setDraft(d);
    setEditing(true);
  };

  const tooLong = Object.values(draft).some((lines) => lines.some((l) => words(l) > maxWords || !String(l).trim()));

  const save = async () => {
    const changed = scenes
      .filter((s) => JSON.stringify((s.shots || []).map((sh) => sh.narration_line)) !== JSON.stringify(draft[s.scene_index]))
      .map((s) => ({ scene_index: s.scene_index, lines: draft[s.scene_index] }));
    if (!changed.length) { setEditing(false); return; }
    setSaving(true);
    try {
      await api.put(`/orders/${orderId}/production/narration`, { scenes: changed });
      toast.success("حُفظ النص الجديد 🌱");
      setEditing(false);
      onSaved?.();
    } catch (e) {
      toast.error(errorMessage(e, "تعذّر حفظ النص"));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="bg-white rounded-[2rem] p-6 md:p-8 border border-[#E2D8C9] mb-5" data-testid="plan-script">
      <div className="flex items-center justify-between gap-3 mb-1 flex-wrap">
        <div className="flex items-center gap-2 text-[#729352] font-body text-sm font-bold">
          <BookOpen className="w-4 h-4" /> نص الحكاية كما سيرويه الراوي
        </div>
        {editable && !editing && (
          <button onClick={start} className="inline-flex items-center gap-1.5 rounded-full bg-[#F8F1E7] hover:bg-[#F2E8DA] text-[#8B5A2B] px-4 py-1.5 text-sm font-bold" data-testid="edit-script-btn">
            <Pencil className="w-3.5 h-3.5" /> تعديل الصياغة
          </button>
        )}
      </div>
      <p className="font-body text-xs text-[#8A9AB0] mb-4">
        {editing
          ? `عدّل الكلمات كما تحب — كل سطر يُقال أثناء لقطة واحدة، فلا يزيد عن ${maxWords} كلمة. لتغيير الأحداث نفسها استخدم «إعادة إعداد الخطة».`
          : summary?.narration_edited
            ? "عدّلت هذا النص بنفسك — سيقرؤه الراوي كما هو."
            : "اقرأه قبل الاعتماد — يمكنك تعديل الصياغة، أو إعادة إعداد الخطة إذا لم تناسبك."}
      </p>
      <ol className="space-y-3">
        {scenes.map((s) => (
          <li key={s.scene_index} className="bg-[#FDFBF7] rounded-2xl p-4 border border-[#E2D8C9]">
            <div className="font-heading font-bold text-[#2D3748] text-sm mb-1">
              المشهد {s.scene_index}{s.title ? ` — ${s.title}` : ""}
            </div>
            {editing ? (
              <div className="space-y-2">
                {(draft[s.scene_index] || []).map((line, i) => {
                  const n = words(line);
                  const bad = n > maxWords || !String(line).trim();
                  return (
                    <div key={i}>
                      <textarea rows={2} value={line} dir="rtl"
                        onChange={(e) => setDraft((d) => ({ ...d, [s.scene_index]: d[s.scene_index].map((l, j) => (j === i ? e.target.value : l)) }))}
                        className={`w-full bg-white border rounded-xl px-3 py-2 font-body leading-relaxed ${bad ? "border-[#E07A5F]" : "border-[#E2D8C9]"}`}
                        data-testid={`script-line-${s.scene_index}-${i + 1}`} />
                      <div className={`text-[11px] font-body ${bad ? "text-[#B8612F] font-bold" : "text-[#8A9AB0]"}`}>
                        {n} / {maxWords} كلمة
                      </div>
                    </div>
                  );
                })}
              </div>
            ) : (
              <p className="font-body text-[#2D3748] leading-loose">{s.narration_text}</p>
            )}
          </li>
        ))}
      </ol>
      {editing && (
        <div className="flex flex-wrap gap-2 mt-4">
          <button onClick={save} disabled={saving || tooLong} className="btn-primary inline-flex items-center gap-2 disabled:opacity-50" data-testid="save-script-btn">
            {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />} حفظ النص
          </button>
          <button onClick={() => setEditing(false)} disabled={saving} className="inline-flex items-center gap-1.5 rounded-full bg-[#F8F1E7] text-[#8B5A2B] px-5 py-2.5 font-bold">
            <X className="w-4 h-4" /> إلغاء
          </button>
        </div>
      )}
    </div>
  );
}
