import React, { useEffect, useState } from "react";
import { api } from "../../lib/api";
import { toast } from "sonner";
import { Save, FileText } from "lucide-react";

export default function AdminContent() {
  const [blocks, setBlocks] = useState([]);
  const [edits, setEdits] = useState({});

  const reload = () => api.get("/admin/content").then((r) => setBlocks(r.data));
  useEffect(() => { reload(); }, []);

  const grouped = blocks.reduce((acc, b) => {
    const key = b.section || "other";
    acc[key] = acc[key] || [];
    acc[key].push(b);
    return acc;
  }, {});

  const save = async (b) => {
    const value = edits[b.key] !== undefined ? edits[b.key] : b.value;
    try {
      const payload = { key: b.key, value, section: b.section };
      await api.put("/admin/content", payload);
      toast.success("تم الحفظ");
      setEdits((e) => { const n = { ...e }; delete n[b.key]; return n; });
      reload();
    } catch {
      toast.error("فشل");
    }
  };

  return (
    <div data-testid="admin-content">
      <h1 className="font-heading text-3xl font-bold text-[#2D3748] mb-2">محتوى الصفحة</h1>
      <p className="font-body text-[#5A677D] mb-6">عدّل نصوص الموقع مباشرة من هنا — تنعكس فوراً على الصفحة الرئيسية</p>

      {Object.entries(grouped).map(([section, items]) => (
        <div key={section} className="mb-8">
          <h2 className="font-heading text-xl font-bold text-[#729352] mb-4 flex items-center gap-2">
            <FileText className="w-5 h-5" /> قسم: {section}
          </h2>
          <div className="bg-white rounded-3xl border border-[#E2D8C9] divide-y divide-[#E2D8C9]">
            {items.map((b) => {
              const current = edits[b.key] !== undefined ? edits[b.key] : b.value;
              const isString = typeof current === "string";
              const isLong = isString && current.length > 80;
              return (
                <div key={b.key} className="p-5" data-testid={`content-row-${b.key}`}>
                  <label className="block text-xs font-bold text-[#8A9AB0] mb-2 font-body">{b.key}</label>
                  {isString ? (
                    isLong ? (
                      <textarea rows={3} value={current} onChange={(e) => setEdits({ ...edits, [b.key]: e.target.value })} className="w-full bg-[#FDFBF7] border border-[#E2D8C9] rounded-2xl px-4 py-2 font-body mb-3" />
                    ) : (
                      <input value={current} onChange={(e) => setEdits({ ...edits, [b.key]: e.target.value })} className="w-full bg-[#FDFBF7] border border-[#E2D8C9] rounded-2xl px-4 py-2 font-body mb-3" />
                    )
                  ) : (
                    <textarea rows={6} value={JSON.stringify(current, null, 2)} onChange={(e) => { try { setEdits({ ...edits, [b.key]: JSON.parse(e.target.value) }); } catch {} }} className="w-full bg-[#FDFBF7] border border-[#E2D8C9] rounded-2xl px-4 py-2 font-body text-xs mb-3" />
                  )}
                  <button onClick={() => save(b)} className="rounded-full bg-[#87A96B] hover:bg-[#729352] text-white px-5 py-2 text-sm font-bold font-body inline-flex items-center gap-2">
                    <Save className="w-4 h-4" /> حفظ
                  </button>
                </div>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}
