import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { Gift, Loader2, Plus, Save, Trash2, Wallet, X } from "lucide-react";
import { api } from "../../lib/api";
import { AdminPage, ConfirmAction, PageState, useDebounced } from "../../components/admin/AdminKit";
import { formatDate } from "../../lib/orderStatus";

// Top-ups and customer balances (M6): bundles are now wallet credit — the parent
// pays `price` and gets `credit_sar` (the difference is the bonus). The older
// per-story bundles stay listed for purchases that still have credits.

const OUTPUT_LABEL = { video: "فيديو", pdf: "كتاب PDF", both: "فيديو + PDF" };
const sar = (v) => `${Number(v || 0).toLocaleString("en-US", { maximumFractionDigits: 2 })} ر.س`;
const input = "w-full bg-[#FDFBF7] border border-[#E2D8C9] rounded-2xl px-3 py-2 font-body text-sm";

export default function AdminBundles() {
  const [bundles, setBundles] = useState(null);
  const [error, setError] = useState(null);
  const [editing, setEditing] = useState(null);
  const [granting, setGranting] = useState(null);

  const load = () => {
    setError(null);
    api.get("/admin/bundles").then((r) => setBundles(r.data.bundles || [])).catch(() => setError("تعذّر تحميل الباقات"));
  };
  useEffect(load, []);

  const save = async (b) => {
    try {
      if (b.id) await api.put(`/admin/bundles/${b.id}`, b);
      else await api.post("/admin/bundles", b);
      toast.success("اتحفظ");
      setEditing(null);
      load();
    } catch (e) { toast.error(e?.response?.data?.detail || "فشل الحفظ"); }
  };
  const deactivate = async (b) => {
    try { await api.delete(`/admin/bundles/${b.id}`); toast.success("اتوقفت — مش هتظهر للعملاء"); load(); }
    catch (e) { toast.error(e?.response?.data?.detail || "فشل"); }
  };

  const topups = (bundles || []).filter((b) => b.credit_sar).sort((a, b) => a.price - b.price);
  const legacy = (bundles || []).filter((b) => !b.credit_sar);
  return (
    <AdminPage title="الباقات والرصيد" testId="admin-bundles-page"
      description="باقات الشحن: العميل يدفع السعر ورصيده يزيد بقيمة أكبر (الفرق هدية). الرصيد بيدفع أي قصة. تحت: رصيد أي عميل وتعديله."
      actions={<button onClick={() => setEditing({ name: "", description: "", price: 100, credit_sar: 110, is_active: true })}
        className="btn-primary inline-flex items-center gap-2" data-testid="add-bundle-btn"><Plus className="w-4 h-4" /> باقة شحن جديدة</button>}>
      <PageState loading={!bundles && !error} error={error} onRetry={load}>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-8">
          {topups.map((b) => (
            <div key={b.id} className={`bg-white rounded-3xl p-5 border-2 ${b.is_active ? "border-[#E2D8C9]" : "border-dashed border-[#E2D8C9] opacity-60"}`} data-testid={`bundle-${b.id}`}>
              <div className="flex items-start justify-between gap-2 mb-2">
                <h3 className="font-heading text-lg font-bold text-[#2D3748]">{b.name}</h3>
                <span className={`text-xs font-bold rounded-full px-2 py-0.5 shrink-0 ${b.is_active ? "bg-[#E8F0E1] text-[#4F6B3B]" : "bg-[#FCE6D4] text-[#B8612F]"}`}>{b.is_active ? "معروضة" : "موقوفة"}</span>
              </div>
              <p className="font-body text-xs text-[#5A677D] mb-3 min-h-[32px]">{b.description}</p>
              <div className="font-body text-sm mb-4">
                يدفع <b>{sar(b.price)}</b> ← رصيد <b className="text-[#4F6B3B]">{sar(b.credit_sar)}</b>
                {b.credit_sar > b.price && <span className="text-xs text-[#4F6B3B]"> (هدية {Math.round((b.credit_sar / b.price - 1) * 100)}%)</span>}
              </div>
              <div className="flex gap-2 flex-wrap">
                <button onClick={() => setEditing(b)} className="text-xs bg-[#F8F1E7] text-[#8B5A2B] rounded-full px-3 py-1 font-body font-bold">تعديل</button>
                {b.is_active && (
                  <button onClick={() => setGranting(b)} className="text-xs bg-[#E8F0E1] text-[#4F6B3B] rounded-full px-3 py-1 font-body font-bold inline-flex items-center gap-1"><Gift className="w-3 h-3" /> امنحها لعميل</button>
                )}
                {b.is_active && (
                  <ConfirmAction title={`توقف "${b.name}"؟`} description="مش هتظهر للعملاء. الرصيد اللي اتشحن قبل كده مش بيتأثر."
                    confirmLabel="أوقفها" onConfirm={() => deactivate(b)}
                    className="text-xs bg-[#FCE6D4] text-[#B8612F] rounded-full px-3 py-1 font-body font-bold inline-flex items-center gap-1">
                    <Trash2 className="w-3 h-3" /> إيقاف
                  </ConfirmAction>
                )}
              </div>
            </div>
          ))}
        </div>

        <WalletAdmin />

        {legacy.length > 0 && (
          <details className="mt-8">
            <summary className="font-heading text-lg font-bold text-[#5A677D] cursor-pointer">باقات القصص القديمة ({legacy.length})</summary>
            <p className="font-body text-xs text-[#8A9AB0] my-2">قبل الرصيد بالريال: كل باقة عدد قصص. موقوفة عن البيع؛ اللي اشتراها لسه يقدر يستخدم قصصه الباقية.</p>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {legacy.map((b) => (
                <div key={b.id} className="bg-white rounded-2xl p-4 border border-dashed border-[#E2D8C9] font-body text-sm flex items-center justify-between gap-3">
                  <div>
                    <div className="font-bold text-[#2D3748]">{b.name}</div>
                    <div className="text-xs text-[#5A677D]">{b.quantity}× {OUTPUT_LABEL[b.output_type]} · {sar(b.price)} · {b.validity_days} يوم</div>
                  </div>
                  <span className={`text-xs font-bold rounded-full px-2 py-0.5 ${b.is_active ? "bg-[#E8F0E1] text-[#4F6B3B]" : "bg-[#F0E9DD] text-[#8A9AB0]"}`}>{b.is_active ? "معروضة" : "موقوفة"}</span>
                </div>
              ))}
            </div>
          </details>
        )}
      </PageState>

      {editing && <TopupEditor bundle={editing} onClose={() => setEditing(null)} onSave={save} />}
      {granting && <GrantModal bundle={granting} onClose={() => setGranting(null)} />}
    </AdminPage>
  );
}

