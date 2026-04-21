import React, { useEffect, useState } from "react";
import { api } from "../../lib/api";
import { ShieldCheck, RefreshCcw, CheckCircle2, XCircle, Loader2, Info, Key } from "lucide-react";
import { toast } from "sonner";

export default function AdminApiStatus() {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [testing, setTesting] = useState(null);
  const [testResults, setTestResults] = useState({});

  const load = async () => {
    setLoading(true);
    try {
      const { data } = await api.get("/admin/api-status");
      setRows(data.providers);
    } catch {
      toast.error("تعذّر تحميل حالة API");
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { load(); }, []);

  const test = async (provider) => {
    setTesting(provider);
    try {
      const { data } = await api.post("/admin/providers/test", { provider });
      setTestResults((t) => ({ ...t, [provider]: data }));
      if (data.ok) toast.success(`✓ ${provider}: متاح`);
      else toast.error(`✗ ${provider}: غير مُهيّأ`);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "فشل الاختبار");
    } finally {
      setTesting(null);
    }
  };

  return (
    <div className="space-y-6" data-testid="admin-api-status-page" dir="rtl">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="font-heading text-3xl font-bold text-[#2D3748] mb-1 flex items-center gap-2">
            <ShieldCheck className="w-6 h-6 text-[#87A96B]" />
            حالة API
          </h1>
          <p className="font-body text-sm text-[#5A677D]">
            عرض للقراءة فقط لحالة الـEnv Vars. القيم تظهر مُقنّعة (masked) ولا تُعرض قيمة المفتاح أبداً.
          </p>
        </div>
        <button onClick={load} className="inline-flex items-center gap-2 bg-[#F8F1E7] text-[#8B5A2B] rounded-full px-4 py-2 text-sm font-bold">
          <RefreshCcw className="w-4 h-4" /> تحديث
        </button>
      </div>

      <div className="rounded-2xl overflow-hidden bg-[#FCE6D4] border border-[#E07A5F]/30 p-4 text-sm font-body text-[#8B5A2B] flex items-start gap-2">
        <Info className="w-4 h-4 mt-0.5 shrink-0" />
        <div>
          <b>قاعدة الأمان:</b> مفاتيح الـAPI يجب أن تبقى في ملف <code className="bg-white rounded px-1">.env</code> فقط. لا تُخزّن في قاعدة البيانات.
          الصفحة هنا للتحقق من وجود المفاتيح فقط — لا لحفظها أو عرضها.
          <br/>
          لتعديل أي مفتاح: حرّر <code className="bg-white rounded px-1">/app/backend/.env</code> ثم أعد تشغيل الخدمة.
        </div>
      </div>

      {loading ? (
        <div className="text-center py-8"><Loader2 className="w-6 h-6 animate-spin mx-auto text-[#87A96B]" /></div>
      ) : (
        <div className="grid sm:grid-cols-2 gap-4" data-testid="api-status-grid">
          {rows.map((p) => {
            const result = testResults[p.provider];
            return (
              <div key={p.provider} className="bg-white rounded-2xl border border-[#E2D8C9] p-4" data-testid={`api-${p.provider}`}>
                <div className="flex items-start justify-between gap-2 mb-2">
                  <div>
                    <div className="font-heading font-bold text-[#2D3748]">{p.label}</div>
                    <div className="text-xs text-[#8A9AB0]">{p.provider}</div>
                  </div>
                  {p.configured ? (
                    <span className="inline-flex items-center gap-1 bg-[#E8F0E1] text-[#4F6B3B] text-xs font-bold rounded-full px-2 py-1">
                      <CheckCircle2 className="w-3 h-3" /> مُهيّأ
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1 bg-[#FCE6D4] text-[#B8612F] text-xs font-bold rounded-full px-2 py-1">
                      <XCircle className="w-3 h-3" /> غير مُهيّأ
                    </span>
                  )}
                </div>
                <div className="text-xs font-body text-[#5A677D] space-y-1">
                  <div className="inline-flex items-center gap-1"><Key className="w-3 h-3" /> Env: <code className="bg-[#F8F1E7] rounded px-1">{p.env_key || "—"}</code></div>
                  <div>القيمة: <code className="bg-[#F8F1E7] rounded px-1">{p.masked}</code></div>
                </div>
                {p.env_key && (
                  <button
                    onClick={() => test(p.provider)}
                    disabled={testing === p.provider}
                    className="mt-3 inline-flex items-center gap-2 bg-[#F8F1E7] text-[#8B5A2B] rounded-full px-3 py-1.5 text-xs font-bold disabled:opacity-40"
                    data-testid={`test-${p.provider}`}
                  >
                    {testing === p.provider ? <Loader2 className="w-3 h-3 animate-spin" /> : <ShieldCheck className="w-3 h-3" />}
                    اختبار سريع
                  </button>
                )}
                {result && (
                  <div className={`mt-2 text-xs font-body ${result.ok ? "text-[#4F6B3B]" : "text-[#B8612F]"}`}>
                    {result.ok ? "✓" : "✗"} {result.note}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
