import React, { useEffect, useState } from "react";
import { api } from "../../lib/api";
import { toast } from "sonner";
import { Plus, Edit2, Trash2, X, Save, BookOpen } from "lucide-react";

export default function AdminStyles() {
  const [styles, setStyles] = useState([]);
  const [editing, setEditing] = useState(null);

  const reload = () => api.get("/admin/styles").then((r) => setStyles(r.data));
  useEffect(() => { reload(); }, []);

  const empty = { name_ar: "", description: "", sort_order: styles.length, is_active: true, image_url: "" };

  const save = async () => {
    try {
      if (editing.id) await api.patch(`/admin/styles/${editing.id}`, editing);
      else await api.post("/admin/styles", editing);
      toast.success("تم الحفظ");
      setEditing(null);
      reload();
    } catch { toast.error("فشل"); }
  };
  const del = async (s) => {
    if (!window.confirm("حذف هذا الأسلوب؟")) return;
    await api.delete(`/admin/styles/${s.id}`);
    toast.success("تم الحذف");
    reload();
  };

  return (
    <div data-testid="admin-styles">
      <div className="flex items-end justify-between mb-6 flex-wrap gap-4">
        <div>
          <h1 className="font-heading text-3xl font-bold text-[#2D3748] mb-2">أساليب القصة</h1>
          <p className="font-body text-[#5A677D]">الأساليب الظاهرة للمستخدم في الخطوة الرابعة</p>
        </div>
        <button onClick={() => setEditing(empty)} className="btn-primary inline-flex items-center gap-2" data-testid="style-new">
          <Plus className="w-4 h-4" /> أسلوب جديد
        </button>
      </div>

      <div className="grid md:grid-cols-2 gap-4">
        {styles.map((s) => (
          <div key={s.id} className="bg-white rounded-3xl p-6 border border-[#E2D8C9]" data-testid={`style-${s.id}`}>
            <div className="flex items-start justify-between mb-3">
              <div className="w-12 h-12 rounded-2xl bg-[#E8F0E1] grid place-content-center">
                <BookOpen className="w-6 h-6 text-[#729352]" />
              </div>
              <div className="flex gap-2">
                <button onClick={() => setEditing(s)} className="text-[#4F6B3B] p-2 rounded-xl bg-[#E8F0E1]"><Edit2 className="w-4 h-4" /></button>
                <button onClick={() => del(s)} className="text-[#B8612F] p-2 rounded-xl bg-[#FCE6D4]"><Trash2 className="w-4 h-4" /></button>
              </div>
            </div>
            <h3 className="font-heading text-lg font-bold text-[#2D3748]">{s.name_ar}</h3>
            <p className="font-body text-sm text-[#5A677D] mt-1">{s.description}</p>
            <div className="mt-3 flex items-center gap-2 text-xs text-[#8A9AB0] font-body">
              <span>ترتيب: {s.sort_order}</span>
              <span>•</span>
              <span>{s.is_active ? "نشط" : "غير نشط"}</span>
            </div>
          </div>
        ))}
      </div>

      {editing && (
        <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4" onClick={() => setEditing(null)}>
          <div className="bg-white rounded-[2rem] p-8 max-w-lg w-full" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-6">
              <h2 className="font-heading text-xl font-bold">{editing.id ? "تعديل أسلوب" : "أسلوب جديد"}</h2>
              <button onClick={() => setEditing(null)}><X className="w-5 h-5" /></button>
            </div>
            <label className="block text-sm font-bold text-[#2D3748] mb-2 font-body">الاسم</label>
            <input value={editing.name_ar} onChange={(e) => setEditing({ ...editing, name_ar: e.target.value })} className="w-full bg-[#FDFBF7] border border-[#E2D8C9] rounded-2xl px-4 py-2 font-body mb-4" />
            <label className="block text-sm font-bold text-[#2D3748] mb-2 font-body">الوصف</label>
            <textarea rows={3} value={editing.description || ""} onChange={(e) => setEditing({ ...editing, description: e.target.value })} className="w-full bg-[#FDFBF7] border border-[#E2D8C9] rounded-2xl px-4 py-2 font-body mb-4" />
            <label className="block text-sm font-bold text-[#2D3748] mb-2 font-body">الترتيب</label>
            <input type="number" value={editing.sort_order} onChange={(e) => setEditing({ ...editing, sort_order: parseInt(e.target.value || 0) })} className="w-full bg-[#FDFBF7] border border-[#E2D8C9] rounded-2xl px-4 py-2 font-body mb-4" />
            <label className="flex items-center gap-2 mb-6"><input type="checkbox" checked={editing.is_active} onChange={(e) => setEditing({ ...editing, is_active: e.target.checked })} className="accent-[#87A96B]" /><span className="font-body">نشط</span></label>
            <button onClick={save} className="btn-primary w-full inline-flex items-center justify-center gap-2"><Save className="w-4 h-4" /> حفظ</button>
          </div>
        </div>
      )}
    </div>
  );
}
