import React, { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../lib/api";
import {
  Layers, Save, Loader2, RefreshCcw, Info, Star, AlertTriangle,
  CheckCircle2, ShieldCheck, ShieldAlert, RotateCcw, Beaker, Lock,
  FileText, Volume2, Cpu, Workflow,
} from "lucide-react";
import { toast } from "sonner";

const STATUS_COLORS = {
  "real-call":               "bg-[#FCE6D4] text-[#B8612F]",
  "real-call-when-keyed":    "bg-[#FFE9C7] text-[#9A6515]",
  "preview-only":            "bg-[#F8F1E7] text-[#8B5A2B]",
  "not-yet-wired":           "bg-[#EEE9E0] text-[#5A677D]",
  "local-binary":            "bg-[#DEEBCF] text-[#3F5B2E]",
  "reuse-from-other-stage":  "bg-[#E8F0E1] text-[#4F6B3B]",
};

const SOURCE_COLORS = {
  override: "bg-[#DEEBCF] text-[#3F5B2E]",
  env:      "bg-[#F8F1E7] text-[#8B5A2B]",
  missing:  "bg-[#FCE6D4] text-[#B8612F]",
  "n/a":    "bg-[#EEE9E0] text-[#5A677D]",
};

const EXECUTOR_LABEL_AR = {
  "real-call":              "استدعاء حقيقي",
  "real-call-when-keyed":   "استدعاء حقيقي عند توفّر المفتاح",
  "preview-only":           "معاينة فقط",
  "not-yet-wired":          "غير موصَّل بعد",
  "local-binary":           "تنفيذ محلّي",
  "reuse-from-other-stage": "إعادة استخدام مرحلة أخرى",
};

export default function AdminStageControl() {
  const [state, setState] = useState(null);
  const [loading, setLoading] = useState(true);
  const [savingKey, setSavingKey] = useState(null);
  const [drafts, setDrafts] = useState({});

  const load = async () => {
    setLoading(true);
    try {
      const { data } = await api.get("/admin/stage-control/state");
      setState(data);
      setDrafts({});
    } catch {
      toast.error("تعذّر تحميل لوحة التحكم بالمراحل");
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { load(); }, []);

  const setDraft = (stage, patch) =>
    setDrafts((d) => ({ ...d, [stage]: { ...(d[stage] || {}), ...patch } }));

  const saveStage = async (stage) => {
    const draft = drafts[stage.stage_key];
    if (!draft || Object.keys(draft).length === 0) return;
    setSavingKey(stage.stage_key);
    try {
      await api.patch(`/admin/stage-control/${stage.stage_key}`, draft);
      toast.success(`تم حفظ ${stage.name_ar}`);
      await load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "تعذّر الحفظ");
    } finally {
      setSavingKey(null);
    }
  };

  const resetStage = async (stage) => {
    if (!window.confirm(`إعادة تعيين "${stage.name_ar}" للقيم الافتراضية؟`)) return;
    setSavingKey(stage.stage_key);
    try {
      await api.post(`/admin/stage-control/${stage.stage_key}/reset`);
      toast.success("تم إعادة التعيين");
      await load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "تعذّر إعادة التعيين");
    } finally {
      setSavingKey(null);
    }
  };

  const counts = useMemo(() => {
    if (!state) return { total: 0, callable: 0, missingKeys: 0, notWired: 0, prompts: 0 };
    const stages = state.stages || [];
    return {
      total:        stages.length,
      callable:     stages.filter((s) => s.executor_callable).length,
      missingKeys:  stages.filter((s) => s.env_key && s.secret_source === "missing").length,
      notWired:     stages.filter((s) => s.executor_status === "not-yet-wired").length,
      prompts:      stages.filter((s) => s.prompt_driven).length,
    };
  }, [state]);

  if (loading || !state) {
    return (
      <div className="text-center py-12">
        <Loader2 className="w-6 h-6 animate-spin mx-auto text-[#87A96B]" />
      </div>
    );
  }

  const stages = state.stages || [];

  return (
    <div className="space-y-5" data-testid="admin-stage-control-page" dir="rtl">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="font-heading text-3xl font-bold text-[#2D3748] mb-1 flex items-center gap-2">
            <Layers className="w-6 h-6 text-[#87A96B]" />
            مركز التحكم بالمراحل
          </h1>
          <p className="font-body text-sm text-[#5A677D]">
            لوحة موحَّدة لكل المراحل الـ {state.supported_stages_count} —
            المزوّد، النموذج، مصدر السرّ، حالة المُنفّذ، والقالب — في مكان واحد.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={load}
            className="inline-flex items-center gap-2 bg-[#F8F1E7] text-[#8B5A2B] rounded-full px-4 py-2 text-sm font-bold"
            data-testid="reload-stage-control"
          >
            <RefreshCcw className="w-4 h-4" /> تحديث
          </button>
        </div>
      </div>

      {/* KPI summary */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <KpiCard
          label="مراحل قابلة للتشغيل"
          value={`${counts.callable}/${counts.total}`}
          tone={counts.callable === counts.total ? "ok" : "warn"}
          tid="kpi-callable"
        />
        <KpiCard
          label="مفاتيح ناقصة"
          value={counts.missingKeys}
          tone={counts.missingKeys === 0 ? "ok" : "danger"}
          tid="kpi-missing-keys"
        />
        <KpiCard
          label="غير موصَّل بعد"
          value={counts.notWired}
          tone={counts.notWired === 0 ? "ok" : "warn"}
          tid="kpi-not-wired"
        />
        <KpiCard
          label="قوالب مفعّلة"
          value={counts.prompts}
          tone="info"
          tid="kpi-prompts"
        />
        <KpiCard
          label="السرد TTS حقيقي"
          value={state.narration_real_call_available ? "نعم" : "لا"}
          tone={state.narration_real_call_available ? "ok" : "warn"}
          tid="kpi-narration"
        />
      </div>

      {/* Active preset banner */}
      {state.active_preset && (
        <div
          className="bg-[#DEEBCF] border border-[#87A96B]/40 rounded-2xl p-3 inline-flex items-center gap-2 text-sm"
          data-testid="stage-control-active-preset"
        >
          <Star className="w-4 h-4 text-[#3F5B2E]" />
          <span className="font-body text-[#3F5B2E]">
            Preset النشط: <b>{state.active_preset.name}</b>
          </span>
        </div>
      )}

      {/* Narration banner */}
      {!state.narration_real_call_available && (
        <div
          className="bg-[#FFE9C7]/70 border border-[#D4A373]/40 rounded-2xl p-3 text-sm flex items-start gap-2"
          data-testid="narration-banner"
        >
          <Volume2 className="w-4 h-4 mt-0.5 text-[#9A6515]" />
          <div className="flex-1">
            <div className="font-bold text-[#9A6515] mb-1">السرد TTS — وضع المحاكاة</div>
            <div className="text-xs text-[#7A4F10] leading-relaxed">
              لتفعيل التوليد الصوتي الحقيقي عبر ElevenLabs:
              ضع مفتاح <code className="bg-white px-1 rounded">ELEVENLABS_API_KEY</code> من{" "}
              <Link to="/admin/secrets" className="underline font-bold">صفحة المفاتيح والمزوّدين</Link>.
              النموذج الافتراضي: <code className="bg-white px-1 rounded">{state.narration_defaults?.model}</code>.
              عند توفّر المفتاح ستتحوّل المرحلة تلقائياً إلى استدعاء حقيقي بدون أيّ تعديل برمجي.
            </div>
          </div>
        </div>
      )}

      {/* Integrity */}
      {!state.integrity?.ok && (
        <div className="bg-[#FCE6D4] border border-[#E07A5F]/40 rounded-2xl p-3 text-sm" data-testid="stage-control-integrity-warn">
          <div className="font-bold text-[#B8612F] inline-flex items-center gap-2 mb-1">
            <AlertTriangle className="w-4 h-4" /> اختلال في تكامل خط الإنتاج
          </div>
          {state.integrity.orphan_stages_in_pipeline?.length > 0 && (
            <div className="text-xs text-[#8B3A1F]">
              مراحل يتيمة: {state.integrity.orphan_stages_in_pipeline.join(", ")}
            </div>
          )}
        </div>
      )}

      {/* Stages */}
      <div className="space-y-3" data-testid="stage-control-stages">
        {stages.map((s, idx) => (
          <StageCard
            key={s.stage_key}
            index={idx + 1}
            stage={s}
            draft={drafts[s.stage_key] || {}}
            onChange={(patch) => setDraft(s.stage_key, patch)}
            onSave={() => saveStage(s)}
            onReset={() => resetStage(s)}
            saving={savingKey === s.stage_key}
            elevenlabs_default_model={state.narration_defaults?.model}
          />
        ))}
      </div>

      <div className="rounded-2xl bg-[#F8F1E7]/60 border border-[#D4A373]/30 p-3 text-xs font-body text-[#8B5A2B] flex items-start gap-2">
        <Info className="w-4 h-4 mt-0.5 shrink-0" />
        <span>
          الحفظ يكتب على <code>model_registry</code>. لتفعيل/إيقاف مرحلة في خط الإنتاج
          استخدم <Link to="/admin/pipeline" className="underline">إعدادات خط الإنتاج</Link>.
          لتعديل القوالب: <Link to="/admin/prompts" className="underline">برومبتات AI</Link>.
          لاختبار مرحلة بدون لمس طلب حقيقي: <Link to="/admin/lab" className="underline">مختبر المراحل</Link>.
        </span>
      </div>
    </div>
  );
}

function KpiCard({ label, value, tone = "info", tid }) {
  const tones = {
    ok:     "bg-[#DEEBCF] text-[#3F5B2E] border-[#87A96B]/30",
    warn:   "bg-[#FFE9C7] text-[#9A6515] border-[#D4A373]/30",
    danger: "bg-[#FCE6D4] text-[#B8612F] border-[#E07A5F]/30",
    info:   "bg-white text-[#2D3748] border-[#E2D8C9]",
  };
  return (
    <div className={`rounded-2xl border p-3 ${tones[tone]}`} data-testid={tid}>
      <div className="font-body text-xs opacity-80">{label}</div>
      <div className="font-heading text-2xl font-bold mt-1">{value}</div>
    </div>
  );
}

function StageCard({ index, stage, draft, onChange, onSave, onReset, saving, elevenlabs_default_model }) {
  const dirty = Object.keys(draft).length > 0;
  const editable = stage.executor_status !== "local-binary";
  const provider     = draft.provider     ?? stage.provider     ?? "";
  const model        = draft.model_name   ?? stage.model_name   ?? "";
  const envKey       = draft.env_key      ?? stage.env_key      ?? "";
  const fallbackProv = draft.fallback_provider ?? stage.fallback_provider ?? "";
  const fallbackMod  = draft.fallback_model    ?? stage.fallback_model    ?? "";

  const callableTone = stage.executor_callable
    ? "bg-[#DEEBCF] text-[#3F5B2E]"
    : "bg-[#F8F1E7] text-[#8B5A2B]";

  return (
    <div
      className={`bg-white rounded-2xl border-2 p-4 ${
        stage.executor_callable ? "border-[#87A96B]/40" : "border-[#E2D8C9]"
      }`}
      data-testid={`sc-stage-${stage.stage_key}`}
    >
      <div className="flex items-start gap-3 flex-wrap">
        <div className="w-9 h-9 rounded-full bg-[#F8F1E7] grid place-content-center font-heading font-bold text-[#8B5A2B]">
          {index}
        </div>
        <div className="flex-1 min-w-[260px]">
          <div className="flex items-center gap-2 flex-wrap mb-1">
            <div className="font-heading font-bold text-[#2D3748]">{stage.name_ar}</div>
            <span
              className={`text-[10px] rounded-full px-2 py-0.5 font-bold ${STATUS_COLORS[stage.executor_status] || ""}`}
              data-testid={`sc-${stage.stage_key}-executor-status`}
            >
              {EXECUTOR_LABEL_AR[stage.executor_status] || stage.executor_status}
            </span>
            <span className={`text-[10px] rounded-full px-2 py-0.5 font-bold inline-flex items-center gap-1 ${callableTone}`} data-testid={`sc-${stage.stage_key}-callable`}>
              {stage.executor_callable
                ? <><CheckCircle2 className="w-3 h-3" /> قابلة للتشغيل الآن</>
                : <><AlertTriangle className="w-3 h-3" /> لا تنفّذ الآن</>}
            </span>
            {stage.prompt_driven && (
              <span className="text-[10px] bg-[#E8F0E1] text-[#4F6B3B] rounded-full px-2 py-0.5 font-bold inline-flex items-center gap-1">
                <FileText className="w-3 h-3" /> قالب v{stage.prompt_template_version}
              </span>
            )}
            {!stage.prompt_editable && (
              <span className="text-[10px] bg-[#EEE9E0] text-[#5A677D] rounded-full px-2 py-0.5 font-bold">
                لا يحتاج قالب
              </span>
            )}
            {stage.config_source === "preset" && (
              <span className="text-[10px] bg-[#DEEBCF] text-[#3F5B2E] rounded-full px-2 py-0.5 font-bold inline-flex items-center gap-1">
                <Star className="w-3 h-3" /> preset: {stage.applied_by_preset_name}
              </span>
            )}
          </div>
          <div className="text-[11px] font-mono text-[#8A9AB0] mb-2">{stage.stage_key}</div>
          {stage.executor_notes_ar && (
            <p className="text-[11px] text-[#5A677D] italic mb-2">{stage.executor_notes_ar}</p>
          )}

          {/* Editable fields */}
          {editable ? (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <Field label="المزوّد">
                {stage.provider_choices?.length > 0 ? (
                  <select
                    value={provider}
                    onChange={(e) => onChange({ provider: e.target.value })}
                    className="w-full rounded-xl border border-[#E2D8C9] px-2 py-1.5 text-sm"
                    data-testid={`sc-${stage.stage_key}-provider`}
                  >
                    {stage.provider_choices.map((p) => (
                      <option key={p} value={p}>{p}</option>
                    ))}
                  </select>
                ) : (
                  <input
                    value={provider}
                    onChange={(e) => onChange({ provider: e.target.value })}
                    className="w-full rounded-xl border border-[#E2D8C9] px-2 py-1.5 text-sm"
                  />
                )}
              </Field>
              <Field label="النموذج">
                <input
                  value={model}
                  placeholder={
                    stage.stage_key === "narration_generation"
                      ? elevenlabs_default_model
                      : stage.default_model || ""
                  }
                  onChange={(e) => onChange({ model_name: e.target.value })}
                  className="w-full rounded-xl border border-[#E2D8C9] px-2 py-1.5 text-sm font-mono"
                  data-testid={`sc-${stage.stage_key}-model`}
                />
              </Field>
              <Field label="مزوّد بديل (fallback)">
                <input
                  value={fallbackProv}
                  placeholder={stage.fallback_provider || "—"}
                  onChange={(e) => onChange({ fallback_provider: e.target.value || null })}
                  className="w-full rounded-xl border border-[#E2D8C9] px-2 py-1.5 text-sm"
                />
              </Field>
              <Field label="نموذج بديل">
                <input
                  value={fallbackMod}
                  placeholder={stage.fallback_model || "—"}
                  onChange={(e) => onChange({ fallback_model: e.target.value || null })}
                  className="w-full rounded-xl border border-[#E2D8C9] px-2 py-1.5 text-sm font-mono"
                />
              </Field>
            </div>
          ) : (
            <div className="text-[12px] text-[#8A9AB0] italic">
              لا يمكن تغيير المزوّد لمرحلة محلية ({stage.provider}).
            </div>
          )}

          {/* Secret + cost row */}
          <div className="mt-3 flex flex-wrap items-center gap-3 text-xs text-[#5A677D]">
            <span className="inline-flex items-center gap-1">
              <Lock className="w-3 h-3" />
              <b>env:</b> <code className="font-mono">{envKey || "—"}</code>
              {envKey && (
                <span className={`text-[10px] rounded-full px-1.5 py-0.5 font-bold ${SOURCE_COLORS[stage.secret_source] || ""}`}>
                  {stage.secret_source === "override" ? <ShieldCheck className="w-3 h-3 inline" /> :
                   stage.secret_source === "missing"  ? <ShieldAlert className="w-3 h-3 inline" /> : null}
                  {" "}{stage.secret_source}
                </span>
              )}
            </span>
            <span>·</span>
            <span><b>~{stage.estimated_cost} {stage.currency}</b> لكل وحدة</span>
            {stage.env_key && stage.secret_source === "missing" && (
              <Link
                to="/admin/secrets"
                className="text-[#B8612F] underline font-bold inline-flex items-center gap-1"
                data-testid={`sc-${stage.stage_key}-add-key`}
              >
                <ShieldAlert className="w-3 h-3" /> أضف المفتاح الآن
              </Link>
            )}
          </div>
        </div>

        {/* Action column */}
        <div className="flex flex-col items-end gap-2 shrink-0">
          <Link
            to={`/admin/lab?stage=${stage.stage_key}`}
            className="inline-flex items-center gap-1 bg-[#F8F1E7] text-[#8B5A2B] rounded-full px-3 py-1.5 text-xs font-bold"
            data-testid={`sc-${stage.stage_key}-test`}
          >
            <Beaker className="w-3 h-3" /> اختبار
          </Link>
          {stage.prompt_editable && (
            <Link
              to="/admin/prompts"
              className="inline-flex items-center gap-1 bg-[#E8F0E1] text-[#4F6B3B] rounded-full px-3 py-1.5 text-xs font-bold"
            >
              <FileText className="w-3 h-3" /> القالب
            </Link>
          )}
          <button
            onClick={onReset}
            disabled={saving}
            className="inline-flex items-center gap-1 bg-[#FDFBF7] border border-[#E2D8C9] text-[#5A677D] rounded-full px-3 py-1.5 text-xs disabled:opacity-40"
            data-testid={`sc-${stage.stage_key}-reset`}
          >
            <RotateCcw className="w-3 h-3" /> إعادة افتراضي
          </button>
          <button
            onClick={onSave}
            disabled={!dirty || saving}
            className="inline-flex items-center gap-1 bg-[#87A96B] text-white rounded-full px-3 py-1.5 text-xs font-bold disabled:opacity-40"
            data-testid={`sc-${stage.stage_key}-save`}
          >
            {saving ? <Loader2 className="w-3 h-3 animate-spin" /> : <Save className="w-3 h-3" />}
            حفظ
          </button>
        </div>
      </div>
    </div>
  );
}

function Field({ label, children }) {
  return (
    <label className="block">
      <div className="text-[11px] font-body text-[#5A677D] mb-1">{label}</div>
      {children}
    </label>
  );
}
