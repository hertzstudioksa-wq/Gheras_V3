import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { AlertTriangle, CheckCircle2, ChevronLeft, KeyRound } from "lucide-react";
import { api } from "../../lib/api";
import OrderStatusBadge from "../../components/gheras/OrderStatusBadge";
import { AdminPage, KpiCard, PageState } from "../../components/admin/AdminKit";
import { formatDate, timeAgo } from "../../lib/orderStatus";

// Operations home (M5, audit AF-23): what needs a person now, how the
// business is doing, and whether the engine can run.

const QUEUES = [
  { key: "failed", title: "إنتاج فشل", tone: "bad" },
  { key: "stuck", title: "شغّال ومتوقف", tone: "warn" },
  { key: "waiting_customer", title: "مستني العميل يختار", tone: "neutral" },
];

export default function AdminOverview() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const load = () => {
    setError(null);
    api.get("/admin/overview").then((r) => setData(r.data)).catch(() => setError("تعذّر تحميل الرئيسية"));
  };
  useEffect(load, []);

  if (!data) return <PageState loading={!error} error={error} onRetry={load} />;
  const { kpis, attention, engine } = data;
  const engineOk = !engine.missing_keys.length && !engine.stages_off_catalog.length;

  return (
    <AdminPage title="الرئيسية" description="اللي محتاج تدخّل دلوقتي، وأرقام آخر 30 يوم، وحالة المحرك." testId="admin-overview">
      <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3 mb-6">
        <KpiCard label="طلبات آخر 7 أيام" value={kpis.orders_7d} to="/admin/orders" />
        <KpiCard label="طلبات آخر 30 يوم" value={kpis.orders_30d} to="/admin/orders" />
        <KpiCard label="اتسلّمت (30 يوم)" value={kpis.delivered_30d} tone="good" to="/admin/orders?phase=delivered" />
        <KpiCard label="فشلت (30 يوم)" value={kpis.failed_30d} tone={kpis.failed_30d ? "bad" : "neutral"} to="/admin/orders?phase=failed" />
        <KpiCard label="إيراد 30 يوم" value={`${kpis.revenue_30d_sar.toLocaleString("ar-EG")} ر.س`}
          hint={`آخر 7 أيام: ${kpis.revenue_7d_sar.toLocaleString("ar-EG")} ر.س`} />
        <KpiCard label="المستخدمين" value={kpis.users_total} to="/admin/users" />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-6">
        <div className="lg:col-span-2 min-w-0 bg-white rounded-3xl border border-[#E2D8C9] p-5" data-testid="overview-attention">
          <h2 className="font-heading text-lg font-bold text-[#2D3748] mb-3 flex items-center gap-2">
            {data.attention_count ? <AlertTriangle className="w-5 h-5 text-[#E07A5F]" /> : <CheckCircle2 className="w-5 h-5 text-[#87A96B]" />}
            محتاج تدخّل {data.attention_count ? `(${data.attention_count})` : ""}
          </h2>
          {!data.attention_count && <p className="font-body text-sm text-[#5A677D]">كله ماشي — مفيش طلبات فشلت أو اتعطّلت أو مستنية العميل من مدة طويلة.</p>}
          {QUEUES.map((q) => (attention[q.key] || []).length > 0 && (
            <div key={q.key} className="mb-4">
              <div className={`font-body text-sm font-bold mb-2 ${q.tone === "bad" ? "text-[#B8612F]" : q.tone === "warn" ? "text-[#8B5A2B]" : "text-[#5A677D]"}`}>
                {q.title} ({attention[q.key].length})
              </div>
              <div className="space-y-1.5">
                {attention[q.key].map((o) => (
                  <Link key={o.id} to={`/admin/orders/${o.id}`}
                    className="flex items-center justify-between gap-3 bg-[#FDFBF7] border border-[#E2D8C9] rounded-2xl px-4 py-2.5 hover:border-[#87A96B]">
                    <div className="min-w-0">
                      <div className="font-body text-sm font-bold text-[#2D3748]">{o.child_name || "—"}
                        <span className="font-normal text-xs text-[#8A9AB0]"> • {timeAgo(o.updated_at)}</span></div>
                      <div className="font-body text-xs text-[#8A9AB0] truncate">{o.reason_ar}</div>
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      <OrderStatusBadge status={o.status} />
                      <ChevronLeft className="w-4 h-4 text-[#8A9AB0]" />
                    </div>
                  </Link>
                ))}
              </div>
            </div>
          ))}
        </div>

        <div className={`min-w-0 rounded-3xl border p-5 ${engineOk ? "bg-[#E8F0E1] border-[#87A96B]/30" : "bg-[#FCE6D4] border-[#E07A5F]/40"}`} data-testid="overview-engine">
          <h2 className="font-heading text-lg font-bold text-[#2D3748] mb-3">حالة المحرك</h2>
          <ul className="font-body text-sm space-y-2 text-[#2D3748]">
            <li className="flex items-center gap-2">
              {engine.missing_keys.length ? <KeyRound className="w-4 h-4 text-[#B8612F]" /> : <CheckCircle2 className="w-4 h-4 text-[#4F6B3B]" />}
              {engine.missing_keys.length ? `مفاتيح ناقصة: ${engine.missing_keys.join("، ")}` : `مفاتيح كل المراحل (${engine.stages_total}) موجودة`}
            </li>
            <li className="flex items-center gap-2">
              {engine.stages_off_catalog.length ? <AlertTriangle className="w-4 h-4 text-[#B8612F]" /> : <CheckCircle2 className="w-4 h-4 text-[#4F6B3B]" />}
              {engine.stages_off_catalog.length ? `مراحل على موديل برّه الكتالوج: ${engine.stages_off_catalog.join("، ")}` : "كل المراحل على موديلات من الكتالوج"}
            </li>
            {engine.disabled_optional.length > 0 && (
              <li className="flex items-center gap-2 text-[#8B5A2B]"><AlertTriangle className="w-4 h-4" /> مقفول: {engine.disabled_optional.join("، ")}</li>
            )}
          </ul>
          <Link to="/admin/engine" className="inline-flex items-center gap-1 mt-4 font-body text-sm font-bold text-[#4F6B3B]">
            المحرك والموديلات <ChevronLeft className="w-4 h-4" />
          </Link>
        </div>
      </div>

      <div className="bg-white rounded-3xl border border-[#E2D8C9] p-5">
        <div className="flex items-center justify-between mb-3">
          <h2 className="font-heading text-lg font-bold text-[#2D3748]">آخر الطلبات</h2>
          <Link to="/admin/orders" className="font-body text-sm font-bold text-[#4F6B3B]">كل الطلبات</Link>
        </div>
        <PageState empty={!data.recent_orders.length} emptyText="لسه مفيش طلبات">
          <div className="divide-y divide-[#E2D8C9]">
            {data.recent_orders.map((o) => (
              <Link key={o.id} to={`/admin/orders/${o.id}`} className="flex items-center justify-between gap-3 py-2.5 hover:bg-[#FDFBF7] px-2 rounded-xl">
                <span className="font-body text-sm font-bold text-[#2D3748]">{o.child_name || "—"}
                  <span className="font-normal text-xs text-[#8A9AB0]"> • {formatDate(o.created_at)}</span></span>
                <OrderStatusBadge status={o.status} />
              </Link>
            ))}
          </div>
        </PageState>
      </div>
    </AdminPage>
  );
}
