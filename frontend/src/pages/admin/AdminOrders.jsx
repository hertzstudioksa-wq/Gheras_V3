import React, { useEffect, useState } from "react";
import { api } from "../../lib/api";
import OrderStatusBadge from "../../components/gheras/OrderStatusBadge";
import { toast } from "sonner";
import { Eye, Filter } from "lucide-react";

const STATUSES = [
  { v: "pending", l: "بانتظار المراجعة" },
  { v: "in_review", l: "قيد المراجعة" },
  { v: "ready_for_ai", l: "جاهز للتوليد" },
  { v: "generating", l: "جاري التوليد" },
  { v: "completed", l: "مكتمل" },
];

export default function AdminOrders() {
  const [orders, setOrders] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState("all");
  const [detail, setDetail] = useState(null);
  const [note, setNote] = useState("");

  const reload = () => {
    setLoading(true);
    api.get("/admin/orders").then((r) => setOrders(r.data)).finally(() => setLoading(false));
  };
  useEffect(reload, []);

  const changeStatus = async (id, status) => {
    try {
      await api.patch(`/admin/orders/${id}/status`, { status, admin_note: note || null });
      toast.success("تم تحديث الحالة");
      setDetail(null);
      setNote("");
      reload();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "فشل التحديث");
    }
  };

  const filtered = filter === "all" ? orders : orders.filter((o) => o.status === filter);

  return (
    <div data-testid="admin-orders">
      <h1 className="font-heading text-3xl font-bold text-[#2D3748] mb-2">الطلبات</h1>
      <p className="font-body text-[#5A677D] mb-6">إدارة ومتابعة جميع طلبات القصص</p>

      <div className="flex items-center gap-2 mb-6 flex-wrap">
        <Filter className="w-4 h-4 text-[#8A9AB0]" />
        <button
          onClick={() => setFilter("all")}
          className={`rounded-full px-4 py-1.5 text-sm font-body ${
            filter === "all" ? "bg-[#87A96B] text-white" : "bg-white border border-[#E2D8C9] text-[#5A677D]"
          }`}
          data-testid="filter-all"
        >
          الكل ({orders.length})
        </button>
        {STATUSES.map((s) => (
          <button
            key={s.v}
            onClick={() => setFilter(s.v)}
            className={`rounded-full px-4 py-1.5 text-sm font-body ${
              filter === s.v ? "bg-[#87A96B] text-white" : "bg-white border border-[#E2D8C9] text-[#5A677D]"
            }`}
            data-testid={`filter-${s.v}`}
          >
            {s.l} ({orders.filter((o) => o.status === s.v).length})
          </button>
        ))}
      </div>

      <div className="bg-white rounded-3xl border border-[#E2D8C9] overflow-hidden">
        {loading ? (
          <div className="py-20 text-center text-[#8A9AB0]">جاري التحميل...</div>
        ) : filtered.length === 0 ? (
          <div className="py-20 text-center text-[#8A9AB0]">لا توجد طلبات</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-right">
              <thead className="bg-[#F8F1E7] text-[#5A677D] text-xs font-body">
                <tr>
                  <th className="px-5 py-3 font-bold">الطفل</th>
                  <th className="px-5 py-3 font-bold">الموضوع</th>
                  <th className="px-5 py-3 font-bold">العميل</th>
                  <th className="px-5 py-3 font-bold">التاريخ</th>
                  <th className="px-5 py-3 font-bold">الحالة</th>
                  <th className="px-5 py-3 font-bold">إجراءات</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((o) => (
                  <tr key={o.id} className="border-t border-[#E2D8C9] hover:bg-[#FDFBF7]" data-testid={`order-row-${o.id}`}>
                    <td className="px-5 py-3 font-body">
                      <div className="font-bold text-[#2D3748]">{o.child_snapshot?.name}</div>
                      <div className="text-xs text-[#8A9AB0]">{o.child_snapshot?.age} سنة</div>
                    </td>
                    <td className="px-5 py-3 font-body text-sm">
                      {o.category_name}
                      {o.subcategory_name ? <div className="text-xs text-[#8A9AB0]">{o.subcategory_name}</div> : null}
                    </td>
                    <td className="px-5 py-3 font-body text-sm">{o.user_email}</td>
                    <td className="px-5 py-3 font-body text-xs text-[#8A9AB0]">
                      {new Date(o.created_at).toLocaleDateString("ar-EG")}
                    </td>
                    <td className="px-5 py-3"><OrderStatusBadge status={o.status} /></td>
                    <td className="px-5 py-3">
                      <button
                        onClick={() => { setDetail(o); setNote(o.admin_note || ""); }}
                        className="inline-flex items-center gap-1 text-[#729352] hover:text-[#4F6B3B] text-sm font-body"
                        data-testid={`order-view-${o.id}`}
                      >
                        <Eye className="w-4 h-4" /> عرض
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {detail && (
        <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4" onClick={() => setDetail(null)}>
          <div className="bg-white rounded-[2rem] p-8 max-w-2xl w-full max-h-[90vh] overflow-y-auto" onClick={(e) => e.stopPropagation()} data-testid="order-modal">
            <h2 className="font-heading text-2xl font-bold text-[#2D3748] mb-2">
              طلب قصة {detail.child_snapshot?.name}
            </h2>
            <p className="font-body text-sm text-[#8A9AB0] mb-6">{detail.id}</p>

            <div className="grid grid-cols-2 gap-3 mb-6">
              <Field label="التصنيف" value={detail.category_name} />
              {detail.subcategory_name && <Field label="الموضوع" value={detail.subcategory_name} />}
              <Field label="الأسلوب" value={detail.style_name} />
              <Field label="الطفل" value={`${detail.child_snapshot?.name} • ${detail.child_snapshot?.age} سنة`} />
              <Field label="الجنس" value={detail.child_snapshot?.gender === "male" ? "ولد" : "بنت"} />
              <Field label="العميل" value={detail.user_email} />
              {detail.child_snapshot?.personality && <Field label="الشخصية" value={detail.child_snapshot.personality} />}
              {detail.child_snapshot?.interests && <Field label="الاهتمامات" value={detail.child_snapshot.interests} />}
            </div>

            {detail.notes && (
              <div className="bg-[#FDFBF7] rounded-2xl p-4 mb-4">
                <div className="text-xs text-[#8A9AB0] font-body mb-1">ملاحظات العميل</div>
                <p className="font-body text-sm">{detail.notes}</p>
              </div>
            )}

            {detail.ai_prompt_snapshot && (
              <details className="bg-[#F8F1E7] rounded-2xl p-4 mb-4">
                <summary className="font-body text-sm font-bold text-[#8B5A2B] cursor-pointer">معاينة برومبت الذكاء الاصطناعي</summary>
                <pre className="font-body text-xs text-[#2D3748] whitespace-pre-wrap mt-3">{detail.ai_prompt_snapshot}</pre>
              </details>
            )}

            <div className="mb-4">
              <label className="block text-sm font-bold text-[#2D3748] mb-2 font-body">ملاحظة للعميل (اختياري)</label>
              <textarea
                value={note}
                onChange={(e) => setNote(e.target.value)}
                rows={2}
                className="w-full bg-[#FDFBF7] border border-[#E2D8C9] rounded-2xl px-4 py-2 font-body"
                data-testid="admin-note"
              />
            </div>

            <div className="flex flex-wrap gap-2 mb-2">
              {STATUSES.map((s) => (
                <button
                  key={s.v}
                  onClick={() => changeStatus(detail.id, s.v)}
                  className={`rounded-full px-4 py-2 text-xs font-body font-bold border ${
                    detail.status === s.v
                      ? "bg-[#87A96B] border-[#87A96B] text-white"
                      : "bg-white border-[#E2D8C9] text-[#5A677D] hover:border-[#87A96B]"
                  }`}
                  data-testid={`admin-set-${s.v}`}
                >
                  {s.l}
                </button>
              ))}
            </div>

            <button onClick={() => setDetail(null)} className="mt-4 rounded-full px-4 py-2 bg-[#F8F1E7] text-[#8B5A2B] text-sm font-body">إغلاق</button>
          </div>
        </div>
      )}
    </div>
  );
}

function Field({ label, value }) {
  return (
    <div className="bg-[#FDFBF7] rounded-xl p-3 border border-[#E2D8C9]">
      <div className="text-xs text-[#8A9AB0] font-body">{label}</div>
      <div className="font-body font-bold text-[#2D3748] text-sm">{value}</div>
    </div>
  );
}
