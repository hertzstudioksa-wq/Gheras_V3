import React, { useEffect, useState } from "react";
import { api } from "../../lib/api";
import { CreditCard, Save, Loader2, RefreshCw, ShieldCheck, ShieldAlert, AlertTriangle } from "lucide-react";
import { toast } from "sonner";

export default function AdminPaymentSettings() {
  const [settings, setSettings] = useState(null);
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [payments, setPayments] = useState([]);

  const load = async () => {
    setLoading(true);
    try {
      const [s, st, p] = await Promise.all([
        api.get("/admin/payment/settings"),
        api.get("/admin/payment/status"),
        api.get("/admin/payment/payments?limit=20"),
      ]);
      setSettings(s.data); setStatus(st.data); setPayments(p.data?.payments || []);
    } catch { toast.error("تعذّر تحميل إعدادات الدفع"); }
    finally { setLoading(false); }
  };
  useEffect(() => { load(); }, []);

  const save = async () => {
    setSaving(true);
    try {
      const { data } = await api.put("/admin/payment/settings", {
        publishable_key: settings.publishable_key,
        sandbox_mode: !!settings.sandbox_mode,
        supported_methods: settings.supported_methods,
        supported_currencies: settings.supported_currencies,
        payout_destination_label: settings.payout_destination_label,
        apple_pay_domain_verified: !!settings.apple_pay_domain_verified,
      });
      setSettings(data); toast.success("تم الحفظ");
    } catch (e) { toast.error(e?.response?.data?.detail || "فشل"); }
    finally { setSaving(false); }
  };

  if (loading || !settings || !status) {
    return <div className="flex items-center justify-center py-20"><Loader2 className="w-6 h-6 animate-spin text-[#87A96B]" /></div>;
  }

  return (
    <div data-testid="admin-payment-settings-page" className="max-w-4xl">
      <div className="mb-6 flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h1 className="font-heading text-3xl font-bold text-[#2D3748] inline-flex items-center gap-2"><CreditCard className="w-7 h-7 text-[#87A96B]" /> الدفع و Stripe</h1>
          <p className="font-body text-sm text-[#5A677D] mt-2">إعدادات الدفع والإعدادات العامة. الأسرار الفعلية في .env.</p>
        </div>
        <button onClick={load} className="rounded-full bg-[#F8F1E7] hover:bg-[#F2E8DA] text-[#8B5A2B] px-4 py-2 text-sm font-bold inline-flex items-center gap-1"><RefreshCw className="w-4 h-4" /> تحديث</button>
      </div>

      {/* Provider status */}
      <section className={`rounded-2xl p-5 mb-5 border-2 ${status.active ? "bg-[#E8F0E1] border-[#87A96B]/40" : "bg-[#FCE6D4] border-[#E07A5F]/40"}`} data-testid="payment-status">
        <div className="flex items-center gap-3 mb-3">
          {status.active ? <ShieldCheck className="w-5 h-5 text-[#4F6B3B]" /> : <ShieldAlert className="w-5 h-5 text-[#B8612F]" />}
          <h3 className="font-heading font-bold text-[#2D3748]">حالة المزوّد: <span className={status.active ? "text-[#4F6B3B]" : "text-[#B8612F]"}>{status.active ? "مفعّل" : "غير مفعّل"}</span></h3>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-3 gap-2 text-xs font-body mb-3">
          <Stat label="STRIPE_API_KEY" v={status.secret_key_configured ? `✓ ${status.secret_key_masked || ""}` : "✗ مفقود"} />
          <Stat label="Publishable key" v={status.publishable_key_configured ? "✓" : "✗"} />
          <Stat label="Webhook secret" v={status.webhook_secret_configured ? "✓" : "✗ (موصى به)"} />
          <Stat label="Sandbox" v={status.sandbox_mode ? "نعم" : "لا"} />
        </div>
        <div className="bg-white/60 rounded-xl p-3 text-xs font-body text-[#2D3748] flex items-start gap-2">
          <AlertTriangle className="w-4 h-4 text-[#8B5A2B] mt-0.5 shrink-0" />
          <span>{status.note_ar}</span>
        </div>
      </section>

      {/* Settings form */}
      <section className="bg-white rounded-2xl p-5 border border-[#E2D8C9] mb-5">
        <h3 className="font-heading text-lg font-bold text-[#2D3748] mb-4">الإعدادات العامة</h3>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <Field label="Publishable Key (آمن للنشر)">
            <input className="input w-full" value={settings.publishable_key || ""} onChange={(e) => setSettings({ ...settings, publishable_key: e.target.value })} placeholder="pk_test_..." data-testid="pub-key" />
          </Field>
          <Field label="وضع التطوير">
            <label className="inline-flex items-center gap-2"><input type="checkbox" checked={!!settings.sandbox_mode} onChange={(e) => setSettings({ ...settings, sandbox_mode: e.target.checked })} data-testid="sandbox-toggle" /> Sandbox</label>
          </Field>
          <Field label="طرق الدفع (مفصولة بفاصلة)">
            <input className="input w-full" value={(settings.supported_methods || []).join(", ")} onChange={(e) => setSettings({ ...settings, supported_methods: e.target.value.split(",").map(s => s.trim()).filter(Boolean) })} />
          </Field>
          <Field label="العملات (مفصولة بفاصلة)">
            <input className="input w-full" value={(settings.supported_currencies || []).join(", ")} onChange={(e) => setSettings({ ...settings, supported_currencies: e.target.value.split(",").map(s => s.trim()).filter(Boolean) })} />
          </Field>
          <Field label="وجهة التحويل البنكي (نصياً فقط — معلوماتية)">
            <input className="input w-full" value={settings.payout_destination_label || ""} onChange={(e) => setSettings({ ...settings, payout_destination_label: e.target.value })} placeholder="مثال: مصرف الراجحي — IBAN ينتهي بـ 1234" />
          </Field>
          <Field label="Apple Pay domain verified">
            <label className="inline-flex items-center gap-2"><input type="checkbox" checked={!!settings.apple_pay_domain_verified} onChange={(e) => setSettings({ ...settings, apple_pay_domain_verified: e.target.checked })} /> تم التحقّق من الدومين في Stripe Dashboard</label>
          </Field>
        </div>
        <p className="text-xs text-[#8A9AB0] font-body mt-3">
          <b>ملاحظة:</b> Apple Pay طريقة دفع للعميل (يختارها في صفحة Stripe على أجهزة Apple). الأرباح تُحوَّل إلى الحساب البنكي للتاجر، وليس إلى Apple Pay wallet.
        </p>
        <div className="flex justify-end mt-3">
          <button onClick={save} disabled={saving} className="btn-primary inline-flex items-center gap-2" data-testid="save-payment-settings"><Save className="w-4 h-4" /> {saving ? "جاري..." : "حفظ"}</button>
        </div>
      </section>

      {/* Recent payments */}
      <section className="bg-white rounded-2xl p-5 border border-[#E2D8C9]" data-testid="payments-table">
        <h3 className="font-heading text-lg font-bold text-[#2D3748] mb-3">آخر العمليات</h3>
        {payments.length === 0 ? (
          <p className="text-sm text-[#8A9AB0] font-body">لا توجد عمليات دفع بعد.</p>
        ) : (
          <table className="w-full text-sm font-body">
            <thead className="text-xs text-[#5A677D]">
              <tr className="border-b border-[#E2D8C9]"><th className="py-2 text-right">المستخدم</th><th>الباقة</th><th>المبلغ</th><th>الحالة</th><th>التاريخ</th></tr>
            </thead>
            <tbody>
              {payments.map(p => (
                <tr key={p.id} className="border-b border-[#E2D8C9]">
                  <td className="py-2">{p.user_email || p.user_id?.slice(0, 8)}</td>
                  <td>{p.bundle_snapshot?.name || p.bundle_id?.slice(0, 8)}</td>
                  <td>{p.amount} {p.currency}</td>
                  <td><span className="text-xs px-2 py-0.5 rounded-full bg-[#FDFBF7] border border-[#E2D8C9]">{p.payment_status || p.status}</span></td>
                  <td className="text-xs text-[#8A9AB0]">{p.created_at?.slice(0, 16)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <style>{`.input { background:#FDFBF7; border:1px solid #E2D8C9; border-radius:14px; padding:8px 12px; font-family:'Tajawal',sans-serif; font-size:14px; }`}</style>
    </div>
  );
}

function Stat({ label, v }) { return <div className="bg-white/70 rounded-xl px-2 py-1"><div className="text-[10px] text-[#8A9AB0]">{label}</div><b className="text-[#2D3748]">{v}</b></div>; }
function Field({ label, children }) { return <label className="block"><div className="text-xs text-[#5A677D] font-body mb-1">{label}</div>{children}</label>; }
