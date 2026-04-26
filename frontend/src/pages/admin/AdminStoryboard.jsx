import React, { useEffect, useState, useRef, useMemo } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { api, fileSrc } from "../../lib/api";
import { toast } from "sonner";
import {
  ArrowRight, RefreshCw, Copy, Download, Clock, AlertTriangle,
  CheckCircle2, CircleDashed, PlayCircle, XCircle, Zap, Loader2,
  Hash, ChevronDown, ChevronUp, Image as ImageIcon, FileText, Video,
  Volume2, BookOpen, User as UserIcon, Sparkles,
} from "lucide-react";

const STATUS_STYLE = {
  completed: { bg: "bg-[#DEEBCF]", fg: "text-[#3F5B2E]", label: "مكتمل",       Icon: CheckCircle2 },
  running:   { bg: "bg-[#FCE6D4]", fg: "text-[#B8612F]", label: "قيد التنفيذ",  Icon: Loader2 },
  failed:    { bg: "bg-[#FCE6D4]", fg: "text-[#B8612F]", label: "فشل",          Icon: XCircle },
  skipped:   { bg: "bg-[#EEE9E0]", fg: "text-[#5A677D]", label: "متخطَّى",       Icon: CircleDashed },
  pending:   { bg: "bg-[#F8F1E7]", fg: "text-[#8B5A2B]", label: "بانتظار",       Icon: Clock },
};

