import React, { useEffect, useState } from "react";
import { api } from "../../lib/api";
import { Beaker, Loader2, AlertTriangle, RefreshCw, Play, CheckCircle2, XCircle, Clock } from "lucide-react";
import { toast } from "sonner";

const STAGE_LABELS = {
  scenario_generation:    "توليد السيناريوهات (نص)",
  production_planning:    "خطة الإنتاج (نص JSON ضخم)",
  child_character_i2i:    "إعادة رسم الطفل (i2i)",
  scene_image_generation: "صورة مشهد (preview)",
  narration_generation:   "السرد الصوتي (preview)",
  video_generation:       "فيديو لكل مشهد (preview)",
  music_generation:       "موسيقى المشهد (preview)",
};

export default function AdminStageLab() {
  const [catalog, setCatalog] = useState([]);
  const [stageKey, setStageKey] = useState("scenario_generation");
  const [inputs, setInputs] = useState({});
  const [running, setRunning] = useState(false);
  const [acknowledged, setAcknowledged] = useState(false);
  const [latestRun, setLatestRun] = useState(null);
  const [history, setHistory] = useState([]);

  useEffect(() => {
    api.get("/admin/lab/stages")
      .then((r) => setCatalog(r.data?.stages || []))
      .catch(() => toast.error("تعذّر تحميل قائمة المراحل"));
    refreshHistory();
  }, []);

  const refreshHistory = async () => {
    try {
      const { data } = await api.get("/admin/lab/runs?limit=15");
      setHistory(data?.runs || []);
    } catch { /* silent */ }
  };

  const stageMeta = catalog.find((s) => s.stage_key === stageKey);
  const isRealCall = stageMeta?.real_call;
  const estCost = stageMeta?.estimated_cost ?? 0;
  const currency = stageMeta?.currency || "SAR";

  const setInput = (k, v) => setInputs((cur) => ({ ...cur, [k]: v }));

  const [preview, setPreview] = useState(null);
  const [previewing, setPreviewing] = useState(false);

  const onPreview = async () => {
    setPreviewing(true);
    setPreview(null);
    try {
      const { data } = await api.post("/admin/lab/preview", {
        stage_key: stageKey,
        inputs: inputs,
      });
      setPreview(data);
      toast.success("Effective Prompt جاهز (بدون استدعاء موفّر)");
    } catch (e) {
      toast.error(e?.response?.data?.detail || "فشل المعاينة");
    } finally {
      setPreviewing(false);
    }
  };

  const onRun = async () => {
    if (isRealCall && !acknowledged) {
      toast.error("يجب تأكيد التكلفة قبل التشغيل");
      return;
    }
    setRunning(true);
    setLatestRun(null);
    try {
      const { data } = await api.post("/admin/lab/run", {
        stage_key: stageKey,
        inputs: inputs,
        acknowledged_cost: !!acknowledged,
      });
      setLatestRun(data);
      toast.success(`تم التشغيل (${data.latency_ms}ms)`);
      refreshHistory();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "فشل التشغيل");
    } finally {
      setRunning(false);
    }
  };

  const copyPrompt = () => {
    if (!preview?.effective_prompt) return;
    navigator.clipboard.writeText(preview.effective_prompt).then(
      () => toast.success("نُسخ الـ prompt"),
      () => toast.error("تعذّر النسخ"),
    );
  };

  return (
    <div data-testid="admin-stage-lab-page" className="max-w-5xl">
      <div className="mb-6 flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h1 className="font-heading text-3xl font-bold text-[#2D3748] inline-flex items-center gap-2">
            <Beaker className="w-7 h-7 text-[#87A96B]" />
            مختبر اختبار المراحل
          </h1>
          <p className="font-body text-sm text-[#5A677D] mt-2">
            شغّل أي مرحلة بشكل مستقل لاختبار جودة المخرج، الموفّر، الـ prompt، والـ latency. لا يُنشئ هذا المختبر طلبات حقيقية.
          </p>
        </div>
        <button onClick={refreshHistory} className="rounded-full bg-[#F8F1E7] hover:bg-[#F2E8DA] text-[#8B5A2B] px-4 py-2 text-sm font-bold inline-flex items-center gap-1" data-testid="reload-lab">
          <RefreshCw className="w-4 h-4" /> تحديث
        </button>
      </div>

      <section className="bg-white rounded-2xl p-5 border border-[#E2D8C9] mb-5">
        <div className="flex items-center gap-3 mb-4">
          <select
            value={stageKey}
            onChange={(e) => { setStageKey(e.target.value); setAcknowledged(false); setLatestRun(null); }}
            className="input flex-1"
            data-testid="lab-stage-select"
          >
            {catalog.map((s) => (
              <option key={s.stage_key} value={s.stage_key}>
                {STAGE_LABELS[s.stage_key] || s.stage_key} {s.real_call ? "• REAL" : "• preview"}
              </option>
            ))}
          </select>
          <span className="text-xs font-body text-[#5A677D] whitespace-nowrap">
            تكلفة تقديرية: <b className="text-[#2D3748]">{estCost} {currency}</b>
          </span>
        </div>

        {isRealCall && (
          <div className="bg-[#FCE6D4] border border-[#E07A5F]/40 rounded-2xl p-3 mb-4 flex items-start gap-2 text-sm" data-testid="lab-cost-warning">
            <AlertTriangle className="w-4 h-4 text-[#B8612F] mt-0.5 shrink-0" />
            <div className="flex-1">
              <div className="font-body text-[#B8612F] font-bold">هذه المرحلة تستهلك رصيد API حقيقي</div>
              <label className="inline-flex items-center gap-2 mt-2 text-[#8B3A1F] font-body cursor-pointer">
                <input type="checkbox" checked={acknowledged} onChange={(e) => setAcknowledged(e.target.checked)} data-testid="lab-ack-cost" />
                أفهم أن هذا التشغيل يستهلك ~{estCost} {currency} من رصيد API
              </label>
            </div>
          </div>
        )}

        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mb-4">
          <LabInput label="اسم الطفل (للـ context)" value={inputs.child_name} onChange={(v) => setInput("child_name", v)} testId="lab-input-child-name" />
          <LabInput label="عمر الطفل" type="number" value={inputs.child_age} onChange={(v) => setInput("child_age", v)} testId="lab-input-child-age" />
          <LabInput label="جنس الطفل" value={inputs.child_gender} onChange={(v) => setInput("child_gender", v)} placeholder="male / female" testId="lab-input-gender" />
          <LabInput label="مدة القصة (ثوانٍ)" type="number" value={inputs.duration_seconds} onChange={(v) => setInput("duration_seconds", v)} placeholder="60" testId="lab-input-duration" />
          <LabInput label="عدد المشاهد المستهدف" type="number" value={inputs.scene_target} onChange={(v) => setInput("scene_target", v)} placeholder="5" testId="lab-input-scenes" />
          <LabInput label="output_type" value={inputs.output_type} onChange={(v) => setInput("output_type", v)} placeholder="both / video / pdf" testId="lab-input-output" />
        </div>
        <LabInput label="الموقف الحقيقي / context" value={inputs.context} onChange={(v) => setInput("context", v)} multiline testId="lab-input-context" />

        {stageKey === "production_planning" && (
          <>
            <LabInput label="عنوان السيناريو المختار" value={inputs.scenario_title} onChange={(v) => setInput("scenario_title", v)} testId="lab-input-scenario-title" />
            <LabInput label="ملخص السيناريو" value={inputs.scenario_summary} onChange={(v) => setInput("scenario_summary", v)} multiline testId="lab-input-scenario-summary" />
          </>
        )}

        {stageKey === "child_character_i2i" && (
          <LabInput label="رابط صورة الطفل (داخلي مثل /api/uploads/file/{id})" value={inputs.child_image_url} onChange={(v) => setInput("child_image_url", v)} testId="lab-input-child-image" />
        )}

        {stageKey === "scene_image_generation" && (
          <div className="bg-[#F8F1E7] border border-[#D4A373]/40 rounded-2xl p-3 mb-2 space-y-2" data-testid="lab-scene-refs-block">
            <div className="text-xs font-bold text-[#8B5A2B]">
              معاينة المراجع للمشهد (Phase E) — مرّر معرّف الطلب ورقم المشهد لرؤية ماذا سيُحقَن وماذا سيُتخطّى
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
              <LabInput label="order_id" value={inputs.order_id} onChange={(v) => setInput("order_id", v)} testId="lab-input-order-id" />
              <LabInput label="scene_index" type="number" value={inputs.scene_index} onChange={(v) => setInput("scene_index", v)} testId="lab-input-scene-index" />
            </div>
          </div>
        )}

        <div className="mt-4 flex justify-end gap-2 flex-wrap">
          <button
            onClick={onPreview}
            disabled={previewing}
            className="rounded-full bg-[#F8F1E7] hover:bg-[#F2E8DA] text-[#8B5A2B] px-5 py-2 text-sm font-bold inline-flex items-center gap-2 disabled:opacity-50"
            data-testid="lab-preview-btn"
            title="معاينة الـ prompt النهائي بدون استدعاء أي موفّر — مجانية"
          >
            {previewing ? <Loader2 className="w-4 h-4 animate-spin" /> : <Beaker className="w-4 h-4" />}
            معاينة Prompt الفعّال
          </button>
          <button
            onClick={onRun}
            disabled={running || (isRealCall && !acknowledged)}
            className="btn-primary inline-flex items-center gap-2 disabled:opacity-50"
            data-testid="lab-run-btn"
          >
            {running ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
            تشغيل المرحلة
          </button>
        </div>
      </section>

      {preview && (
        <section className="bg-white rounded-2xl p-5 border-2 border-[#D4A373]/50 mb-5" data-testid="lab-preview-result">
          <div className="flex items-center gap-2 mb-3 flex-wrap">
            <Beaker className="w-5 h-5 text-[#8B5A2B]" />
            <span className="font-heading font-bold text-[#2D3748]">Effective Prompt — {preview.stage_key}</span>
            <span className="text-[10px] bg-[#F8F1E7] text-[#8B5A2B] rounded-full px-2 py-0.5 font-bold">
              لم يُستدعَ أي موفّر
            </span>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2 mb-3 text-xs font-body">
            <Stat label="provider" value={preview.provider} />
            <Stat label="model" value={preview.model_name} />
            <Stat label="model_source" value={preview.model_source} />
            <Stat label="transport" value={preview.transport} />
            <Stat label="prompt_source" value={preview.prompt_source} />
            <Stat label="template_id" value={(preview.template_id || "—").slice(0, 8)} />
            <Stat label="version" value={preview.template_version ?? "—"} />
            <Stat label="prompt_hash" value={(preview.prompt_hash || "").slice(7, 19)} />
            <Stat label="context_source" value={preview.context_source} />
            <Stat label="fallback_would_happen" value={String(preview.fallback_would_happen)} />
            <Stat label="est. cost" value={`${preview.estimated_cost} ${preview.currency}`} />
            <Stat label="env_key" value={preview.env_key} />
          </div>

          {preview.warnings?.length > 0 && (
            <div className="bg-[#FCE6D4] border border-[#E07A5F]/40 rounded-2xl p-3 mb-3 text-sm" data-testid="preview-warnings">
              <div className="font-bold text-[#B8612F] inline-flex items-center gap-1 mb-1">
                <AlertTriangle className="w-4 h-4" /> تنبيهات ({preview.warnings.length})
              </div>
              <ul className="text-[#8B3A1F] text-xs space-y-1 list-disc pr-4">
                {preview.warnings.map((w, i) => <li key={i}>{w}</li>)}
              </ul>
            </div>
          )}

          {preview.unresolved_placeholders?.length > 0 && (
            <div className="bg-[#FCE6D4] border border-[#E07A5F]/40 rounded-2xl p-2 mb-3 text-xs font-mono" data-testid="preview-unresolved">
              <span className="font-bold text-[#B8612F]">متغيّرات غير محلولة:</span>{" "}
              {preview.unresolved_placeholders.map((p, i) => (
                <span key={i} className="bg-white text-[#B8612F] rounded px-1 mx-0.5">${p}</span>
              ))}
            </div>
          )}

          <div className="mb-2 flex items-center justify-between">
            <span className="text-[11px] font-bold text-[#5A677D] uppercase">الـ prompt النهائي</span>
            <button
              onClick={copyPrompt}
              className="rounded-full bg-[#F8F1E7] text-[#8B5A2B] px-3 py-1 text-xs font-bold inline-flex items-center gap-1"
              data-testid="preview-copy-btn"
            >
              نسخ
            </button>
          </div>
          <pre className="bg-[#FDFBF7] border border-[#E2D8C9] rounded-2xl p-3 text-xs whitespace-pre-wrap break-words max-h-96 overflow-auto font-mono" data-testid="preview-effective-prompt">
            {preview.effective_prompt}
          </pre>

          {preview.scene_image_extras && (
            <details className="mt-3 cursor-pointer" data-testid="preview-scene-extras">
              <summary className="text-[11px] font-bold text-[#5A677D] uppercase">Scene References (dry-run)</summary>
              <pre className="mt-2 bg-[#FDFBF7] border border-[#E2D8C9] rounded-xl p-3 text-[10px] whitespace-pre-wrap font-mono">
                {JSON.stringify(preview.scene_image_extras, null, 2)}
              </pre>
            </details>
          )}

          <details className="mt-3 cursor-pointer">
            <summary className="text-[11px] font-bold text-[#5A677D] uppercase">السياق المُستخدَم في الـ render</summary>
            <pre className="mt-2 bg-[#FDFBF7] border border-[#E2D8C9] rounded-xl p-3 text-[10px] whitespace-pre-wrap font-mono">
              {JSON.stringify(preview.context_used, null, 2)}
            </pre>
          </details>
        </section>
      )}

      {latestRun && (
        <section className="bg-white rounded-2xl p-5 border-2 border-[#87A96B]/40 mb-5" data-testid="lab-result">
          <div className="flex items-center gap-2 mb-3">
            {latestRun.status === "success" ? (
              <CheckCircle2 className="w-5 h-5 text-[#4F6B3B]" />
            ) : latestRun.status === "preview-only" ? (
              <Clock className="w-5 h-5 text-[#8B5A2B]" />
            ) : (
              <XCircle className="w-5 h-5 text-[#B8612F]" />
            )}
            <span className="font-heading font-bold text-[#2D3748]">
              {STAGE_LABELS[latestRun.stage_key] || latestRun.stage_key} • {latestRun.status}
            </span>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2 mb-3 text-xs font-body">
            <Stat label="provider" value={latestRun.provider} />
            <Stat label="model" value={latestRun.model_name} />
            <Stat label="transport" value={latestRun.transport} />
            <Stat label="env_key" value={latestRun.env_key} />
            <Stat label="latency" value={`${latestRun.latency_ms}ms`} />
            <Stat label="prompt_source" value={latestRun.prompt_source} />
            <Stat label="prompt_hash" value={(latestRun.prompt_hash || "").slice(7, 19)} />
            <Stat label="est. cost" value={`${latestRun.estimated_cost} SAR`} />
            <Stat label="fallback_used" value={String(latestRun.fallback_used)} />
          </div>
          {latestRun.error_message && (
            <div className="bg-[#FCE6D4] border border-[#E07A5F]/40 rounded-2xl p-3 mb-3 text-sm font-mono text-[#B8612F]" data-testid="lab-error">
              {latestRun.error_message}
            </div>
          )}
          <pre className="bg-[#FDFBF7] border border-[#E2D8C9] rounded-2xl p-3 text-xs overflow-x-auto whitespace-pre-wrap" data-testid="lab-output-preview">
            {JSON.stringify(latestRun.output_preview, null, 2)}
          </pre>
        </section>
      )}

      <section className="bg-white rounded-2xl p-5 border border-[#E2D8C9]" data-testid="lab-history">
        <h3 className="font-heading text-lg font-bold text-[#2D3748] mb-3">السجل (آخر 15 تشغيلاً)</h3>
        {history.length === 0 ? (
          <p className="text-sm text-[#8A9AB0] font-body">لا توجد تشغيلات سابقة بعد.</p>
        ) : (
          <div className="divide-y divide-[#E2D8C9]">
            {history.map((r) => (
              <div key={r.id} className="py-2 flex items-center gap-3 text-xs font-body" data-testid={`lab-history-row-${r.id}`}>
                <span className={`px-2 py-0.5 rounded-full font-bold ${
                  r.status === "success" ? "bg-[#E8F0E1] text-[#4F6B3B]" :
                  r.status === "preview-only" ? "bg-[#F8F1E7] text-[#8B5A2B]" :
                  "bg-[#FCE6D4] text-[#B8612F]"
                }`}>{r.status}</span>
                <span className="text-[#2D3748] font-bold flex-1 truncate">{r.stage_key}</span>
                <span className="text-[#5A677D]">{r.provider}/{r.model_name}</span>
                <span className="text-[#8A9AB0]">{r.latency_ms}ms</span>
                <span className="text-[#8A9AB0]">{r.created_at?.slice(0, 16)}</span>
              </div>
            ))}
          </div>
        )}
      </section>

      <style>{`
        .input {
          background: #FDFBF7;
          border: 1px solid #E2D8C9;
          border-radius: 14px;
          padding: 8px 12px;
          font-family: 'Tajawal', sans-serif;
          color: #2D3748;
          font-size: 14px;
        }
        .input:focus { outline: 2px solid #87A96B; outline-offset: 1px; }
      `}</style>
    </div>
  );
}

function LabInput({ label, value, onChange, type = "text", placeholder, multiline, testId }) {
  return (
    <label className="block mb-3">
      <div className="text-xs text-[#5A677D] font-body mb-1">{label}</div>
      {multiline ? (
        <textarea className="input w-full min-h-[80px]" value={value || ""} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} data-testid={testId} />
      ) : (
        <input type={type} className="input w-full" value={value || ""} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} data-testid={testId} />
      )}
    </label>
  );
}

function Stat({ label, value }) {
  return (
    <div className="bg-[#FDFBF7] border border-[#E2D8C9] rounded-xl px-3 py-2">
      <div className="text-[10px] text-[#8A9AB0] font-body uppercase tracking-wide">{label}</div>
      <div className="text-sm text-[#2D3748] font-body font-bold truncate">{value || "—"}</div>
    </div>
  );
}
