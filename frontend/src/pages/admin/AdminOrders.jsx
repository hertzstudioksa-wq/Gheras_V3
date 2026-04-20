import React, { useEffect, useState } from "react";
import { api, fileSrc } from "../../lib/api";
import OrderStatusBadge from "../../components/gheras/OrderStatusBadge";
import { toast } from "sonner";
import { Eye, Filter, Wand2, Save, RefreshCw, X } from "lucide-react";

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
  const [promptEdit, setPromptEdit] = useState("");
  const [tab, setTab] = useState("overview"); // overview | json | prompt

  const reload = () => {
    setLoading(true);
    api.get("/admin/orders").then((r) => setOrders(r.data)).finally(() => setLoading(false));
  };
  useEffect(reload, []);

  const openDetail = async (id) => {
    const { data } = await api.get(`/admin/orders/${id}`);
    setDetail(data);
    setNote(data.admin_note || "");
    setPromptEdit(data.ai_prompt_snapshot || "");
    setTab("overview");
  };

  const changeStatus = async (id, status) => {
    try {
      await api.patch(`/admin/orders/${id}/status`, { status, admin_note: note || null });
      toast.success("تم تحديث الحالة");
      reload();
      openDetail(id);
    } catch {
      toast.error("فشل");
    }
  };

  const savePrompt = async () => {
    try {
      await api.patch(`/admin/orders/${detail.id}/prompt`, { ai_prompt_snapshot: promptEdit });
      toast.success("تم حفظ البرومبت");
      openDetail(detail.id);
    } catch {
      toast.error("فشل");
    }
  };

  const regeneratePrompt = async () => {
    try {
      const { data } = await api.post(`/admin/orders/${detail.id}/regenerate-prompt`);
      setPromptEdit(data.ai_prompt_snapshot);
      toast.success("تم إعادة التوليد من JSON");
    } catch {
      toast.error("فشل");
    }
  };

  const filtered = filter === "all" ? orders : orders.filter((o) => o.status === filter);

  return (
    <div data-testid="admin-orders">
      <h1 className="font-heading text-3xl font-bold text-[#2D3748] mb-2">الطلبات</h1>
      <p className="font-body text-[#5A677D] mb-6">إدارة طلبات القصص</p>

      <div className="flex items-center gap-2 mb-6 flex-wrap">
        <Filter className="w-4 h-4 text-[#8A9AB0]" />
        <button onClick={() => setFilter("all")} className={`rounded-full px-4 py-1.5 text-sm font-body ${filter === "all" ? "bg-[#87A96B] text-white" : "bg-white border border-[#E2D8C9] text-[#5A677D]"}`}>
          الكل ({orders.length})
        </button>
        {STATUSES.map((s) => (
          <button key={s.v} onClick={() => setFilter(s.v)} className={`rounded-full px-4 py-1.5 text-sm font-body ${filter === s.v ? "bg-[#87A96B] text-white" : "bg-white border border-[#E2D8C9] text-[#5A677D]"}`}>
            {s.l} ({orders.filter((o) => o.status === s.v).length})
          </button>
        ))}
      </div>

      <div className="bg-white rounded-3xl border border-[#E2D8C9] overflow-hidden">
        {loading ? <div className="py-20 text-center text-[#8A9AB0]">جاري التحميل...</div> : filtered.length === 0 ? <div className="py-20 text-center text-[#8A9AB0]">لا توجد طلبات</div> : (
          <div className="overflow-x-auto">
            <table className="w-full text-right">
              <thead className="bg-[#F8F1E7] text-[#5A677D] text-xs font-body">
                <tr>
                  <th className="px-5 py-3 font-bold">الطفل</th>
                  <th className="px-5 py-3 font-bold">العميل</th>
                  <th className="px-5 py-3 font-bold">التاريخ</th>
                  <th className="px-5 py-3 font-bold">الحالة</th>
                  <th className="px-5 py-3 font-bold">إجراء</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((o) => (
                  <tr key={o.id} className="border-t border-[#E2D8C9] hover:bg-[#FDFBF7]">
                    <td className="px-5 py-3 font-body font-bold">{o.child_name}</td>
                    <td className="px-5 py-3 font-body text-sm">{o.user_email}</td>
                    <td className="px-5 py-3 font-body text-xs text-[#8A9AB0]">{new Date(o.created_at).toLocaleDateString("ar-EG")}</td>
                    <td className="px-5 py-3"><OrderStatusBadge status={o.status} /></td>
                    <td className="px-5 py-3">
                      <button onClick={() => openDetail(o.id)} className="inline-flex items-center gap-1 text-[#729352] hover:text-[#4F6B3B] text-sm font-body">
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
          <div className="bg-white rounded-[2rem] p-6 md:p-8 max-w-3xl w-full max-h-[92vh] overflow-y-auto" onClick={(e) => e.stopPropagation()} data-testid="order-modal">
            <div className="flex items-start justify-between mb-4">
              <div>
                <h2 className="font-heading text-2xl font-bold text-[#2D3748]">قصة {detail.data?.child?.name}</h2>
                <p className="font-body text-xs text-[#8A9AB0]">{detail.id} • {detail.user_email}</p>
              </div>
              <button onClick={() => setDetail(null)} className="text-[#8A9AB0]"><X className="w-5 h-5" /></button>
            </div>

            <div className="flex gap-2 mb-5 border-b border-[#E2D8C9]">
              {[
                { k: "overview", l: "نظرة عامة" },
                { k: "json", l: "JSON الكامل" },
                { k: "prompt", l: "البرومبت" },
              ].map((t) => (
                <button key={t.k} onClick={() => setTab(t.k)} className={`px-4 py-2 text-sm font-body font-bold border-b-2 ${tab === t.k ? "border-[#87A96B] text-[#4F6B3B]" : "border-transparent text-[#8A9AB0]"}`}>
                  {t.l}
                </button>
              ))}
            </div>

            {tab === "overview" && (
              <div>
                {detail.data?.child?.image_url && (
                  <img src={fileSrc(detail.data.child.image_url)} alt="" className="w-24 h-24 rounded-2xl object-cover border border-[#E2D8C9] mb-4" />
                )}
                <div className="grid grid-cols-2 gap-2 mb-4">
                  <Field label="التصنيف" value={detail.enriched?.category_name} />
                  <Field label="الموضوع" value={detail.enriched?.subcategory_name || detail.data?.goal?.custom_subcategory} />
                  <Field label="العمر" value={`${detail.data?.child?.age} سنة`} />
                  <Field label="الجنس" value={detail.data?.child?.gender === "male" ? "ولد" : "بنت"} />
                  <Field label="نوع القصة" value={detail.enriched?.type_name} />
                  <Field label="النبرة" value={detail.enriched?.tone_name} />
                  <Field label="البيئة" value={detail.enriched?.setting_name} />
                  <Field label="اللغة" value={detail.enriched?.language_name} />
                </div>
                <div className="bg-[#E8F0E1] rounded-2xl p-4 mb-4">
                  <div className="text-xs font-bold text-[#4F6B3B] mb-1">الموقف الحقيقي</div>
                  <p className="text-sm whitespace-pre-wrap">{detail.data?.goal?.context}</p>
                </div>

                <label className="block text-sm font-bold mb-2 font-body">ملاحظة للعميل</label>
                <textarea value={note} onChange={(e) => setNote(e.target.value)} rows={2} className="w-full bg-[#FDFBF7] border border-[#E2D8C9] rounded-2xl px-4 py-2 font-body mb-4" />

                <div className="flex flex-wrap gap-2">
                  {STATUSES.map((s) => (
                    <button key={s.v} onClick={() => changeStatus(detail.id, s.v)} className={`rounded-full px-4 py-2 text-xs font-body font-bold border ${detail.status === s.v ? "bg-[#87A96B] border-[#87A96B] text-white" : "bg-white border-[#E2D8C9] text-[#5A677D] hover:border-[#87A96B]"}`}>
                      {s.l}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {tab === "json" && (
              <pre className="bg-[#FDFBF7] rounded-2xl p-4 text-xs overflow-x-auto max-h-[500px] overflow-y-auto border border-[#E2D8C9]">
                {JSON.stringify(detail.data, null, 2)}
              </pre>
            )}

            {tab === "prompt" && (
              <div>
                <div className="flex items-center justify-between mb-3">
                  <div className="flex items-center gap-2 text-[#729352] font-body font-bold text-sm">
                    <Wand2 className="w-4 h-4" /> برومبت الذكاء الاصطناعي
                    {detail.prompt_edited && <span className="text-xs bg-[#D4A373]/20 text-[#8B5A2B] rounded-full px-2 py-0.5">معدّل يدوياً</span>}
                  </div>
                  <button onClick={regeneratePrompt} className="inline-flex items-center gap-1 text-xs font-body text-[#5A677D] hover:text-[#2D3748]">
                    <RefreshCw className="w-3 h-3" /> إعادة التوليد من JSON
                  </button>
                </div>
                <textarea
                  value={promptEdit}
                  onChange={(e) => setPromptEdit(e.target.value)}
                  rows={18}
                  className="w-full bg-[#FDFBF7] border border-[#E2D8C9] rounded-2xl p-4 font-body text-sm"
                  data-testid="admin-prompt-editor"
                />
                <button onClick={savePrompt} className="btn-primary inline-flex items-center gap-2 mt-3">
                  <Save className="w-4 h-4" /> حفظ البرومبت
                </button>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function Field({ label, value }) {
  return (
    <div className="bg-[#FDFBF7] rounded-xl p-2 border border-[#E2D8C9]">
      <div className="text-xs text-[#8A9AB0] font-body">{label}</div>
      <div className="font-body font-bold text-[#2D3748] text-sm">{value || "—"}</div>
    </div>
  );
}
