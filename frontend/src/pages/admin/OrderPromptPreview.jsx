import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { Copy, RefreshCw, CheckCircle2, AlertTriangle } from "lucide-react";
import { api } from "../../lib/api";

// Exactly what each stage sends to its model for this order, composed by the
// same builders generation uses, with the engine layers as they are right now.
// Where a stage already ran, the text that was actually sent sits beside it.

const STAGE_LABELS = {
  scenario_generation: "السيناريوهات",
  production_planning: "خطة الإنتاج",
  child_character_i2i: "شخصية الطفل من الصورة",
};
const SOURCE_LABELS = { admin: "قالب الأدمن", default: "النص الأصلي من الكود", code: "النص الأصلي من الكود" };
const NARRATOR = { male: "راوي", female: "راوية" };
const QUALITY = { low: "منخفضة", medium: "متوسطة", high: "عالية" };

function copy(text) {
  navigator.clipboard?.writeText(text || "").then(() => toast.success("اتنسخ"), () => toast.error("النسخ ما نفعش"));
}

function Block({ title, text, note, open = false }) {
  if (!text) return null;
  return (
    <details open={open} className="bg-[#FDFBF7] border border-[#E2D8C9] rounded-2xl mb-2 group">
      <summary className="flex items-center justify-between gap-2 px-4 py-2.5 cursor-pointer">
        <span className="font-body text-sm font-bold text-[#2D3748]">{title}</span>
        <span className="flex items-center gap-2">
          {note}
          <span className="font-body text-[11px] text-[#8A9AB0]">{text.length.toLocaleString("ar-EG")} حرف</span>
          <button type="button" onClick={(e) => { e.preventDefault(); copy(text); }} className="text-[#8A9AB0] hover:text-[#2D3748]" title="نسخ">
            <Copy className="w-3.5 h-3.5" />
          </button>
        </span>
      </summary>
      <pre dir="auto" className="whitespace-pre-wrap break-words text-xs leading-relaxed text-[#2D3748] px-4 pb-4 max-h-[420px] overflow-y-auto font-mono">
        {text}
      </pre>
    </details>
  );
}

function Chip({ label, value }) {
  if (value === undefined || value === null || value === "") return null;
  return (
    <div className="bg-white border border-[#E2D8C9] rounded-2xl px-3 py-2">
      <div className="font-body text-[11px] text-[#8A9AB0]">{label}</div>
      <div className="font-body text-sm font-bold text-[#2D3748]" dir="auto">{value}</div>
    </div>
  );
}

function Same({ now, used }) {
  if (!used) return <span className="font-body text-[11px] text-[#8A9AB0]">لسه ما اتبعتش</span>;
  return now === used
    ? <span className="inline-flex items-center gap-1 font-body text-[11px] text-[#3F5B2E] font-bold"><CheckCircle2 className="w-3 h-3" /> مطابق للي اتبعت</span>
    : <span className="inline-flex items-center gap-1 font-body text-[11px] text-[#B8612F] font-bold"><AlertTriangle className="w-3 h-3" /> مختلف عن اللي اتبعت</span>;
}

