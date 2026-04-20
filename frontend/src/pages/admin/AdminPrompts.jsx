import React, { useEffect, useState } from "react";
import { api } from "../../lib/api";
import { toast } from "sonner";
import { Plus, Edit2, Trash2, X, Save, Wand2 } from "lucide-react";

export default function AdminPrompts() {
  const [items, setItems] = useState([]);
  const [editing, setEditing] = useState(null);

  const reload = () => api.get("/admin/prompts").then((r) => setItems(r.data));
  useEffect(() => { reload(); }, []);

  const empty = { key: "", title_ar: "", description: "", template: "", variables: [], is_active: true };

  const save = async () => {
    try {
      const p = { ...editing };
      if (typeof p.variables === "string") p.variables = p.variables.split(",").map((s) => s.trim()).filter(Boolean);
      if (editing.id) await api.patch(`/admin/prompts/${editing.id}`, p);
      else await api.post("/admin/prompts", p);
      toast.success("تم الحفظ");
      setEditing(null);
      reload();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "فشل");
    }
  };

  const del = async (p) => {
    if (!window.confirm(`حذف "${p.title_ar}"؟`)) return;
    await api.delete(`/admin/prompts/${p.id}`);
    toast.success("تم الحذف");
    reload();
  };

  return (
    <div data-testid="admin-prompts">
      <div className="flex items-end justify-between mb-6 flex-wrap gap-4">
        <div>
          <h1 className="font-heading text-3xl font-bold text-[#2D3748] mb-2">برومبتات الذكاء الاصطناعي</h1>
          <p className="font-body text-[#5A677D]">القوالب التي ستُرسل لنماذج AI عند تفعيل التوليد لاحقاً</p>
        </div>
        <button onClick={() => setEditing(empty)} className="btn-primary inline-flex items-center gap-2" data-testid="prompt-new">
          <Plus className="w-4 h-4" /> برومبت جديد
        </button>
      </div>

      <div className="space-y-4">
        {items.map((p) => (
          <div key={p.id} className="bg-white rounded-3xl p-6 border border-[#E2D8C9]" data-testid={`prompt-${p.key}`}>
            <div className="flex items-start justify-between mb-3 gap-3 flex-wrap">
              <div className="flex items-start gap-3 flex-1">
                <div className="w-12 h-12 rounded-2xl bg-[#E8F0E1] grid place-content-center shrink-0">
                  <Wand2 className="w-6 h-6 text-[#729352]" />
                </div>
                <div>
                  <h3 className="font-heading text-lg font-bold text-[#2D3748]">{p.title_ar}</h3>
                  <p className="font-mono text-xs text-[#8A9AB0]">{p.key}</p>
                  {p.description && <p className="font-body text-sm text-[#5A677D] mt-1">{p.description}</p>}
                </div>
              </div>
              <div className="flex gap-2">
                <button onClick={() => setEditing(p)} className="text-[#4F6B3B] p-2 rounded-xl bg-[#E8F0E1]"><Edit2 className="w-4 h-4" /></button>
                <button onClick={() => del(p)} className="text-[#B8612F] p-2 rounded-xl bg-[#FCE6D4]"><Trash2 className="w-4 h-4" /></button>
              </div>
            </div>
            <pre className="bg-[#FDFBF7] rounded-2xl p-4 font-body text-xs text-[#2D3748] whitespace-pre-wrap border border-[#E2D8C9] overflow-x-auto">{p.template}</pre>
            {p.variables?.length > 0 && (
              <div className="flex flex-wrap gap-2 mt-3">
                {p.variables.map((v) => (
                  <span key={v} className="font-mono text-xs bg-[#F8F1E7] text-[#8B5A2B] rounded-full px-3 py-1">{`{${v}}`}</span>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>

      {editing && (
        <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4" onClick={() => setEditing(null)}>
          <div className="bg-white rounded-[2rem] p-8 max-w-2xl w-full max-h-[90vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-6">
              <h2 className="font-heading text-xl font-bold">{editing.id ? "تعديل" : "برومبت جديد"}</h2>
              <button onClick={() => setEditing(null)}><X className="w-5 h-5" /></button>
            </div>
            <label className="block text-sm font-bold text-[#2D3748] mb-2 font-body">المفتاح</label>
            <input value={editing.key} onChange={(e) => setEditing({ ...editing, key: e.target.value })} disabled={!!editing.id} className="w-full bg-[#FDFBF7] border border-[#E2D8C9] rounded-2xl px-4 py-2 font-mono mb-4 disabled:opacity-60" placeholder="story.generate.master" />
            <label className="block text-sm font-bold text-[#2D3748] mb-2 font-body">العنوان</label>
            <input value={editing.title_ar} onChange={(e) => setEditing({ ...editing, title_ar: e.target.value })} className="w-full bg-[#FDFBF7] border border-[#E2D8C9] rounded-2xl px-4 py-2 font-body mb-4" />
            <label className="block text-sm font-bold text-[#2D3748] mb-2 font-body">الوصف</label>
            <textarea rows={2} value={editing.description || ""} onChange={(e) => setEditing({ ...editing, description: e.target.value })} className="w-full bg-[#FDFBF7] border border-[#E2D8C9] rounded-2xl px-4 py-2 font-body mb-4" />
            <label className="block text-sm font-bold text-[#2D3748] mb-2 font-body">القالب</label>
            <textarea rows={8} value={editing.template} onChange={(e) => setEditing({ ...editing, template: e.target.value })} className="w-full bg-[#FDFBF7] border border-[#E2D8C9] rounded-2xl px-4 py-2 font-body text-sm mb-4" />
            <label className="block text-sm font-bold text-[#2D3748] mb-2 font-body">المتغيرات (مفصولة بفاصلة)</label>
            <input value={Array.isArray(editing.variables) ? editing.variables.join(", ") : editing.variables} onChange={(e) => setEditing({ ...editing, variables: e.target.value })} className="w-full bg-[#FDFBF7] border border-[#E2D8C9] rounded-2xl px-4 py-2 font-mono text-sm mb-6" placeholder="child_name, child_age, goal" />
            <button onClick={save} className="btn-primary w-full inline-flex items-center justify-center gap-2"><Save className="w-4 h-4" /> حفظ</button>
          </div>
        </div>
      )}
    </div>
  );
}
