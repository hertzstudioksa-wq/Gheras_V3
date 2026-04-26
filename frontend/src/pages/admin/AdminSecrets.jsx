import React, { useEffect, useState } from "react";
import { api } from "../../lib/api";
import { Lock, ShieldCheck, ShieldAlert, RefreshCw, Loader2, Copy, Check, Save, Trash2, Activity, KeyRound } from "lucide-react";
import { toast } from "sonner";

export default function AdminSecrets() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [copied, setCopied] = useState(null);
  const [editing, setEditing] = useState({});      // { ENV_KEY: "raw" }
  const [saving, setSaving] = useState({});
  const [testing, setTesting] = useState({});
  const [testResults, setTestResults] = useState({});

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

  const saveOverride = async (envKey) => {
    const raw = editing[envKey];
    if (!raw || !raw.trim()) { toast.error("القيمة مطلوبة"); return; }
    setSaving((s) => ({ ...s, [envKey]: true }));
    try {
      await api.put(`/admin/secrets/${envKey}`, { value: raw });
      toast.success(`${envKey} حُفظ مشفّراً (override آمن)`);
      setEditing((cur) => { const n = { ...cur }; delete n[envKey]; return n; });
      await load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "تعذّر الحفظ");
    } finally {
      setSaving((s) => ({ ...s, [envKey]: false }));
    }
  };

  const removeOverride = async (envKey) => {
    if (!confirm(`حذف override المخزّن لـ ${envKey}؟ سيتمّ الرجوع لقيمة .env.`)) return;
    try {
      await api.delete(`/admin/secrets/${envKey}`);
      toast.success(`${envKey}: حُذف الـ override`);
      await load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "تعذّر الحذف");
    }
  };

  const testProvider = async (providerKey, envKey) => {
    if (!providerKey) return;
    setTesting((s) => ({ ...s, [envKey]: true }));
    try {
      const { data } = await api.post(`/admin/secrets/test/${providerKey}`);
      setTestResults((cur) => ({ ...cur, [envKey]: data }));
      if (data.ok) toast.success(`${providerKey}: متّصل (${data.latency_ms}ms)`);
      else toast.error(`${providerKey}: ${data.error || "فشل"}`);
    } catch (e) {
      toast.error("تعذّر الاختبار");
    } finally {
      setTesting((s) => ({ ...s, [envKey]: false }));
    }
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
            تخزين آمن مشفّر (Fernet) في قاعدة البيانات، أو الرجوع تلقائياً لـ .env. القيمة الخام لا تُعاد بعد الحفظ.
          </p>
        </div>
        <button onClick={load} className="rounded-full bg-[#F8F1E7] hover:bg-[#F2E8DA] text-[#8B5A2B] px-4 py-2 text-sm font-bold inline-flex items-center gap-1" data-testid="reload-secrets">
          <RefreshCw className="w-4 h-4" /> تحديث
        </button>
      </div>

      <div className="bg-[#F8F1E7] border border-[#D4A373]/40 rounded-2xl p-3 mb-5 flex items-start gap-2 text-sm" data-testid="secrets-warning">
        <ShieldAlert className="w-4 h-4 text-[#8B5A2B] mt-0.5 shrink-0" />
        <span className="font-body text-[#8B5A2B]">
          {data.note_ar}{" "}
          <b>encryption_available={String(data.encryption_available)}</b>
        </span>
      </div>

      <div className="space-y-4">
        {(data.items || []).map((it) => {
          const tr = testResults[it.key];
          return (
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
                    {it.optional && <span className="bg-[#EEE9E0] text-[#5A677D] text-[10px] rounded-full px-2 py-0.5">OPTIONAL</span>}
                    <span className={`text-[10px] rounded-full px-2 py-0.5 font-bold ${
                      it.source === "override" ? "bg-[#DEEBCF] text-[#3F5B2E]" :
                      it.source === "env"      ? "bg-[#F8F1E7] text-[#8B5A2B]" :
                                                  "bg-[#FCE6D4] text-[#B8612F]"
                    }`} data-testid={`secret-${it.key}-source`}>
                      source: {it.source}
                    </span>
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
                {it.override_updated_at && (
                  <div className="text-[10px] text-[#8A9AB0] mt-0.5" title={it.override_updated_at}>
                    حُدّث: {new Date(it.override_updated_at).toLocaleDateString("ar-SA")}
                  </div>
                )}
              </div>
            </div>

            <p className="text-sm text-[#5A677D] font-body mb-3"><b>الاستخدام:</b> {it.purpose}</p>

            {/* Phase H — secure write controls */}
            {!it.system && (
              <div className="bg-[#FDFBF7] border border-[#E2D8C9] rounded-2xl p-3 mb-3 space-y-2" data-testid={`override-block-${it.key}`}>
                <div className="text-[11px] font-bold text-[#5A677D] inline-flex items-center gap-1">
                  <KeyRound className="w-3 h-3" /> Override آمن (مشفّر في DB)
                </div>
                <div className="flex items-center gap-2 flex-wrap">
                  <input
                    type="password"
                    placeholder="ألصق مفتاحاً جديداً هنا"
                    value={editing[it.key] || ""}
                    onChange={(e) => setEditing((c) => ({ ...c, [it.key]: e.target.value }))}
                    className="input flex-1 min-w-[200px] font-mono text-xs"
                    data-testid={`override-input-${it.key}`}
                  />
                  <button
                    onClick={() => saveOverride(it.key)}
                    disabled={saving[it.key] || !data.encryption_available}
                    className="btn-primary text-xs inline-flex items-center gap-1 disabled:opacity-50"
                    data-testid={`override-save-${it.key}`}
                  >
                    {saving[it.key] ? <Loader2 className="w-3 h-3 animate-spin" /> : <Save className="w-3 h-3" />}
                    حفظ آمن
                  </button>
                  {it.override_present && (
                    <button
                      onClick={() => removeOverride(it.key)}
                      className="rounded-full bg-[#FCE6D4] hover:bg-[#F4D2B6] text-[#B8612F] px-3 py-1.5 text-xs font-bold inline-flex items-center gap-1"
                      data-testid={`override-delete-${it.key}`}
                    >
                      <Trash2 className="w-3 h-3" /> حذف override
                    </button>
                  )}
                  {it.test_provider_key && (
                    <button
                      onClick={() => testProvider(it.test_provider_key, it.key)}
                      disabled={testing[it.key]}
                      className="rounded-full bg-[#DEEBCF] hover:bg-[#C8DCB1] text-[#3F5B2E] px-3 py-1.5 text-xs font-bold inline-flex items-center gap-1 disabled:opacity-50"
                      data-testid={`test-provider-${it.key}`}
                    >
                      {testing[it.key] ? <Loader2 className="w-3 h-3 animate-spin" /> : <Activity className="w-3 h-3" />}
                      اختبار اتصال
                    </button>
                  )}
                </div>
                {tr && (
                  <div className={`text-[11px] rounded-xl p-2 ${tr.ok ? "bg-[#DEEBCF] text-[#3F5B2E]" : "bg-[#FCE6D4] text-[#B8612F]"}`} data-testid={`test-result-${it.key}`}>
                    <b>{tr.ok ? "متّصل ✓" : "فشل ✗"}</b> · auth_ok={String(tr.auth_ok)} · reachable={String(tr.reachable)} · latency={tr.latency_ms}ms · source={tr.secret_source}
                    {tr.error && <div className="mt-1 font-mono text-[10px] opacity-80">{tr.error}</div>}
                  </div>
                )}
              </div>
            )}

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
          );
        })}
      </div>
    </div>
  );
}
