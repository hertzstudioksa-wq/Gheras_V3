import React, { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import {
  ArrowDown, ArrowUp, Award, ExternalLink, Heart, Moon, PenTool, Plus, Rocket, Save, Shield, Sparkles, Sprout, Star, Sun,
  Trash2,
} from "lucide-react";
import { api, fileSrc, uploadImage } from "../../lib/api";
import { AdminPage, PageState } from "../../components/admin/AdminKit";

// Site content (M5b, audit AF-14): Arabic section and field names instead of
// raw keys, and a real editor for card lists (the old JSON box dropped every
// keystroke that made the JSON invalid).

const SECTIONS = {
  hero: "الواجهة الرئيسية", how: "كيف تعمل غِراس", values: "لماذا غِراس", footer: "التذييل",
  business: "بيانات المنشأة (تظهر في الشروط والخصوصية والتذييل)",
  showcase: "عينة الصفحة الرئيسية (فيديو وصور — القسم مخفي لحد ما ترفع حاجة)",
};
const ORDER = ["business", "showcase", "hero", "how", "values", "footer"];
const mediaKind = (key) => (/\.video_url$/.test(key) ? "video" : /\.(poster_url|image_url|step\d_image)$/.test(key) ? "image" : null);
// Business details read in the order a registration certificate lists them.
const BUSINESS_ORDER = ["business.legal_name", "business.cr_number", "business.vat_number", "business.address",
  "business.phone"];
// The icons the homepage cards can show (Landing.ICON_MAP), picked by sight.
const ICONS = [
  ["heart", Heart, "قلب"], ["shield", Shield, "درع"], ["sprout", Sprout, "نبتة"], ["sparkles", Sparkles, "لمعة"],
  ["award", Award, "وسام"], ["star", Star, "نجمة"], ["sun", Sun, "شمس"], ["moon", Moon, "قمر"],
  ["rocket", Rocket, "صاروخ"], ["pen-tool", PenTool, "قلم"],
];

function fieldLabel(key) {
  const tail = key.split(".").slice(1).join(".");
  const step = tail.match(/^step(\d+)\.(title|desc)$/);
  if (step) return `الخطوة ${step[1]} — ${step[2] === "title" ? "العنوان" : "الوصف"}`;
  return {
    title: "العنوان", subtitle: "الوصف تحت العنوان", cta_primary: "الزر الأساسي", cta_secondary: "الزر التاني",
    copyright: "حقوق النشر", tagline: "الشعار", items: "البطاقات",
    contact_email: "إيميل التواصل", instagram: "رابط إنستغرام", x: "رابط X (تويتر)",
    legal_name: "الاسم التجاري المسجّل", cr_number: "رقم السجل التجاري", vat_number: "الرقم الضريبي",
    address: "العنوان الوطني", phone: "رقم التواصل / واتساب",
    caption: "سطر تحت الفيديو", image_url: "صورة الواجهة (غلاف قصة حقيقية)", image_caption: "اسم القصة تحت الصورة", video_url: "فيديو العينة (MP4، حد أقصى 40 ميجا)", poster_url: "صورة الغلاف قبل التشغيل",
    step1_image: "الشريط — 1) صورة الطفل", step2_image: "الشريط — 2) شخصيته الكرتون", step3_image: "الشريط — 3) مشهد من القصة",
  }[tail] || tail;
}

export default function AdminContent() {
  const [blocks, setBlocks] = useState(null);
  const [error, setError] = useState(null);
  const [edits, setEdits] = useState({});

  const load = () => {
    setError(null);
    api.get("/admin/content").then((r) => setBlocks(r.data)).catch(() => setError("تعذّر تحميل المحتوى"));
  };
  useEffect(load, []);

  const grouped = useMemo(() => {
    const g = {};
    (blocks || []).forEach((b) => { (g[b.section || "other"] = g[b.section || "other"] || []).push(b); });
    const rank = (k) => { const i = BUSINESS_ORDER.indexOf(k); return i < 0 ? 99 : i; };
    Object.values(g).forEach((list) => list.sort((a, b) =>
      rank(a.key) - rank(b.key) || a.key.localeCompare(b.key, "en", { numeric: true })));
    return g;
  }, [blocks]);

  const save = async (b) => {
    try {
      await api.put("/admin/content", { key: b.key, value: edits[b.key], section: b.section });
      toast.success("اتحفظ — ظاهر في الموقع دلوقتي");
      setEdits((e) => { const n = { ...e }; delete n[b.key]; return n; });
      load();
    } catch (e) { toast.error(e?.response?.data?.detail || "فشل الحفظ"); }
  };

  const sections = [...ORDER.filter((s) => grouped[s]), ...Object.keys(grouped).filter((s) => !ORDER.includes(s))];
  return (
    <AdminPage title="نصوص الموقع" description="النصوص اللي بتظهر في الصفحة الرئيسية. أي حفظ بيظهر في الموقع على طول."
      actions={<a href="/" target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 rounded-full bg-white border border-[#E2D8C9] px-4 py-2 text-sm font-body font-bold text-[#5A677D]">
        <ExternalLink className="w-4 h-4" /> افتح الصفحة الرئيسية</a>}
      testId="admin-content">
      <PageState loading={!blocks && !error} error={error} onRetry={load} empty={blocks && !blocks.length}>
        {sections.map((section) => (
          <section key={section} className="mb-8">
            <h2 className="font-heading text-xl font-bold text-[#729352] mb-3">{SECTIONS[section] || section}</h2>
            <div className="bg-white rounded-3xl border border-[#E2D8C9] divide-y divide-[#E2D8C9]">
              {grouped[section].map((b) => {
                const value = edits[b.key] !== undefined ? edits[b.key] : b.value;
                const dirty = edits[b.key] !== undefined && JSON.stringify(edits[b.key]) !== JSON.stringify(b.value);
                const set = (v) => setEdits({ ...edits, [b.key]: v });
                return (
                  <div key={b.key} className="p-5" data-testid={`content-row-${b.key}`}>
                    <label className="block text-sm font-bold text-[#2D3748] mb-2 font-body">{fieldLabel(b.key)}</label>
                    {mediaKind(b.key) ? <MediaField kind={mediaKind(b.key)} value={value || ""} onChange={set} />
                      : Array.isArray(value) ? <CardsEditor items={value} onChange={set} />
                      : typeof value === "string" && value.length > 70
                        ? <textarea rows={3} value={value} onChange={(e) => set(e.target.value)}
                            className="w-full bg-[#FDFBF7] border border-[#E2D8C9] rounded-2xl px-4 py-2 font-body mb-3" />
                        : <input value={value ?? ""} onChange={(e) => set(e.target.value)}
                            className="w-full bg-[#FDFBF7] border border-[#E2D8C9] rounded-2xl px-4 py-2 font-body mb-3" />}
                    <button onClick={() => save(b)} disabled={!dirty}
                      className="rounded-full bg-[#87A96B] hover:bg-[#729352] text-white px-5 py-2 text-sm font-bold font-body inline-flex items-center gap-2 disabled:opacity-40">
                      <Save className="w-4 h-4" /> حفظ
                    </button>
                  </div>
                );
              })}
            </div>
          </section>
        ))}
      </PageState>
    </AdminPage>
  );
}

// Upload + preview for homepage media (public "site" files). Save to publish.
function MediaField({ kind, value, onChange }) {
  const [busy, setBusy] = useState(false);
  const pick = async (e) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    setBusy(true);
    try {
      if (kind === "image") {
        const r = await uploadImage(file, "site");
        onChange(r.url);
      } else {
        const form = new FormData();
        form.append("file", file);
        const { data } = await api.post("/uploads/site-video", form, {
          headers: { "Content-Type": "multipart/form-data" }, timeout: 300000,
        });
        onChange(data.url);
      }
      toast.success("اترفع — اضغط «حفظ» عشان يظهر في الموقع");
    } catch (err) {
      toast.error(err?.response?.data?.detail || err.message || "فشل الرفع");
    } finally {
      setBusy(false);
    }
  };
  const src = value ? fileSrc(value) : "";
  return (
    <div className="flex items-center gap-3 flex-wrap mb-3">
      <div className="w-40 h-24 rounded-xl bg-[#FDFBF7] border border-[#E2D8C9] overflow-hidden grid place-content-center text-xs text-[#8A9AB0] font-body">
        {!src ? "مفيش" : kind === "video"
          ? <video src={src} muted className="w-40 h-24 object-cover" />
          : <img src={src} alt="" className="w-40 h-24 object-cover" />}
      </div>
      <label className={`rounded-full bg-white border border-[#87A96B] text-[#4F6B3B] px-4 py-1.5 text-sm font-bold font-body cursor-pointer ${busy ? "opacity-50 pointer-events-none" : ""}`}>
        {busy ? "جاري الرفع…" : value ? "استبدال" : "رفع"}
        <input type="file" hidden accept={kind === "video" ? "video/mp4,video/webm" : "image/png,image/jpeg,image/webp"} onChange={pick} />
      </label>
      {value && (
        <button type="button" onClick={() => onChange("")} className="rounded-full bg-[#FCE6D4] text-[#B8612F] px-4 py-1.5 text-sm font-bold font-body">
          إزالة
        </button>
      )}
    </div>
  );
}

function CardsEditor({ items, onChange }) {
  const update = (i, patch) => onChange(items.map((it, j) => (j === i ? { ...it, ...patch } : it)));
  const move = (i, d) => {
    const next = [...items];
    const [it] = next.splice(i, 1);
    next.splice(i + d, 0, it);
    onChange(next);
  };
  return (
    <div className="space-y-3 mb-3">
      {items.map((it, i) => (
        <div key={i} className="bg-[#FDFBF7] border border-[#E2D8C9] rounded-2xl p-3 grid md:grid-cols-[120px_1fr_auto] gap-3 items-start">
          <div className="grid grid-cols-5 md:grid-cols-3 gap-1" role="radiogroup" aria-label="الأيقونة">
            {ICONS.map(([ic, Icon, label]) => (
              <button key={ic} type="button" role="radio" aria-checked={it.icon === ic} title={label} aria-label={label}
                onClick={() => update(i, { icon: ic })}
                className={`h-8 rounded-lg grid place-content-center border ${it.icon === ic
                  ? "bg-[#87A96B] border-[#87A96B] text-white" : "bg-white border-[#E2D8C9] text-[#729352] hover:border-[#87A96B]"}`}>
                <Icon className="w-4 h-4" />
              </button>
            ))}
          </div>
          <div className="space-y-2">
            <input value={it.title || ""} onChange={(e) => update(i, { title: e.target.value })} placeholder="العنوان"
              className="w-full bg-white border border-[#E2D8C9] rounded-xl px-3 py-1.5 font-body font-bold" />
            <textarea rows={2} value={it.desc || ""} onChange={(e) => update(i, { desc: e.target.value })} placeholder="الوصف"
              className="w-full bg-white border border-[#E2D8C9] rounded-xl px-3 py-1.5 font-body text-sm" />
          </div>
          <div className="flex md:flex-col gap-1">
            <button type="button" onClick={() => move(i, -1)} disabled={i === 0} className="p-1.5 rounded-lg bg-white border border-[#E2D8C9] disabled:opacity-30" aria-label="لفوق"><ArrowUp className="w-4 h-4" /></button>
            <button type="button" onClick={() => move(i, 1)} disabled={i === items.length - 1} className="p-1.5 rounded-lg bg-white border border-[#E2D8C9] disabled:opacity-30" aria-label="لتحت"><ArrowDown className="w-4 h-4" /></button>
            <button type="button" onClick={() => onChange(items.filter((_, j) => j !== i))} className="p-1.5 rounded-lg bg-[#FCE6D4] text-[#B8612F]" aria-label="امسح"><Trash2 className="w-4 h-4" /></button>
          </div>
        </div>
      ))}
      <button type="button" onClick={() => onChange([...items, { icon: "sparkles", title: "", desc: "" }])}
        className="inline-flex items-center gap-1 rounded-full bg-white border border-dashed border-[#87A96B] px-4 py-1.5 text-sm font-body font-bold text-[#4F6B3B]">
        <Plus className="w-4 h-4" /> بطاقة جديدة
      </button>
    </div>
  );
}
