import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { Mail, Save, Send, Trash2 } from "lucide-react";
import { api } from "../../lib/api";
import { AdminPage, ConfirmAction, PageState } from "../../components/admin/AdminKit";
import { formatDate } from "../../lib/orderStatus";

// System settings (M5b, audit AF-15): only the settings the code reads, each
// with a label, a type and limits. Old keys nothing reads are listed for cleanup.

// Email notifications: send a test, and the latest sends.
function NotifyCard() {
  const [log, setLog] = useState(null);
  const [to, setTo] = useState("");
  const [busy, setBusy] = useState(false);
  const load = () => api.get("/admin/notify/log").then((r) => setLog(r.data)).catch(() => setLog({ rows: [], configured: false }));
  useEffect(() => { load(); }, []);
  const test = async () => {
    setBusy(true);
    try {
      const { data } = await api.post("/admin/notify/test", { to });
      if (data.ok) toast.success("اتبعت — شوف صندوق الوارد"); else toast.error(data.error || "ما اتبعتش");
    } catch (e) { toast.error(e?.response?.data?.detail || "فشل"); } finally { setBusy(false); }
  };
  if (!log) return null;
  const KIND = { plan_ready: "خطة جاهزة", delivered: "القصة جاهزة", failed: "مشكلة", ops_failed: "تنبيه: طلب وقع", ops_safety: "تنبيه: مراجعة سلامة" };
  return (
    <div className="bg-white rounded-3xl border border-[#E2D8C9] p-5 mb-6" data-testid="notify-card">
      <h3 className="font-heading font-bold text-[#2D3748] mb-1 inline-flex items-center gap-2"><Mail className="w-4 h-4 text-[#87A96B]" /> الإيميلات</h3>
      <p className="font-body text-sm text-[#5A677D] mb-3">
        {log.configured ? "SMTP متسجّل — الإيميلات بتتبعت تلقائياً." : "SMTP مش متسجّل — مفيش إيميلات بتتبعت. سجّل SMTP_URL من صفحة المفاتيح."}
      </p>
      <div className="flex gap-2 flex-wrap mb-4">
        <input type="email" value={to} onChange={(e) => setTo(e.target.value)} placeholder="ابعت تجربة لـ name@example.com" dir="ltr"
          className="flex-1 min-w-[220px] bg-[#FDFBF7] border border-[#E2D8C9] rounded-2xl px-4 py-2 font-body" />
        <button onClick={test} disabled={!log.configured || busy || !to.includes("@")}
          className="rounded-full bg-[#87A96B] text-white px-5 py-2 text-sm font-bold font-body inline-flex items-center gap-2 disabled:opacity-40">
          <Send className="w-4 h-4" /> جرّب الإيميل
        </button>
      </div>
      {log.rows.length > 0 && (
        <div className="divide-y divide-[#F0E9DD] font-body text-sm">
          {log.rows.slice(0, 10).map((r) => (
            <div key={r.id} className="py-2 flex justify-between gap-3">
              <span>{KIND[r.kind] || r.kind} → <span dir="ltr">{r.to}</span></span>
              <span className={r.ok ? "text-[#4F6B3B]" : "text-[#B8612F]"} title={r.error || ""}>{r.ok ? "اتبعت" : "فشل"} · {formatDate(r.at)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

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
            const numeric = it.type === "int" || it.type === "float";
            return (
              <div key={it.key} className="p-5 flex flex-col md:flex-row md:items-center gap-4" data-testid={`setting-${it.key}`}>
                <div className="flex-1">
                  <div className="font-body font-bold text-[#2D3748]">{it.label_ar}</div>
                  <div className="font-body text-sm text-[#5A677D]">{it.description_ar}</div>
                  <div className="font-body text-xs text-[#8A9AB0] mt-1">
                    {numeric ? `من ${it.min} لـ ${it.max} • الافتراضي ${it.default}` : ""}
                    {it.updated_at ? `${numeric ? " • " : ""}آخر تعديل ${formatDate(it.updated_at)}` : ""}
                  </div>
                </div>
                {it.type === "bool" ? (
                  <label className="inline-flex items-center gap-2 font-body text-sm cursor-pointer">
                    <input type="checkbox" checked={!!value} onChange={(e) => setEdits({ ...edits, [it.key]: e.target.checked })}
                      className="w-5 h-5 accent-[#87A96B]" />
                    {value ? "شغّال" : "موقوف"}
                  </label>
                ) : it.type === "email" ? (
                  <input type="email" value={value || ""} placeholder="name@example.com" dir="ltr"
                    onChange={(e) => setEdits({ ...edits, [it.key]: e.target.value })}
                    className="md:w-64 bg-[#FDFBF7] border border-[#E2D8C9] rounded-2xl px-4 py-2 font-body" />
                ) : (
                  <input type="number" min={it.min} max={it.max} step={it.type === "float" ? it.step || "any" : 1}
                    value={value} dir="ltr"
                    onChange={(e) => setEdits({ ...edits, [it.key]: e.target.value })}
                    className={`${it.type === "float" ? "w-32" : "w-28"} bg-[#FDFBF7] border border-[#E2D8C9] rounded-2xl px-4 py-2 font-body text-center`} />
                )}
                <button onClick={() => save(it)} disabled={!dirty}
                  className="rounded-full bg-[#87A96B] text-white px-5 py-2 text-sm font-bold font-body inline-flex items-center gap-2 disabled:opacity-40">
                  <Save className="w-4 h-4" /> حفظ
                </button>
              </div>
            );
          })}
        </div>

        <NotifyCard />

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
