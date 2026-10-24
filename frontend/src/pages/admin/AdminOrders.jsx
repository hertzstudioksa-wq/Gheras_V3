import React, { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Search } from "lucide-react";
import { api } from "../../lib/api";
import OrderStatusBadge from "../../components/gheras/OrderStatusBadge";
import { AdminPage, PageState } from "../../components/admin/AdminKit";
import { ORDER_PHASES, formatDate, phaseOf } from "../../lib/orderStatus";

// Order list (M5): search + phase filters (kept in the URL so links can point
// at a filtered view); every row opens the full order page.

export default function AdminOrders() {
  const [orders, setOrders] = useState(null);
  const [error, setError] = useState(null);
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const phase = params.get("phase") || "all";
  const q = params.get("q") || "";

  const reload = () => {
    setError(null);
    api.get("/admin/orders").then((r) => setOrders(r.data)).catch(() => setError("تعذّر تحميل الطلبات"));
  };
  useEffect(reload, []);

  const setParam = (key, value) => {
    const next = new URLSearchParams(params);
    if (value && value !== "all") next.set(key, value); else next.delete(key);
    setParams(next, { replace: true });
  };

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return (orders || []).filter((o) => {
      if (phase !== "all" && phaseOf(o.status).key !== phase) return false;
      if (!needle) return true;
      return [o.child_name, o.user_email, o.user_name, o.id].some((v) => (v || "").toLowerCase().includes(needle));
    });
  }, [orders, phase, q]);

  const count = (key) => (orders || []).filter((o) => phaseOf(o.status).key === key).length;

  return (
    <AdminPage title="الطلبات" description="كل طلبات القصص. افتح أي طلب عشان تشوف إنتاجه لقطة بلقطة والبرومبت والتكلفة." testId="admin-orders">
      <div className="flex flex-col md:flex-row md:items-center gap-3 mb-5">
        <label className="relative md:w-80">
          <Search className="w-4 h-4 text-[#8A9AB0] absolute top-1/2 -translate-y-1/2 right-3" />
          <input
            value={q}
            onChange={(e) => setParam("q", e.target.value)}
            placeholder="اسم الطفل أو إيميل العميل أو رقم الطلب"
            className="w-full bg-white border border-[#E2D8C9] rounded-2xl pr-9 pl-4 py-2 font-body text-sm focus:outline-none focus:border-[#87A96B]"
            data-testid="orders-search"
          />
        </label>
        <div className="flex gap-2 overflow-x-auto pb-1">
          {[{ key: "all", label: "الكل" }, ...ORDER_PHASES].map((p) => (
            <button key={p.key} onClick={() => setParam("phase", p.key)}
              className={`rounded-full px-4 py-1.5 text-sm font-body whitespace-nowrap ${
                phase === p.key ? "bg-[#87A96B] text-white" : "bg-white border border-[#E2D8C9] text-[#5A677D]"
              } ${p.key === "failed" && count("failed") ? "border-[#E07A5F]" : ""}`}
              data-testid={`orders-phase-${p.key}`}>
              {p.label} ({p.key === "all" ? (orders || []).length : count(p.key)})
            </button>
          ))}
        </div>
      </div>

      <PageState loading={!orders && !error} error={error} onRetry={reload} empty={orders && !filtered.length}
        emptyText={orders?.length ? "مفيش طلبات بالفلتر ده" : "لسه مفيش طلبات"}>
        {/* Desktop table */}
        <div className="hidden md:block bg-white rounded-3xl border border-[#E2D8C9] overflow-hidden">
          <table className="w-full text-right">
            <thead className="bg-[#F8F1E7] text-[#5A677D] text-xs font-body">
              <tr>
                <th className="px-5 py-3 font-bold">الطفل</th>
                <th className="px-5 py-3 font-bold">العميل</th>
                <th className="px-5 py-3 font-bold">المدة</th>
                <th className="px-5 py-3 font-bold">السعر</th>
                <th className="px-5 py-3 font-bold">التاريخ</th>
                <th className="px-5 py-3 font-bold">الحالة</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((o) => (
                <tr key={o.id} onClick={() => navigate(`/admin/orders/${o.id}`)}
                  className="border-t border-[#E2D8C9] hover:bg-[#FDFBF7] cursor-pointer" data-testid={`order-row-${o.id}`}>
                  <td className="px-5 py-3 font-body font-bold">{o.child_name || "—"}</td>
                  <td className="px-5 py-3 font-body text-sm">{o.user_name || o.user_email || "—"}
                    {o.user_name && <div className="text-xs text-[#8A9AB0]">{o.user_email}</div>}</td>
                  <td className="px-5 py-3 font-body text-sm">{o.duration?.seconds ? `${o.duration.seconds} ث` : "—"}</td>
                  <td className="px-5 py-3 font-body text-sm">{o.price_quote?.price_sar ? `${o.price_quote.price_sar} ر.س` : "—"}</td>
                  <td className="px-5 py-3 font-body text-xs text-[#8A9AB0]">{formatDate(o.created_at)}</td>
                  <td className="px-5 py-3"><OrderStatusBadge status={o.status} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {/* Mobile cards */}
        <div className="md:hidden space-y-2">
          {filtered.map((o) => (
            <button key={o.id} onClick={() => navigate(`/admin/orders/${o.id}`)}
              className="w-full text-right bg-white rounded-2xl border border-[#E2D8C9] p-4">
              <div className="flex items-center justify-between gap-2 mb-1">
                <span className="font-body font-bold text-[#2D3748]">{o.child_name || "—"}</span>
                <OrderStatusBadge status={o.status} />
              </div>
              <div className="font-body text-xs text-[#8A9AB0]">
                {o.user_email} • {formatDate(o.created_at, false)}{o.duration?.seconds ? ` • ${o.duration.seconds} ث` : ""}
              </div>
            </button>
          ))}
        </div>
      </PageState>
    </AdminPage>
  );
}