function StatusBadge({ status }) {
  const s = STATUS_STYLE[status] || STATUS_STYLE.pending;
  const Icon = s.Icon;
  const spin = status === "running";
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-bold ${s.bg} ${s.fg}`}
      data-testid={`status-badge-${status}`}
    >
      <Icon className={`w-3 h-3 ${spin ? "animate-spin" : ""}`} />
      {s.label}
    </span>
  );
}

function fmtMs(ms) {
  if (ms == null) return "—";
  if (ms < 1000) return `~${ms}ms`;
  if (ms < 60000) return `~${(ms / 1000).toFixed(1)}s`;
  return `~${(ms / 60000).toFixed(1)}m`;
}

function copyToClipboard(text) {
  if (!text) return;
  navigator.clipboard.writeText(text).then(
    () => toast.success("نُسخ النص"),
    () => toast.error("تعذّر النسخ")
  );
}

export default function AdminStoryboard() {
  const { orderId } = useParams();
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState({}); // stage_key -> bool
  const refs = useRef({});

  const load = async () => {
    try {
      const { data: d } = await api.get(`/admin/orders/${orderId}/storyboard`);
      setData(d);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "تعذّر تحميل الـ Storyboard");
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { load(); }, [orderId]);

  const toggle = (key) => setExpanded((p) => ({ ...p, [key]: !p[key] }));
  const allExpanded = useMemo(
    () => data?.stages?.every((s) => expanded[s.stage_key]) || false,
    [data, expanded]
  );
  const toggleAll = () => {
    if (!data) return;
    const next = {};
    if (!allExpanded) data.stages.forEach((s) => (next[s.stage_key] = true));
    setExpanded(next);
  };

  const scrollTo = (key) => {
    const el = refs.current[key];
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "start" });
      setExpanded((p) => ({ ...p, [key]: true }));
    }
  };

  if (loading) {
    return (
      <div className="py-12 text-center" data-testid="storyboard-loading">
        <Loader2 className="w-6 h-6 mx-auto animate-spin text-[#87A96B]" />
      </div>
    );
  }
  if (!data) {
    return <div className="py-12 text-center text-[#8A9AB0]">تعذّر التحميل</div>;
  }

  return (
    <div dir="rtl" className="space-y-5 pb-10" data-testid="admin-storyboard-page">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <button
            onClick={() => navigate("/admin/orders")}
            className="inline-flex items-center gap-1 text-sm text-[#5A677D] hover:text-[#2D3748] mb-1"
            data-testid="storyboard-back-btn"
          >
            <ArrowRight className="w-4 h-4" /> العودة للطلبات
          </button>
          <h1 className="font-heading text-2xl md:text-3xl font-bold text-[#2D3748] flex items-center gap-2">
            <Zap className="w-6 h-6 text-[#87A96B]" />
            Storyboard — تتبّع خط الإنتاج
          </h1>
          <p className="text-xs text-[#8A9AB0] mt-1 font-mono">
            order: <span className="text-[#2D3748]">{data.order.id}</span>
            {" · "}
            {data.order.child_name} ({data.order.child_age}) · {data.order.status_ar}
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={toggleAll}
            className="bg-[#F8F1E7] text-[#8B5A2B] rounded-full px-3 py-1.5 text-xs font-bold"
            data-testid="storyboard-toggle-all"
          >
            {allExpanded ? "طيّ الكل" : "توسيع الكل"}
          </button>
          <button
            onClick={load}
            className="bg-[#F8F1E7] text-[#8B5A2B] rounded-full px-3 py-1.5 text-xs font-bold inline-flex items-center gap-1"
            data-testid="storyboard-refresh"
          >
            <RefreshCw className="w-3 h-3" /> تحديث
          </button>
        </div>
      </div>

      {/* Info banner — estimates */}
      <div className="bg-[#F8F1E7] border border-[#D4A373]/40 rounded-2xl p-3 text-xs text-[#8B5A2B] flex items-start gap-2" data-testid="storyboard-estimate-banner">
        <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" />
        <span>
          قيم <b>latency</b> تقديرية (محسوبة من فرق الطوابع الزمنية). القيم غير المُخزَّنة (مثل request_id) لا تظهر. prompt_hash يُحسب عند الاستجابة.
        </span>
      </div>

      {/* Phase D.3 — Uploaded inputs overview */}
      {(data.order.child_image_url || data.order.toy_image_url) && (
        <div className="bg-white rounded-2xl border border-[#E2D8C9] p-3" data-testid="storyboard-uploaded-inputs">
          <div className="text-[11px] font-bold text-[#5A677D] uppercase tracking-wide mb-2">المدخلات المرفوعة</div>
          <div className="flex gap-4 flex-wrap">
            {data.order.child_image_url && (
              <div data-testid="storyboard-child-input">
                <div className="text-[10px] text-[#8A9AB0] mb-1">صورة الطفل</div>
                <img src={fileSrc(data.order.child_image_url)} alt="child" className="w-20 h-20 rounded-lg object-cover border border-[#E2D8C9]" />
              </div>
            )}
            {data.order.toy_image_url && (
              <div data-testid="storyboard-toy-input">
                <div className="text-[10px] text-[#8A9AB0] mb-1 inline-flex items-center gap-1">
                  صورة اللعبة/الغرض
                  <span className="bg-[#E8F0E1] text-[#4F6B3B] rounded px-1 text-[9px]">vision ✓</span>
                </div>
                <img src={fileSrc(data.order.toy_image_url)} alt="toy" className="w-20 h-20 rounded-lg object-cover border border-[#E2D8C9]" />
                {data.order.toy_description_auto && (
                  <details className="mt-1 cursor-pointer max-w-[240px]">
                    <summary className="text-[10px] font-bold text-[#5A677D]">وصف بصري</summary>
                    <p className="mt-1 text-[10px] text-[#2D3748] whitespace-pre-wrap">{data.order.toy_description_auto}</p>
                  </details>
                )}
              </div>
            )}
            {data.order.custom_notes && (
              <div className="flex-1 min-w-[240px]">
                <div className="text-[10px] text-[#8A9AB0] mb-1">ملاحظات خاصة</div>
                <p className="text-[11px] text-[#2D3748] bg-[#FDFBF7] rounded-lg p-2 border border-[#E2D8C9]">{data.order.custom_notes}</p>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Timeline */}
      <Timeline items={data.timeline} onClick={scrollTo} />

      {/* Stage cards */}
      <div className="space-y-4" data-testid="storyboard-stages">
        {data.stages.map((s) => (
          <StageCard
            key={s.stage_key}
            stage={s}
            expanded={!!expanded[s.stage_key]}
            onToggle={() => toggle(s.stage_key)}
            innerRef={(el) => (refs.current[s.stage_key] = el)}
            onReload={load}
          />
        ))}
      </div>

      <div className="text-[10px] text-[#8A9AB0] font-mono text-center pt-4" data-testid="storyboard-meta">
        generated_at: {data.meta?.generated_at}
      </div>
    </div>
  );
}

function Timeline({ items, onClick }) {
  return (
    <div
      className="bg-white rounded-2xl border border-[#E2D8C9] p-4 overflow-x-auto"
      data-testid="storyboard-timeline"
    >
      <div className="flex items-stretch gap-1 min-w-max">
        {items.map((t, idx) => {
          const s = STATUS_STYLE[t.status] || STATUS_STYLE.pending;
          const Icon = s.Icon;
          return (
            <React.Fragment key={t.stage_key}>
              <button
                onClick={() => onClick(t.stage_key)}
                className={`flex-1 min-w-[120px] rounded-xl px-3 py-2 border text-start hover:shadow-sm transition ${s.bg} border-[#E2D8C9]`}
                data-testid={`timeline-node-${t.stage_key}`}
              >
                <div className={`text-[11px] font-bold ${s.fg} mb-1 flex items-center gap-1`}>
                  <Icon className={`w-3 h-3 ${t.status === "running" ? "animate-spin" : ""}`} />
                  {idx + 1}. {t.name_ar}
                </div>
                <div className="text-[10px] text-[#5A677D] font-mono flex items-center gap-2 flex-wrap">
                  <span>{fmtMs(t.latency_ms_estimate)}</span>
                  <span>·</span>
                  <span>محاولات: {t.attempts || 0}</span>
                  {t.fallback_used && <span className="bg-[#FCE6D4] text-[#B8612F] rounded px-1">fallback</span>}
                  {t.mock_mode && <span className="bg-[#F8F1E7] text-[#8B5A2B] rounded px-1">mock</span>}
                </div>
              </button>
              {idx < items.length - 1 && (
                <div className="self-center text-[#D4A373] px-1">›</div>
              )}
            </React.Fragment>
          );
        })}
      </div>
    </div>
  );
}

