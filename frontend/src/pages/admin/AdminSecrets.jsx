import React, { useEffect, useState } from "react";
import { api } from "../../lib/api";
import {
  Lock, ShieldCheck, ShieldAlert, RefreshCw, Loader2, Copy, Check, Save, Trash2, Activity, KeyRound, ChevronLeft,
} from "lucide-react";
import { toast } from "sonner";

// Keys grouped by what they do today: the engine's keys first, then payment
// and email, then providers nothing uses right now (folded), then the system.
const GROUPS = [
  { key: "engine", title: "مفاتيح المحرك المستخدمة الآن", hint: "المراحل اللي شغّالة دلوقتي بتقرا المفاتيح دي." },
  { key: "business", title: "الدفع والإيميلات", hint: "لازمين قبل الإطلاق: ميسر للدفع بالبطاقة، وSMTP لإيميلات العملاء." },
  { key: "alternative", title: "مزوّدات بديلة — مش مستخدمة حالياً", hint: "محتاجها بس لو غيّرت موديل مرحلة لمزوّد منهم من «المحرك والموديلات».", folded: true },
  { key: "system", title: "النظام", hint: "بيتدار من السيرفر نفسه، مش من هنا." },
];

const SOURCE = {
  override: { label: "محفوظ هنا (مشفّر)", cls: "bg-[#DEEBCF] text-[#3F5B2E]" },
  env: { label: "من ملف الإعدادات (.env)", cls: "bg-[#F8F1E7] text-[#8B5A2B]" },
  missing: { label: "مش موجود", cls: "bg-[#FCE6D4] text-[#B8612F]" },
};

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
      toast.success("اتحفظ المفتاح مشفّراً — شغّال على طول");
      setEditing((cur) => { const n = { ...cur }; delete n[envKey]; return n; });
      await load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "تعذّر الحفظ");
    } finally {
      setSaving((s) => ({ ...s, [envKey]: false }));
    }
  };

  const removeOverride = async (envKey) => {
    if (!window.confirm("تمسح المفتاح المحفوظ هنا؟ هيرجع يتقري من ملف الإعدادات (.env) لو موجود فيه.")) return;
    try {
      await api.delete(`/admin/secrets/${envKey}`);
      toast.success("اتمسح المفتاح المحفوظ");
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
      if (data.ok) toast.success(`المفتاح شغّال (${data.latency_ms} مللي ثانية)`);
      else toast.error(data.error || "الاختبار فشل");
    } catch {
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

  const items = data.items || [];
  const card = (it) => (
    <SecretCard key={it.key} it={it} canStore={data.encryption_available} value={editing[it.key] || ""}
      onEdit={(v) => setEditing((c) => ({ ...c, [it.key]: v }))} onSave={() => saveOverride(it.key)}
      onRemove={() => removeOverride(it.key)} onTest={() => testProvider(it.test_provider_key, it.key)}
      saving={saving[it.key]} testing={testing[it.key]} result={testResults[it.key]}
      copied={copied === it.key} onCopy={() => copy(it.rotation_instructions, it.key)} />
  );

  return (
    <div data-testid="admin-secrets-page" className="max-w-4xl">
      <div className="mb-6 flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h1 className="font-heading text-3xl font-bold text-[#2D3748] inline-flex items-center gap-2">
            <Lock className="w-7 h-7 text-[#87A96B]" />
            المفاتيح والمزوّدين
          </h1>
          <p className="font-body text-sm text-[#5A677D] mt-2">
            المفتاح اللي تحفظه هنا بيتخزّن مشفّر وبيشتغل على طول من غير إعادة تشغيل، وقيمته مبتظهرش تاني بعد الحفظ.
            لو مش محفوظ هنا، بيتقري من ملف الإعدادات على السيرفر (.env).
          </p>
        </div>
        <button onClick={load} className="rounded-full bg-[#F8F1E7] hover:bg-[#F2E8DA] text-[#8B5A2B] px-4 py-2 text-sm font-bold inline-flex items-center gap-1" data-testid="reload-secrets">
          <RefreshCw className="w-4 h-4" /> تحديث
        </button>
      </div>

      {!data.encryption_available && (
        <div className="bg-[#FCE6D4] border border-[#E07A5F]/40 rounded-2xl p-3 mb-5 flex items-start gap-2 text-sm" data-testid="secrets-warning">
          <ShieldAlert className="w-4 h-4 text-[#B8612F] mt-0.5 shrink-0" />
          <span className="font-body text-[#B8612F]">
            الحفظ من هنا مقفول: السيرفر محتاج <b dir="ltr">SECRETS_ENCRYPTION_KEY</b> في ملف الإعدادات عشان يشفّر المفاتيح.
            لحد ما يتضاف، المفاتيح بتتقري من .env بس.
          </span>
        </div>
      )}

      <div className="space-y-8">
        {GROUPS.map((g) => {
          const list = items.filter((it) => (it.group || "alternative") === g.key);
          if (!list.length) return null;
          const header = (
            <div>
              <h2 className="font-heading text-xl font-bold text-[#729352]">{g.title} <span className="text-sm text-[#8A9AB0] font-body">({list.length})</span></h2>
              <p className="font-body text-xs text-[#5A677D]">{g.hint}</p>
            </div>
          );
          if (g.folded) {
            return (
              <details key={g.key} className="group" data-testid={`secrets-group-${g.key}`}>
                <summary className="cursor-pointer list-none flex items-center justify-between gap-3">
                  {header}
                  <ChevronLeft className="w-5 h-5 text-[#87A96B] transition group-open:-rotate-90 shrink-0" />
                </summary>
                <div className="space-y-4 mt-4">{list.map(card)}</div>
              </details>
            );
          }
          return (
            <section key={g.key} className="space-y-4" data-testid={`secrets-group-${g.key}`}>
              {header}
              {list.map(card)}
            </section>
          );
        })}
      </div>
    </div>
  );
}

function SecretCard({ it, canStore, value, onEdit, onSave, onRemove, onTest, saving, testing, result, copied, onCopy }) {
  const source = SOURCE[it.source] || SOURCE.missing;
  const needed = it.group === "engine" || it.group === "business";
  return (
    <section className="bg-white rounded-2xl p-5 border border-[#E2D8C9]" data-testid={`secret-${it.key}`}>
      <div className="flex items-start justify-between flex-wrap gap-2 mb-2">
        <div className="inline-flex items-start gap-3">
          {it.configured ? <ShieldCheck className="w-5 h-5 text-[#4F6B3B] mt-0.5" />
            : <ShieldAlert className={`w-5 h-5 mt-0.5 ${needed ? "text-[#B8612F]" : "text-[#8A9AB0]"}`} />}
          <div>
            <div className="font-heading font-bold text-[#2D3748] inline-flex items-center gap-2 flex-wrap">
              {it.label}
              <span className={`text-[10px] rounded-full px-2 py-0.5 font-bold ${source.cls}`} data-testid={`secret-${it.key}-source`}>
                {source.label}
              </span>
            </div>
            <div className="text-xs text-[#8A9AB0] font-mono" dir="ltr" style={{ textAlign: "right" }}>{it.key}</div>
          </div>
        </div>
        <div className="text-left">
          <div className={`text-xs font-bold ${it.configured ? "text-[#4F6B3B]" : needed ? "text-[#B8612F]" : "text-[#8A9AB0]"}`} data-testid={`secret-${it.key}-status`}>
            {it.configured ? "موجود ✓" : needed ? "ناقص ✗" : "مش متضاف"}
          </div>
          {it.masked && <div className="text-xs text-[#5A677D] font-mono mt-1" dir="ltr" data-testid={`secret-${it.key}-masked`}>{it.masked}</div>}
          {it.override_updated_at && (
            <div className="text-[10px] text-[#8A9AB0] mt-0.5" title={it.override_updated_at}>
              اتحفظ: {new Date(it.override_updated_at).toLocaleDateString("ar-EG")}
            </div>
          )}
        </div>
      </div>

      <p className="text-sm text-[#5A677D] font-body mb-2">{it.purpose}</p>
      {it.used_by?.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mb-3" data-testid={`secret-${it.key}-used-by`}>
          {it.used_by.map((s) => (
            <span key={s} className="text-[11px] font-bold font-body rounded-full bg-[#E8F0E1] text-[#4F6B3B] px-2 py-0.5">{s}</span>
          ))}
        </div>
      )}

      {!it.system && (
        <div className="bg-[#FDFBF7] border border-[#E2D8C9] rounded-2xl p-3 mb-3 space-y-2" data-testid={`override-block-${it.key}`}>
          <div className="text-[11px] font-bold text-[#5A677D] inline-flex items-center gap-1">
            <KeyRound className="w-3 h-3" /> {it.override_present ? "استبدال المفتاح المحفوظ" : "حفظ مفتاح هنا (مشفّر)"}
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            <input type="password" placeholder="ألصق المفتاح هنا" value={value} onChange={(e) => onEdit(e.target.value)}
              className="input flex-1 min-w-[200px] font-mono text-xs" dir="ltr" data-testid={`override-input-${it.key}`} />
            <button onClick={onSave} disabled={saving || !canStore}
              className="btn-primary text-xs inline-flex items-center gap-1 disabled:opacity-50" data-testid={`override-save-${it.key}`}>
              {saving ? <Loader2 className="w-3 h-3 animate-spin" /> : <Save className="w-3 h-3" />} حفظ
            </button>
            {it.override_present && (
              <button onClick={onRemove}
                className="rounded-full bg-[#FCE6D4] hover:bg-[#F4D2B6] text-[#B8612F] px-3 py-1.5 text-xs font-bold inline-flex items-center gap-1"
                data-testid={`override-delete-${it.key}`}>
                <Trash2 className="w-3 h-3" /> مسح المحفوظ
              </button>
            )}
            {it.test_provider_key && (
              <button onClick={onTest} disabled={testing}
                className="rounded-full bg-[#DEEBCF] hover:bg-[#C8DCB1] text-[#3F5B2E] px-3 py-1.5 text-xs font-bold inline-flex items-center gap-1 disabled:opacity-50"
                data-testid={`test-provider-${it.key}`}>
                {testing ? <Loader2 className="w-3 h-3 animate-spin" /> : <Activity className="w-3 h-3" />} اختبار
              </button>
            )}
          </div>
          {result && (
            <div className={`text-[11px] rounded-xl p-2 font-body ${result.ok ? "bg-[#DEEBCF] text-[#3F5B2E]" : "bg-[#FCE6D4] text-[#B8612F]"}`} data-testid={`test-result-${it.key}`}>
              <b>{result.ok ? "شغّال ✓" : "مش شغّال ✗"}</b>
              {" · "}المفتاح {result.auth_ok ? "مقبول" : "مرفوض"}
              {" · "}الخدمة {result.reachable ? "متاحة" : "مش بترد"}
              {result.latency_ms != null && ` · ${result.latency_ms} مللي ثانية`}
              {result.error && <div className="mt-1 text-[10px] opacity-80" dir="auto">{result.error}</div>}
            </div>
          )}
        </div>
      )}

      {it.rotation_instructions && (
        <details className="bg-[#FDFBF7] rounded-2xl border border-[#E2D8C9]" data-testid={`rotation-${it.key}`}>
          <summary className="cursor-pointer px-4 py-3 font-body text-sm font-bold text-[#2D3748] inline-flex items-center justify-between w-full">
            <span>إزاي أجيب مفتاح جديد؟</span>
            <button type="button" onClick={(e) => { e.preventDefault(); onCopy(); }}
              className="text-xs text-[#87A96B] hover:text-[#4F6B3B] inline-flex items-center gap-1">
              {copied ? <Check className="w-3 h-3" /> : <Copy className="w-3 h-3" />} نسخ
            </button>
          </summary>
          <pre className="px-4 pb-3 font-body text-xs text-[#5A677D] whitespace-pre-wrap leading-6">{it.rotation_instructions}</pre>
        </details>
      )}
    </section>
  );
}
