import React, { useEffect, useState } from "react";
import { api } from "../../lib/api";
import { toast } from "sonner";
import { Plus, Edit2, Trash2, X, Save, CreditCard, Check } from "lucide-react";

export default function AdminPlans() {
  const [plans, setPlans] = useState([]);
  const [editing, setEditing] = useState(null);

  const reload = () => api.get("/admin/plans").then((r) => setPlans(r.data));
  useEffect(() => { reload(); }, []);

  const empty = { name_ar: "", price: 0, currency: "SAR", story_limit: 1, features: [], is_active: true, sort_order: plans.length };

  const save = async () => {
    try {
      const p = { ...editing };
      if (typeof p.features === "string") p.features = p.features.split("\n").map((s) => s.trim()).filter(Boolean);
      if (editing.id) await api.patch(`/admin/plans/${editing.id}`, p);
      else await api.post("/admin/plans", p);
      toast.success("تم الحفظ");
      setEditing(null);
      reload();
    } catch { toast.error("فشل"); }
  };
  const del = async (p) => {
    if (!window.confirm("حذف هذه الباقة؟")) return;
    await api.delete(`/admin/plans/${p.id}`);
    toast.success("تم الحذف");
    reload();
  };

  return (
    <div data-testid="admin-plans">
      <div className="flex items-end justify-between mb-6 flex-wrap gap-4">
        <div>
          <h1 className="font-heading text-3xl font-bold text-[#2D3748] mb-2">الأسعار والباقات</h1>
          <p className="font-body text-[#5A677D]">باقات الاشتراك وحدود القصص</p>
        </div>
        <button onClick={() => setEditing(empty)} className="btn-primary inline-flex items-center gap-2" data-testid="plan-new">
          <Plus className="w-4 h-4" /> باقة جديدة
        </button>
      </div>

      <div className="grid md:grid-cols-3 gap-5">
        {plans.map((p) => (
          <div key={p.id} className="bg-white rounded-3xl p-6 border border-[#E2D8C9]" data-testid={`plan-${p.id}`}>
            <div className="flex items-center justify-between mb-4">
              <CreditCard className="w-6 h-6 text-[#729352]" />
              <div className="flex gap-1">
                <button onClick={() => setEditing(p)} className="text-[#4F6B3B] p-1.5 rounded-lg bg-[#E8F0E1]"><Edit2 className="w-4 h-4" /></button>
                <button onClick={() => del(p)} className="text-[#B8612F] p-1.5 rounded-lg bg-[#FCE6D4]"><Trash2 className="w-4 h-4" /></button>
              </div>
            </div>
            <h3 className="font-heading text-2xl font-bold text-[#2D3748]">{p.name_ar}</h3>
            <div className="mt-2 mb-5">
              <span className="font-heading text-4xl font-bold text-[#729352]">{p.price}</span>
              <span className="font-body text-sm text-[#8A9AB0] mr-2">{p.currency} / شهرياً</span>
            </div>
            <div className="text-sm font-body text-[#5A677D] mb-3">
              حد القصص: <span className="font-bold text-[#2D3748]">{p.story_limit >= 999 ? "غير محدود" : p.story_limit}</span>
            </div>
            <ul className="space-y-2">
              {p.features.map((f, i) => (
                <li key={i} className="flex items-start gap-2 text-sm font-body text-[#2D3748]">
                  <Check className="w-4 h-4 text-[#87A96B] mt-0.5 shrink-0" /> {f}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>

      {editing && (
        <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4" onClick={() => setEditing(null)}>
          <div className="bg-white rounded-[2rem] p-8 max-w-lg w-full max-h-[90vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-6">
              <h2 className="font-heading text-xl font-bold">{editing.id ? "تعديل" : "باقة جديدة"}</h2>
              <button onClick={() => setEditing(null)}><X className="w-5 h-5" /></button>
            </div>
            <Field label="الاسم"><input value={editing.name_ar} onChange={(e) => setEditing({ ...editing, name_ar: e.target.value })} className="w-full bg-[#FDFBF7] border border-[#E2D8C9] rounded-2xl px-4 py-2 font-body" /></Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="السعر"><input type="number" value={editing.price} onChange={(e) => setEditing({ ...editing, price: parseFloat(e.target.value || 0) })} className="w-full bg-[#FDFBF7] border border-[#E2D8C9] rounded-2xl px-4 py-2 font-body" /></Field>
              <Field label="العملة"><input value={editing.currency} onChange={(e) => setEditing({ ...editing, currency: e.target.value })} className="w-full bg-[#FDFBF7] border border-[#E2D8C9] rounded-2xl px-4 py-2 font-body" /></Field>
            </div>
            <Field label="حد القصص الشهرية"><input type="number" value={editing.story_limit} onChange={(e) => setEditing({ ...editing, story_limit: parseInt(e.target.value || 1) })} className="w-full bg-[#FDFBF7] border border-[#E2D8C9] rounded-2xl px-4 py-2 font-body" /></Field>
            <Field label="الميّزات (كل ميزة في سطر)">
              <textarea rows={4} value={Array.isArray(editing.features) ? editing.features.join("\n") : editing.features} onChange={(e) => setEditing({ ...editing, features: e.target.value })} className="w-full bg-[#FDFBF7] border border-[#E2D8C9] rounded-2xl px-4 py-2 font-body" />
            </Field>
            <Field label="الترتيب"><input type="number" value={editing.sort_order} onChange={(e) => setEditing({ ...editing, sort_order: parseInt(e.target.value || 0) })} className="w-full bg-[#FDFBF7] border border-[#E2D8C9] rounded-2xl px-4 py-2 font-body" /></Field>
            <label className="flex items-center gap-2 mb-6"><input type="checkbox" checked={editing.is_active} onChange={(e) => setEditing({ ...editing, is_active: e.target.checked })} className="accent-[#87A96B]" /><span className="font-body">نشط</span></label>
            <button onClick={save} className="btn-primary w-full inline-flex items-center justify-center gap-2"><Save className="w-4 h-4" /> حفظ</button>
          </div>
        </div>
      )}
    </div>
  );
}

function Field({ label, children }) {
  return (
    <div className="mb-4">
      <label className="block text-sm font-bold text-[#2D3748] mb-2 font-body">{label}</label>
      {children}
    </div>
  );
}
