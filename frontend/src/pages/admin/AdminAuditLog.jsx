import React, { useEffect, useState } from "react";
import { api } from "../../lib/api";
import { ScrollText, Loader2, RefreshCw, Filter } from "lucide-react";
import { toast } from "sonner";

const ENTITY_LABEL = {
  pricing_config: "إعدادات التسعير",
  model_registry: "سجل النماذج",
  pipeline_config: "إعدادات الـ Pipeline",
  prompt_template: "قالب برومبت",
  bundle: "باقة",
  bundle_purchase: "شراء باقة",
  payment_settings: "إعدادات الدفع",
  payment: "عملية دفع",
};
const ACTION_COLORS = {
  create: "bg-[#E8F0E1] text-[#4F6B3B]",
  update: "bg-[#F8F1E7] text-[#8B5A2B]",
  delete: "bg-[#FCE6D4] text-[#B8612F]",
  grant:  "bg-[#E8F0E1] text-[#4F6B3B]",
  reserve: "bg-[#F8F1E7] text-[#8B5A2B]",
  consume: "bg-[#E8F0E1] text-[#4F6B3B]",
  refund:  "bg-[#FCE6D4] text-[#B8612F]",
  expire:  "bg-[#FCE6D4] text-[#B8612F]",
  config_change: "bg-[#F8F1E7] text-[#8B5A2B]",
};

export default function AdminAuditLog() {
  const [data, setData] = useState({ rows: [], entity_types: [], actions: [] });
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState({ entity_type: "", action: "" });
  const [expanded, setExpanded] = useState({});

  const load = async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (filter.entity_type) params.set("entity_type", filter.entity_type);
      if (filter.action) params.set("action", filter.action);
      params.set("limit", "200");
      const { data } = await api.get(`/admin/audit/log?${params.toString()}`);
      setData(data);
    } catch { toast.error("تعذّر تحميل السجل"); }
    finally { setLoading(false); }
  };
  useEffect(() => { load(); }, [filter.entity_type, filter.action]);

  return (
    <div data-testid="admin-audit-page" className="max-w-5xl">
      <div className="mb-6 flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h1 className="font-heading text-3xl font-bold text-[#2D3748] inline-flex items-center gap-2">
            <ScrollText className="w-7 h-7 text-[#87A96B]" /> سجل التدقيق
          </h1>
          <p className="font-body text-sm text-[#5A677D] mt-2">
            كل تغيير على pricing/models/prompts/bundles/payments يُسجَّل هنا مع snapshot قبل/بعد و actor.
          </p>
        </div>
        <button onClick={load} className="rounded-full bg-[#F8F1E7] hover:bg-[#F2E8DA] text-[#8B5A2B] px-4 py-2 text-sm font-bold inline-flex items-center gap-1" data-testid="reload-audit"><RefreshCw className="w-4 h-4" /> تحديث</button>
      </div>

      <div className="bg-white rounded-2xl p-4 border border-[#E2D8C9] mb-4 inline-flex items-center gap-3 flex-wrap">
        <Filter className="w-4 h-4 text-[#5A677D]" />
        <select className="input" value={filter.entity_type} onChange={(e) => setFilter({ ...filter, entity_type: e.target.value })} data-testid="audit-filter-entity">
          <option value="">كل الكيانات</option>
          {(data.entity_types || []).map(e => <option key={e} value={e}>{ENTITY_LABEL[e] || e}</option>)}
        </select>
        <select className="input" value={filter.action} onChange={(e) => setFilter({ ...filter, action: e.target.value })} data-testid="audit-filter-action">
          <option value="">كل الإجراءات</option>
          {(data.actions || []).map(a => <option key={a} value={a}>{a}</option>)}
        </select>
        <span className="text-xs text-[#8A9AB0] font-body ms-auto">{data.count} سجل</span>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-12"><Loader2 className="w-6 h-6 animate-spin text-[#87A96B]" /></div>
      ) : (
        <div className="bg-white rounded-2xl border border-[#E2D8C9] overflow-hidden">
          {(data.rows || []).length === 0 ? (
            <div className="p-8 text-center text-[#8A9AB0] font-body">لا توجد سجلات.</div>
          ) : (
            <div className="divide-y divide-[#E2D8C9]">
              {data.rows.map((r) => (
                <div key={r.id} className="p-4" data-testid={`audit-row-${r.id}`}>
                  <button className="w-full text-right" onClick={() => setExpanded((m) => ({ ...m, [r.id]: !m[r.id] }))}>
                    <div className="flex items-center gap-3 flex-wrap">
                      <span className={`text-[10px] font-bold rounded-full px-2 py-0.5 ${ACTION_COLORS[r.action] || "bg-[#FDFBF7] text-[#5A677D]"}`}>{r.action}</span>
                      <span className="text-sm font-bold text-[#2D3748]">{ENTITY_LABEL[r.entity_type] || r.entity_type}</span>
                      <span className="text-xs text-[#5A677D] font-body flex-1 text-right">{r.summary}</span>
                      <span className="text-xs text-[#8A9AB0] font-body">{r.created_at?.slice(0, 16)}</span>
                    </div>
                    <div className="text-xs text-[#8A9AB0] mt-1 font-body">
                      by: {r.actor_email || r.actor_id?.slice(0, 8) || "system"}
                      {r.entity_id && <> • entity: {r.entity_id.slice(0, 8)}</>}
                    </div>
                  </button>
                  {expanded[r.id] && (
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mt-3" data-testid={`audit-diff-${r.id}`}>
                      {r.before && <pre className="bg-[#FCE6D4]/30 border border-[#E07A5F]/30 rounded-2xl p-3 text-xs overflow-x-auto whitespace-pre-wrap">before:{"\n"}{JSON.stringify(r.before, null, 2)}</pre>}
                      {r.after && <pre className="bg-[#E8F0E1]/50 border border-[#87A96B]/30 rounded-2xl p-3 text-xs overflow-x-auto whitespace-pre-wrap">after:{"\n"}{JSON.stringify(r.after, null, 2)}</pre>}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      <style>{`.input { background:#FDFBF7; border:1px solid #E2D8C9; border-radius:14px; padding:6px 10px; font-family:'Tajawal',sans-serif; font-size:13px; }`}</style>
    </div>
  );
}