export default function OrderPromptPreview({ orderId }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  const load = () => {
    setLoading(true);
    setError(null);
    api.get(`/admin/orders/${orderId}/prompt-preview`, { timeout: 60000 })
      .then((r) => setData(r.data))
      .catch((e) => setError(e?.response?.data?.detail || "تعذّر تحميل المعاينة"))
      .finally(() => setLoading(false));
  };
  useEffect(load, [orderId]); // eslint-disable-line react-hooks/exhaustive-deps

  if (error) return <p className="font-body text-sm text-[#B8612F]">{error}</p>;
  if (!data) return <p className="font-body text-sm text-[#8A9AB0]">جاري تجميع البرومبتات…</p>;

  const { layers, stages } = data;
  const shots = stages.shots;

  return (
    <div data-testid="order-prompt-preview">
      <div className="flex items-start justify-between gap-3 mb-3">
        <p className="font-body text-xs text-[#5A677D] max-w-xl">
          النص اللي هيتبعت لكل موديل لو المرحلة اتشغلت دلوقتي بالإعدادات الحالية. تعدّل الأجزاء دي من{" "}
          <Link to="/admin/engine?tab=styles" className="text-[#4F6B3B] font-bold underline">محرك الإنتاج</Link>.
        </p>
        <button onClick={load} disabled={loading} className="inline-flex items-center gap-1 text-xs font-body font-bold text-[#5A677D] hover:text-[#2D3748] shrink-0">
          <RefreshCw className={`w-3 h-3 ${loading ? "animate-spin" : ""}`} /> تحديث
        </button>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-2 mb-3">
        <Chip label="الستايل" value={`${layers.style?.name_ar || layers.style?.key} • v${layers.style?.version || 1}`} />
        <Chip label="اللهجة" value={`${layers.dialect?.name_ar} • v${layers.dialect?.version || 1}`} />
        <Chip label="الراوي" value={`${NARRATOR[layers.narrator] || layers.narrator} (${layers.dialect?.voices?.[layers.narrator] || "—"})`} />
        <Chip label="جودة الفيديو" value={layers.video_tier === "premium" ? "فاخر" : "متوازن"} />
        <Chip label="سرعة الكلام" value={`${layers.pacing?.words_per_second} كلمة/ث`} />
        <Chip label="طول اللقطة" value={`${layers.pacing?.shot_seconds} ث`} />
        <Chip label="جودة صور اللقطات" value={QUALITY[layers.pacing?.image_quality?.scene_image_generation || "high"]} />
        <Chip label="توجيه الصوت" value={layers.dialect?.tts_direction} />
      </div>
      {layers.story_fragments && <Block title="توجيهات الإدارة لاختيارات العميل" text={layers.story_fragments} open />}

      {["scenario_generation", "production_planning"].map((k) => {
        const s = stages[k];
        if (!s) return null;
        return (
          <section key={k} className="mt-4">
            <h4 className="font-heading font-bold text-[#2D3748] mb-2 flex items-center gap-2 flex-wrap">
              {STAGE_LABELS[k]}
              {s.model && <span className="font-body text-[11px] font-normal text-[#8A9AB0]" dir="ltr">{s.model}</span>}
            </h4>
            {s.error ? <p className="font-body text-xs text-[#B8612F]">{s.error}</p> : (
              <>
                <Block title={`رسالة النظام — ${SOURCE_LABELS[s.trace?.system_prompt?.source] || "—"}${s.trace?.system_prompt?.version ? ` (نسخة ${s.trace.system_prompt.version})` : ""}`} text={s.system} />
                <Block title={`رسالة الطلب — ${SOURCE_LABELS[s.trace?.user_prompt_source] || "—"}`} text={s.user} />
              </>
            )}
          </section>
        );
      })}
      {!stages.production_planning && (
        <p className="font-body text-xs text-[#8A9AB0] mt-3">خطة الإنتاج هتظهر هنا بعد ما يتختار سيناريو.</p>
      )}

      {stages.child_character_i2i && (
        <section className="mt-4">
          <h4 className="font-heading font-bold text-[#2D3748] mb-2 flex items-center gap-2 flex-wrap">
            {STAGE_LABELS.child_character_i2i}
            <span className="font-body text-[11px] font-normal text-[#8A9AB0]" dir="ltr">
              {stages.child_character_i2i.model} • {QUALITY[stages.child_character_i2i.quality] || stages.child_character_i2i.quality}
            </span>
          </h4>
          {stages.child_character_i2i.error ? <p className="font-body text-xs text-[#B8612F]">{stages.child_character_i2i.error}</p> : (
            <>
              <p className="font-body text-xs text-[#5A677D] mb-2">
                الصور المرفقة: {(stages.child_character_i2i.references || []).map((r) => (r === "child photo" ? "صورة الطفل" : "صورة الستايل المرجعية")).join(" + ")}
              </p>
              <Block title={`البرومبت — ${SOURCE_LABELS[stages.child_character_i2i.prompt_source] || "—"}`} text={stages.child_character_i2i.prompt} />
            </>
          )}
        </section>
      )}

      {shots && (
        <section className="mt-4">
          <h4 className="font-heading font-bold text-[#2D3748] mb-1 flex items-center gap-2 flex-wrap">
            اللقطات ({shots.shots?.length || 0})
            <span className="font-body text-[11px] font-normal text-[#8A9AB0]">
              فيديو: <bdi>{shots.video_model}</bdi> • صور: <bdi>{shots.image_model}</bdi>
              {!shots.image_on_comfy && <> ({QUALITY[shots.image_quality] || shots.image_quality})</>}
            </span>
          </h4>
          {shots.error ? <p className="font-body text-xs text-[#B8612F]">{shots.error}</p> : (
            <>
              <Block title="الممنوعات في الفيديو (negative prompt)" text={shots.shots?.[0]?.negative_prompt} />
              {(shots.shots || []).map((sh) => (
                <div key={`${sh.scene_index}-${sh.shot_index}`} className="border border-[#E2D8C9] rounded-2xl p-3 mb-2">
                  <div className="font-body text-xs font-bold text-[#8B5A2B] mb-1">مشهد {sh.scene_index} • لقطة {sh.shot_index}</div>
                  <p className="font-body text-sm text-[#2D3748] mb-2" dir="rtl">«{sh.narration_line}»</p>
                  <Block title="صورة اللقطة" text={sh.keyframe_prompt} note={<Same now={sh.keyframe_prompt} used={sh.keyframe_prompt_used} />} />
                  {sh.keyframe_references?.length > 0 && (
                    <p className="font-body text-[11px] text-[#5A677D] mb-2" dir="ltr">
                      {sh.keyframe_references.join(" • ")}
                    </p>
                  )}
                  <Block title="حركة الفيديو" text={sh.motion_prompt} note={<Same now={sh.motion_prompt} used={sh.motion_prompt_used} />} />
                </div>
              ))}
            </>
          )}
        </section>
      )}
    </div>
  );
}
