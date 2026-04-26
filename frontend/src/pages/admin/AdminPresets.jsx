import React, { useEffect, useState } from "react";
import { api } from "../../lib/api";
import { Layers, RefreshCw, Loader2, Play, Eye, Copy, Trash2, Star } from "lucide-react";
import { toast } from "sonner";

const STATUS_COLORS = {
  "real-call":              "bg-[#FCE6D4] text-[#B8612F]",
  "preview-only":           "bg-[#F8F1E7] text-[#8B5A2B]",
  "not-yet-wired":          "bg-[#EEE9E0] text-[#5A677D]",
  "local-binary":           "bg-[#DEEBCF] text-[#3F5B2E]",
  "reuse-from-other-stage": "bg-[#E8F0E1] text-[#4F6B3B]",
};

const SOURCE_COLORS = {
  override: "bg-[#DEEBCF] text-[#3F5B2E]",
  env:      "bg-[#F8F1E7] text-[#8B5A2B]",
  missing:  "bg-[#FCE6D4] text-[#B8612F]",
};

export default function AdminPresets() {
  const [presets, setPresets] = useState([]);
  const [active, setActive] = useState(null);
  const [loading, setLoading] = useState(true);
  const [previewing, setPreviewing] = useState({});
  const [applying, setApplying] = useState({});
  const [dryRun, setDryRun] = useState(null);

  const load = async () => {
    setLoading(true);
    try {
      const [{ data: list }, { data: act }] = await Promise.all([
        api.get("/admin/presets"),
        api.get("/admin/presets/active"),
      ]);
      setPresets(list.items || []);
      setActive(act.active);
    } catch {
      toast.error("تعذّر تحميل الـ presets");
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { load(); }, []);

  const onPreview = async (id) => {
    setPreviewing((s) => ({ ...s, [id]: true }));
    try {
      const { data } = await api.post(`/admin/presets/${id}/dry-run`);
      setDryRun(data);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "تعذّرت المعاينة");
    } finally {
      setPreviewing((s) => ({ ...s, [id]: false }));
    }
  };

  const onApply = async (id, name) => {
    if (!confirm(`تطبيق "${name}" على model_registry؟ سيتم تحديث المراحل المُغطّاة فقط.`)) return;
    setApplying((s) => ({ ...s, [id]: true }));
    try {
      const { data } = await api.post(`/admin/presets/${id}/apply`);
      toast.success(`طُبِّق "${data.preset_name}" على ${data.applied_stages.length} مرحلة`);
      setDryRun(null);
      await load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "تعذّر التطبيق");
    } finally {
      setApplying((s) => ({ ...s, [id]: false }));
    }
  };

  const onClone = async (id) => {
    try {
      await api.post(`/admin/presets/${id}/clone`);
      toast.success("نُسخ — يمكنك تعديله الآن من قاعدة البيانات");
      await load();
    } catch (e) {
      toast.error("تعذّر النسخ");
    }
  };

  const onDelete = async (id, name, isSeeded) => {
    const msg = isSeeded ? `أرشفة "${name}" (preset مُجهَّز — سيُؤرشَف بدل الحذف)؟` : `حذف "${name}"؟`;
    if (!confirm(msg)) return;
    try {
      await api.delete(`/admin/presets/${id}`);
      toast.success("تم");
      await load();
    } catch (e) {
      toast.error("تعذّر");
    }
  };

  if (loading) {
    return <div className="flex items-center justify-center py-20"><Loader2 className="w-6 h-6 animate-spin text-[#87A96B]" /></div>;
  }

  return (
    <div data-testid="admin-presets-page" className="max-w-6xl">
      <div className="mb-6 flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h1 className="font-heading text-3xl font-bold text-[#2D3748] inline-flex items-center gap-2">
            <Layers className="w-7 h-7 text-[#87A96B]" />
            Preset Stacks (مكدّسات الإعداد)
          </h1>
          <p className="font-body text-sm text-[#5A677D] mt-2">
            بدّل بين إعدادات الموفّر/النموذج عبر المراحل بضغطة واحدة. لا تحفظ أيّ مفاتيح خام.
          </p>
        </div>
        <button onClick={load} className="rounded-full bg-[#F8F1E7] hover:bg-[#F2E8DA] text-[#8B5A2B] px-4 py-2 text-sm font-bold inline-flex items-center gap-1" data-testid="reload-presets">
          <RefreshCw className="w-4 h-4" /> تحديث
        </button>
      </div>

      {active && (
        <div className="bg-[#DEEBCF] border border-[#87A96B]/40 rounded-2xl p-3 mb-5 inline-flex items-center gap-2 text-sm" data-testid="active-preset-banner">
          <Star className="w-4 h-4 text-[#3F5B2E]" />
          <span className="font-body text-[#3F5B2E]">
            النشط حالياً: <b>{active.name}</b>
            {active.applied_at && <span className="opacity-70 mr-2"> · طُبِّق {new Date(active.applied_at).toLocaleString("ar-SA")}</span>}
          </span>
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
        {presets.filter(p => !p.is_archived).map((p) => (
          <section key={p.id} className={`bg-white rounded-2xl p-5 border-2 ${p.is_active ? "border-[#87A96B]" : "border-[#E2D8C9]"}`} data-testid={`preset-${p.slug}`}>
            <div className="flex items-start justify-between gap-2 mb-2">
              <div>
                <div className="font-heading font-bold text-[#2D3748] inline-flex items-center gap-2">
                  {p.name}
                  {p.is_active && <span className="bg-[#87A96B] text-white text-[10px] rounded-full px-2 py-0.5 font-bold">نشط</span>}
                  {p.is_seeded && <span className="bg-[#F8F1E7] text-[#8B5A2B] text-[10px] rounded-full px-2 py-0.5">SEEDED</span>}
                </div>
                <div className="text-xs font-mono text-[#8A9AB0]">{p.slug} · {p.intended_use}</div>
              </div>
              <div className="text-xs text-[#5A677D] font-bold">
                {Object.keys(p.stage_map || {}).length} مرحلة
              </div>
            </div>
            <p className="text-sm text-[#5A677D] font-body mb-3 line-clamp-2">{p.description}</p>

            <div className="flex flex-wrap gap-1 mb-3">
              {Object.keys(p.stage_map || {}).slice(0, 6).map((sk) => (
                <span key={sk} className="bg-[#F8F1E7] text-[#8B5A2B] text-[10px] font-mono rounded px-2 py-0.5">{sk}</span>
              ))}
              {Object.keys(p.stage_map || {}).length > 6 && (
                <span className="text-[10px] text-[#8A9AB0]">+{Object.keys(p.stage_map).length - 6}</span>
              )}
            </div>

            <div className="flex flex-wrap gap-2">
              <button onClick={() => onPreview(p.id)} disabled={previewing[p.id]} className="rounded-full bg-[#F8F1E7] hover:bg-[#F2E8DA] text-[#8B5A2B] px-3 py-1.5 text-xs font-bold inline-flex items-center gap-1 disabled:opacity-50" data-testid={`preview-${p.slug}`}>
                {previewing[p.id] ? <Loader2 className="w-3 h-3 animate-spin" /> : <Eye className="w-3 h-3" />}
                معاينة (dry-run)
              </button>
              <button onClick={() => onApply(p.id, p.name)} disabled={applying[p.id]} className="btn-primary text-xs inline-flex items-center gap-1 disabled:opacity-50" data-testid={`apply-${p.slug}`}>
                {applying[p.id] ? <Loader2 className="w-3 h-3 animate-spin" /> : <Play className="w-3 h-3" />}
                تطبيق
              </button>
              <button onClick={() => onClone(p.id)} className="rounded-full bg-[#EEE9E0] hover:bg-[#E2D8C9] text-[#5A677D] px-3 py-1.5 text-xs font-bold inline-flex items-center gap-1" data-testid={`clone-${p.slug}`}>
                <Copy className="w-3 h-3" /> نسخ
              </button>
              <button onClick={() => onDelete(p.id, p.name, p.is_seeded)} className="rounded-full bg-[#FCE6D4] hover:bg-[#F4D2B6] text-[#B8612F] px-3 py-1.5 text-xs font-bold inline-flex items-center gap-1" data-testid={`delete-${p.slug}`}>
                <Trash2 className="w-3 h-3" /> {p.is_seeded ? "أرشفة" : "حذف"}
              </button>
            </div>
          </section>
        ))}
      </div>

      {dryRun && (
        <section className="bg-white rounded-2xl p-5 border-2 border-[#D4A373]/50" data-testid="dry-run-result">
          <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
            <div className="font-heading font-bold text-[#2D3748] inline-flex items-center gap-2">
              <Eye className="w-5 h-5 text-[#8B5A2B]" /> Dry-run: {dryRun.preset_name}
            </div>
            <button onClick={() => setDryRun(null)} className="text-xs text-[#5A677D]">إغلاق</button>
          </div>

          <div className="grid grid-cols-2 md:grid-cols-4 gap-2 mb-3 text-xs font-body">
            <Stat label="مراحل" value={dryRun.summary.stages_in_preset} />
            <Stat label="ستتغيّر" value={dryRun.summary.stages_changed} hl={dryRun.summary.stages_changed > 0} />
            <Stat label="بدون تغيير" value={dryRun.summary.stages_unchanged} />
            <Stat label="غير قابلة للتشغيل" value={dryRun.summary.non_executable_stages?.length || 0} />
          </div>

          {dryRun.warnings?.length > 0 && (
            <div className="bg-[#FCE6D4] border border-[#E07A5F]/40 rounded-2xl p-3 mb-3 text-sm" data-testid="dry-run-warnings">
              <div className="font-bold text-[#B8612F] mb-1">تنبيهات ({dryRun.warnings.length})</div>
              <ul className="text-[#8B3A1F] text-xs space-y-1 list-disc pr-4">
                {dryRun.warnings.map((w, i) => <li key={i}>{w}</li>)}
              </ul>
            </div>
          )}

          <div className="space-y-2">
            {dryRun.diff.map((d) => (
              <div key={d.stage_key} className={`bg-[#FDFBF7] border rounded-2xl p-3 ${d.changed ? "border-[#D4A373]/40" : "border-[#E2D8C9]"}`} data-testid={`diff-${d.stage_key}`}>
                <div className="flex items-center gap-2 mb-2 flex-wrap">
                  <b className="text-[#2D3748] text-sm">{d.stage_name_ar}</b>
                  <span className="text-[10px] font-mono text-[#8A9AB0]">{d.stage_key}</span>
                  <span className={`text-[10px] rounded-full px-2 py-0.5 font-bold ${STATUS_COLORS[d.executor_status] || ""}`}>
                    {d.executor_status}
                  </span>
                  <span className={`text-[10px] rounded-full px-2 py-0.5 font-bold ${SOURCE_COLORS[d.secret_status] || "bg-[#EEE9E0] text-[#5A677D]"}`}>
                    secret: {d.secret_status}
                  </span>
                  {d.changed ? (
                    <span className="text-[10px] bg-[#FCE6D4] text-[#B8612F] rounded-full px-2 py-0.5 font-bold">سيتغيّر</span>
                  ) : (
                    <span className="text-[10px] bg-[#E2D8C9] text-[#5A677D] rounded-full px-2 py-0.5">بدون تغيير</span>
                  )}
                </div>
                {d.executor_warning && (
                  <div className="text-[11px] text-[#8B3A1F] bg-[#FCE6D4] border border-[#E07A5F]/30 rounded-xl px-2 py-1 mb-1">
                    ⚠ {d.executor_warning}
                  </div>
                )}
                {d.changed && (
                  <div className="text-xs font-mono text-[#5A677D] grid grid-cols-2 gap-2">
                    <div className="bg-white rounded px-2 py-1 border border-[#E2D8C9]"><b className="text-[#8A9AB0]">الحالي:</b><br/>{d.current.provider}/{d.current.model_name}<br/><span className="opacity-60">env: {d.current.env_key || "—"}</span></div>
                    <div className="bg-white rounded px-2 py-1 border border-[#D4A373]/40"><b className="text-[#3F5B2E]">الجديد:</b><br/>{d.new.provider}/{d.new.model_name}<br/><span className="opacity-60">env: {d.new.env_key || "—"}</span></div>
                  </div>
                )}
                {d.notes && <div className="text-[10px] text-[#8A9AB0] mt-1 italic">{d.notes}</div>}
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

function Stat({ label, value, hl }) {
  return (
    <div className={`rounded-xl border p-2 ${hl ? "bg-[#F8F1E7] border-[#D4A373]/40" : "bg-[#FDFBF7] border-[#E2D8C9]"}`}>
      <div className="text-[10px] text-[#8A9AB0]">{label}</div>
      <div className="text-base font-bold text-[#2D3748]">{value}</div>
    </div>
  );
}
