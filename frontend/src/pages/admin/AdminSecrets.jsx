import React, { useEffect, useState } from "react";
import { api } from "../../lib/api";
import { Lock, ShieldCheck, ShieldAlert, RefreshCw, Loader2, Copy, Check } from "lucide-react";
import { toast } from "sonner";

export default function AdminSecrets() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [copied, setCopied] = useState(null);

  const load = async () => {
    setLoading(true);
    try {
      const { data } = await api.get("/admin/secrets/status");
      setData(data);
    } catch {
      toast.error("تعذّر تحميل حالة المفاتيح");
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { load(); }, []);

  const copy = (text, key) => {
    navigator.clipboard.writeText(text || "");
    setCopied(key);
    setTimeout(() => setCopied(null), 1500);
  };

  if (loading || !data) {
    return (
      <div className="flex items-center justify-center py-20" data-testid="admin-secrets-loading">
        <Loader2 className="w-6 h-6 animate-spin text-[#87A96B]" />
      </div>
    );
  }

  return (
    <div data-testid="admin-secrets-page" className="max-w-4xl">
      <div className="mb-6 flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h1 className="font-heading text-3xl font-bold text-[#2D3748] inline-flex items-center gap-2">
            <Lock className="w-7 h-7 text-[#87A96B]" />
            مفاتيح الأمان والمزوّدين
          </h1>
          <p className="font-body text-sm text-[#5A677D] mt-2">
            عرض حالة المفاتيح فقط. لا يمكن تعديل أي مفتاح من هنا — حماية أمنية مقصودة.
          </p>
        </div>
        <button onClick={load} className="rounded-full bg-[#F8F1E7] hover:bg-[#F2E8DA] text-[#8B5A2B] px-4 py-2 text-sm font-bold inline-flex items-center gap-1" data-testid="reload-secrets">
          <RefreshCw className="w-4 h-4" /> تحديث
        </button>
      </div>

      <div className="bg-[#F8F1E7] border border-[#D4A373]/40 rounded-2xl p-3 mb-5 flex items-start gap-2 text-sm" data-testid="secrets-warning">
        <ShieldAlert className="w-4 h-4 text-[#8B5A2B] mt-0.5 shrink-0" />
        <span className="font-body text-[#8B5A2B]">
          {data.note_ar}
        </span>
      </div>

      <div className="space-y-4">
        {(data.items || []).map((it) => (
          <section key={it.key} className="bg-white rounded-2xl p-5 border border-[#E2D8C9]" data-testid={`secret-${it.key}`}>
            <div className="flex items-center justify-between flex-wrap gap-2 mb-2">
              <div className="inline-flex items-center gap-3">
                {it.configured ? (
                  <ShieldCheck className="w-5 h-5 text-[#4F6B3B]" />
                ) : (
                  <ShieldAlert className="w-5 h-5 text-[#B8612F]" />
                )}
                <div>
                  <div className="font-heading font-bold text-[#2D3748] inline-flex items-center gap-2">
                    {it.label}
                    {it.system && <span className="bg-[#E2D8C9] text-[#5A677D] text-[10px] rounded-full px-2 py-0.5">SYSTEM</span>}
                  </div>
                  <div className="text-xs text-[#8A9AB0] font-body font-mono">{it.key}</div>
                </div>
              </div>
              <div className="text-right">
                <div className={`text-xs font-bold ${it.configured ? "text-[#4F6B3B]" : "text-[#B8612F]"}`} data-testid={`secret-${it.key}-status`}>
                  {it.configured ? "مُعَدّ ✓" : "غير مُعَدّ ✗"}
                </div>
                {it.masked && (
                  <div className="text-xs text-[#5A677D] font-mono mt-1" data-testid={`secret-${it.key}-masked`}>
                    {it.masked}
                  </div>
                )}
              </div>
            </div>

            <p className="text-sm text-[#5A677D] font-body mb-3"><b>الاستخدام:</b> {it.purpose}</p>

            <details className="bg-[#FDFBF7] rounded-2xl border border-[#E2D8C9]" data-testid={`rotation-${it.key}`}>
              <summary className="cursor-pointer px-4 py-3 font-body text-sm font-bold text-[#2D3748] inline-flex items-center justify-between w-full">
                <span>تعليمات تدوير المفتاح</span>
                <button
                  type="button"
                  onClick={(e) => { e.preventDefault(); copy(it.rotation_instructions, it.key); }}
                  className="text-xs text-[#87A96B] hover:text-[#4F6B3B] inline-flex items-center gap-1"
                >
                  {copied === it.key ? <Check className="w-3 h-3" /> : <Copy className="w-3 h-3" />}
                  نسخ
                </button>
              </summary>
              <pre className="px-4 pb-3 font-body text-xs text-[#5A677D] whitespace-pre-wrap leading-6">
                {it.rotation_instructions}
              </pre>
            </details>
          </section>
        ))}
      </div>
    </div>
  );
}
