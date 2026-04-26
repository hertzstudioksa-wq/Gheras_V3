import React, { useEffect, useState } from "react";
import { api } from "../../lib/api";
import { Library, Loader2, RefreshCw, Filter, ExternalLink, Archive, RotateCcw, Trash2, AlertTriangle } from "lucide-react";
import { toast } from "sonner";

const STATUS_BADGE = {
  live:     { bg: "bg-[#E8F0E1]", fg: "text-[#4F6B3B]", label: "نشطة" },
  archived: { bg: "bg-[#F8F1E7]", fg: "text-[#8B5A2B]", label: "مؤرشفة" },
  purged:   { bg: "bg-[#FCE6D4]", fg: "text-[#B8612F]", label: "مُطهَّرة" },
};
const TYPE_LABEL = { video: "فيديو", pdf: "PDF" };

export default function AdminAssetLibrary() {
  const [data, setData] = useState({ assets: [], count: 0 });
  const [loading, setLoading] = useState(true);
  const [filters, setFilters] = useState({ asset_type: "", lifecycle_status: "", order_status: "", min_age_days: "" });
  const [busy, setBusy] = useState(null); // {asset_type, asset_id, op}

  const load = async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      Object.entries(filters).forEach(([k, v]) => { if (v) params.set(k, v); });
      params.set("limit", "200");
      const { data } = await api.get(`/admin/assets?${params.toString()}`);
      setData(data);
    } catch { toast.error("تعذّر تحميل المكتبة"); }
    finally { setLoading(false); }
  };
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [filters.asset_type, filters.lifecycle_status, filters.order_status, filters.min_age_days]);

  const doAction = async (a, op, force = false) => {
    const verb = { archive: "أرشفة", restore: "استعادة", purge: "تطهير" }[op];
    if (op === "purge" && !force) {
      if (!window.confirm(`تأكيد ${verb} ${TYPE_LABEL[a.asset_type]} نهائياً؟ لا يمكن التراجع بعد التطهير.`)) return;
    }
    setBusy({ asset_id: a.asset_id, op });
    try {
      const url = `/admin/assets/${a.asset_type}/${a.asset_id}/${op}${force ? "?force=true" : ""}`;
      const { data } = await api.post(url);
      if (data.needs_force) {
        if (window.confirm(`الإجراء محظور بحارس: ${data.reason}\n\nهل تريد تجاوز الحارس وتنفيذ ${verb}؟`)) {
          return doAction(a, op, true);
        }
      } else {
        toast.success(`تمت ${verb}`);
        load();
      }
    } catch (e) {
      toast.error(e?.response?.data?.detail || "فشل");
    } finally { setBusy(null); }
  };

  return (
    <div data-testid="admin-asset-library-page" className="max-w-6xl">
      <div className="mb-6 flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h1 className="font-heading text-3xl font-bold text-[#2D3748] inline-flex items-center gap-2"><Library className="w-7 h-7 text-[#87A96B]" /> مكتبة الأصول</h1>
          <p className="font-body text-sm text-[#5A677D] mt-2">كل الفيديوهات وكتب PDF النهائية. تحكّم بالأرشفة والتطهير مع حُرّاس أمان.</p>
        </div>
        <button onClick={load} className="rounded-full bg-[#F8F1E7] hover:bg-[#F2E8DA] text-[#8B5A2B] px-4 py-2 text-sm font-bold inline-flex items-center gap-1" data-testid="reload-assets"><RefreshCw className="w-4 h-4" /> تحديث</button>
      </div>

      <div className="bg-white rounded-2xl p-4 border border-[#E2D8C9] mb-4 inline-flex items-center gap-2 flex-wrap">
        <Filter className="w-4 h-4 text-[#5A677D]" />
        <select className="input" value={filters.asset_type} onChange={(e) => setFilters({ ...filters, asset_type: e.target.value })} data-testid="filter-type">
          <option value="">كل الأنواع</option><option value="video">فيديو</option><option value="pdf">PDF</option>
        </select>
        <select className="input" value={filters.lifecycle_status} onChange={(e) => setFilters({ ...filters, lifecycle_status: e.target.value })} data-testid="filter-lifecycle">
          <option value="">كل الحالات</option><option value="live">نشطة</option><option value="archived">مؤرشفة</option><option value="purged">مُطهَّرة</option>
        </select>
        <select className="input" value={filters.order_status} onChange={(e) => setFilters({ ...filters, order_status: e.target.value })} data-testid="filter-order-status">
          <option value="">كل حالات الطلب</option><option value="delivered">تم التسليم</option><option value="assembling">قيد التجميع</option><option value="media_failed">فشل وسائط</option>
        </select>
        <input type="number" placeholder="عمر أدنى (أيام)" className="input w-32" value={filters.min_age_days} onChange={(e) => setFilters({ ...filters, min_age_days: e.target.value })} data-testid="filter-age" />
        <span className="text-xs text-[#8A9AB0] font-body ms-auto">{data.count} أصل</span>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-12"><Loader2 className="w-6 h-6 animate-spin text-[#87A96B]" /></div>
      ) : (
        <div className="bg-white rounded-2xl border border-[#E2D8C9] overflow-hidden">
          {data.assets.length === 0 ? (
            <div className="p-8 text-center text-[#8A9AB0] font-body">لا توجد أصول مطابقة.</div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm font-body">
                <thead className="text-xs text-[#5A677D] bg-[#FDFBF7]">
                  <tr><th className="py-2 px-3 text-right">النوع</th><th>الطلب</th><th>المستخدم</th><th>الحالة</th><th>عمر</th><th>الإجراءات</th></tr>
                </thead>
                <tbody>
                  {data.assets.map((a) => {
                    const stt = STATUS_BADGE[a.lifecycle_status] || STATUS_BADGE.live;
                    return (
                      <tr key={`${a.asset_type}-${a.asset_id}`} className="border-t border-[#E2D8C9]" data-testid={`asset-row-${a.asset_id}`}>
                        <td className="py-2 px-3 font-bold text-[#2D3748]">{TYPE_LABEL[a.asset_type]}</td>
                        <td className="text-xs text-[#5A677D]">
                          <div>{a.order_id?.slice(0, 8)}</div>
                          <div className="text-[10px] text-[#8A9AB0]">{a.order_status}</div>
                        </td>
                        <td className="text-xs text-[#5A677D]">{a.user_email || a.user_id?.slice(0, 8) || "—"}</td>
                        <td>
                          <span className={`inline-block text-[10px] font-bold rounded-full px-2 py-0.5 ${stt.bg} ${stt.fg}`}>{stt.label}</span>
                          {a.has_active_bundle && <div className="text-[10px] text-[#4F6B3B] mt-1">⛓ bundle نشط</div>}
                        </td>
                        <td className="text-xs text-[#5A677D]">{a.age_days}d</td>
                        <td>
                          <div className="flex gap-1 flex-wrap">
                            {a.file_url && (
                              <a href={a.file_url} target="_blank" rel="noreferrer" className="text-xs bg-[#F8F1E7] hover:bg-[#F2E8DA] text-[#8B5A2B] rounded-full px-3 py-1 font-bold inline-flex items-center gap-1" data-testid={`download-${a.asset_id}`}><ExternalLink className="w-3 h-3" /> تحميل</a>
                            )}
                            {a.lifecycle_status === "live" && (
                              <button onClick={() => doAction(a, "archive")} disabled={busy?.asset_id === a.asset_id} className="text-xs bg-[#F8F1E7] hover:bg-[#F2E8DA] text-[#8B5A2B] rounded-full px-3 py-1 font-bold inline-flex items-center gap-1 disabled:opacity-50" data-testid={`archive-${a.asset_id}`}><Archive className="w-3 h-3" /> أرشف</button>
                            )}
                            {a.lifecycle_status === "archived" && (
                              <>
                                <button onClick={() => doAction(a, "restore")} disabled={busy?.asset_id === a.asset_id} className="text-xs bg-[#E8F0E1] hover:bg-[#D8E3CB] text-[#4F6B3B] rounded-full px-3 py-1 font-bold inline-flex items-center gap-1 disabled:opacity-50" data-testid={`restore-${a.asset_id}`}><RotateCcw className="w-3 h-3" /> استعد</button>
                                <button onClick={() => doAction(a, "purge")} disabled={busy?.asset_id === a.asset_id} className="text-xs bg-[#FCE6D4] hover:bg-[#F5D8C0] text-[#B8612F] rounded-full px-3 py-1 font-bold inline-flex items-center gap-1 disabled:opacity-50" data-testid={`purge-${a.asset_id}`}><Trash2 className="w-3 h-3" /> طهّر</button>
                              </>
                            )}
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      <div className="bg-[#F8F1E7] border border-[#D4A373]/40 rounded-2xl p-3 mt-4 flex items-start gap-2 text-xs font-body" data-testid="storage-note">
        <AlertTriangle className="w-4 h-4 text-[#8B5A2B] mt-0.5 shrink-0" />
        <span className="text-[#8B5A2B]">
          <b>ملاحظة شفّافة:</b> التطهير يُلغي إشارة الملف من التطبيق فوراً (الرابط لن يعود يُسلَّم للعملاء). الـ object storage الحالي (Emergent) لا يكشف API حذف عام، لذلك قد يظل الملف موجوداً في طبقة التخزين البعيدة لفترة. يُعتبر "محذوفاً" من ناحية التطبيق.
        </span>
      </div>

      <style>{`.input { background:#FDFBF7; border:1px solid #E2D8C9; border-radius:14px; padding:6px 10px; font-family:'Tajawal',sans-serif; font-size:13px; }`}</style>
    </div>
  );
}
