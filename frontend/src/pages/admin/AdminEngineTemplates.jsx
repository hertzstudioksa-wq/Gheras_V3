import React, { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { AlertTriangle, Eye, RotateCcw, Save } from "lucide-react";
import { api } from "../../lib/api";
import { Badge, Panel, errText, inputCls } from "./engineUi";

// The user-message templates generation actually reads (audit AF-3): scenario
// request, production-plan request and the child's character sheet. $variables
// come from the order; a template with a variable the code doesn't provide
// would be skipped silently at run time, so saving one is refused.

export function TemplatesTab() {
  const [items, setItems] = useState(null);
  const reload = () => api.get("/admin/engine/prompt-templates", { timeout: 30000 })
    .then((r) => setItems(r.data)).catch(() => setItems([]));
  useEffect(() => { reload(); }, []);
  if (!items) return <p className="font-body text-[#8A9AB0]">جاري التحميل…</p>;
  return (
    <div className="space-y-4" data-testid="engine-templates">
      <p className="font-body text-sm text-[#5A677D] max-w-3xl">
        الرسالة اللي بتتبعت للموديل مع برومبت النظام، ومليانة ببيانات الطلب عن طريق المتغيرات (<span dir="ltr">$child_name</span> وهكذا).
        من غير قالب مفعّل، الكود هو اللي بيكتب الرسالة. المعاينة بتستخدم {items[0]?.sample_order_id ? "آخر طلب اتختار له سيناريو" : "طلب تجريبي متخيَّل"}.
      </p>
      {items.map((t) => <TemplateCard key={t.stage} t={t} onChanged={reload} />)}
    </div>
  );
}

function TemplateCard({ t, onChanged }) {
  const startText = t.active?.template_text || t.versions?.[0]?.template_text || "";
  const [text, setText] = useState(startText);
  const [preview, setPreview] = useState(null);
  const [busy, setBusy] = useState(false);
  const ref = useRef(null);
  useEffect(() => { setText(t.active?.template_text || t.versions?.[0]?.template_text || ""); setPreview(null); }, [t]);
  const dirty = text !== (t.active?.template_text || "");

  const insertVar = (v) => {
    const el = ref.current;
    const token = `$${v}`;
    if (!el) { setText((x) => x + token); return; }
    const { selectionStart: a, selectionEnd: b } = el;
    setText((x) => x.slice(0, a) + token + x.slice(b));
    requestAnimationFrame(() => { el.focus(); el.selectionStart = el.selectionEnd = a + token.length; });
  };

  const run = async (fn, ok) => {
    setBusy(true);
    try { await fn(); if (ok) toast.success(ok); onChanged(); }
    catch (e) { toast.error(errText(e)); }
    finally { setBusy(false); }
  };

  const doPreview = async () => {
    try {
      const { data } = await api.post(`/admin/engine/prompt-templates/${t.stage}/preview`, { template_text: text });
      setPreview(data);
    } catch (e) { toast.error(errText(e, "تعذّرت المعاينة")); }
  };

  return (
    <Panel>
      <div className="flex items-center justify-between gap-3 flex-wrap mb-1">
        <div className="flex items-center gap-2 flex-wrap">
          <h3 className="font-heading text-lg font-bold text-[#2D3748]">{t.name_ar}</h3>
          {t.active ? <Badge tone="green">نسخة الأدمن {t.active.version}</Badge> : <Badge>الكود بيكتبها</Badge>}
          {t.active_broken && <Badge tone="red">مش بتشتغل</Badge>}
        </div>
        <span className="font-body text-xs text-[#8A9AB0]">{text.length.toLocaleString("ar-EG")} حرف</span>
      </div>
      <p className="font-body text-xs text-[#5A677D] mb-3">{t.purpose_ar}</p>
      {t.active_broken && (
        <p className="font-body text-xs text-[#B8612F] font-bold mb-3 inline-flex items-center gap-1">
          <AlertTriangle className="w-3.5 h-3.5" />
          النسخة المفعّلة فيها متغيرات مش موجودة ({t.active_unknown_vars.map((v) => `$${v}`).join("، ")})، فالتوليد بيتجاهلها وبيبعت نص الكود.
        </p>
      )}

      <div className="mb-2 flex flex-wrap gap-1.5" aria-label="المتغيرات المتاحة">
        {t.variables.map((v) => (
          <button key={v} type="button" onClick={() => insertVar(v)} title={t.sample?.[v] || ""}
            className="rounded-full bg-[#F8F1E7] hover:bg-[#F2E8DA] px-2.5 py-0.5 text-[11px] font-mono text-[#8B5A2B]" dir="ltr">
            ${v}
          </button>
        ))}
      </div>
      <textarea ref={ref} rows={14} value={text} onChange={(e) => { setText(e.target.value); setPreview(null); }}
        dir="auto" className={`${inputCls} leading-relaxed`} data-testid={`template-text-${t.stage}`}
        placeholder="اكتب القالب هنا، ودوس على أي متغير فوق عشان يتحط مكان المؤشر" />

      <div className="flex gap-2 flex-wrap mt-3">
        <button onClick={doPreview} disabled={!text.trim()}
          className="inline-flex items-center gap-1 rounded-2xl bg-white border border-[#E2D8C9] px-4 py-2 text-sm font-body font-bold text-[#5A677D] hover:border-[#87A96B] disabled:opacity-50"
          data-testid={`template-preview-${t.stage}`}>
          <Eye className="w-4 h-4" /> معاينة
        </button>
        <button disabled={!dirty || busy || text.trim().length < 50}
          onClick={() => run(() => api.post(`/admin/engine/prompt-templates/${t.stage}`, { template_text: text, activate: true }), "اتحفظت نسخة جديدة واتفعّلت")}
          className="btn-primary inline-flex items-center gap-2 disabled:opacity-50" data-testid={`template-save-${t.stage}`}>
          <Save className="w-4 h-4" /> حفظ كنسخة جديدة وتفعيلها
        </button>
        {t.active && (
          <button disabled={busy}
            onClick={() => window.confirm("ترجع لنص الكود؟ نسخك هتفضل في السجل.") &&
              run(() => api.post(`/admin/engine/prompt-templates/${t.stage}/reset`), "الكود هو اللي بيكتب الرسالة دلوقتي")}
            className="inline-flex items-center gap-1 rounded-2xl bg-white border border-[#E2D8C9] px-4 py-2 text-sm font-body font-bold text-[#5A677D]">
            <RotateCcw className="w-4 h-4" /> رجوع لنص الكود
          </button>
        )}
      </div>

      {preview && (
        <div className="mt-3">
          {preview.unknown_vars?.length ? (
            <p className="font-body text-sm text-[#B8612F] font-bold">متغيرات مش موجودة: {preview.unknown_vars.map((v) => `$${v}`).join("، ")}</p>
          ) : (
            <pre dir="auto" className="whitespace-pre-wrap bg-[#FDFBF7] border border-[#E2D8C9] rounded-2xl p-4 text-xs max-h-80 overflow-y-auto font-body">{preview.rendered}</pre>
          )}
        </div>
      )}

      <details className="mt-4">
        <summary className="font-body text-xs font-bold text-[#5A677D] cursor-pointer">النص اللي الكود بيكتبه لو مفيش قالب</summary>
        <pre dir="auto" className="whitespace-pre-wrap bg-[#FDFBF7] border border-[#E2D8C9] rounded-2xl p-4 text-xs max-h-80 overflow-y-auto font-body mt-2">{t.code_default_preview}</pre>
      </details>
      {t.versions?.length > 0 && (
        <details className="mt-2">
          <summary className="font-body text-xs font-bold text-[#5A677D] cursor-pointer">النسخ ({t.versions.length})</summary>
          <div className="mt-2 space-y-1.5">
            {t.versions.map((v) => (
              <div key={v.id} className="flex items-center justify-between gap-2 bg-[#FDFBF7] border border-[#E2D8C9] rounded-xl px-3 py-2">
                <span className="font-body text-xs text-[#5A677D]">
                  نسخة {v.version} • {v.created_at ? new Date(v.created_at).toLocaleString("ar-EG") : ""}{v.created_by ? ` • ${v.created_by}` : ""}
                </span>
                <span className="flex items-center gap-2">
                  <button onClick={() => { setText(v.template_text); setPreview(null); }} className="text-xs font-body font-bold text-[#5A677D]">افتح</button>
                  {v.active ? <Badge tone="green">مفعّلة</Badge> : (
                    <button disabled={busy}
                      onClick={() => run(() => api.post(`/admin/engine/prompt-templates/${t.stage}/activate/${v.id}`), `نسخة ${v.version} اتفعّلت`)}
                      className="text-xs font-body font-bold text-[#4F6B3B]">تفعيل</button>
                  )}
                </span>
              </div>
            ))}
          </div>
        </details>
      )}
    </Panel>
  );
}
