import React, { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Search } from "lucide-react";
import { api } from "../../lib/api";
import OrderStatusBadge from "../../components/gheras/OrderStatusBadge";
import { AdminPage, PageState, Pager, useDebounced } from "../../components/admin/AdminKit";
import { ORDER_PHASES, formatDate } from "../../lib/orderStatus";

// Order list (M5b): search, phase filter and pages come from the server and
// live in the URL, so a filtered view can be linked to; rows open the order page.

const LIMIT = 25;

export default function AdminOrders() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const phase = params.get("phase") || "all";
  const page = Number(params.get("page") || 1);
  const [q, setQ] = useState(params.get("q") || "");
  const debouncedQ = useDebounced(q);

  const setParam = (patch) => {
    const next = new URLSearchParams(params);
    Object.entries(patch).forEach(([k, v]) => (v && v !== "all" && !(k === "page" && v === 1) ? next.set(k, v) : next.delete(k)));
    setParams(next, { replace: true });
  };

  useEffect(() => {
    if (debouncedQ !== (params.get("q") || "")) setParam({ q: debouncedQ, page: 1 });
  }, [debouncedQ]); // eslint-disable-line react-hooks/exhaustive-deps

  const load = () => {
    setError(null);
    api.get("/admin/orders", { params: { q: params.get("q") || "", phase, page, limit: LIMIT } })
      .then((r) => setData(r.data)).catch(() => setError("تعذّر تحميل الطلبات"));
  };
  useEffect(load, [params]); // eslint-disable-line react-hooks/exhaustive-deps

  const items = data?.items || [];
  return (
    <AdminPage title="الطلبات" description="كل طلبات القصص. افتح أي طلب عشان تشوف إنتاجه لقطة بلقطة والبرومبت والتكلفة." testId="admin-orders">
      <div className="flex flex-col md:flex-row md:items-center gap-3 mb-5">
        <label className="relative md:w-80">
          <Search className="w-4 h-4 text-[#8A9AB0] absolute top-1/2 -translate-y-1/2 right-3" />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="اسم الطفل أو العميل أو الإيميل أو رقم الطلب"
            className="w-full bg-white border border-[#E2D8C9] rounded-2xl pr-9 pl-4 py-2 font-body text-sm focus:outline-none focus:border-[#87A96B]"
            data-testid="orders-search" />
        </label>
        <div className="flex gap-2 overflow-x-auto pb-1">
          {[{ key: "all", label: "الكل" }, ...ORDER_PHASES].map((p) => {
            const n = p.key === "all" ? data?.all_count : data?.phase_counts?.[p.key];
            return (
              <button key={p.key} onClick={() => setParam({ phase: p.key, page: 1 })}
                className={`rounded-full px-4 py-1.5 text-sm font-body whitespace-nowrap ${
                  phase === p.key ? "bg-[#87A96B] text-white" : "bg-white border border-[#E2D8C9] text-[#5A677D]"
                } ${p.key === "failed" && n ? "border-[#E07A5F]" : ""}`}
                data-testid={`orders-phase-${p.key}`}>
                {p.label}{n !== undefined ? ` (${n})` : ""}
              </button>
            );
          })}
        </div>
      </div>

      <PageState loading={!data && !error} error={error} onRetry={load} empty={data && !items.length}
        emptyText={data?.all_count ? "مفيش طلبات بالبحث أو الفلتر ده" : "لسه مفيش طلبات"}>
        <div className="hidden md:block bg-white rounded-3xl border border-[#E2D8C9] overflow-hidden">
          <table className="w-full text-right">
            <thead className="bg-[#F8F1E7] text-[#5A677D] text-xs font-body">
              <tr>
                <th className="px-5 py-3 font-bold">القصة</th>
                <th className="px-5 py-3 font-bold">العميل</th>
                <th className="px-5 py-3 font-bold">المدة</th>
                <th className="px-5 py-3 font-bold">السعر</th>
                <th className="px-5 py-3 font-bold">التكلفة · الهامش</th>
                <th className="px-5 py-3 font-bold">التاريخ</th>
                <th className="px-5 py-3 font-bold">الحالة</th>
              </tr>
            </thead>
            <tbody>
              {items.map((o) => (
                <tr key={o.id} onClick={() => navigate(`/admin/orders/${o.id}`)}
                  className="border-t border-[#E2D8C9] hover:bg-[#FDFBF7] cursor-pointer" data-testid={`order-row-${o.id}`}>
                  <td className="px-5 py-3 font-body">
                    <div className="font-bold">{o.title || `قصة ${o.child_name || "—"}`}</div>
                    <div className="flex items-center gap-1.5 mt-0.5 flex-wrap"><OrderFlags o={o} /></div>
                  </td>
                  <td className="px-5 py-3 font-body text-sm">{o.user_name || o.user_email || "—"}
                    {o.user_name && <div className="text-xs text-[#8A9AB0]">{o.user_email}</div>}</td>
                  <td className="px-5 py-3 font-body text-sm">{o.duration?.seconds ? `${o.duration.seconds} ث` : "—"}</td>
                  <td className="px-5 py-3 font-body text-sm">{o.price_quote?.price_sar ? `${o.price_quote.price_sar} ر.س` : "—"}</td>
                  <td className="px-5 py-3 font-body text-sm"><CostCell o={o} /></td>
                  <td className="px-5 py-3 font-body text-xs text-[#8A9AB0]">{formatDate(o.created_at)}</td>
                  <td className="px-5 py-3"><OrderStatusBadge status={o.status} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="md:hidden space-y-2">
          {items.map((o) => (
            <button key={o.id} onClick={() => navigate(`/admin/orders/${o.id}`)}
              className="w-full text-right bg-white rounded-2xl border border-[#E2D8C9] p-4">
              <div className="flex items-center justify-between gap-2 mb-1">
                <span className="font-body font-bold text-[#2D3748]">{o.title || `قصة ${o.child_name || "—"}`}</span>
                <OrderStatusBadge status={o.status} />
              </div>
              <div className="flex items-center gap-1.5 mb-1 flex-wrap"><OrderFlags o={o} /></div>
              <div className="font-body text-xs text-[#8A9AB0]">
                {o.user_email} • {formatDate(o.created_at, false)}{o.duration?.seconds ? ` • ${o.duration.seconds} ث` : ""}
              </div>
              {o.cost_sar > 0 && <div className="font-body text-xs mt-1"><CostCell o={o} /></div>}
            </button>
          ))}
        </div>
        <Pager page={data?.page || 1} limit={LIMIT} total={data?.total || 0} onPage={(p) => setParam({ page: p })} />
      </PageState>
    </AdminPage>
  );
}

// Actual cost so far and the margin left (same numbers as the order's cost tab).
function CostCell({ o }) {
  if (!o.cost_sar) return <span className="text-[#8A9AB0]">—</span>;
  const m = o.margin_pct;
  const tone = m == null ? "text-[#8A9AB0]" : m >= 40 ? "text-[#4F6B3B]" : m >= 20 ? "text-[#8B5A2B]" : "text-[#B8612F]";
  return (
    <span className="whitespace-nowrap">
      {o.cost_sar} ر.س{m != null && <b className={`${tone} mr-1`}> · {m}%</b>}
    </span>
  );
}

// Small chips under the story name: what was bought and what needs attention.
function OrderFlags({ o }) {
  const chip = "rounded-full px-2 py-0.5 text-[11px] font-bold font-body";
  return (
    <>
      {o.child_name && o.title && <span className="text-xs text-[#8A9AB0] font-body">{o.child_name}</span>}
      <span className={`${chip} ${o.output_type === "pdf" ? "bg-[#F8F1E7] text-[#8B5A2B]" : "bg-[#E8F0E1] text-[#4F6B3B]"}`}>
        {o.output_type === "pdf" ? "كتاب فقط" : o.video_tier === "premium" ? "فيديو فاخر" : "فيديو متوازن"}
      </span>
      {o.engine_paused && <span className={`${chip} bg-[#FBEFD5] text-[#8B5A2B]`}>موقوف — رصيد المحرك</span>}
      {o.feedback?.problem && o.feedback?.problem_status !== "resolved" && (
        <span className={`${chip} bg-[#E07A5F] text-white`}>بلاغ مشكلة</span>
      )}
      {o.feedback?.rating && <span className={`${chip} bg-[#FFF6DD] text-[#8B6A00]`}>★ {o.feedback.rating}</span>}
      {o.flagged_shots > 0 && (
        <span className={`${chip} bg-[#FCE6D4] text-[#B8612F]`} title="لقطات علّمت عليها المراجعة الآلية — افتح تبويب «اللقطات»">
          ⚑ {o.flagged_shots} لقطة متعلّمة
        </span>
      )}
    </>
  );
}
