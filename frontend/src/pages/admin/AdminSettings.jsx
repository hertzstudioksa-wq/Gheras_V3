import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { Save, Trash2 } from "lucide-react";
import { api } from "../../lib/api";
import { AdminPage, ConfirmAction, PageState } from "../../components/admin/AdminKit";
import { formatDate } from "../../lib/orderStatus";

// System settings (M5b, audit AF-15): only the settings the code reads, each
// with a label, a type and limits. Old keys nothing reads are listed for cleanup.

export default function AdminSettings() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [edits, setEdits] = useState({});

  const load = () => {
    setError(null);
    api.get("/admin/settings").then((r) => setData(r.data)).catch(() => setError("تعذّر تحميل الإعدادات"));
  };
  useEffect(load, []);

  const save = async (it) => {
    try {
      await api.put("/admin/settings", { key: it.key, value: edits[it.key] });
      toast.success("اتحفظ");
      setEdits((e) => { const n = { ...e }; delete n[it.key]; return n; });
      load();
    } catch (e) { toast.error(e?.response?.data?.detail || "فشل الحفظ"); }
  };

  const remove = async (key) => {
    try {
      await api.delete(`/admin/settings/${encodeURIComponent(key)}`);
      toast.success("اتمسح");
      load();
    } catch (e) { toast.error(e?.response?.data?.detail || "فشل"); }
  };

  return (
    <AdminPage title="إعدادات النظام" description="الإعدادات اللي الموقع بيستخدمها فعلاً." testId="admin-settings">
      <PageState loading={!data && !error} error={error} onRetry={load}>
        <div className="bg-white rounded-3xl border border-[#E2D8C9] divide-y divide-[#E2D8C9] mb-6">
          {(data?.items || []).map((it) => {
            const value = edits[it.key] ?? it.value;
            const dirty = edits[it.key] !== undefined && String(edits[it.key]) !== String(it.value);
            return (
              <div key={it.key} className="p-5 flex flex-col md:flex-row md:items-center gap-4" data-testid={`setting-${it.key}`}>
                <div className="flex-1">
                  <div className="font-body font-bold text-[#2D3748]">{it.label_ar}</div>
                  <div className="font-body text-sm text-[#5A677D]">{it.description_ar}</div>
                  <div className="font-body text-xs text-[#8A9AB0] mt-1">
                    من {it.min} لـ {it.max} • الافتراضي {it.default}{it.updated_at ? ` • آخر تعديل ${formatDate(it.updated_at)}` : ""}
                  </div>
                </div>
                <input type="number" min={it.min} max={it.max} value={value}
                  onChange={(e) => setEdits({ ...edits, [it.key]: e.target.value })}
                  className="w-28 bg-[#FDFBF7] border border-[#E2D8C9] rounded-2xl px-4 py-2 font-body text-center" />
                <button onClick={() => save(it)} disabled={!dirty}
                  className="rounded-full bg-[#87A96B] text-white px-5 py-2 text-sm font-bold font-body inline-flex items-center gap-2 disabled:opacity-40">
                  <Save className="w-4 h-4" /> حفظ
                </button>
              </div>
            );
          })}
        </div>

        {data?.unused?.length > 0 && (
          <div className="bg-white rounded-3xl border border-dashed border-[#E2D8C9] p-5">
            <h3 className="font-heading font-bold text-[#2D3748] mb-1">مفاتيح قديمة مش مستخدمة</h3>
            <p className="font-body text-sm text-[#5A677D] mb-3">مفيش حاجة في الموقع بتقراها — ممكن تمسحها.</p>
            <div className="space-y-2">
              {data.unused.map((u) => (
                <div key={u.key} className="flex items-center justify-between gap-3 bg-[#FDFBF7] rounded-2xl px-4 py-2 border border-[#E2D8C9]">
                  <span className="font-mono text-xs text-[#5A677D]" dir="ltr">{u.key} = {JSON.stringify(u.value)}</span>
                  <ConfirmAction title={`تمسح ${u.key}؟`} description="المفتاح ده مش مستخدم في أي حتة." confirmLabel="امسح"
                    onConfirm={() => remove(u.key)} className="text-[#B8612F]" testId={`setting-delete-${u.key}`}>
                    <Trash2 className="w-4 h-4" />
                  </ConfirmAction>
                </div>
              ))}
            </div>
          </div>
        )}
      </PageState>
    </AdminPage>
  );
}
