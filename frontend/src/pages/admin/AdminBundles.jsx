import React, { useEffect, useState } from "react";
import { api } from "../../lib/api";
import { Package, Plus, Trash2, Save, X, Loader2, Gift, RefreshCw } from "lucide-react";
import { toast } from "sonner";

const OUTPUT_LABEL = { video: "فيديو", pdf: "كتاب PDF", both: "فيديو + PDF" };

export default function AdminBundles() {
  const [bundles, setBundles] = useState([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(null); // bundle being edited (or {} for new)
  const [grantOpen, setGrantOpen] = useState(null); // bundle whose grant modal is open

  const load = async () => {
    setLoading(true);
    try {
      const { data } = await api.get("/admin/bundles");
      setBundles(data.bundles || []);
    } catch { toast.error("تعذّر تحميل الباقات"); }
    finally { setLoading(false); }
  };
  useEffect(() => { load(); }, []);

  const onSave = async (b) => {
    try {
      if (b.id) {
        await api.put(`/admin/bundles/${b.id}`, b);
      } else {
        await api.post("/admin/bundles", b);
      }
      toast.success("تم الحفظ");
      setEditing(null); load();
    } catch (e) { toast.error(e?.response?.data?.detail || "فشل"); }
  };
  const onDelete = async (b) => {
    if (!window.confirm(`تعطيل باقة "${b.name}"؟ (الشراءات الحالية لن تتأثر)`)) return;
    try { await api.delete(`/admin/bundles/${b.id}`); toast.success("تم"); load(); }
    catch (e) { toast.error(e?.response?.data?.detail || "فشل"); }
  };

  return (
    <div data-testid="admin-bundles-page" className="max-w-5xl">
      <div className="mb-6 flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h1 className="font-heading text-3xl font-bold text-[#2D3748] inline-flex items-center gap-2">
            <Package className="w-7 h-7 text-[#87A96B]" /> الباقات والـ Bundles
          </h1>
          <p className="font-body text-sm text-[#5A677D] mt-2">
            باقات قابلة للشراء (أو المنح يدوياً). كل باقة تمنح عدداً محدداً من القصص ضمن مدة صلاحية.
          </p>
        </div>
        <div className="flex gap-2">
          <button onClick={load} className="rounded-full bg-[#F8F1E7] hover:bg-[#F2E8DA] text-[#8B5A2B] px-4 py-2 text-sm font-bold inline-flex items-center gap-1" data-testid="reload-bundles">
            <RefreshCw className="w-4 h-4" /> تحديث
          </button>
          <button onClick={() => setEditing({ name: "", output_type: "both", quantity: 5, validity_days: 90, price: 0, currency: "SAR", is_active: true })} className="btn-primary inline-flex items-center gap-2" data-testid="add-bundle-btn">
            <Plus className="w-4 h-4" /> باقة جديدة
          </button>
        </div>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-12"><Loader2 className="w-6 h-6 animate-spin text-[#87A96B]" /></div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {bundles.map((b) => (
            <div key={b.id} className={`bg-white rounded-2xl p-5 border-2 ${b.is_active ? "border-[#E2D8C9]" : "border-dashed border-[#E2D8C9] opacity-70"}`} data-testid={`bundle-${b.id}`}>
              <div className="flex items-center justify-between gap-2 mb-2">
                <div>
                  <h3 className="font-heading text-lg font-bold text-[#2D3748]">{b.name}</h3>
                  <p className="text-xs text-[#5A677D] font-body">{b.description || "—"}</p>
                </div>
                <span className={`text-xs font-bold rounded-full px-2 py-0.5 ${b.is_active ? "bg-[#E8F0E1] text-[#4F6B3B]" : "bg-[#FCE6D4] text-[#B8612F]"}`}>
                  {b.is_active ? "نشطة" : "معطّلة"}
                </span>
              </div>
              <div className="grid grid-cols-2 gap-2 mb-3 text-sm font-body">
                <Stat label="نوع التسليم" v={OUTPUT_LABEL[b.output_type]} />
                <Stat label="الكمية" v={b.quantity} />
                <Stat label="الصلاحية (يوم)" v={b.validity_days} />
                <Stat label="السعر" v={`${b.price} ${b.currency}`} />
              </div>
              <div className="flex gap-2 flex-wrap">
                <button onClick={() => setEditing(b)} className="text-xs bg-[#F8F1E7] hover:bg-[#F2E8DA] text-[#8B5A2B] rounded-full px-3 py-1 font-body font-bold" data-testid={`edit-bundle-${b.id}`}>تعديل</button>
                <button onClick={() => setGrantOpen(b)} className="text-xs bg-[#E8F0E1] hover:bg-[#D8E3CB] text-[#4F6B3B] rounded-full px-3 py-1 font-body font-bold inline-flex items-center gap-1" data-testid={`grant-bundle-${b.id}`}><Gift className="w-3 h-3" /> منح لمستخدم</button>
                {b.is_active && (
                  <button onClick={() => onDelete(b)} className="text-xs bg-[#FCE6D4] hover:bg-[#F5D8C0] text-[#B8612F] rounded-full px-3 py-1 font-body font-bold inline-flex items-center gap-1" data-testid={`delete-bundle-${b.id}`}><Trash2 className="w-3 h-3" /> تعطيل</button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {editing && <BundleEditor bundle={editing} onClose={() => setEditing(null)} onSave={onSave} />}
      {grantOpen && <GrantModal bundle={grantOpen} onClose={() => setGrantOpen(null)} onGranted={() => { setGrantOpen(null); load(); }} />}

      <style>{`
        .input { background:#FDFBF7; border:1px solid #E2D8C9; border-radius:14px; padding:8px 12px; font-family:'Tajawal',sans-serif; color:#2D3748; font-size:14px; }
        .input:focus { outline:2px solid #87A96B; outline-offset:1px; }
      `}</style>
    </div>
  );
}

function Stat({ label, v }) {
  return <div><span className="text-[#8A9AB0] text-xs">{label}: </span><b className="text-[#2D3748]">{v}</b></div>;
}

function BundleEditor({ bundle, onClose, onSave }) {
  const [b, setB] = useState({ ...bundle });
  return (
    <div className="fixed inset-0 bg-black/50 z-40 flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-[#FDFBF7] rounded-3xl max-w-lg w-full p-6 max-h-[90vh] overflow-y-auto" onClick={(e) => e.stopPropagation()} data-testid="bundle-editor">
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-heading text-xl font-bold text-[#2D3748]">{b.id ? "تعديل باقة" : "باقة جديدة"}</h2>
          <button onClick={onClose}><X className="w-5 h-5 text-[#5A677D]" /></button>
        </div>
        <div className="space-y-3">
          <Field label="اسم الباقة"><input className="input w-full" value={b.name || ""} onChange={(e) => setB({ ...b, name: e.target.value })} data-testid="bundle-name" /></Field>
          <Field label="الوصف"><textarea className="input w-full" rows={2} value={b.description || ""} onChange={(e) => setB({ ...b, description: e.target.value })} /></Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="نوع التسليم">
              <select className="input w-full" value={b.output_type} onChange={(e) => setB({ ...b, output_type: e.target.value })} data-testid="bundle-output-type">
                <option value="both">فيديو + PDF</option>
                <option value="video">فيديو فقط</option>
                <option value="pdf">PDF فقط</option>
              </select>
            </Field>
            <Field label="الكمية"><input type="number" className="input w-full" value={b.quantity} onChange={(e) => setB({ ...b, quantity: parseInt(e.target.value) || 1 })} data-testid="bundle-qty" /></Field>
            <Field label="الصلاحية (يوم)"><input type="number" className="input w-full" value={b.validity_days} onChange={(e) => setB({ ...b, validity_days: parseInt(e.target.value) || 90 })} /></Field>
            <Field label="السعر (SAR)"><input type="number" step="0.5" className="input w-full" value={b.price} onChange={(e) => setB({ ...b, price: parseFloat(e.target.value) || 0 })} data-testid="bundle-price" /></Field>
          </div>
          <label className="inline-flex items-center gap-2 font-body text-sm cursor-pointer">
            <input type="checkbox" checked={!!b.is_active} onChange={(e) => setB({ ...b, is_active: e.target.checked })} /> نشطة
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

function GrantModal({ bundle, onClose, onGranted }) {
  const [users, setUsers] = useState([]);
  const [selected, setSelected] = useState("");
  const [reason, setReason] = useState("منح يدوي من admin");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.get("/admin/users").then((r) => {
      const list = Array.isArray(r.data) ? r.data : (r.data?.users || []);
      setUsers(list.map(u => ({ id: u.id, label: `${u.email}${u.name ? " — " + u.name : ""}` })));
    }).catch(() => toast.error("تعذّر تحميل المستخدمين"));
  }, []);

  const grant = async () => {
    if (!selected) return toast.error("اختر مستخدماً");
    setBusy(true);
    try {
      await api.post(`/admin/bundles/${bundle.id}/grant`, { user_id: selected, reason });
      toast.success("تم منح الباقة");
      onGranted();
    } catch (e) { toast.error(e?.response?.data?.detail || "فشل"); }
    finally { setBusy(false); }
  };

  return (
    <div className="fixed inset-0 bg-black/50 z-40 flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-[#FDFBF7] rounded-3xl max-w-md w-full p-6" onClick={(e) => e.stopPropagation()} data-testid="grant-modal">
        <h2 className="font-heading text-lg font-bold text-[#2D3748] mb-3">منح باقة "{bundle.name}"</h2>
        <Field label="المستخدم">
          <select className="input w-full" value={selected} onChange={(e) => setSelected(e.target.value)} data-testid="grant-user-select">
            <option value="">— اختر —</option>
            {users.map(u => <option key={u.id} value={u.id}>{u.label}</option>)}
          </select>
        </Field>
        <Field label="السبب"><input className="input w-full" value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
        <div className="flex justify-end gap-2 pt-3">
          <button onClick={onClose} className="rounded-full bg-[#F8F1E7] text-[#8B5A2B] px-4 py-2 text-sm font-bold">إلغاء</button>
          <button onClick={grant} disabled={busy} className="btn-primary inline-flex items-center gap-2" data-testid="grant-confirm-btn">
            {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Gift className="w-4 h-4" />} منح
          </button>
        </div>
      </div>
    </div>
  );
}

function Field({ label, children }) {
  return <label className="block mb-1"><div className="text-xs text-[#5A677D] font-body mb-1">{label}</div>{children}</label>;
}