function StageCard({ stage, expanded, onToggle, innerRef, onReload }) {
  const s = STATUS_STYLE[stage.status] || STATUS_STYLE.pending;
  return (
    <section
      ref={innerRef}
      className="bg-white rounded-2xl border border-[#E2D8C9] overflow-hidden"
      data-testid={`stage-card-${stage.stage_key}`}
    >
      {/* Header */}
      <button
        onClick={onToggle}
        className="w-full text-start px-4 py-3 flex items-center justify-between gap-3 flex-wrap hover:bg-[#FDFBF7] transition border-r-4"
        style={{ borderRightColor: s.fg.includes("3F5B2E") ? "#87A96B" :
                                   s.fg.includes("B8612F") ? "#E07A5F" :
                                   s.fg.includes("8B5A2B") ? "#D4A373" : "#C6CEDA" }}
        data-testid={`stage-toggle-${stage.stage_key}`}
      >
        <div className="flex items-center gap-3 min-w-0 flex-1">
          <StageIcon stageKey={stage.stage_key} />
          <div className="min-w-0">
            <div className="font-heading font-bold text-[#2D3748] flex items-center gap-2">
              {stage.name_ar}
              <span className="text-[10px] text-[#8A9AB0] font-mono">{stage.stage_key}</span>
            </div>
            <div className="flex items-center gap-2 flex-wrap mt-0.5">
              <StatusBadge status={stage.status} />
              <span className="text-[10px] text-[#8A9AB0] inline-flex items-center gap-1">
                <Clock className="w-3 h-3" /> {fmtMs(stage.latency_ms_estimate)}~
              </span>
              <span className="text-[10px] text-[#8A9AB0]">محاولات: {stage.attempts ?? 0}</span>
              {stage.fallback_used && (
                <span className="bg-[#FCE6D4] text-[#B8612F] rounded-full px-2 py-0.5 text-[10px] font-bold">
                  fallback
                </span>
              )}
              {stage.mock_mode && (
                <span className="bg-[#F8F1E7] text-[#8B5A2B] rounded-full px-2 py-0.5 text-[10px] font-bold">
                  MOCK MODE
                </span>
              )}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-3 flex-wrap">
          <div className="text-[11px] text-[#5A677D] font-mono">
            <div>
              {stage.provider}/{stage.model_name}
              <span className="text-[#8A9AB0]"> · {stage.model_source}</span>
            </div>
            <div>
              prompt: <b>{stage.prompt_source}</b>
              {stage.prompt_template_version && <> · v{stage.prompt_template_version}</>}
            </div>
          </div>
          {expanded ? <ChevronUp className="w-4 h-4 text-[#8A9AB0]" /> : <ChevronDown className="w-4 h-4 text-[#8A9AB0]" />}
        </div>
      </button>

      {/* Body */}
      {expanded && (
        <div className="border-t border-[#E2D8C9] p-4 space-y-4 bg-[#FDFBF7]" data-testid={`stage-body-${stage.stage_key}`}>
          {/* Error */}
          {stage.error_message && (
            <div className="bg-[#FCE6D4] text-[#B8612F] rounded-xl p-3 text-sm border border-[#E07A5F]/40" data-testid={`stage-error-${stage.stage_key}`}>
              <div className="font-bold mb-1 inline-flex items-center gap-1"><AlertTriangle className="w-4 h-4" /> خطأ</div>
              <pre className="text-[11px] font-mono whitespace-pre-wrap break-all">{stage.error_message}</pre>
            </div>
          )}

          {/* Input Summary */}
          <DetailBlock title="Input Summary (ما وصل للمرحلة)">
            <KeyValueTable obj={stage.input_summary} />
          </DetailBlock>

          {/* Prompt */}
          {stage.prompt_used && (
            <DetailBlock
              title={`Prompt المستخدم (source=${stage.prompt_source}${stage.prompt_template_version ? `, v${stage.prompt_template_version}` : ""})`}
              right={
                <div className="flex items-center gap-2">
                  <span className="text-[10px] font-mono text-[#8A9AB0] inline-flex items-center gap-1">
                    <Hash className="w-3 h-3" />{stage.prompt_hash || "—"}
                  </span>
                  <button
                    onClick={() => copyToClipboard(stage.prompt_used)}
                    className="inline-flex items-center gap-1 text-[10px] font-bold bg-[#F8F1E7] text-[#8B5A2B] rounded-full px-2 py-0.5"
                    data-testid={`stage-copy-prompt-${stage.stage_key}`}
                  >
                    <Copy className="w-3 h-3" /> نسخ
                  </button>
                </div>
              }
            >
              <pre className="bg-white rounded-xl p-3 border border-[#E2D8C9] font-mono text-[11px] whitespace-pre-wrap break-words max-h-56 overflow-auto">
                {stage.prompt_used}
              </pre>
            </DetailBlock>
          )}

          {/* Output summary — custom rendering per stage */}
          <DetailBlock title="Output">
            <StageOutput stage={stage} />
          </DetailBlock>

          {/* Events */}
          <DetailBlock title={`Events (${(stage.events || []).length})`}>
            {(stage.events || []).length === 0 ? (
              <div className="text-[11px] text-[#8A9AB0]">لا توجد أحداث مسجّلة لهذه المرحلة</div>
            ) : (
              <ul className="space-y-1 max-h-56 overflow-auto" data-testid={`stage-events-${stage.stage_key}`}>
                {stage.events.map((e, i) => (
                  <li key={i} className="text-[11px] font-mono bg-white rounded-lg p-2 border border-[#E2D8C9]">
                    <span className="text-[#8A9AB0]">[{e.type}]</span>{" "}
                    <span className="text-[#8A9AB0]">{e.at}</span>{" → "}
                    <span className="text-[#2D3748]">{e.message}</span>
                  </li>
                ))}
              </ul>
            )}
          </DetailBlock>

          {/* Actions */}
          <div className="flex items-center gap-2 flex-wrap pt-1">
            {stage.actions?.regenerate_endpoint && (
              <RegenerateButton endpoint={stage.actions.regenerate_endpoint} stageKey={stage.stage_key} onDone={onReload} />
            )}
            {stage.actions?.download_url && (
              <a
                href={fileSrc(stage.actions.download_url)}
                target="_blank"
                rel="noreferrer"
                download
                className="inline-flex items-center gap-1 bg-[#E8F0E1] text-[#4F6B3B] rounded-full px-3 py-1.5 text-xs font-bold"
                data-testid={`stage-download-${stage.stage_key}`}
              >
                <Download className="w-3 h-3" /> تحميل الناتج
              </a>
            )}
          </div>
        </div>
      )}
    </section>
  );
}

