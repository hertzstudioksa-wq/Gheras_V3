import React, { useEffect, useState } from "react";
import { api } from "../../lib/api";
import { Cpu, Save, Loader2, CheckCircle2, Ban, RefreshCcw, Info } from "lucide-react";
import { toast } from "sonner";

export default function AdminModels() {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [savingKey, setSavingKey] = useState(null);
  const [drafts, setDrafts] = useState({}); // keyed by stage_key

  const load = async () => {
    setLoading(true);
    try {
      const { data } = await api.get("/admin/models");
      setRows(data);
      setDrafts({});
    } catch (e) {
      toast.error("تعذّر تحميل إعدادات النماذج");
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { load(); }, []);

  const setDraft = (stage, patch) => setDrafts((d) => ({ ...d, [stage]: { ...d[stage], ...patch } }));

  const save = async (row) => {
    const draft = drafts[row.stage_key];
    if (!draft) return;
    setSavingKey(row.stage_key);
    try {
      await api.patch(`/admin/models/${row.stage_key}`, draft);
      toast.success("تم الحفظ");
      await load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "تعذّر الحفظ");
    } finally {
      setSavingKey(null);
    }
  };

  return (
    <div className="space-y-6" data-testid="admin-models-page" dir="rtl">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="font-heading text-3xl font-bold text-[#2D3748] mb-1 flex items-center gap-2">
            <Cpu className="w-6 h-6 text-[#87A96B]" />
            إعدادات النماذج
          </h1>
          <p className="font-body text-sm text-[#5A677D]">
            إدارة مركزية للنموذج النشط والـfallback لكل مرحلة في خط الإنتاج.
            التغييرات تُحفظ في قاعدة البيانات؛ الخدمات الحالية ستعمل بالـfallback للإعدادات الافتراضية حتى ربط Phase B.
          </p>
        </div>
        <button onClick={load} className="inline-flex items-center gap-2 bg-[#F8F1E7] text-[#8B5A2B] rounded-full px-4 py-2 text-sm font-bold">
          <RefreshCcw className="w-4 h-4" /> تحديث
        </button>
      </div>

      <div className="rounded-2xl overflow-hidden bg-[#E8F0E1] border border-[#87A96B]/30 p-4 text-sm font-body text-[#4F6B3B] flex items-start gap-2">
        <Info className="w-4 h-4 mt-0.5 shrink-0" />
        <span>
          الاتصال الفعلي بالنماذج يتم عبر <b>env vars</b>. الأكواد السرية لا تُخزَّن في قاعدة البيانات أبداً. راجع صفحة <b>حالة API</b> لمعرفة أي env vars مفعّلة.
        </span>
      </div>

      {loading ? (
        <div className="text-center py-8"><Loader2 className="w-6 h-6 animate-spin mx-auto text-[#87A96B]" /></div>
      ) : (
        <div className="bg-white rounded-2xl border border-[#E2D8C9] overflow-hidden">
          <table className="w-full text-right text-sm font-body">
            <thead className="bg-[#FDFBF7] text-xs text-[#5A677D]">
              <tr>
                <th className="p-3">المرحلة</th>
                <th className="p-3">المزوّد</th>
                <th className="p-3">النموذج</th>
                <th className="p-3">fallback</th>
                <th className="p-3">Env Key</th>
                <th className="p-3">نشط</th>
                <th className="p-3"></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const d = drafts[r.stage_key] || {};
                const dirty = Object.keys(d).length > 0;
                return (
                  <tr key={r.stage_key} className="border-t border-[#E2D8C9]" data-testid={`model-row-${r.stage_key}`}>
                    <td className="p-3 align-top">
                      <div className="font-bold text-[#2D3748]">{r.stage_name_ar}</div>
                      <div className="text-xs text-[#8A9AB0]">{r.stage_key}</div>
                    </td>
                    <td className="p-3 align-top">
                      <input
                        className="w-32 rounded-xl border border-[#E2D8C9] px-2 py-1 text-sm"
                        defaultValue={r.provider}
                        onChange={(e) => setDraft(r.stage_key, { provider: e.target.value })}
                      />
                    </td>
                    <td className="p-3 align-top">
                      <input
                        className="w-64 rounded-xl border border-[#E2D8C9] px-2 py-1 text-sm"
                        defaultValue={r.model_name}
                        onChange={(e) => setDraft(r.stage_key, { model_name: e.target.value })}
                      />
                    </td>
                    <td className="p-3 align-top">
                      <input
                        className="w-44 rounded-xl border border-[#E2D8C9] px-2 py-1 text-sm"
                        placeholder={r.fallback_provider || "—"}
                        defaultValue={r.fallback_model || ""}
                        onChange={(e) => setDraft(r.stage_key, { fallback_model: e.target.value || null })}
                      />
                    </td>
                    <td className="p-3 align-top">
                      <code className="text-xs bg-[#F8F1E7] rounded px-2 py-1">{r.env_key || "—"}</code>
                    </td>
                    <td className="p-3 align-top">
                      <label className="inline-flex items-center gap-2 text-xs">
                        <input
                          type="checkbox"
                          defaultChecked={r.active}
                          onChange={(e) => setDraft(r.stage_key, { active: e.target.checked })}
                        />
                        {r.active ? <CheckCircle2 className="w-4 h-4 text-[#4F6B3B]" /> : <Ban className="w-4 h-4 text-[#B8612F]" />}
                      </label>
                    </td>
                    <td className="p-3 align-top">
                      <button
                        disabled={!dirty || savingKey === r.stage_key}
                        onClick={() => save(r)}
                        className="inline-flex items-center gap-2 bg-[#E8F0E1] text-[#4F6B3B] rounded-full px-3 py-1.5 text-xs font-bold disabled:opacity-40"
                        data-testid={`save-${r.stage_key}`}
                      >
                        {savingKey === r.stage_key ? <Loader2 className="w-3 h-3 animate-spin" /> : <Save className="w-3 h-3" />}
                        حفظ
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
