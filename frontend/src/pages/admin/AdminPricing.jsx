import React, { useEffect, useState } from "react";
import { api } from "../../lib/api";
import { Coins, Save, Loader2, AlertTriangle, RefreshCw } from "lucide-react";
import { toast } from "sonner";

export default function AdminPricing() {
  const [cfg, setCfg] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const { data } = await api.get("/admin/pricing/config");
      setCfg(data);
    } catch (e) {
      toast.error("تعذّر تحميل إعدادات التسعير");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const save = async () => {
    setSaving(true);
    try {
      const payload = {
        currency: cfg.currency,
        markup_percent: parseFloat(cfg.markup_percent),
        minimum_price: parseFloat(cfg.minimum_price),
        rounding: parseFloat(cfg.rounding ?? 1),
        retry_attempt_cost_fraction: parseFloat(cfg.retry_attempt_cost_fraction ?? 0.3),
        per_stage_costs: Object.fromEntries(
          Object.entries(cfg.per_stage_costs || {}).map(([k, v]) => [k, parseFloat(v) || 0])
        ),
        per_output_modifier: Object.fromEntries(
          Object.entries(cfg.per_output_modifier || {}).map(([k, v]) => [k, parseFloat(v) || 1])
        ),
        per_cost_tier_modifier: Object.fromEntries(
          Object.entries(cfg.per_cost_tier_modifier || {}).map(([k, v]) => [k, parseFloat(v) || 1])
        ),
      };
      const { data } = await api.put("/admin/pricing/config", payload);
      setCfg(data);
      toast.success("تم حفظ إعدادات التسعير");
    } catch (e) {
      toast.error(e?.response?.data?.detail || "فشل الحفظ");
    } finally {
      setSaving(false);
    }
  };

  if (loading || !cfg) {
    return (
      <div className="flex items-center justify-center py-20" data-testid="admin-pricing-loading">
        <Loader2 className="w-6 h-6 animate-spin text-[#87A96B]" />
      </div>
    );
  }

  const setField = (k, v) => setCfg((c) => ({ ...c, [k]: v }));
  const setStage = (key, v) => setCfg((c) => ({ ...c, per_stage_costs: { ...c.per_stage_costs, [key]: v } }));
  const setOutMod = (key, v) => setCfg((c) => ({ ...c, per_output_modifier: { ...c.per_output_modifier, [key]: v } }));
  const setTierMod = (key, v) => setCfg((c) => ({ ...c, per_cost_tier_modifier: { ...c.per_cost_tier_modifier, [key]: v } }));

  return (
    <div data-testid="admin-pricing-page" className="max-w-4xl">
      <div className="mb-6 flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h1 className="font-heading text-3xl font-bold text-[#2D3748] inline-flex items-center gap-2">
            <Coins className="w-7 h-7 text-[#87A96B]" />
            التسعير والتكلفة الداخلية
          </h1>
          <p className="font-body text-sm text-[#5A677D] mt-2">
            تكاليف داخلية بالـ {cfg.currency} لكل مرحلة، هامش الربح، والحد الأدنى للسعر. كل طلب يحفظ snapshot عند <b>production_ready</b> وعند <b>delivered</b>.
          </p>
        </div>
        <button onClick={load} className="rounded-full bg-[#F8F1E7] hover:bg-[#F2E8DA] text-[#8B5A2B] px-4 py-2 text-sm font-bold inline-flex items-center gap-1" data-testid="reload-pricing">
          <RefreshCw className="w-4 h-4" /> تحديث
        </button>
      </div>

      <div className="bg-[#F8F1E7] border border-[#D4A373]/40 rounded-2xl p-3 mb-5 flex items-start gap-2 text-sm" data-testid="pricing-warning">
        <AlertTriangle className="w-4 h-4 text-[#8B5A2B] mt-0.5 shrink-0" />
        <span className="font-body text-[#8B5A2B]">
          هذه إعدادات داخلية تؤثر على كل الطلبات الجديدة. الطلبات القديمة تحتفظ بـ snapshot القديم. يمكنك إعادة حساب الـ snapshot يدوياً من صفحة الطلب.
        </span>
      </div>

      <section className="bg-white rounded-2xl p-5 border border-[#E2D8C9] mb-5">
        <h3 className="font-heading text-lg font-bold text-[#2D3748] mb-4">الإعدادات العامة</h3>
        <div className="grid grid-cols-2 gap-4">
          <Field label="العملة">
            <input className="input w-full" value={cfg.currency} onChange={(e) => setField("currency", e.target.value)} data-testid="pricing-currency" />
          </Field>
          <Field label="هامش الربح (%)">
            <input type="number" step="0.5" className="input w-full" value={cfg.markup_percent} onChange={(e) => setField("markup_percent", e.target.value)} data-testid="pricing-markup" />
          </Field>
          <Field label={`الحد الأدنى للسعر (${cfg.currency})`}>
            <input type="number" step="1" className="input w-full" value={cfg.minimum_price} onChange={(e) => setField("minimum_price", e.target.value)} data-testid="pricing-min" />
          </Field>
          <Field label="تقريب السعر إلى">
            <input type="number" step="0.5" className="input w-full" value={cfg.rounding ?? 1} onChange={(e) => setField("rounding", e.target.value)} data-testid="pricing-rounding" />
          </Field>
          <Field label="تكلفة كل محاولة retry إضافية (نسبة من تكلفة المرحلة)">
            <input type="number" step="0.05" className="input w-full" value={cfg.retry_attempt_cost_fraction ?? 0.3} onChange={(e) => setField("retry_attempt_cost_fraction", e.target.value)} data-testid="pricing-retry-frac" />
          </Field>
        </div>
      </section>

      <section className="bg-white rounded-2xl p-5 border border-[#E2D8C9] mb-5">
        <h3 className="font-heading text-lg font-bold text-[#2D3748] mb-4">تكلفة كل مرحلة (وحدة → {cfg.currency})</h3>
        <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
          {Object.entries(cfg.per_stage_costs || {}).map(([k, v]) => (
            <Field key={k} label={k}>
              <input type="number" step="0.01" className="input w-full" value={v} onChange={(e) => setStage(k, e.target.value)} data-testid={`stage-cost-${k}`} />
            </Field>
          ))}
        </div>
      </section>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-5 mb-5">
        <section className="bg-white rounded-2xl p-5 border border-[#E2D8C9]">
          <h3 className="font-heading text-lg font-bold text-[#2D3748] mb-4">معامل نوع التسليم</h3>
          {Object.entries(cfg.per_output_modifier || {}).map(([k, v]) => (
            <Field key={k} label={({video: "فيديو", pdf: "PDF", both: "فيديو + PDF"})[k] || k}>
              <input type="number" step="0.05" className="input w-full" value={v} onChange={(e) => setOutMod(k, e.target.value)} data-testid={`out-mod-${k}`} />
            </Field>
          ))}
        </section>
        <section className="bg-white rounded-2xl p-5 border border-[#E2D8C9]">
          <h3 className="font-heading text-lg font-bold text-[#2D3748] mb-4">معامل فئة المدة</h3>
          {Object.entries(cfg.per_cost_tier_modifier || {}).map(([k, v]) => (
            <Field key={k} label={({low: "اقتصادي", medium: "متوازن", high: "مميّز"})[k] || k}>
              <input type="number" step="0.05" className="input w-full" value={v} onChange={(e) => setTierMod(k, e.target.value)} data-testid={`tier-mod-${k}`} />
            </Field>
          ))}
        </section>
      </div>

      <div className="flex justify-end">
        <button
          onClick={save}
          disabled={saving}
          className="btn-primary inline-flex items-center gap-2 disabled:opacity-60"
          data-testid="save-pricing-btn"
        >
          {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
          حفظ التغييرات
        </button>
      </div>

      <style>{`
        .input {
          background: #FDFBF7;
          border: 1px solid #E2D8C9;
          border-radius: 14px;
          padding: 8px 12px;
          font-family: 'Tajawal', sans-serif;
          color: #2D3748;
          font-size: 14px;
        }
        .input:focus { outline: 2px solid #87A96B; outline-offset: 1px; }
      `}</style>
    </div>
  );
}

function Field({ label, children }) {
  return (
    <label className="block">
      <div className="text-xs text-[#5A677D] font-body mb-1">{label}</div>
      {children}
    </label>
  );
}