function TopupEditor({ bundle, onClose, onSave }) {
  const [b, setB] = useState({ ...bundle });
  return (
    <div className="fixed inset-0 bg-black/50 z-40 flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-[#FDFBF7] rounded-3xl max-w-md w-full p-6" onClick={(e) => e.stopPropagation()} data-testid="bundle-editor">
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-heading text-xl font-bold text-[#2D3748]">{b.id ? "تعديل باقة شحن" : "باقة شحن جديدة"}</h2>
          <button onClick={onClose} aria-label="إغلاق"><X className="w-5 h-5 text-[#5A677D]" /></button>
        </div>
        <div className="space-y-3">
          <Field label="الاسم"><input className={input} value={b.name || ""} onChange={(e) => setB({ ...b, name: e.target.value })} data-testid="bundle-name" /></Field>
          <Field label="الوصف للعميل"><textarea className={input} rows={2} value={b.description || ""} onChange={(e) => setB({ ...b, description: e.target.value })} /></Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="العميل يدفع (ر.س)"><input type="number" className={input} value={b.price} onChange={(e) => setB({ ...b, price: parseFloat(e.target.value) || 0 })} data-testid="bundle-price" /></Field>
            <Field label="الرصيد اللي ياخده (ر.س)"><input type="number" className={input} value={b.credit_sar} onChange={(e) => setB({ ...b, credit_sar: parseFloat(e.target.value) || 0 })} data-testid="bundle-credit" /></Field>
          </div>
          {b.credit_sar > b.price && <p className="font-body text-xs text-[#4F6B3B]">هدية {sar(b.credit_sar - b.price)}</p>}
          <label className="inline-flex items-center gap-2 font-body text-sm cursor-pointer">
            <input type="checkbox" checked={!!b.is_active} onChange={(e) => setB({ ...b, is_active: e.target.checked })} /> معروضة للعملاء
          </label>
          <div className="flex justify-end gap-2 pt-2">
            <button onClick={onClose} className="rounded-full bg-[#F8F1E7] text-[#8B5A2B] px-5 py-2 text-sm font-bold">إلغاء</button>
            <button onClick={() => onSave(b)} className="btn-primary inline-flex items-center gap-2" data-testid="save-bundle"><Save className="w-4 h-4" /> حفظ</button>
          </div>
        </div>
      </div>
    </div>
  );
}

function useUserSearch(q) {
  const [users, setUsers] = useState([]);
  const debounced = useDebounced(q);
  useEffect(() => {
    api.get("/admin/users", { params: { q: debounced, role: "user", limit: 20 } })
      .then((r) => setUsers((r.data?.items || []).map((u) => ({ id: u.id, label: `${u.email}${u.full_name ? " — " + u.full_name : ""}` }))))
      .catch(() => setUsers([]));
  }, [debounced]);
  return users;
}

function GrantModal({ bundle, onClose }) {
  const [q, setQ] = useState("");
  const [selected, setSelected] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const users = useUserSearch(q);

  const grant = async () => {
    if (!selected) return toast.error("اختار العميل");
    setBusy(true);
    try {
      await api.post(`/admin/bundles/${bundle.id}/grant`, { user_id: selected, reason: reason || "منحة من الإدارة" });
      toast.success(`اتضاف ${sar(bundle.credit_sar)} لرصيده`);
      onClose();
    } catch (e) { toast.error(e?.response?.data?.detail || "فشل"); } finally { setBusy(false); }
  };

  return (
    <div className="fixed inset-0 bg-black/50 z-40 flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-[#FDFBF7] rounded-3xl max-w-md w-full p-6" onClick={(e) => e.stopPropagation()} data-testid="grant-modal">
        <h2 className="font-heading text-lg font-bold text-[#2D3748] mb-1">امنح "{bundle.name}"</h2>
        <p className="font-body text-xs text-[#5A677D] mb-3">يتضاف {sar(bundle.credit_sar)} لرصيد العميل من غير دفع.</p>
        <Field label="ابحث"><input className={input} value={q} onChange={(e) => setQ(e.target.value)} placeholder="الاسم أو الإيميل" /></Field>
        <Field label="العميل">
          <select className={input} value={selected} onChange={(e) => setSelected(e.target.value)} data-testid="grant-user-select">
            <option value="">— اختار —</option>
            {users.map((u) => <option key={u.id} value={u.id}>{u.label}</option>)}
          </select>
        </Field>
        <Field label="السبب"><input className={input} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="تعويض، هدية، تجربة…" /></Field>
        <div className="flex justify-end gap-2 pt-3">
          <button onClick={onClose} className="rounded-full bg-[#F8F1E7] text-[#8B5A2B] px-4 py-2 text-sm font-bold">إلغاء</button>
          <button onClick={grant} disabled={busy} className="btn-primary inline-flex items-center gap-2" data-testid="grant-confirm-btn">
            {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Gift className="w-4 h-4" />} امنح
          </button>
        </div>
      </div>
    </div>
  );
}

function WalletAdmin() {
  const [q, setQ] = useState("");
  const [selected, setSelected] = useState("");
  const [wallet, setWallet] = useState(null);
  const [amount, setAmount] = useState("");
  const [reason, setReason] = useState("");
  const [publicNote, setPublicNote] = useState("");
  const users = useUserSearch(q);

  useEffect(() => {
    setWallet(null);
    if (selected) api.get(`/admin/wallets/${selected}`).then((r) => setWallet(r.data)).catch(() => toast.error("تعذّر تحميل الرصيد"));
  }, [selected]);

  const adjust = async () => {
    try {
      const r = await api.post(`/admin/wallets/${selected}/adjust`,
        { amount_sar: Number(amount), reason, public_note: publicNote.trim() || null });
      setWallet(r.data);
      setAmount("");
      setReason("");
      setPublicNote("");
      toast.success("اتعدّل الرصيد");
    } catch (e) { toast.error(e?.response?.data?.detail || "فشل"); }
  };

  return (
    <section className="bg-white rounded-3xl border border-[#E2D8C9] p-5" data-testid="wallet-admin">
      <h2 className="font-heading text-xl font-bold text-[#729352] mb-3 inline-flex items-center gap-2"><Wallet className="w-5 h-5" /> رصيد عميل</h2>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mb-4">
        <input className={input} value={q} onChange={(e) => setQ(e.target.value)} placeholder="ابحث بالاسم أو الإيميل" />
        <select className={input} value={selected} onChange={(e) => setSelected(e.target.value)} data-testid="wallet-user-select">
          <option value="">— اختار العميل —</option>
          {users.map((u) => <option key={u.id} value={u.id}>{u.label}</option>)}
        </select>
      </div>
      {selected && !wallet && <Loader2 className="w-5 h-5 animate-spin text-[#87A96B]" />}
      {wallet && (
        <>
          <div className="font-heading text-3xl font-bold text-[#2D3748] mb-4" data-testid="admin-wallet-balance">{sar(wallet.balance_halalas / 100)}</div>
          <div className="grid grid-cols-1 sm:grid-cols-[140px_1fr_auto] gap-2 mb-5 items-start">
            <input type="number" className={input} value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="+50 أو −20" dir="ltr" />
            <div className="space-y-2">
              <input className={input} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="السبب (داخلي — للسجل بس)" />
              <input className={input} value={publicNote} onChange={(e) => setPublicNote(e.target.value)}
                placeholder="رسالة للعميل في حركاته (اختياري — وإلا: «تعديل رصيد من فريق غِراس»)" />
            </div>
            <ConfirmAction title={`${Number(amount) >= 0 ? "تضيف" : "تخصم"} ${sar(Math.abs(Number(amount) || 0))}؟`}
              description={reason ? `السبب: ${reason}` : "اكتب السبب الأول"} tone="cost" confirmLabel="تأكيد"
              disabled={!Number(amount) || reason.trim().length < 3} onConfirm={adjust}
              className="rounded-full bg-[#87A96B] text-white px-5 py-2 text-sm font-bold font-body disabled:opacity-40">
              تعديل الرصيد
            </ConfirmAction>
          </div>
          <div className="divide-y divide-[#F0E9DD] font-body text-sm">
            {wallet.history.length === 0 && <div className="text-[#8A9AB0] py-2">مفيش حركات</div>}
            {wallet.history.map((h) => (
              <div key={h.id} className="py-2 flex justify-between gap-3">
                <div className="min-w-0">
                  <b className="text-[#2D3748]">{h.kind_ar}</b> <span className="text-[#5A677D]">{h.note}</span>
                  {h.public_note && <span className="text-[#4F6B3B]"> · للعميل: {h.public_note}</span>}
                  <div className="text-xs text-[#8A9AB0]">{formatDate(h.created_at)}{h.actor_email ? ` — ${h.actor_email}` : ""}</div>
                </div>
                <b className={h.amount_halalas > 0 ? "text-[#4F6B3B]" : "text-[#B8612F]"} dir="ltr">{h.amount_halalas > 0 ? "+" : "−"}{Math.abs(h.amount_halalas) / 100}</b>
              </div>
            ))}
          </div>
        </>
      )}
    </section>
  );
}

function Field({ label, children }) {
  return <label className="block mb-2"><div className="text-xs text-[#5A677D] font-body mb-1">{label}</div>{children}</label>;
}