function RegenerateButton({ endpoint, stageKey, onDone }) {
  const [busy, setBusy] = useState(false);
  // endpoint is like: "POST /api/admin/orders/{id}/..."
  const urlPart = endpoint.replace(/^POST\s+\/api/, "");
  const run = async () => {
    if (!window.confirm("تأكيد إعادة تشغيل هذه المرحلة؟")) return;
    setBusy(true);
    try {
      await api.post(urlPart);
      toast.success("بدأت إعادة التوليد");
      setTimeout(onDone, 1500);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "فشل");
    } finally {
      setBusy(false);
    }
  };
  return (
    <button
      onClick={run}
      disabled={busy}
      className="inline-flex items-center gap-1 bg-[#87A96B] text-white rounded-full px-3 py-1.5 text-xs font-bold disabled:opacity-50"
      data-testid={`stage-regenerate-${stageKey}`}
    >
      {busy ? <Loader2 className="w-3 h-3 animate-spin" /> : <RefreshCw className="w-3 h-3" />}
      إعادة توليد هذه المرحلة
    </button>
  );
}

function DetailBlock({ title, right, children }) {
  return (
    <div>
      <div className="flex items-center justify-between mb-1.5">
        <div className="text-[11px] font-bold text-[#5A677D] uppercase tracking-wide">{title}</div>
        {right}
      </div>
      {children}
    </div>
  );
}

