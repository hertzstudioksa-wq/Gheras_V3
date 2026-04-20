import React, { useEffect, useState } from "react";
import { api } from "../../lib/api";
import { toast } from "sonner";
import { Plus, Edit2, Trash2, X, Save, Sprout } from "lucide-react";

const ICON_OPTIONS = ["sun", "heart", "award", "sparkles", "moon", "rocket", "moon-star", "pen-tool", "sprout"];
const COLOR_OPTIONS = ["#87A96B", "#D4A373", "#E07A5F", "#8B5A2B", "#729352", "#5A677D"];

export default function AdminCategories() {
  const [cats, setCats] = useState([]);
  const [editing, setEditing] = useState(null);
  const [subcatEditingCat, setSubcatEditingCat] = useState(null);

  const reload = () => api.get("/public/categories").then((r) => setCats(r.data));
  useEffect(() => { reload(); }, []);

  const emptyCat = { name_ar: "", slug: "", description: "", icon: "sprout", color: "#87A96B", sort_order: cats.length, is_active: true };

  const saveCat = async () => {
    try {
      const p = { ...editing };
      if (!p.slug) p.slug = (p.name_ar || "").toLowerCase().replace(/\s+/g, "-").slice(0, 30) + "-" + Date.now();
      if (editing.id) {
        await api.patch(`/admin/categories/${editing.id}`, p);
      } else {
        await api.post("/admin/categories", p);
      }
      toast.success("تم الحفظ");
      setEditing(null);
      reload();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "فشل الحفظ");
    }
  };

  const delCat = async (c) => {
    if (!window.confirm(`حذف "${c.name_ar}" وكل مواضيعه؟`)) return;
    try {
      await api.delete(`/admin/categories/${c.id}`);
      toast.success("تم الحذف");
      reload();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "فشل");
    }
  };

  return (
    <div data-testid="admin-categories">
      <div className="flex items-end justify-between mb-6 flex-wrap gap-4">
        <div>
          <h1 className="font-heading text-3xl font-bold text-[#2D3748] mb-2">التصنيفات</h1>
          <p className="font-body text-[#5A677D]">إدارة تصنيفات ومواضيع القصص</p>
        </div>
        <button onClick={() => setEditing(emptyCat)} className="btn-primary inline-flex items-center gap-2" data-testid="cat-new-btn">
          <Plus className="w-4 h-4" /> تصنيف جديد
        </button>
      </div>

      <div className="grid md:grid-cols-2 gap-4">
        {cats.map((c) => (
          <div key={c.id} className="bg-white rounded-3xl p-5 border border-[#E2D8C9]" data-testid={`cat-${c.slug}`}>
            <div className="flex items-start gap-3 mb-3">
              <div className="w-12 h-12 rounded-2xl grid place-content-center" style={{ backgroundColor: `${c.color}20` }}>
                <Sprout className="w-6 h-6" style={{ color: c.color }} />
              </div>
              <div className="flex-1">
                <h3 className="font-heading text-lg font-bold text-[#2D3748]">{c.name_ar}</h3>
                <p className="font-body text-xs text-[#8A9AB0]">{c.subcategories?.length || 0} مواضيع • {c.slug}</p>
              </div>
            </div>
            <p className="font-body text-sm text-[#5A677D] mb-4 min-h-[40px]">{c.description}</p>
            <div className="flex flex-wrap gap-2 mb-4">
              {c.subcategories?.slice(0, 5).map((s) => (
                <span key={s.id} className="bg-[#F8F1E7] text-[#8B5A2B] rounded-full px-3 py-1 text-xs">{s.name_ar}</span>
              ))}
              {c.subcategories?.length > 5 && (
                <span className="bg-[#E8F0E1] text-[#4F6B3B] rounded-full px-3 py-1 text-xs">+{c.subcategories.length - 5}</span>
              )}
            </div>
            <div className="flex gap-2">
              <button onClick={() => setSubcatEditingCat(c)} className="flex-1 rounded-2xl bg-[#FDFBF7] border border-[#E2D8C9] px-3 py-2 text-sm font-body text-[#2D3748] hover:bg-[#F8F1E7]">
                المواضيع
              </button>
              <button onClick={() => setEditing(c)} className="rounded-2xl bg-[#E8F0E1] px-3 py-2 text-sm font-body text-[#4F6B3B]">
                <Edit2 className="w-4 h-4" />
              </button>
              <button onClick={() => delCat(c)} className="rounded-2xl bg-[#FCE6D4] px-3 py-2 text-sm font-body text-[#B8612F]">
                <Trash2 className="w-4 h-4" />
              </button>
            </div>
          </div>
        ))}
      </div>

      {editing && (
        <Modal onClose={() => setEditing(null)} title={editing.id ? "تعديل تصنيف" : "تصنيف جديد"}>
          <Field label="الاسم">
            <input value={editing.name_ar} onChange={(e) => setEditing({ ...editing, name_ar: e.target.value })} className="w-full bg-[#FDFBF7] border border-[#E2D8C9] rounded-2xl px-4 py-2 font-body" data-testid="cat-edit-name" />
          </Field>
          <Field label="المعرّف (slug)">
            <input value={editing.slug} onChange={(e) => setEditing({ ...editing, slug: e.target.value })} className="w-full bg-[#FDFBF7] border border-[#E2D8C9] rounded-2xl px-4 py-2 font-body" />
          </Field>
          <Field label="الوصف">
            <textarea rows={2} value={editing.description || ""} onChange={(e) => setEditing({ ...editing, description: e.target.value })} className="w-full bg-[#FDFBF7] border border-[#E2D8C9] rounded-2xl px-4 py-2 font-body" />
          </Field>
          <Field label="الأيقونة">
            <div className="flex flex-wrap gap-2">
              {ICON_OPTIONS.map((i) => (
                <button key={i} type="button" onClick={() => setEditing({ ...editing, icon: i })} className={`rounded-xl px-3 py-1 text-xs font-body border ${editing.icon === i ? "bg-[#87A96B] text-white border-[#87A96B]" : "bg-white border-[#E2D8C9]"}`}>
                  {i}
                </button>
              ))}
            </div>
          </Field>
          <Field label="اللون">
            <div className="flex gap-2">
              {COLOR_OPTIONS.map((c) => (
                <button key={c} type="button" onClick={() => setEditing({ ...editing, color: c })} className={`w-8 h-8 rounded-full ring-2 ${editing.color === c ? "ring-[#2D3748]" : "ring-transparent"}`} style={{ backgroundColor: c }} />
              ))}
            </div>
          </Field>
          <Field label="الترتيب">
            <input type="number" value={editing.sort_order} onChange={(e) => setEditing({ ...editing, sort_order: parseInt(e.target.value || 0) })} className="w-full bg-[#FDFBF7] border border-[#E2D8C9] rounded-2xl px-4 py-2 font-body" />
          </Field>
          <button onClick={saveCat} className="btn-primary inline-flex items-center gap-2 w-full justify-center" data-testid="cat-save-btn">
            <Save className="w-4 h-4" /> حفظ
          </button>
        </Modal>
      )}

      {subcatEditingCat && (
        <SubcategoryManager category={subcatEditingCat} onClose={() => { setSubcatEditingCat(null); reload(); }} />
      )}
    </div>
  );
}

