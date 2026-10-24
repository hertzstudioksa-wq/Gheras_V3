import React, { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { Beaker, Clock, Save } from "lucide-react";
import { api, fileSrc } from "../../lib/api";
import OrderStatusBadge from "../../components/gheras/OrderStatusBadge";
import { AdminPage, ConfirmAction, PageState } from "../../components/admin/AdminKit";
import { STATUS_LABELS, formatDate } from "../../lib/orderStatus";
import AdminStoryboard from "./AdminStoryboard";
import OrderPromptPreview from "./OrderPromptPreview";
import { AdminMediaTab, AdminPricingTab, AdminProductionTab, AdminScenariosTab, Field } from "./orders/OrderTabs";

// The full order page (M5, replaces the orders modal and the separate
// Storyboard page): one URL per order, tabs in the URL (?tab=) so any tab can
// be linked to, and a status override that asks for a reason.

const TABS = [
  { k: "summary", l: "ملخص" },
  { k: "scenarios", l: "السيناريوهات" },
  { k: "production", l: "خطة الإنتاج" },
  { k: "media", l: "الوسائط والتسليم" },
  { k: "trace", l: "تتبّع الإنتاج" },
  { k: "prompt", l: "البرومبت الفعلي" },
  { k: "cost", l: "التكلفة" },
  { k: "history", l: "السجل" },
];

export default function OrderDetailPage() {
  const { orderId } = useParams();
  const [params, setParams] = useSearchParams();
  const tab = TABS.some((t) => t.k === params.get("tab")) ? params.get("tab") : "summary";
  const [order, setOrder] = useState(null);
  const [error, setError] = useState(null);
  const [scenariosData, setScenariosData] = useState(null);
  const pollRef = useRef(null);

  const load = useCallback(() => {
    setError(null);
    return api.get(`/admin/orders/${orderId}`).then((r) => setOrder(r.data))
      .catch((e) => setError(e?.response?.status === 404 ? "الطلب مش موجود" : "تعذّر تحميل الطلب"));
  }, [orderId]);
  const loadScenarios = useCallback(() => api.get(`/admin/orders/${orderId}/scenarios`)
    .then((r) => setScenariosData(r.data))
    .catch(() => setScenariosData({ scenarios: [], generation: null, selected_scenario_id: null })), [orderId]);

  useEffect(() => {
    load();
    loadScenarios();
    return () => clearInterval(pollRef.current);
  }, [load, loadScenarios]);

  const regenerateScenarios = async () => {
    try {
      await api.post(`/admin/orders/${orderId}/scenarios/regenerate`);
      toast.success("جاري إعادة توليد السيناريوهات…");
      setScenariosData({ scenarios: [], generation: null, selected_scenario_id: null });
      let i = 0;
      clearInterval(pollRef.current);
      pollRef.current = setInterval(async () => {
        i += 1;
        const { data } = await api.get(`/admin/orders/${orderId}/scenarios`).catch(() => ({ data: null }));
        if (data) setScenariosData(data);
        if ((data?.scenarios?.length || 0) > 0 || i > 24) clearInterval(pollRef.current);
      }, 2500);
    } catch (e) { toast.error(e?.response?.data?.detail || "فشل"); }
  };

  const selectScenario = async (sid) => {
    try {
      await api.post(`/admin/orders/${orderId}/scenarios/${sid}/select`);
      toast.success("اتختار نيابة عن العميل — خطة الإنتاج بدأت");
      loadScenarios();
      load();
    } catch (e) { toast.error(e?.response?.data?.detail || "فشل"); }
  };

  const deleteScenarios = async () => {
    try {
      await api.delete(`/admin/orders/${orderId}/scenarios`);
      toast.success("السيناريوهات اتمسحت");
      loadScenarios();
    } catch (e) { toast.error(e?.response?.data?.detail || "فشل"); }
  };

  const setTab = (k) => setParams(k === "summary" ? {} : { tab: k }, { replace: true });

  if (!order) {
    return <PageState loading={!error} error={error} onRetry={load} />;
  }

  const child = order.data?.child || {};
  return (
    <AdminPage
      title={`قصة ${child.name || "—"}`}
      description={`${order.user_name || order.user_email || ""}${order.user_name ? ` • ${order.user_email}` : ""} • ${formatDate(order.created_at)}`}
      back={{ to: "/admin/orders", label: "كل الطلبات" }}
      actions={<>
        <OrderStatusBadge status={order.status} />
        <Link to={`/admin/lab?order=${order.id}`} title="جرّب مرحلة على بيانات الطلب ده"
          className="rounded-full bg-white border border-[#E2D8C9] px-3 py-1.5 text-xs font-body font-bold text-[#5A677D] inline-flex items-center gap-1">
          <Beaker className="w-3.5 h-3.5" /> المختبر
        </Link>
        <StatusOverride order={order} onDone={load} />
      </>}
      testId="order-page"
    >
      <div className="flex gap-1 mb-5 border-b border-[#E2D8C9] overflow-x-auto" role="tablist">
        {TABS.map((t) => (
          <button key={t.k} role="tab" aria-selected={tab === t.k} onClick={() => setTab(t.k)}
            className={`px-4 py-2 text-sm font-body font-bold border-b-2 whitespace-nowrap ${
              tab === t.k ? "border-[#87A96B] text-[#4F6B3B]" : "border-transparent text-[#8A9AB0] hover:text-[#5A677D]"
            }`} data-testid={`order-tab-${t.k}`}>
            {t.l}
          </button>
        ))}
      </div>

      <div className={tab === "trace" ? "" : "bg-white rounded-3xl border border-[#E2D8C9] p-4 md:p-6"}>
        {tab === "summary" && <Summary order={order} onSaved={load} />}
        {tab === "scenarios" && (
          <AdminScenariosTab scenariosData={scenariosData} onRegenerate={regenerateScenarios}
            onDelete={() => window.confirm("تمسح كل السيناريوهات؟") && deleteScenarios()} onSelect={selectScenario} />
        )}
        {tab === "production" && <AdminProductionTab orderId={orderId} />}
        {tab === "media" && <AdminMediaTab orderId={orderId} />}
        {tab === "trace" && <AdminStoryboard embedded />}
        {tab === "prompt" && <OrderPromptPreview orderId={orderId} />}
        {tab === "cost" && <AdminPricingTab orderId={orderId} />}
        {tab === "history" && <History order={order} />}
      </div>
    </AdminPage>
  );
}

function Summary({ order, onSaved }) {
  const [note, setNote] = useState(order.admin_note || "");
  const [busy, setBusy] = useState(false);
  const d = order.data || {};
  const e = order.enriched || {};
  const saveNote = async () => {
    setBusy(true);
    try {
      await api.patch(`/admin/orders/${order.id}/note`, { admin_note: note });
      toast.success("الملاحظة اتحفظت");
      onSaved();
    } catch (err) { toast.error(err?.response?.data?.detail || "فشل"); }
    finally { setBusy(false); }
  };
  const review = async (decision, reason) => {
    try {
      await api.post(`/admin/orders/${order.id}/safety-review`, { decision, reason });
      toast.success(decision === "approve" ? "اتوافق — العميل يقدر يعتمد الخطة" : "اتوقف الطلب");
      onSaved();
    } catch (err) { toast.error(err?.response?.data?.detail || "فشل"); }
  };
  return (
    <div data-testid="order-summary">
      {order.safety_flag && !order.safety_review && (
        <div className="bg-[#FBEFD5] border border-[#D4A373]/50 rounded-2xl p-4 mb-4 font-body" data-testid="safety-review-banner">
          <div className="font-bold text-[#8B5A2B] mb-1">الخطة فيها موضوع حسّاس — محتاجة مراجعتك</div>
          <p className="text-sm text-[#5A677D] mb-3">
            موديل الخطة علّم القصة «للمراجعة». العميل مش هيقدر يعتمدها لحد ما توافق. اقرأ الخطة في تبويب «خطة الإنتاج» الأول.
          </p>
          <div className="flex gap-2 flex-wrap">
            <ConfirmAction title="توافق على الخطة؟" description="العميل هيقدر يعتمدها ويبدأ الرسم. اكتب سبب الموافقة."
              requireReason tone="cost" confirmLabel="موافقة" onConfirm={(r) => review("approve", r)}
              className="rounded-full bg-[#87A96B] text-white px-4 py-1.5 text-sm font-bold">موافقة</ConfirmAction>
            <ConfirmAction title="توقف الطلب؟" description="الطلب هيتحوّل لفشل. لو كان مدفوع رجّع المبلغ لرصيده من تبويب التكلفة. اكتب السبب."
              requireReason confirmLabel="وقّف الطلب" onConfirm={(r) => review("reject", r)}
              className="rounded-full bg-[#FCE6D4] text-[#B8612F] px-4 py-1.5 text-sm font-bold">رفض</ConfirmAction>
          </div>
        </div>
      )}
      {order.safety_review && (
        <div className="bg-[#FDFBF7] border border-[#E2D8C9] rounded-2xl p-3 mb-4 font-body text-sm text-[#5A677D]">
          مراجعة السلامة: <b>{order.safety_review.decision === "approve" ? "موافقة" : "رفض"}</b> — {order.safety_review.reason}
          {" "}({order.safety_review.by}، {formatDate(order.safety_review.at)})
        </div>
      )}
      {order.safety && order.safety.checked === false && (
        <div className="bg-[#FDFBF7] border border-dashed border-[#E2D8C9] rounded-2xl p-3 mb-4 font-body text-xs text-[#8A9AB0]">
          فحص نص ولي الأمر ما اشتغلش وقت الطلب (المزوّد ما ردّش) — اقرأ الموقف والملاحظات بنفسك.
        </div>
      )}
      <div className="flex gap-4 items-start flex-wrap mb-4">
        {d.child?.image_url && (
          <img src={fileSrc(d.child.image_url)} alt="" className="w-24 h-24 rounded-2xl object-cover border border-[#E2D8C9]" />
        )}
        <div className="grid grid-cols-2 md:grid-cols-3 gap-2 flex-1 min-w-[260px]">
          <Field label="العمر" value={d.child?.age ? `${d.child.age} سنة` : "—"} />
          <Field label="الجنس" value={d.child?.gender === "male" ? "ولد" : d.child?.gender === "female" ? "بنت" : "—"} />
          <Field label="المدة" value={order.duration?.seconds ? `${order.duration.seconds} ثانية` : "—"} />
          <Field label="التصنيف" value={e.category_name} />
          <Field label="الموضوع" value={e.subcategory_name || d.goal?.custom_subcategory} />
          <Field label="نوع القصة" value={e.type_name} />
          <Field label="النبرة" value={e.tone_name} />
          <Field label="اللغة" value={e.language_name} />
          <Field label="ستايل الرسم" value={e.art_style_name || "الافتراضي"} />
          <Field label="التسليم" value={{ both: "فيديو + كتاب", video: "فيديو", pdf: "كتاب PDF" }[d.delivery?.output_type || "both"]} />
          <Field label="جودة الفيديو" value={d.delivery?.video_tier === "premium" ? "فاخر" : "متوازن"} />
          <Field label="السعر" value={order.price_quote?.price_sar ? `${order.price_quote.price_sar} ر.س` : "—"} />
          <Field label="موافقة ولي الأمر" value={order.consent?.accepted_at ? formatDate(order.consent.accepted_at) : "—"} />
          <Field label="الصور الأصلية" value={order.data_deleted_at ? "الحساب اتمسح" : order.photos_deleted_at ? `اتمسحت ${formatDate(order.photos_deleted_at)}` : "موجودة"} />
        </div>
      </div>
      {(d.characters || []).length > 0 && (
        <div className="font-body text-sm text-[#5A677D] mb-3">
          الشخصيات: {(d.characters || []).map((c) => `${c.name || c.type}${c.role === "mentioned" ? " (بالاسم بس)" : ""}`).join("، ")}
        </div>
      )}
      <div className="bg-[#E8F0E1] rounded-2xl p-4 mb-4">
        <div className="text-xs font-bold text-[#4F6B3B] mb-1 font-body">الموقف الحقيقي</div>
        <p className="text-sm whitespace-pre-wrap font-body">{d.goal?.context || "—"}</p>
      </div>
      {d.personalization?.custom_notes && (
        <div className="bg-[#F8F1E7] rounded-2xl p-4 mb-4">
          <div className="text-xs font-bold text-[#8B5A2B] mb-1 font-body">تفاصيل خاصة من ولي الأمر</div>
          <p className="text-sm whitespace-pre-wrap font-body">{d.personalization.custom_notes}</p>
        </div>
      )}
      <label className="block text-sm font-bold mb-2 font-body" htmlFor="order-note">ملاحظة للعميل (بتظهر له في صفحة طلبه)</label>
      <textarea id="order-note" value={note} onChange={(ev) => setNote(ev.target.value)} rows={2}
        className="w-full bg-[#FDFBF7] border border-[#E2D8C9] rounded-2xl px-4 py-2 font-body mb-2" />
      <button onClick={saveNote} disabled={busy || note === (order.admin_note || "")}
        className="btn-primary inline-flex items-center gap-2 disabled:opacity-50 mb-4">
        <Save className="w-4 h-4" /> حفظ الملاحظة
      </button>
      <details className="mt-2">
        <summary className="font-body text-xs text-[#8A9AB0] cursor-pointer">تفاصيل للمطوّر (بيانات الطلب الخام)</summary>
        <div dir="ltr" className="font-mono text-[11px] text-[#8A9AB0] mt-2">{order.id}</div>
        <pre dir="ltr" className="bg-[#FDFBF7] rounded-2xl p-4 text-xs overflow-x-auto max-h-[420px] overflow-y-auto border border-[#E2D8C9] mt-2 text-left">
          {JSON.stringify(order.data, null, 2)}
        </pre>
      </details>
    </div>
  );
}

function StatusOverride({ order, onDone }) {
  const [status, setStatus] = useState(order.status);
  return (
    <ConfirmAction
      title="تغيير حالة الطلب يدوياً"
      description={
        <span className="block space-y-3">
          <span className="block">ده بيغيّر الحالة بس — مش بيشغّل أو يوقف أي إنتاج. استخدمه لتصحيح حالة غلط، والسبب بيتسجّل.</span>
          <select value={status} onChange={(e) => setStatus(e.target.value)}
            className="w-full bg-[#FDFBF7] border border-[#E2D8C9] rounded-2xl px-3 py-2 text-sm text-[#2D3748]">
            {Object.entries(STATUS_LABELS).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
          </select>
        </span>
      }
      confirmLabel="غيّر الحالة"
      requireReason
      onConfirm={async (reason) => {
        if (status === order.status) { toast.info("دي نفس الحالة"); return; }
        try {
          await api.patch(`/admin/orders/${order.id}/status`, { status, reason });
          toast.success("الحالة اتغيّرت");
          onDone();
        } catch (e) { toast.error(e?.response?.data?.detail || "فشل"); }
      }}
      className="rounded-full bg-white border border-[#E2D8C9] px-3 py-1.5 text-xs font-body font-bold text-[#5A677D] hover:border-[#87A96B]"
      testId="order-status-override"
    >
      تغيير الحالة
    </ConfirmAction>
  );
}

function History({ order }) {
  const rows = [...(order.status_history || [])].reverse();
  if (!rows.length) return <p className="font-body text-sm text-[#8A9AB0]">مفيش سجل.</p>;
  return (
    <div className="space-y-2" data-testid="order-history">
      {rows.map((h, i) => (
        <div key={i} className="bg-[#FDFBF7] rounded-2xl p-3 border border-[#E2D8C9] flex items-center gap-3">
          <Clock className="w-4 h-4 text-[#87A96B] shrink-0" />
          <div className="flex-1 text-sm font-body">
            <div className="text-[#2D3748] font-bold">{STATUS_LABELS[h.from] || h.from || "—"} ← {STATUS_LABELS[h.to] || h.to}</div>
            <div className="text-xs text-[#8A9AB0]">
              {formatDate(h.at)} • {{ admin: "الإدارة", system: "النظام", user: "العميل" }[h.by] || h.by}{h.reason ? ` • ${h.reason}` : ""}
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}
