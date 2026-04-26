import React, { useEffect, useMemo, useState } from "react";
import { api } from "../../lib/api";
import {
  Workflow, Save, Loader2, RefreshCcw, Info, ArrowDown,
  Star, AlertTriangle, CheckCircle2, ShieldCheck, ShieldAlert,
} from "lucide-react";
import { toast } from "sonner";

const STATUS_COLORS = {
  "real-call":              "bg-[#FCE6D4] text-[#B8612F]",
  "preview-only":           "bg-[#F8F1E7] text-[#8B5A2B]",
  "not-yet-wired":          "bg-[#EEE9E0] text-[#5A677D]",
  "local-binary":           "bg-[#DEEBCF] text-[#3F5B2E]",
  "reuse-from-other-stage": "bg-[#E8F0E1] text-[#4F6B3B]",
};
const SOURCE_COLORS = {
  override: "bg-[#DEEBCF] text-[#3F5B2E]",
  env:      "bg-[#F8F1E7] text-[#8B5A2B]",
  missing:  "bg-[#FCE6D4] text-[#B8612F]",
  "n/a":    "bg-[#EEE9E0] text-[#5A677D]",
};
const FLAG_LABELS_AR = {
  reference_aware:        "يستخدم مراجع الصور",
  audio_aware:            "يحترم وضع الصوت",
  local_binary:           "ffmpeg/reportlab محلّي",
  reuse_from_scene_image: "يُعيد استخدام صورة المشهد",
  runs_before_scenes:     "يعمل قبل المشاهد",
};

function flagLabel(flag) {
  if (flag.startsWith("gated:")) return `يعمل فقط لـ ${flag.split(":")[1]}`;
  return FLAG_LABELS_AR[flag] || flag;
}

