import React, { useEffect, useState } from "react";
import { api } from "../../lib/api";
import { Hourglass, Loader2, Save, RefreshCw, Eye, Play, AlertTriangle, Archive, Trash2 } from "lucide-react";
import { toast } from "sonner";

export default function AdminRetention() {
  const [cfg, setCfg] = useState(null);
  const [preview, setPreview] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [enforcing, setEnforcing] = useState(false);
  const [previewing, setPreviewing] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const { data } = await api.get("/admin/retention/config");
      setCfg(data);
    } catch { toast.error("تعذّر تحميل الإعدادات"); }
    finally { setLoading(false); }
  };
  useEffect(() => { load(); }, []);

  const save = async () => {
    setSaving(true);
    try {
      const payload = {
        min_age_for_archive_days: parseInt(cfg.min_age_for_archive_days) || 0,
        min_archived_days_before_purge: parseInt(cfg.min_archived_days_before_purge) || 0,
        auto_archive_after_delivered_days: parseInt(cfg.auto_archive_after_delivered_days) || 0,
        auto_purge_after_archived_days: parseInt(cfg.auto_purge_after_archived_days) || 0,
        protect_recent_delivered_days: parseInt(cfg.protect_recent_delivered_days) || 0,
        protect_active_bundle_orders: !!cfg.protect_active_bundle_orders,
      };
      const { data } = await api.put("/admin/retention/config", payload);
      setCfg(data); toast.success("تم الحفظ");
    } catch (e) { toast.error(e?.response?.data?.detail || "فشل"); }
    finally { setSaving(false); }
  };

  const doPreview = async () => {
    setPreviewing(true);
    try {
      const { data } = await api.get("/admin/retention/preview");
      setPreview(data);
    } catch { toast.error("فشل المعاينة"); }
    finally { setPreviewing(false); }
  };

  const doEnforce = async () => {
    if (!preview) {
      toast.error("شغّل المعاينة أولاً");
      return;
    }
    if (!window.confirm(`سيتم أرشفة ${preview.to_archive_count} وتطهير ${preview.to_purge_count} أصل. تأكيد؟`)) return;
    setEnforcing(true);
    try {
      const { data } = await api.post("/admin/retention/enforce");
      toast.success(`تم: أُرشف ${data.archived_count}، طُهّر ${data.purged_count}، فشل ${data.failed_count}`);
      doPreview();
    } catch (e) { toast.error(e?.response?.data?.detail || "فشل"); }
    finally { setEnforcing(false); }
  };

  if (loading || !cfg) {
    return <div className="flex items-center justify-center py-20"><Loader2 className="w-6 h-6 animate-spin text-[#87A96B]" /></div>;
  }

  const setF = (k, v) => setCfg({ ...cfg, [k]: v });

  return (
    <div data-testid="admin-retention-page" className="max-w-4xl">
      <div className="mb-6 flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h1 className="font-heading text-3xl font-bold text-[#2D3748] inline-flex items-center gap-2"><Hourglass className="w-7 h-7 text-[#87A96B]" /> سياسة الاحتفاظ بالأصول</h1>
          <p className="font-body text-sm text-[#5A677D] mt-2">قواعد الأرشفة والتطهير التلقائي. يجب تشغيل المعاينة قبل التطبيق.</p>
        </div>
        <button onClick={load} className="rounded-full bg-[#F8F1E7] hover:bg-[#F2E8DA] text-[#8B5A2B] px-4 py-2 text-sm font-bold inline-flex items-center gap-1"><RefreshCw className="w-4 h-4" /> تحديث</button>
      </div>

      <section className="bg-white rounded-2xl p-5 border border-[#E2D8C9] mb-5">
        <h3 className="font-heading text-lg font-bold text-[#2D3748] mb-4">القواعد</h3>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <Field label="حماية الأصول المُسلَّمة حديثاً (أيام)" hint="لا تُؤرشف ولا تُطهّر إن كان الطلب delivered خلال هذه المدة">
            <input type="number" className="input w-full" value={cfg.protect_recent_delivered_days} onChange={(e) => setF("protect_recent_delivered_days", e.target.value)} data-testid="cfg-protect-delivered" />
          </Field>
          <Field label="حد أدنى للعمر قبل الأرشفة اليدوية (أيام)">
            <input type="number" className="input w-full" value={cfg.min_age_for_archive_days} onChange={(e) => setF("min_age_for_archive_days", e.target.value)} data-testid="cfg-min-age-archive" />
          </Field>
          <Field label="حد أدنى لمدة الأرشفة قبل التطهير (أيام)">
            <input type="number" className="input w-full" value={cfg.min_archived_days_before_purge} onChange={(e) => setF("min_archived_days_before_purge", e.target.value)} data-testid="cfg-min-archived" />
          </Field>
          <Field label="أرشفة تلقائية بعد التسليم (أيام)" hint="القاعدة التلقائية للأرشفة في 'enforce'">
            <input type="number" className="input w-full" value={cfg.auto_archive_after_delivered_days} onChange={(e) => setF("auto_archive_after_delivered_days", e.target.value)} data-testid="cfg-auto-archive" />
          </Field>
          <Field label="تطهير تلقائي بعد الأرشفة (أيام)">
            <input type="number" className="input w-full" value={cfg.auto_purge_after_archived_days} onChange={(e) => setF("auto_purge_after_archived_days", e.target.value)} data-testid="cfg-auto-purge" />
          </Field>
          <Field label="حماية الطلبات ذات الـ bundle النشط">
            <label className="inline-flex items-center gap-2"><input type="checkbox" checked={!!cfg.protect_active_bundle_orders} onChange={(e) => setF("protect_active_bundle_orders", e.target.checked)} data-testid="cfg-protect-bundle" /> مفعّلة</label>
          </Field>
        </div>
        <div className="flex justify-end mt-3">
          <button onClick={save} disabled={saving} className="btn-primary inline-flex items-center gap-2" data-testid="save-retention"><Save className="w-4 h-4" /> {saving ? "جاري..." : "حفظ"}</button>
        </div>
      </section>

      <section className="bg-white rounded-2xl p-5 border-2 border-[#87A96B]/40 mb-5">
        <div className="flex items-center justify-between flex-wrap gap-2 mb-4">
          <h3 className="font-heading text-lg font-bold text-[#2D3748]">المعاينة + التطبيق</h3>
          <div className="flex gap-2">
            <button onClick={doPreview} disabled={previewing} className="rounded-full bg-[#F8F1E7] hover:bg-[#F2E8DA] text-[#8B5A2B] px-4 py-2 text-sm font-bold inline-flex items-center gap-1" data-testid="preview-btn">
              {previewing ? <Loader2 className="w-4 h-4 animate-spin" /> : <Eye className="w-4 h-4" />} معاينة
            </button>
            <button onClick={doEnforce} disabled={enforcing || !preview || (preview.to_archive_count + preview.to_purge_count === 0)} className="rounded-full bg-[#FCE6D4] hover:bg-[#F5D8C0] text-[#B8612F] px-4 py-2 text-sm font-bold inline-flex items-center gap-1 disabled:opacity-50" data-testid="enforce-btn">
              {enforcing ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />} تطبيق الآن
            </button>
          </div>
        </div>

        {!preview ? (
          <p className="text-sm text-[#8A9AB0] font-body">شغّل المعاينة لمشاهدة الأصول المتأثرة قبل التطبيق.</p>
        ) : (
          <>
            <div className="grid grid-cols-3 gap-2 mb-4">
              <Stat label="ستُؤرشف" value={preview.to_archive_count} color="amber" />
              <Stat label="ستُطهَّر" value={preview.to_purge_count} color="red" />
              <Stat label="مَحميّة (skipped)" value={preview.skipped_count} color="green" />
            </div>

            {preview.to_archive_count > 0 && (
              <Section title="ستُؤرشف" icon={Archive} items={preview.to_archive} testId="preview-archive" />
            )}
            {preview.to_purge_count > 0 && (
              <Section title="ستُطهَّر" icon={Trash2} items={preview.to_purge} testId="preview-purge" />
            )}
            {preview.skipped_count > 0 && (
              <Section title="محمية" icon={AlertTriangle} items={preview.skipped} testId="preview-skipped" />
            )}
          </>
        )}
      </section>

      <style>{`.input { background:#FDFBF7; border:1px solid #E2D8C9; border-radius:14px; padding:8px 12px; font-family:'Tajawal',sans-serif; font-size:14px; }`}</style>
    </div>
  );
}

