import React, { useEffect, useState } from "react";
import { api } from "../../lib/api";
import { Workflow, Save, Loader2, RefreshCcw, Info, ArrowDown } from "lucide-react";
import { toast } from "sonner";

const STAGE_LABELS = {
  scenario_generation: "توليد السيناريوهات",
  production_planning: "إعداد خطة الإنتاج",
  child_character_i2i: "تحويل صورة الطفل لشخصية",
  scene_image_generation: "توليد صور المشاهد",
  narration_generation: "توليد السرد الصوتي",
  final_assembly: "التجميع النهائي",
};

export default function AdminPipeline() {
  const [config, setConfig] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const { data } = await api.get("/admin/pipeline-config");
      setConfig(data);
      setDirty(false);
    } catch {
      toast.error("تعذّر تحميل إعدادات خط الإنتاج");
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { load(); }, []);

  const updateStage = (stageKey, patch) => {
    setConfig((c) => ({ ...c, stages: { ...c.stages, [stageKey]: { ...c.stages[stageKey], ...patch } } }));
    setDirty(true);
  };

  const save = async () => {
    setSaving(true);
    try {
      await api.patch("/admin/pipeline-config", { order: config.order, stages: config.stages });
      toast.success("تم حفظ إعدادات خط الإنتاج");
      setDirty(false);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "تعذّر الحفظ");
    } finally {
      setSaving(false);
    }
  };

  if (loading || !config) {
    return <div className="text-center py-8"><Loader2 className="w-6 h-6 animate-spin mx-auto text-[#87A96B]" /></div>;
  }

  return (
    <div className="space-y-6" data-testid="admin-pipeline-page" dir="rtl">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="font-heading text-3xl font-bold text-[#2D3748] mb-1 flex items-center gap-2">
            <Workflow className="w-6 h-6 text-[#87A96B]" />
            إعدادات خط الإنتاج
          </h1>
          <p className="font-body text-sm text-[#5A677D]">
            تحكّم في مراحل خط الإنتاج، ترتيبها، عدد محاولات الإعادة، وصلاحيات fallback.
          </p>
        </div>
        <div className="flex gap-2">
          <button onClick={load} className="inline-flex items-center gap-2 bg-[#F8F1E7] text-[#8B5A2B] rounded-full px-4 py-2 text-sm font-bold">
            <RefreshCcw className="w-4 h-4" /> تحديث
          </button>
          <button
            disabled={!dirty || saving}
            onClick={save}
            className="inline-flex items-center gap-2 bg-[#87A96B] text-white rounded-full px-4 py-2 text-sm font-bold disabled:opacity-40"
            data-testid="pipeline-save-btn"
          >
            {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />} حفظ التغييرات
          </button>
        </div>
      </div>

      <div className="rounded-2xl overflow-hidden bg-[#E8F0E1] border border-[#87A96B]/30 p-4 text-sm font-body text-[#4F6B3B] flex items-start gap-2">
        <Info className="w-4 h-4 mt-0.5 shrink-0" />
        <span>
          <b>child_character_i2i</b> مُعطّل افتراضياً. بتفعيله ستُولَّد شخصية كرتونية مرجعية للطفل قبل مشاهد القصة (حالياً في وضع <b>mock/dry-run</b> — بدون استدعاء مزوّد حقيقي). لا يكسر المشاهد الحالية حتى لو فشل.
        </span>
      </div>

      <div className="space-y-3" data-testid="pipeline-stages">
        {config.order.map((stageKey, idx) => {
          const s = config.stages[stageKey] || {};
          return (
            <div key={stageKey}>
              <div className="bg-white rounded-2xl border border-[#E2D8C9] p-4 flex flex-wrap items-center gap-4" data-testid={`stage-${stageKey}`}>
                <div className="w-8 h-8 rounded-full bg-[#F8F1E7] grid place-content-center font-heading font-bold text-[#8B5A2B] text-sm">{idx + 1}</div>
                <div className="flex-1 min-w-0">
                  <div className="font-heading font-bold text-[#2D3748]">{STAGE_LABELS[stageKey] || stageKey}</div>
                  <div className="text-xs text-[#8A9AB0]">{stageKey}</div>
                </div>
                <label className="inline-flex items-center gap-2 text-sm font-body text-[#2D3748]">
                  <input
                    type="checkbox"
                    checked={!!s.enabled}
                    onChange={(e) => updateStage(stageKey, { enabled: e.target.checked })}
                  />
                  مفعّل
                </label>
                <label className="inline-flex items-center gap-2 text-sm font-body text-[#2D3748]">
                  <input
                    type="checkbox"
                    checked={!!s.fallback_allowed}
                    onChange={(e) => updateStage(stageKey, { fallback_allowed: e.target.checked })}
                  />
                  fallback مسموح
                </label>
                <label className="inline-flex items-center gap-2 text-sm font-body text-[#2D3748]">
                  محاولات:
                  <input
                    type="number"
                    min={1}
                    max={5}
                    value={s.max_retries ?? 2}
                    onChange={(e) => updateStage(stageKey, { max_retries: parseInt(e.target.value) || 1 })}
                    className="w-16 rounded-xl border border-[#E2D8C9] px-2 py-1 text-sm"
                  />
                </label>
              </div>
              {idx < config.order.length - 1 && (
                <div className="flex justify-center py-2 text-[#8A9AB0]"><ArrowDown className="w-4 h-4" /></div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