export default function AdminPipeline() {
  const [readiness, setReadiness] = useState(null);
  const [pipelineCfg, setPipelineCfg] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const [{ data: r }, { data: cfg }] = await Promise.all([
        api.get("/admin/pipeline-readiness"),
        api.get("/admin/pipeline-config"),
      ]);
      setReadiness(r);
      setPipelineCfg(cfg);
      setDirty(false);
    } catch {
      toast.error("تعذّر تحميل خط الإنتاج");
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { load(); }, []);

  const updateStage = (stageKey, patch) => {
    setPipelineCfg((c) => ({
      ...c,
      stages: { ...c.stages, [stageKey]: { ...(c.stages[stageKey] || {}), ...patch } },
    }));
    setDirty(true);
  };

  const save = async () => {
    setSaving(true);
    try {
      await api.patch("/admin/pipeline-config", {
        order: pipelineCfg.order,
        stages: pipelineCfg.stages,
      });
      toast.success("تم حفظ إعدادات خط الإنتاج");
      setDirty(false);
      await load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "تعذّر الحفظ");
    } finally {
      setSaving(false);
    }
  };

  const integrity = readiness?.integrity || {};
  const stages = useMemo(() => readiness?.stages || [], [readiness]);

  if (loading || !readiness || !pipelineCfg) {
    return <div className="text-center py-8"><Loader2 className="w-6 h-6 animate-spin mx-auto text-[#87A96B]" /></div>;
  }

  return (
    <div className="space-y-5" data-testid="admin-pipeline-page" dir="rtl">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="font-heading text-3xl font-bold text-[#2D3748] mb-1 flex items-center gap-2">
            <Workflow className="w-6 h-6 text-[#87A96B]" />
            خط الإنتاج — Pipeline
          </h1>
          <p className="font-body text-sm text-[#5A677D]">
            مصدر الحقيقة الموحَّد: {stages.length} مرحلة، يعكس الإعدادات الفعليّة عبر الـ lab + presets + النماذج + القوالب + الأسرار.
          </p>
        </div>
        <div className="flex gap-2">
          <button onClick={load} className="inline-flex items-center gap-2 bg-[#F8F1E7] text-[#8B5A2B] rounded-full px-4 py-2 text-sm font-bold" data-testid="reload-pipeline">
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

      {readiness.active_preset && (
        <div className="bg-[#DEEBCF] border border-[#87A96B]/40 rounded-2xl p-3 inline-flex items-center gap-2 text-sm" data-testid="active-preset-banner">
          <Star className="w-4 h-4 text-[#3F5B2E]" />
          <span className="font-body text-[#3F5B2E]">
            Preset النشط: <b>{readiness.active_preset.name}</b>
            {readiness.active_preset.applied_at && (
              <span className="opacity-70 mr-2"> · طُبّق {new Date(readiness.active_preset.applied_at).toLocaleDateString("ar-SA")}</span>
            )}
          </span>
        </div>
      )}

      {!integrity.ok ? (
        <div className="bg-[#FCE6D4] border border-[#E07A5F]/40 rounded-2xl p-3 text-sm" data-testid="integrity-warning">
          <div className="font-bold text-[#B8612F] inline-flex items-center gap-2 mb-1">
            <AlertTriangle className="w-4 h-4" /> اختلال في تكامل الـ pipeline
          </div>
          {integrity.orphan_stages_in_pipeline?.length > 0 && (
            <div className="text-xs text-[#8B3A1F]">مراحل في الـ pipeline لا تنتمي للمراحل المدعومة: {integrity.orphan_stages_in_pipeline.join(", ")}</div>
          )}
          {integrity.missing_stages_in_pipeline?.length > 0 && (
            <div className="text-xs text-[#8B3A1F]">مراحل مدعومة غير موجودة في الـ pipeline: {integrity.missing_stages_in_pipeline.join(", ")}</div>
          )}
        </div>
      ) : (
        <div className="bg-[#DEEBCF]/60 rounded-2xl p-2 text-xs text-[#3F5B2E] inline-flex items-center gap-2" data-testid="integrity-ok">
          <CheckCircle2 className="w-4 h-4" /> تكامل المراحل: <b>{readiness.supported_stages_count}/{readiness.supported_stages_count} مدعومة، 0 يتيمة</b>
        </div>
      )}

      <div className="rounded-2xl bg-[#F8F1E7]/60 border border-[#D4A373]/30 p-3 text-xs font-body text-[#8B5A2B] flex items-start gap-2">
        <Info className="w-4 h-4 mt-0.5 shrink-0" />
        <span>
          الترتيب أدناه يطابق التنفيذ الفعلي. المراحل ذات <b>local-binary</b> أو <b>not-yet-wired</b> تظهر بصدق ولا يمكن تشغيلها كموفّر، فقط الإعدادات قابلة للضبط.
          العلامات: مراجع={readiness.reference_aware_stages.join(", ")} · صوت={readiness.audio_aware_stages.join(", ")}.
        </span>
      </div>

      <div className="space-y-2" data-testid="pipeline-stages">
        {stages.map((s, idx) => {
          const ps = pipelineCfg.stages[s.stage_key] || {};
          const editable = !["local-binary", "reuse-from-other-stage"].includes(s.executor_status);
          return (
            <div key={s.stage_key}>
              <div
                className={`bg-white rounded-2xl border-2 p-4 ${
                  s.executor_status === "real-call" ? "border-[#87A96B]/40" : "border-[#E2D8C9]"
                }`}
                data-testid={`stage-${s.stage_key}`}
              >
                <div className="flex items-start gap-3 flex-wrap">
                  <div className="w-8 h-8 rounded-full bg-[#F8F1E7] grid place-content-center font-heading font-bold text-[#8B5A2B] text-sm shrink-0">
                    {idx + 1}
                  </div>
                  <div className="flex-1 min-w-[200px]">
                    <div className="flex items-center gap-2 flex-wrap mb-1">
                      <div className="font-heading font-bold text-[#2D3748]">{s.name_ar}</div>
                      <span className={`text-[10px] rounded-full px-2 py-0.5 font-bold ${STATUS_COLORS[s.executor_status] || ""}`} data-testid={`stage-${s.stage_key}-executor-status`}>
                        {s.executor_status}
                      </span>
                      {s.prompt_driven && (
                        <span className="text-[10px] bg-[#E8F0E1] text-[#4F6B3B] rounded-full px-2 py-0.5 font-bold">
                          prompt-driven · v{s.prompt_template_version}
                        </span>
                      )}
                      {s.config_source === "preset" && (
                        <span className="text-[10px] bg-[#DEEBCF] text-[#3F5B2E] rounded-full px-2 py-0.5 font-bold inline-flex items-center gap-1">
                          <Star className="w-2.5 h-2.5" /> preset: {s.applied_by_preset_name}
                        </span>
                      )}
                    </div>
                    <div className="text-[11px] font-mono text-[#8A9AB0] mb-1">{s.stage_key}</div>
                    <div className="text-[11px] text-[#5A677D] flex items-center gap-2 flex-wrap">
                      {s.provider && (
                        <span><b>provider:</b> {s.provider}/{s.model_name}</span>
                      )}
                      {s.env_key && (
                        <>
                          <span>·</span>
                          <span><b>env:</b> {s.env_key}</span>
                          <span className={`text-[10px] rounded-full px-1.5 py-0.5 font-bold ${SOURCE_COLORS[s.secret_source] || ""}`} title={`secret source: ${s.secret_source}`}>
                            {s.secret_source === "override" ? <ShieldCheck className="w-3 h-3 inline" /> :
                             s.secret_source === "missing" ? <ShieldAlert className="w-3 h-3 inline" /> : null}
                            {" "}{s.secret_source}
                          </span>
                        </>
                      )}
                      <span>·</span>
                      <span><b>~{s.estimated_cost} {s.currency}</b></span>
                    </div>
                    {s.flags?.length > 0 && (
                      <div className="flex flex-wrap gap-1 mt-2">
                        {s.flags.map((f) => (
                          <span key={f} className="text-[10px] bg-[#FDFBF7] border border-[#E2D8C9] text-[#5A677D] rounded px-2 py-0.5">
                            {flagLabel(f)}
                          </span>
                        ))}
                      </div>
                    )}
                    {s.executor_notes_ar && (
                      <p className="text-[11px] text-[#8A9AB0] italic mt-1">{s.executor_notes_ar}</p>
                    )}
                  </div>
                  <div className="flex flex-wrap items-center gap-3 shrink-0">
                    <label className={`inline-flex items-center gap-2 text-sm font-body ${editable ? "text-[#2D3748]" : "text-[#8A9AB0] cursor-not-allowed"}`}>
                      <input
                        type="checkbox"
                        checked={!!ps.enabled}
                        disabled={!editable}
                        onChange={(e) => updateStage(s.stage_key, { enabled: e.target.checked })}
                        data-testid={`stage-${s.stage_key}-enabled`}
                      />
                      مفعّل
                    </label>
                    <label className={`inline-flex items-center gap-2 text-sm font-body ${editable ? "text-[#2D3748]" : "text-[#8A9AB0] cursor-not-allowed"}`}>
                      <input
                        type="checkbox"
                        checked={!!ps.fallback_allowed}
                        disabled={!editable}
                        onChange={(e) => updateStage(s.stage_key, { fallback_allowed: e.target.checked })}
                      />
                      fallback
                    </label>
                    <label className={`inline-flex items-center gap-2 text-sm font-body ${editable ? "text-[#2D3748]" : "text-[#8A9AB0]"}`}>
                      محاولات:
                      <input
                        type="number"
                        min={1}
                        max={5}
                        value={ps.max_retries ?? 1}
                        disabled={!editable}
                        onChange={(e) => updateStage(s.stage_key, { max_retries: parseInt(e.target.value) || 1 })}
                        className="w-14 rounded-xl border border-[#E2D8C9] px-2 py-1 text-sm disabled:bg-[#F2E8DA]"
                      />
                    </label>
                  </div>
                </div>
              </div>
              {idx < stages.length - 1 && (
                <div className="flex justify-center py-1.5 text-[#8A9AB0]"><ArrowDown className="w-4 h-4" /></div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