function KeyValueTable({ obj }) {
  if (!obj || Object.keys(obj).length === 0) {
    return <div className="text-[11px] text-[#8A9AB0]">لا توجد بيانات</div>;
  }
  return (
    <div className="bg-white rounded-xl border border-[#E2D8C9] overflow-hidden">
      <table className="w-full text-[11px] font-mono">
        <tbody>
          {Object.entries(obj).map(([k, v]) => (
            <tr key={k} className="border-b last:border-0 border-[#E2D8C9]">
              <td className="px-2 py-1.5 text-[#5A677D] w-1/3 align-top">{k}</td>
              <td className="px-2 py-1.5 text-[#2D3748] break-all">{renderValue(v)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function renderValue(v) {
  if (v == null) return <span className="text-[#8A9AB0]">—</span>;
  if (typeof v === "boolean") return v ? "✓ true" : "✗ false";
  if (typeof v === "object") {
    return <pre className="whitespace-pre-wrap text-[10px]">{JSON.stringify(v, null, 2)}</pre>;
  }
  return String(v);
}

function StageIcon({ stageKey }) {
  const Map = {
    scenario_generation:     Sparkles,
    production_planning:     FileText,
    child_character_i2i:     UserIcon,
    extra_character_i2i:     UserIcon,
    scene_image_generation:  ImageIcon,
    narration_generation:    Volume2,
    book_assets_generation:  BookOpen,
    video_assembly:          Video,
    pdf_assembly:            FileText,
  };
  const Ico = Map[stageKey] || PlayCircle;
  return <Ico className="w-5 h-5 text-[#87A96B] shrink-0" />;
}

// --- Per-stage output renderers ------------------------------------------
function StageOutput({ stage }) {
  const o = stage.output_summary || {};
  switch (stage.stage_key) {
    case "scenario_generation": return <OutScenarios o={o} />;
    case "production_planning": return <OutProduction o={o} />;
    case "child_character_i2i": return <OutChildCharacter o={o} stage={stage} />;
    case "extra_character_i2i": return <OutExtraCharacters o={o} />;
    case "scene_image_generation": return <OutSceneImages o={o} />;
    case "narration_generation": return <OutNarration o={o} />;
    case "book_assets_generation": return <OutBookAssets o={o} />;
    case "video_assembly": return <OutVideo o={o} />;
    case "pdf_assembly": return <OutPDF o={o} />;
    default: return <KeyValueTable obj={o} />;
  }
}

function OutScenarios({ o }) {
  return (
    <div className="space-y-2">
      <div className="text-[11px] text-[#5A677D]">
        المجموع: <b>{o.total_scenarios_all_batches}</b> · في الدفعة الحالية: <b>{o.current_batch_count}</b>
      </div>
      {(o.scenarios || []).map((s) => (
        <div key={s.id} className={`bg-white rounded-xl p-3 border ${s.is_selected ? "border-[#87A96B] ring-1 ring-[#87A96B]/30" : "border-[#E2D8C9]"}`} data-testid={`scenario-${s.index}`}>
          <div className="flex items-center gap-2 mb-1">
            <span className="bg-[#87A96B] text-white rounded-full w-6 h-6 grid place-content-center text-xs font-bold">{s.index}</span>
            <span className="font-heading font-bold text-[#2D3748]">{s.title}</span>
            {s.is_selected && <span className="bg-[#E8F0E1] text-[#4F6B3B] rounded-full px-2 py-0.5 text-[10px] font-bold">مختار</span>}
            <span className="text-[10px] text-[#8A9AB0] font-mono">source={s.source}</span>
          </div>
          <div className="text-xs text-[#5A677D]">{s.summary_preview}...</div>
        </div>
      ))}
    </div>
  );
}

function OutProduction({ o }) {
  return (
    <div className="space-y-2 text-sm">
      <div className="grid grid-cols-3 gap-2">
        <Stat label="المشاهد" value={o.scene_count} />
        <Stat label="صفحات الكتاب" value={o.book_pages_count} />
        <Stat label="شخصيات" value={o.character_profiles_count} />
      </div>
      <div className="bg-white rounded-xl p-3 border border-[#E2D8C9] text-xs text-[#2D3748]">
        <div><b>العنوان:</b> {o.title || "—"}</div>
        <div className="text-[#5A677D] mt-1">{o.story_summary_preview}</div>
        <div className="text-[#87A96B] mt-1">رسالة: {o.main_message_preview}</div>
      </div>
      {o.cover_prompt_preview && (
        <details className="cursor-pointer">
          <summary className="text-[11px] font-bold text-[#5A677D]">Cover Prompt</summary>
          <pre className="mt-1 bg-white rounded-xl p-2 border border-[#E2D8C9] font-mono text-[10px] whitespace-pre-wrap">{o.cover_prompt_preview}</pre>
        </details>
      )}

      {/* Phase D.4 — story-level downstream fields */}
      {(o.story_keywords?.length || o.story_music_prompt || o.story_voice_prompt) && (
        <div className="bg-[#F8F1E7] rounded-xl p-3 border border-[#D4A373]/40" data-testid="production-story-level">
          <div className="text-[11px] font-bold text-[#8B5A2B] mb-1.5">Story-level downstream (Phase D.4)</div>
          {o.story_keywords?.length > 0 && (
            <div className="flex flex-wrap gap-1 mb-2">
              {o.story_keywords.map((k, i) => (
                <span key={i} className="text-[10px] bg-white text-[#8B5A2B] rounded px-1.5 py-0.5 border border-[#D4A373]/30">{k}</span>
              ))}
            </div>
          )}
          {o.story_music_prompt && (
            <div className="text-[11px] text-[#2D3748] mb-1"><b>Music:</b> {o.story_music_prompt}</div>
          )}
          {o.story_music_keywords?.length > 0 && (
            <div className="text-[10px] text-[#8A9AB0] mb-1">music tags: {o.story_music_keywords.join(", ")}</div>
          )}
          {o.story_voice_prompt && (
            <div className="text-[11px] text-[#2D3748]"><b>Voice:</b> {o.story_voice_prompt}</div>
          )}
        </div>
      )}

      {/* Phase D.4 — per-scene downstream fields */}
      {o.scenes_detail?.length > 0 && (
        <details className="cursor-pointer" data-testid="production-scenes-detail">
          <summary className="text-[11px] font-bold text-[#5A677D]">Per-scene downstream package ({o.scenes_detail.length})</summary>
          <div className="mt-2 space-y-2">
            {o.scenes_detail.map((s) => (
              <div key={s.scene_index} className="bg-white rounded-xl p-2 border border-[#E2D8C9] text-[11px]">
                <div className="flex items-center gap-2 mb-1 flex-wrap">
                  <span className="bg-[#87A96B] text-white rounded-full w-5 h-5 grid place-content-center text-[10px] font-bold">{s.scene_index}</span>
                  <span className="font-bold">{s.title}</span>
                  {s.estimated_duration_seconds && <span className="text-[9px] text-[#8A9AB0]">~{s.estimated_duration_seconds}s</span>}
                  <span className="text-[9px] text-[#8A9AB0]">{s.word_count} words</span>
                </div>
                {s.scene_goal && <div className="text-[10px] text-[#5A677D] mb-1">🎯 {s.scene_goal}</div>}
                <div className="text-[10px] text-[#2D3748] mb-1"><b>نص السرد:</b> {s.narration_preview}...</div>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-1 mt-1 font-mono">
                  {s.video_prompt && <div className="bg-[#FDFBF7] rounded p-1 text-[9px]" title={s.video_prompt}><b>🎬 video:</b> {s.video_prompt.slice(0, 80)}...</div>}
                  {s.voice_prompt && <div className="bg-[#FDFBF7] rounded p-1 text-[9px]" title={s.voice_prompt}><b>🎙️ voice:</b> {s.voice_prompt.slice(0, 80)}...</div>}
                  {s.music_prompt && <div className="bg-[#FDFBF7] rounded p-1 text-[9px]" title={s.music_prompt}><b>🎵 music:</b> {s.music_prompt.slice(0, 80)}...</div>}
                </div>
                {(s.music_keywords?.length > 0 || s.key_objects?.length > 0) && (
                  <div className="flex gap-1 mt-1 flex-wrap text-[9px]">
                    {s.music_keywords?.map((k, i) => <span key={`m${i}`} className="bg-[#E8F0E1] text-[#4F6B3B] rounded px-1">♪ {k}</span>)}
                    {s.key_objects?.map((k, i) => <span key={`o${i}`} className="bg-[#F8F1E7] text-[#8B5A2B] rounded px-1">⊙ {k}</span>)}
                  </div>
                )}
              </div>
            ))}
          </div>
        </details>
      )}

      <KeyValueTable obj={{ style_guide: o.style_guide, production_approved: o.production_approved }} />
    </div>
  );
}

function OutExtraCharacters({ o }) {
  const chars = o.characters || [];
  if (chars.length === 0) {
    return <div className="text-[11px] text-[#8A9AB0]">لا توجد شخصيات ظاهرة مرفوعة (إما غير ظاهرة أو بدون صورة)</div>;
  }
  return (
    <div className="space-y-3" data-testid="storyboard-extra-characters-output">
      <div className="text-[11px] text-[#5A677D]">
        عدد الشخصيات المؤهَّلة: <b>{chars.length}</b>
        {o.any_mock && <span className="mx-2 bg-[#F8F1E7] text-[#8B5A2B] rounded px-1 text-[10px]">يوجد MOCK</span>}
        {o.any_fallback && <span className="mx-2 bg-[#FCE6D4] text-[#B8612F] rounded px-1 text-[10px]">يوجد fallback</span>}
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {chars.map((c) => (
          <div key={c.character_index} className="bg-white rounded-xl p-3 border border-[#E2D8C9]" data-testid={`extra-char-${c.character_index}`}>
            <div className="flex items-center gap-2 mb-2 flex-wrap">
              <span className="bg-[#87A96B] text-white rounded-full w-6 h-6 grid place-content-center text-[10px] font-bold">{c.character_index + 1}</span>
              <span className="font-heading font-bold text-[#2D3748]">
                {c.name || c.type}
              </span>
              <span className="text-[10px] text-[#8A9AB0] font-mono">{c.type}</span>
              {c.status === "completed" && !c.mock && (
                <span className="bg-[#DEEBCF] text-[#3F5B2E] rounded-full px-2 py-0.5 text-[10px] font-bold">REAL</span>
              )}
              {c.mock && (
                <span className="bg-[#F8F1E7] text-[#8B5A2B] rounded-full px-2 py-0.5 text-[10px] font-bold">MOCK</span>
              )}
              {c.fallback_used && (
                <span className="bg-[#FCE6D4] text-[#B8612F] rounded-full px-2 py-0.5 text-[10px] font-bold">fallback</span>
              )}
              {c.status === "pending" && (
                <span className="bg-[#F8F1E7] text-[#8B5A2B] rounded-full px-2 py-0.5 text-[10px] font-bold">pending</span>
              )}
            </div>
            <div className="grid grid-cols-2 gap-2">
              <div>
                <div className="text-[10px] text-[#8A9AB0] mb-1">الصورة المرفوعة</div>
                {c.source_image_url ? (
                  <img src={fileSrc(c.source_image_url)} alt="src" className="w-full aspect-square rounded-lg object-cover border border-[#E2D8C9]" />
                ) : <div className="w-full aspect-square rounded-lg bg-[#F2E8DA] grid place-content-center text-[10px] text-[#8A9AB0]">لا توجد</div>}
              </div>
              <div>
                <div className="text-[10px] text-[#8A9AB0] mb-1">الشخصية المُولَّدة</div>
                {c.generated_image_url ? (
                  <img src={fileSrc(c.generated_image_url)} alt="gen" className="w-full aspect-square rounded-lg object-cover border border-[#E2D8C9]" />
                ) : <div className="w-full aspect-square rounded-lg bg-[#F2E8DA] grid place-content-center text-[10px] text-[#8A9AB0] text-center px-1">لم تُولَّد بعد</div>}
              </div>
            </div>
            <div className="mt-2 text-[10px] text-[#5A677D] font-mono space-y-0.5">
              {c.provider && <div>provider: {c.provider}/{c.model_name}</div>}
              {c.prompt_hash && <div>prompt: {c.prompt_hash.split(":")[1]?.slice(0, 12)}...</div>}
              {c.auto_visual_description && (
                <details className="mt-1 cursor-pointer">
                  <summary className="text-[#5A677D]">وصف بصري (vision)</summary>
                  <p className="mt-1 text-[10px] text-[#2D3748] whitespace-pre-wrap">{c.auto_visual_description}</p>
                </details>
              )}
              {c.error_message && <div className="text-[#B8612F] mt-1">{c.error_message}</div>}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function OutChildCharacter({ o, stage }) {
  return (
    <div className="space-y-3" data-testid="storyboard-child-character-output">
      <div className="grid grid-cols-2 gap-3">
        <div>
          <div className="text-[10px] text-[#8A9AB0] mb-1">الصورة الأصلية</div>
          {stage.input_summary?.source_image_url ? (
            <img src={fileSrc(stage.input_summary.source_image_url)} alt="source" className="w-full max-w-[180px] rounded-xl object-cover border border-[#E2D8C9]" />
          ) : <div className="w-full max-w-[180px] h-40 rounded-xl bg-[#F2E8DA] grid place-content-center text-[10px] text-[#8A9AB0]">لا توجد</div>}
        </div>
        <div>
          <div className="text-[10px] text-[#8A9AB0] mb-1">
            الشخصية المُولَّدة{" "}
            {o.mock ? (
              <span className="bg-[#F8F1E7] text-[#8B5A2B] rounded px-1 text-[9px]">MOCK</span>
            ) : o.generated_image_url ? (
              <span className="bg-[#DEEBCF] text-[#3F5B2E] rounded px-1 text-[9px]">REAL</span>
            ) : null}
          </div>
          {o.generated_image_url ? (
            <img src={fileSrc(o.generated_image_url)} alt="generated" className="w-full max-w-[180px] rounded-xl object-cover border border-[#E2D8C9]" />
          ) : <div className="w-full max-w-[180px] h-40 rounded-xl bg-[#F2E8DA] grid place-content-center text-[10px] text-[#8A9AB0]">غير مُولَّدة</div>}
        </div>
      </div>
      <KeyValueTable obj={{ provider: o.provider, model_name: o.model_name, mock: o.mock, fallback_used: o.fallback_used }} />
    </div>
  );
}

function OutSceneImages({ o }) {
  return (
    <div className="space-y-2">
      <div className="text-[11px] text-[#5A677D] flex items-center gap-3 flex-wrap">
        <span>تم توليد <b>{o.scene_count_generated}</b> مشهد</span>
        <span>·</span>
        <span className={o.fallback_count > 0 ? "text-[#B8612F]" : ""}>fallback: {o.fallback_count}</span>
        <span>·</span>
        <span data-testid="storyboard-refs-injected-total">
          مراجع مُحقَّنة: <b>{o.references_total_injected || 0}</b>
        </span>
        <span data-testid="storyboard-refs-used-scenes">
          (في {o.references_used_scene_count || 0} مشهد)
        </span>
        {o.references_skipped_total > 0 && (
          <span className="text-[#8B5A2B]" data-testid="storyboard-refs-skipped-total">
            تخطٍّ: {o.references_skipped_total}
          </span>
        )}
      </div>
      {o.cover && (
        <div className="bg-white rounded-xl p-2 border border-[#E2D8C9] flex gap-2">
          <img src={fileSrc(o.cover.image_url)} alt="cover" className="w-20 h-20 rounded-lg object-cover" />
          <div className="text-[11px]">
            <div className="font-bold">الغلاف</div>
            <div className="text-[#8A9AB0] font-mono">provider: {o.cover.provider}</div>
            <div className="text-[10px] text-[#5A677D] line-clamp-2 mt-1">{o.cover.prompt_preview}</div>
          </div>
        </div>
      )}
      <div className="grid grid-cols-2 md:grid-cols-3 gap-2" data-testid="storyboard-scene-grid">
        {(o.scenes || []).map((s) => (
          <div key={s.scene_index} className={`bg-white rounded-xl p-2 border ${s.fallback_used ? "border-[#E07A5F]/50" : "border-[#E2D8C9]"}`} data-testid={`storyboard-scene-${s.scene_index}`}>
            <div className="aspect-square rounded-lg overflow-hidden bg-[#F2E8DA] mb-2 relative">
              {s.image_url && <img src={fileSrc(s.image_url)} alt={`scene ${s.scene_index}`} className="w-full h-full object-cover" />}
              <span className="absolute top-1 right-1 bg-[#87A96B] text-white rounded-full w-6 h-6 grid place-content-center text-[10px] font-bold">{s.scene_index}</span>
              {s.fallback_used && <span className="absolute bottom-1 right-1 bg-[#FCE6D4] text-[#B8612F] rounded px-1 text-[9px] font-bold">fallback</span>}
              {s.references?.used && (
                <span className="absolute top-1 left-1 bg-[#DEEBCF] text-[#3F5B2E] rounded px-1 text-[9px] font-bold" data-testid={`scene-refs-badge-${s.scene_index}`}>
                  refs×{s.references.injected_count}
                </span>
              )}
            </div>
            <div className="text-[10px] font-bold text-[#2D3748] truncate">{s.scene_title || "—"}</div>
            <div className="text-[9px] text-[#8A9AB0] font-mono flex items-center gap-1 flex-wrap">
              <span>{s.provider}</span>
              <span>·</span>
              <span>{fmtMs(s.latency_ms_estimate)}</span>
              <span>·</span>
              <span>x{s.attempts || 0}</span>
              {s.prompt_hash && <span title={s.prompt_hash} className="inline-flex items-center gap-0.5"><Hash className="w-2 h-2" />{s.prompt_hash.split(":")[1]?.slice(0, 6)}</span>}
            </div>
            <details className="mt-1 cursor-pointer">
              <summary className="text-[9px] text-[#5A677D]">prompt</summary>
              <p className="text-[9px] font-mono text-[#2D3748] mt-1 max-h-20 overflow-auto">{s.prompt_preview}</p>
            </details>
            {/* Phase E — Reference panel */}
            {s.references && (
              <details className="mt-1 cursor-pointer" data-testid={`scene-refs-panel-${s.scene_index}`}>
                <summary className="text-[9px] text-[#5A677D]">
                  مراجع: مُحقَّنة <b>{s.references.injected_count}</b>
                  {" · "}متاحة (طفل:{s.references.available?.child ? "✓" : "—"} / إضافيين:{(s.references.available?.extras || []).length} / لعبة:{s.references.available?.toy ? "✓" : "—"})
                </summary>
                <div className="mt-1 space-y-1 text-[9px]">
                  <div className="flex flex-wrap gap-1">
                    {s.references.child_used && (
                      <span className="bg-[#DEEBCF] text-[#3F5B2E] rounded px-1 font-bold">child ✓</span>
                    )}
                    {(s.references.extra_indexes_used || []).map((idx) => (
                      <span key={`x${idx}`} className="bg-[#DEEBCF] text-[#3F5B2E] rounded px-1 font-bold">extra#{idx} ✓</span>
                    ))}
                    {s.references.toy_used && (
                      <span className="bg-[#DEEBCF] text-[#3F5B2E] rounded px-1 font-bold">toy ✓</span>
                    )}
                    {!s.references.used && s.references.attempted && (
                      <span className="bg-[#FCE6D4] text-[#B8612F] rounded px-1 font-bold">references attempted but not used</span>
                    )}
                  </div>
                  {s.references.fallback_path && (
                    <div className="text-[#8B5A2B]">
                      fallback: <b>{s.references.fallback_path}</b>
                      {s.references.fallback_reason && <> · {s.references.fallback_reason}</>}
                    </div>
                  )}
                  {(s.references.skipped_reasons || []).length > 0 && (
                    <div>
                      <div className="text-[#5A677D] font-bold">تخطٍّ ({s.references.skipped_reasons.length}):</div>
                      <ul className="space-y-0.5 mt-0.5">
                        {s.references.skipped_reasons.map((r, i) => (
                          <li key={i} className="bg-[#FDFBF7] rounded px-1 py-0.5 border border-[#E2D8C9]">
                            <span className="text-[#8A9AB0]">[{r.kind}]</span>{" "}
                            <span className="text-[#2D3748]">{r.name || r.id || "—"}</span>{" → "}
                            <span className="text-[#B8612F] font-mono">{r.reason}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              </details>
            )}
            {s.error_message && <div className="text-[9px] text-[#B8612F] mt-1">{s.error_message}</div>}
          </div>
        ))}
      </div>
    </div>
  );
}

function OutNarration({ o }) {
  return (
    <div className="space-y-2">
      <div className="text-[11px] text-[#5A677D]">
        عدد: <b>{o.count}</b> · إجمالي المدة: <b>{o.total_duration_seconds?.toFixed?.(1) || o.total_duration_seconds}s</b>
        {o.all_mocked && <span className="mx-2 bg-[#F8F1E7] text-[#8B5A2B] rounded px-1 text-[10px]">ALL MOCKED</span>}
      </div>
      <div className="space-y-1">
        {(o.items || []).map((n) => (
          <div key={n.scene_index} className="bg-white rounded-xl p-2 border border-[#E2D8C9] text-xs" data-testid={`storyboard-narration-${n.scene_index}`}>
            <div className="flex items-center gap-2 mb-1 flex-wrap">
              <span className="bg-[#D4A373] text-white rounded-full w-5 h-5 grid place-content-center text-[10px] font-bold">{n.scene_index}</span>
              <span className="text-[10px] text-[#8A9AB0] font-mono">{n.provider} · {n.voice_type} · {n.language} · ~{n.duration_seconds}s</span>
              {n.audio_url && <audio controls src={fileSrc(n.audio_url)} className="h-7" />}
              {!n.audio_url && <span className="text-[10px] text-[#B8612F]">(mocked — no audio file)</span>}
            </div>
            <p className="text-[#2D3748] text-[11px]">{n.text_preview}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

function OutBookAssets({ o }) {
  return (
    <div className="space-y-2">
      <div className="text-[11px] text-[#5A677D]">صفحات: <b>{o.page_count}</b> · إعادة استخدام: <b>{o.reused_from_scenes}</b></div>
      <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
        {(o.items || []).map((b) => (
          <div key={b.page_number} className="bg-white rounded-xl p-2 border border-[#E2D8C9] text-[10px]" data-testid={`storyboard-book-${b.page_number}`}>
            <div className="flex items-center gap-1 mb-1">
              <span className="bg-[#D4A373] text-white rounded-full w-5 h-5 grid place-content-center text-[10px] font-bold">{b.page_number}</span>
              <span className="text-[9px] text-[#8A9AB0] font-mono">{b.provider}</span>
            </div>
            {b.illustration_url && <img src={fileSrc(b.illustration_url)} alt="" className="w-full aspect-video rounded-md object-cover" />}
            <p className="mt-1 text-[#2D3748]">{b.text_preview}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

function OutVideo({ o }) {
  if (!o.video_url) return <div className="text-[11px] text-[#8A9AB0]">لم يتم التجميع بعد</div>;
  return (
    <div className="space-y-2">
      <video controls poster={o.thumbnail_url ? fileSrc(o.thumbnail_url) : undefined} src={fileSrc(o.video_url)} className="w-full max-w-md rounded-xl border border-[#E2D8C9]" data-testid="storyboard-video-player" />
      <KeyValueTable obj={{ duration_seconds: o.duration_seconds, audio_background_mode: o.audio_background_mode, provider: o.provider, assembly_metadata: o.assembly_metadata }} />
    </div>
  );
}

function OutPDF({ o }) {
  if (!o.pdf_url) return <div className="text-[11px] text-[#8A9AB0]">لم يتم التجميع بعد</div>;
  return (
    <div className="space-y-2">
      <a href={fileSrc(o.pdf_url)} target="_blank" rel="noreferrer" className="inline-flex items-center gap-2 bg-[#E8F0E1] text-[#4F6B3B] rounded-xl px-3 py-2 text-sm font-bold" data-testid="storyboard-pdf-link">
        <FileText className="w-4 h-4" /> افتح الكتاب (PDF) — {o.page_count} صفحة
      </a>
      <KeyValueTable obj={{ page_count: o.page_count, provider: o.provider, assembly_metadata: o.assembly_metadata }} />
    </div>
  );
}

function Stat({ label, value }) {
  return (
    <div className="rounded-xl px-3 py-2 border text-center bg-white border-[#E2D8C9]">
      <div className="text-[10px] font-body text-[#8A9AB0]">{label}</div>
      <div className="font-heading font-bold text-lg text-[#2D3748]">{value ?? "—"}</div>
    </div>
  );
}