function Stat({ label, value, color }) {
  const map = {
    amber: "bg-[#F8F1E7] text-[#8B5A2B]",
    red:   "bg-[#FCE6D4] text-[#B8612F]",
    green: "bg-[#E8F0E1] text-[#4F6B3B]",
  };
  return (
    <div className={`rounded-2xl p-3 text-center ${map[color]}`}>
      <div className="text-xs font-body">{label}</div>
      <div className="text-2xl font-heading font-bold">{value}</div>
    </div>
  );
}

function Section({ title, icon: Icon, items, testId }) {
  return (
    <div className="bg-[#FDFBF7] border border-[#E2D8C9] rounded-2xl p-3 mb-3" data-testid={testId}>
      <div className="font-heading font-bold text-[#2D3748] mb-2 inline-flex items-center gap-2"><Icon className="w-4 h-4" /> {title} ({items.length})</div>
      <div className="text-xs font-body text-[#5A677D] max-h-48 overflow-y-auto">
        {items.slice(0, 30).map((r) => (
          <div key={r.asset_id || `${r.asset_type}-${r.order_id}`} className="border-b border-[#E2D8C9] py-1 flex items-center gap-2">
            <span className="font-bold">{r.asset_type}</span>
            <span>order {r.order_id?.slice(0, 8)}</span>
            <span className="text-[#8A9AB0]">• {r.age_days}d</span>
            <span className="ms-auto text-[#8B5A2B]">{r.matched_rule || r.reason}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function Field({ label, hint, children }) {
  return (
    <label className="block">
      <div className="text-xs text-[#5A677D] font-body mb-1">{label}</div>
      {children}
      {hint && <div className="text-[10px] text-[#8A9AB0] font-body mt-1">{hint}</div>}
    </label>
  );
}
