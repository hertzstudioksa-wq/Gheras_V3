import React, { useEffect, useState } from "react";
import { api } from "../../lib/api";
import { toast } from "sonner";
import { Save, Settings as SettingsIcon, Plus } from "lucide-react";

export default function AdminSettings() {
  const [items, setItems] = useState([]);
  const [edits, setEdits] = useState({});
  const [newItem, setNewItem] = useState({ key: "", value: "" });

  const reload = () => api.get("/admin/settings").then((r) => setItems(r.data));
  useEffect(() => { reload(); }, []);

  const save = async (it) => {
    const v = edits[it.key] !== undefined ? edits[it.key] : it.value;
    try {
      await api.put("/admin/settings", { key: it.key, value: tryParse(v) });
      toast.success("تم الحفظ");
      setEdits((e) => { const n = { ...e }; delete n[it.key]; return n; });
      reload();
    } catch { toast.error("فشل"); }
  };

  const addNew = async () => {
    if (!newItem.key.trim()) return;
    try {
      await api.put("/admin/settings", { key: newItem.key.trim(), value: tryParse(newItem.value) });
      toast.success("أُضيفت");
      setNewItem({ key: "", value: "" });
      reload();
    } catch { toast.error("فشل"); }
  };

  return (
    <div data-testid="admin-settings">
      <h1 className="font-heading text-3xl font-bold text-[#2D3748] mb-2">إعدادات النظام</h1>
      <p className="font-body text-[#5A677D] mb-6">قيم مفاتيح ديناميكية للتحكم بسلوك المنصة</p>

      <div className="bg-white rounded-3xl p-6 border border-[#E2D8C9] mb-8">
        <h3 className="font-heading font-bold text-lg text-[#2D3748] mb-4 flex items-center gap-2">
          <Plus className="w-5 h-5 text-[#729352]" /> إعداد جديد
        </h3>
        <div className="grid md:grid-cols-[1fr_1fr_auto] gap-3">
          <input placeholder="المفتاح (key)" value={newItem.key} onChange={(e) => setNewItem({ ...newItem, key: e.target.value })} className="bg-[#FDFBF7] border border-[#E2D8C9] rounded-2xl px-4 py-2 font-mono" />
          <input placeholder="القيمة" value={newItem.value} onChange={(e) => setNewItem({ ...newItem, value: e.target.value })} className="bg-[#FDFBF7] border border-[#E2D8C9] rounded-2xl px-4 py-2 font-body" />
          <button onClick={addNew} className="btn-primary inline-flex items-center gap-2"><Plus className="w-4 h-4" /> إضافة</button>
        </div>
      </div>

      <div className="bg-white rounded-3xl border border-[#E2D8C9] divide-y divide-[#E2D8C9]">
        {items.map((it) => {
          const current = edits[it.key] !== undefined ? edits[it.key] : (typeof it.value === "string" ? it.value : JSON.stringify(it.value));
          return (
            <div key={it.key} className="p-5 flex flex-col md:flex-row md:items-center gap-3" data-testid={`setting-${it.key}`}>
              <div className="md:w-1/3">
                <div className="flex items-center gap-2 text-[#5A677D] font-body">
                  <SettingsIcon className="w-4 h-4" />
                  <span className="font-mono text-sm">{it.key}</span>
                </div>
              </div>
              <input value={current} onChange={(e) => setEdits({ ...edits, [it.key]: e.target.value })} className="flex-1 bg-[#FDFBF7] border border-[#E2D8C9] rounded-2xl px-4 py-2 font-body" />
              <button onClick={() => save(it)} className="rounded-full bg-[#87A96B] text-white px-5 py-2 text-sm font-bold font-body inline-flex items-center gap-2">
                <Save className="w-4 h-4" /> حفظ
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function tryParse(v) {
  if (typeof v !== "string") return v;
  const t = v.trim();
  if (t === "") return "";
  if (!isNaN(Number(t))) return Number(t);
  if (t === "true") return true;
  if (t === "false") return false;
  try { return JSON.parse(t); } catch { return v; }
}