function SubcategoryManager({ category, onClose }) {
  const [subs, setSubs] = useState(category.subcategories || []);
  const [newName, setNewName] = useState("");

  const add = async () => {
    if (!newName.trim()) return;
    try {
      const { data } = await api.post("/admin/subcategories", { category_id: category.id, name_ar: newName.trim(), sort_order: subs.length, is_active: true });
      setSubs([...subs, data]);
      setNewName("");
      toast.success("أضيف");
    } catch { toast.error("فشل"); }
  };

  const del = async (s) => {
    try {
      await api.delete(`/admin/subcategories/${s.id}`);
      setSubs(subs.filter((x) => x.id !== s.id));
      toast.success("تم الحذف");
    } catch { toast.error("فشل"); }
  };

  return (
    <Modal onClose={onClose} title={`مواضيع "${category.name_ar}"`}>
      <div className="flex gap-2 mb-4">
        <input value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="موضوع جديد..." className="flex-1 bg-[#FDFBF7] border border-[#E2D8C9] rounded-2xl px-4 py-2 font-body" data-testid="sub-new-input" />
        <button onClick={add} className="btn-primary inline-flex items-center gap-1" data-testid="sub-add-btn">
          <Plus className="w-4 h-4" /> إضافة
        </button>
      </div>
      <div className="space-y-2">
        {subs.map((s) => (
          <div key={s.id} className="flex items-center justify-between bg-[#FDFBF7] rounded-2xl p-3 border border-[#E2D8C9]">
            <span className="font-body text-[#2D3748]">{s.name_ar}</span>
            <button onClick={() => del(s)} className="text-[#B8612F]"><Trash2 className="w-4 h-4" /></button>
          </div>
        ))}
        {subs.length === 0 && <p className="text-center text-[#8A9AB0] py-4 font-body text-sm">لا توجد مواضيع</p>}
      </div>
    </Modal>
  );
}

function Modal({ title, children, onClose }) {
  return (
    <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-white rounded-[2rem] p-8 max-w-lg w-full max-h-[90vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-6">
          <h2 className="font-heading text-xl font-bold text-[#2D3748]">{title}</h2>
          <button onClick={onClose} className="text-[#8A9AB0]"><X className="w-5 h-5" /></button>
        </div>
        {children}
      </div>
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
