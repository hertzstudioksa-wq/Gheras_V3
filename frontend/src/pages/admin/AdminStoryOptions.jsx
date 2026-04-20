import React, { useEffect, useState } from "react";
import { api } from "../../lib/api";
import { toast } from "sonner";
import { Plus, Edit2, Trash2, Eye, EyeOff, Save, X } from "lucide-react";

const KINDS = [
  { v: "type", l: "نوع القصة" },
  { v: "tone", l: "النبرة" },
  { v: "setting", l: "البيئة" },
  { v: "language", l: "اللغة" },
  { v: "voice", l: "صوت الراوي" },
];

export default function AdminStoryOptions() {
  const [items, setItems] = useState([]);
  const [editing, setEditing] = useState(null);
  const [activeKind, setActiveKind] = useState("type");

  const reload = () => api.get("/admin/story-options").then((r) => setItems(r.data));
  useEffect(() => { reload(); }, []);

  const empty = { kind: activeKind, name_ar: "", value: "", description: "", sort_order: 0, is_active: true, is_hidden: false };
  const byKind = items.filter((i) => i.kind === activeKind);

  const save = async () => {
    try {
      const p = { ...editing };
      if (!p.value) p.value = (p.name_ar || "").toLowerCase().replace(/\s+/g, "-");
      if (editing.id) await api.patch(`/admin/story-options/${editing.id}`, p);
      else await api.post("/admin/story-options", p);
      toast.success("تم الحفظ");
      setEditing(null);
      reload();
    } catch (e) { toast.error(e?.response?.data?.detail || "فشل"); }
  };

  const del = async (it) => {
    if (!window.confirm(`حذف "${it.name_ar}"؟`)) return;
    await api.delete(`/admin/story-options/${it.id}`);
    toast.success("تم الحذف");
    reload();
  };

  const toggleHidden = async (it) => {
    await api.patch(`/admin/story-options/${it.id}`, { ...it, is_hidden: !it.is_hidden });
    reload();
  };

  return (
    <div data-testid="admin-story-options">
      <div className="flex items-end justify-between mb-6 flex-wrap gap-4">
        <div>
          <h1 className="font-heading text-3xl font-bold text-[#2D3748] mb-2">خيارات نمط القصة</h1>
          <p className="font-body text-[#5A677D]">خيارات الخطوة 5 (نوع/نبرة/بيئة/لغة/راوٍ)</p>
        </div>
        <button onClick={() => setEditing({ ...empty, kind: activeKind })} className="btn-primary inline-flex items-center gap-2" data-testid="opt-new-btn">
          <Plus className="w-4 h-4" /> إضافة
        </button>
      </div>

      <div className="flex flex-wrap gap-2 mb-5">
        {KINDS.map((k) => (
          <button
            key={k.v}
            onClick={() => setActiveKind(k.v)}
            className={`rounded-full px-4 py-2 text-sm font-body font-bold transition ${
              activeKind === k.v ? "bg-[#87A96B] text-white" : "bg-white border border-[#E2D8C9] text-[#5A677D]"
            }`}
          >
            {k.l} ({items.filter((i) => i.kind === k.v).length})
          </button>
        ))}
      </div>

      <div className="bg-white rounded-3xl border border-[#E2D8C9] overflow-hidden">
        <table className="w-full text-right">
          <thead className="bg-[#F8F1E7] text-[#5A677D] text-xs font-body">
            <tr>
              <th className="px-5 py-3 font-bold">الاسم</th>
              <th className="px-5 py-3 font-bold">المعرّف</th>
              <th className="px-5 py-3 font-bold">الترتيب</th>
              <th className="px-5 py-3 font-bold">الحالة</th>
              <th className="px-5 py-3 font-bold">إجراءات</th>
            </tr>
          </thead>
          <tbody>
            {byKind.sort((a, b) => a.sort_order - b.sort_order).map((it) => (
              <tr key={it.id} className="border-t border-[#E2D8C9]" data-testid={`opt-row-${it.id}`}>
                <td className="px-5 py-3 font-body font-bold">{it.name_ar}</td>
                <td className="px-5 py-3 font-mono text-xs text-[#8A9AB0]">{it.value}</td>
                <td className="px-5 py-3 font-body text-sm">{it.sort_order}</td>
                <td className="px-5 py-3">
                  <span className={`rounded-full px-3 py-1 text-xs font-bold ${it.is_hidden ? "bg-[#FCE6D4] text-[#B8612F]" : it.is_active ? "bg-[#DEEBCF] text-[#3F5B2E]" : "bg-[#F8F1E7] text-[#8B5A2B]"}`}>
                    {it.is_hidden ? "مخفي" : it.is_active ? "نشط" : "غير نشط"}
                  </span>
                </td>
                <td className="px-5 py-3">
                  <div className="flex gap-2">
                    <button onClick={() => toggleHidden(it)} className="text-[#8B5A2B] p-1.5 rounded-lg bg-[#F8F1E7]">
                      {it.is_hidden ? <Eye className="w-4 h-4" /> : <EyeOff className="w-4 h-4" />}
                    </button>
                    <button onClick={() => setEditing(it)} className="text-[#4F6B3B] p-1.5 rounded-lg bg-[#E8F0E1]"><Edit2 className="w-4 h-4" /></button>
                    <button onClick={() => del(it)} className="text-[#B8612F] p-1.5 rounded-lg bg-[#FCE6D4]"><Trash2 className="w-4 h-4" /></button>
                  </div>
                </td>
              </tr>
            ))}
            {byKind.length === 0 && <tr><td colSpan={5} className="py-8 text-center text-[#8A9AB0] font-body">لا توجد خيارات</td></tr>}
          </tbody>
        </table>
      </div>

      {editing && (
        <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4" onClick={() => setEditing(null)}>
          <div className="bg-white rounded-[2rem] p-8 max-w-lg w-full" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-6">
              <h2 className="font-heading text-xl font-bold">{editing.id ? "تعديل" : "جديد"}</h2>
              <button onClick={() => setEditing(null)}><X className="w-5 h-5" /></button>
            </div>
            <label className="block text-sm font-bold mb-2 font-body">النوع</label>
            <select value={editing.kind} onChange={(e) => setEditing({ ...editing, kind: e.target.value })} className="w-full bg-[#FDFBF7] border border-[#E2D8C9] rounded-2xl px-4 py-2 font-body mb-4">
              {KINDS.map((k) => <option key={k.v} value={k.v}>{k.l}</option>)}
            </select>
            <label className="block text-sm font-bold mb-2 font-body">الاسم بالعربية</label>
            <input value={editing.name_ar} onChange={(e) => setEditing({ ...editing, name_ar: e.target.value })} className="w-full bg-[#FDFBF7] border border-[#E2D8C9] rounded-2xl px-4 py-2 font-body mb-4" />
            <label className="block text-sm font-bold mb-2 font-body">المعرّف (value)</label>
            <input value={editing.value} onChange={(e) => setEditing({ ...editing, value: e.target.value })} placeholder="realistic" className="w-full bg-[#FDFBF7] border border-[#E2D8C9] rounded-2xl px-4 py-2 font-mono mb-4" />
            <label className="block text-sm font-bold mb-2 font-body">الترتيب</label>
            <input type="number" value={editing.sort_order} onChange={(e) => setEditing({ ...editing, sort_order: parseInt(e.target.value || 0) })} className="w-full bg-[#FDFBF7] border border-[#E2D8C9] rounded-2xl px-4 py-2 font-body mb-4" />
            <label className="flex items-center gap-2 mb-3"><input type="checkbox" checked={editing.is_active} onChange={(e) => setEditing({ ...editing, is_active: e.target.checked })} className="accent-[#87A96B]" /> <span className="font-body">نشط</span></label>
            <label className="flex items-center gap-2 mb-6"><input type="checkbox" checked={editing.is_hidden} onChange={(e) => setEditing({ ...editing, is_hidden: e.target.checked })} className="accent-[#87A96B]" /> <span className="font-body">مخفي عن المستخدم</span></label>
            <button onClick={save} className="btn-primary w-full inline-flex items-center justify-center gap-2"><Save className="w-4 h-4" /> حفظ</button>
          </div>
        </div>
      )}
    </div>
  );
}
