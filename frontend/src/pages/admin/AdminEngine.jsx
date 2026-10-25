import React, { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import {
  Palette, Languages, Gauge, ScrollText, Plus, Save, Star, Power, Upload, RotateCcw, History, Info, Cpu, Library, FileText,
} from "lucide-react";
import { api, uploadImage, errorMessage } from "../../lib/api";
import { AuthImage, Badge, Drawer, Field, Panel, Text, diff, errText, inputCls } from "./engineUi";
import { CatalogTab, StagesTab } from "./AdminEngineModels";
import { TemplatesTab } from "./AdminEngineTemplates";

// The admin's view of what every generation is built from (M3): art styles,
// dialect profiles, pacing/image quality and the text stages' system prompts.
// Every save creates a new version on the server; plans record the versions they used.

const TABS = [
  { k: "stages", l: "المراحل والموديلات", icon: Cpu },
  { k: "catalog", l: "كتالوج الموديلات", icon: Library },
  { k: "styles", l: "ستايلات الرسم", icon: Palette },
  { k: "dialects", l: "اللهجات والأصوات", icon: Languages },
  { k: "pacing", l: "الإيقاع والجودة", icon: Gauge },
  { k: "system", l: "برومبتات النظام", icon: ScrollText },
  { k: "templates", l: "قوالب الرسائل", icon: FileText },
];

export default function AdminEngine() {
  const [params, setParams] = useSearchParams();
  const tab = TABS.some((t) => t.k === params.get("tab")) ? params.get("tab") : "stages";

  return (
    <div data-testid="admin-engine">
      <div className="mb-6">
        <h1 className="font-heading text-3xl font-bold text-[#2D3748] mb-2">محرك الإنتاج</h1>
        <p className="font-body text-[#5A677D] max-w-3xl">
          الموديلات اللي كل مرحلة بتستخدمها وأسعارها، والطبقات اللي بيتبني منها كل برومبت (الستايل، اللهجة، الإيقاع،
          برومبتات النظام). أي تعديل بيتطبق على التوليد اللي بعده، وكل قصة بتسجّل النسخ اللي اتعملت بيها.
        </p>
      </div>

      <div className="flex gap-2 mb-6 overflow-x-auto pb-1">
        {TABS.map((t) => (
          <button
            key={t.k}
            onClick={() => setParams({ tab: t.k })}
            className={`inline-flex items-center gap-2 rounded-full px-4 py-2 text-sm font-body font-bold whitespace-nowrap transition ${
              tab === t.k ? "bg-[#87A96B] text-white" : "bg-white border border-[#E2D8C9] text-[#5A677D] hover:border-[#87A96B]"
            }`}
            data-testid={`engine-tab-${t.k}`}
          >
            <t.icon className="w-4 h-4" /> {t.l}
          </button>
        ))}
      </div>

      {tab === "stages" && <StagesTab />}
      {tab === "catalog" && <CatalogTab />}
      {tab === "styles" && <StylesTab />}
      {tab === "dialects" && <DialectsTab />}
      {tab === "pacing" && <PacingTab />}
      {tab === "system" && <SystemPromptsTab />}
      {tab === "templates" && <TemplatesTab />}
    </div>
  );
}

// ============================================================================ styles
const STYLE_FIELDS = [
  { k: "style_text", l: "وصف الستايل", rows: 6, ltr: true,
    hint: "بيتحط في برومبت كل شيت شخصية وكل صورة لقطة. ده أهم جزء في شكل القصة." },
  { k: "sheet_rules", l: "قواعد شيت الشخصية", rows: 4, ltr: true,
    hint: "تكوين صورة الشخصية المرجعية (وقفة كاملة، خلفية بيضا…)." },
  { k: "frame_rules", l: "قواعد إطار اللقطة", rows: 3, ltr: true,
    hint: "بيتضاف لكل صورة لقطة: 16:9 كامل من غير حواف ولا نصوص." },
  { k: "motion_text", l: "جملة الحركة الثابتة", rows: 2, ltr: true,
    hint: "بتتضاف لآخر كل برومبت حركة بيتبعت لموديل الفيديو." },
  { k: "negative_text", l: "الممنوعات في الفيديو", rows: 3, ltr: true,
    hint: "الـ negative prompt لموديل الفيديو (واقعية، تشوّه، نصوص…)." },
];
const STYLE_KEYS = ["name_ar", "description_ar", "palette", "lighting", "sort_order", "reference_image",
  "thumbnail_url", ...STYLE_FIELDS.map((f) => f.k)];

function StylesTab() {
  const [styles, setStyles] = useState(null);
  const [editing, setEditing] = useState(null); // {original, draft, isNew}

  const reload = () => api.get("/admin/engine/styles").then((r) => setStyles(r.data)).catch(() => setStyles([]));
  useEffect(() => { reload(); }, []);

  const startNew = () => {
    const base = styles?.find((s) => s.is_default) || {};
    setEditing({
      isNew: true,
      original: {},
      draft: {
        key: "", name_ar: "", description_ar: "", palette: base.palette || "", lighting: base.lighting || "",
        sort_order: styles?.length || 0, reference_image: null, thumbnail_url: null,
        ...Object.fromEntries(STYLE_FIELDS.map((f) => [f.k, base[f.k] || ""])),
      },
    });
  };

  const makeDefault = async (s) => {
    try {
      await api.post(`/admin/engine/styles/${s.key}/make-default`);
      toast.success(`"${s.name_ar}" بقى الستايل الافتراضي`);
      reload();
    } catch (e) { toast.error(errText(e, "فشل")); }
  };

  const toggleActive = async (s) => {
    try {
      await api.patch(`/admin/engine/styles/${s.key}`, { active: !s.active });
      toast.success(s.active ? "اتوقف — مش هيظهر للعملاء" : "اتفعّل");
      reload();
    } catch (e) { toast.error(errText(e, "فشل")); }
  };

  if (!styles) return <p className="font-body text-[#8A9AB0]">جاري التحميل…</p>;

  return (
    <div data-testid="engine-styles">
      <div className="flex items-start justify-between gap-4 mb-4 flex-wrap">
        <p className="font-body text-sm text-[#5A677D] max-w-2xl">
          العميل بيختار ستايل من دول في خطوة "أسلوب القصة". الستايل الافتراضي هو اللي بيتطبق لو العميل ما اختارش.
          الصورة المرجعية لازم تكون شخصيات متخيّلة بالستايل ده — <b>عمرها ما تكون صورة طفل حقيقي</b>.
        </p>
        <button onClick={startNew} className="btn-primary inline-flex items-center gap-2" data-testid="style-new-btn">
          <Plus className="w-4 h-4" /> ستايل جديد
        </button>
      </div>

      <div className="grid md:grid-cols-2 xl:grid-cols-3 gap-4">
        {styles.map((s) => (
          <Panel key={s.key} className={`p-0 overflow-hidden ${s.active ? "" : "opacity-60"}`}>
            <AuthImage path={`/admin/engine/styles/${s.key}/reference`} alt={s.name_ar} className="w-full h-48 object-cover" />
            <div className="p-5">
              <div className="flex items-center gap-2 flex-wrap mb-1">
                <h3 className="font-heading text-lg font-bold text-[#2D3748]">{s.name_ar}</h3>
                {s.is_default && <Badge tone="gold">افتراضي</Badge>}
                {!s.active && <Badge tone="red">متوقف</Badge>}
              </div>
              <p className="font-body text-xs text-[#8A9AB0] mb-2" dir="ltr">{s.key} • v{s.version || 1}</p>
              <p className="font-body text-sm text-[#5A677D] mb-4 min-h-[40px]">{s.description_ar}</p>
              <div className="flex gap-2 flex-wrap">
                <button onClick={() => setEditing({ isNew: false, original: s, draft: { ...s } })}
                  className="flex-1 rounded-2xl bg-[#E8F0E1] px-3 py-2 text-sm font-body font-bold text-[#4F6B3B]"
                  data-testid={`style-edit-${s.key}`}>
                  تعديل
                </button>
                {!s.is_default && s.active && (
                  <button onClick={() => makeDefault(s)} title="اجعله الافتراضي"
                    className="rounded-2xl bg-[#FBEFD5] px-3 py-2 text-[#8B5A2B]"><Star className="w-4 h-4" /></button>
                )}
                {!s.is_default && (
                  <button onClick={() => toggleActive(s)} title={s.active ? "إيقاف" : "تفعيل"}
                    className="rounded-2xl bg-[#F8F1E7] px-3 py-2 text-[#8B5A2B]"><Power className="w-4 h-4" /></button>
                )}
              </div>
            </div>
          </Panel>
        ))}
      </div>

      {editing && (
        <StyleEditor
          editing={editing}
          onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); reload(); }}
        />
      )}
    </div>
  );
}

function StyleEditor({ editing, onClose, onSaved }) {
  const [draft, setDraft] = useState(editing.draft);
  const [busy, setBusy] = useState(false);
  const [uploading, setUploading] = useState(null);
  const set = (patch) => setDraft((d) => ({ ...d, ...patch }));
  const changes = useMemo(() => diff(editing.original, draft, STYLE_KEYS), [editing.original, draft]);

  const upload = async (file, field) => {
    if (!file) return;
    setUploading(field);
    try {
      const r = await uploadImage(file, "style");
      set({ [field]: r.url });
      toast.success("اترفعت — هتتطبق لما تحفظ");
    } catch (e) { toast.error(e.message || "فشل الرفع"); }
    finally { setUploading(null); }
  };

  const save = async () => {
    setBusy(true);
    try {
      if (editing.isNew) {
        await api.post("/admin/engine/styles", { ...draft, active: true });
        toast.success("الستايل اتضاف");
      } else {
        if (!Object.keys(changes).length) { toast.info("مفيش تعديل"); setBusy(false); return; }
        const r = await api.patch(`/admin/engine/styles/${editing.original.key}`, changes);
        toast.success(`اتحفظ — نسخة ${r.data.version}`);
      }
      onSaved();
    } catch (e) { toast.error(errText(e)); }
    finally { setBusy(false); }
  };

  const refLabel = (v) => (!v ? "لا توجد" : v.startsWith("asset:") ? `مع الكود (${v.slice(6)})` : "صورة مرفوعة");

  return (
    <Drawer
      title={editing.isNew ? "ستايل جديد" : `تعديل: ${editing.original.name_ar}`}
      onClose={onClose}
      footer={
        <div className="flex items-center gap-3">
          <button onClick={save} disabled={busy || (!editing.isNew && !Object.keys(changes).length)}
            className="btn-primary inline-flex items-center gap-2 disabled:opacity-50" data-testid="style-save-btn">
            <Save className="w-4 h-4" /> {busy ? "جاري الحفظ…" : "حفظ"}
          </button>
          {!editing.isNew && (
            <span className="font-body text-xs text-[#8A9AB0]">
              {Object.keys(changes).length ? `${Object.keys(changes).length} تعديل • هيتحفظ كنسخة ${(editing.original.version || 1) + 1}` : "مفيش تعديل"}
            </span>
          )}
        </div>
      }
    >
      {editing.isNew && (
        <Field label="المفتاح (بالإنجليزي)" hint="حروف صغيرة وأرقام و _ — مثال: bright_cartoon. ما ينفعش يتغير بعدين.">
          <input value={draft.key} onChange={(e) => set({ key: e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, "") })}
            dir="ltr" className={`${inputCls} font-mono`} data-testid="style-key-input" />
        </Field>
      )}
      <div className="grid md:grid-cols-2 gap-x-4">
        <Field label="الاسم اللي يظهر للعميل">
          <input value={draft.name_ar} onChange={(e) => set({ name_ar: e.target.value })} className={inputCls} data-testid="style-name-input" />
        </Field>
        <Field label="الترتيب">
          <input type="number" value={draft.sort_order ?? 0} onChange={(e) => set({ sort_order: parseInt(e.target.value || "0", 10) })} className={inputCls} />
        </Field>
      </div>
      <Field label="وصف قصير للعميل">
        <input value={draft.description_ar || ""} onChange={(e) => set({ description_ar: e.target.value })} className={inputCls} />
      </Field>

      <div className="grid md:grid-cols-2 gap-4 mb-4">
        {[["reference_image", "الصورة المرجعية للستايل", "بتتبعت مع كل شيت شخصية عشان الوشوش تطلع بنفس الستايل."],
          ["thumbnail_url", "صورة العرض للعميل (اختياري)", "لو فاضية، العميل بيشوف الصورة المرجعية."]].map(([field, label, hint]) => (
          <div key={field} className="bg-[#FDFBF7] border border-[#E2D8C9] rounded-2xl p-4">
            <div className="font-body text-sm font-bold text-[#2D3748] mb-1">{label}</div>
            <div className="font-body text-xs text-[#8A9AB0] mb-3">{hint}</div>
            <div className="font-body text-xs text-[#5A677D] mb-2">الحالية: {refLabel(draft[field])}</div>
            <div className="flex gap-2">
              <label className="inline-flex items-center gap-1 rounded-xl bg-white border border-[#E2D8C9] px-3 py-1.5 text-xs font-bold font-body cursor-pointer hover:border-[#87A96B]">
                <Upload className="w-3 h-3" /> {uploading === field ? "جاري الرفع…" : "رفع صورة"}
                <input type="file" accept="image/png,image/jpeg,image/webp" className="hidden"
                  onChange={(e) => upload(e.target.files?.[0], field)} />
              </label>
              {field === "thumbnail_url" && draft[field] && (
                <button onClick={() => set({ [field]: null })} className="text-xs font-body text-[#B8612F]">إزالة</button>
              )}
            </div>
          </div>
        ))}
      </div>

      {STYLE_FIELDS.map((f) => (
        <Field key={f.k} label={f.l} hint={f.hint} counter={<span className="font-body text-xs text-[#8A9AB0]">{(draft[f.k] || "").length}</span>}>
          <Text value={draft[f.k]} onChange={(v) => set({ [f.k]: v })} rows={f.rows} ltr={f.ltr} data-testid={`style-${f.k}`} />
        </Field>
      ))}
      <div className="grid md:grid-cols-2 gap-x-4">
        <Field label="الألوان" hint="بتتسجل في دليل الستايل للخطة.">
          <input value={draft.palette || ""} onChange={(e) => set({ palette: e.target.value })} dir="ltr" className={inputCls} />
        </Field>
        <Field label="الإضاءة">
          <input value={draft.lighting || ""} onChange={(e) => set({ lighting: e.target.value })} dir="ltr" className={inputCls} />
        </Field>
      </div>
      {!editing.isNew && <VersionHistory path={`/admin/engine/styles/${editing.original.key}/versions`} fields={STYLE_FIELDS.map((f) => f.k)} />}
    </Drawer>
  );
}

function VersionHistory({ path, fields }) {
  const [items, setItems] = useState(null);
  const load = () => api.get(path).then((r) => setItems(r.data)).catch(() => setItems([]));
  if (items === null) {
    return (
      <button onClick={load} className="inline-flex items-center gap-1 text-xs font-body font-bold text-[#5A677D] mt-2">
        <History className="w-3 h-3" /> النسخ القديمة
      </button>
    );
  }
  return (
    <div className="mt-4">
      <div className="font-body text-sm font-bold text-[#2D3748] mb-2">النسخ القديمة</div>
      {!items.length && <p className="font-body text-xs text-[#8A9AB0]">مفيش نسخ قديمة لسه.</p>}
      {items.map((v) => (
        <details key={`${v.version}-${v.archived_at}`} className="bg-[#FDFBF7] border border-[#E2D8C9] rounded-2xl p-3 mb-2">
          <summary className="font-body text-xs cursor-pointer text-[#5A677D]">
            نسخة {v.version || 1} • اتبدّلت {new Date(v.archived_at).toLocaleString("ar-EG")} {v.archived_by ? `• ${v.archived_by}` : ""}
          </summary>
          {fields.map((k) => v[k] ? (
            <div key={k} className="mt-2">
              <div className="font-body text-[11px] font-bold text-[#8A9AB0]">{k}</div>
              <pre dir="auto" className="whitespace-pre-wrap text-xs text-[#2D3748] font-mono">{v[k]}</pre>
            </div>
          ) : null)}
        </details>
      ))}
    </div>
  );
}

// ============================================================================ dialects
function DialectsTab() {
  const [state, setState] = useState(null);
  const [editing, setEditing] = useState(null);

  const reload = () => api.get("/admin/engine/dialects").then((r) => setState(r.data)).catch(() => setState({ items: [] }));
  useEffect(() => { reload(); }, []);
  if (!state) return <p className="font-body text-[#8A9AB0]">جاري التحميل…</p>;

  const optionsFor = (key) => (state.language_options || []).filter((o) => o.dialect_key === key);

  return (
    <div data-testid="engine-dialects">
      <div className="flex items-start justify-between gap-4 mb-4 flex-wrap">
        <p className="font-body text-sm text-[#5A677D] max-w-2xl">
          اللهجة بتتحدد من خيار "اللغة" اللي العميل بيختاره. تعليمات الكتابة بتروح لخطة الإنتاج (السرد بيتكتب باللهجة)،
          وتوجيه الصوت والأصوات بيروحوا لموديل الصوت. الفصحى هي الاحتياطي لو اللهجة مش معروفة.
        </p>
        <button onClick={() => setEditing({ isNew: true, original: {}, draft: { key: "", name_ar: "", writing_rules: "", tts_direction: "", voices: { male: "Algieba", female: "Sulafat" } } })}
          className="btn-primary inline-flex items-center gap-2" data-testid="dialect-new-btn">
          <Plus className="w-4 h-4" /> لهجة جديدة
        </button>
      </div>

      <div className="grid lg:grid-cols-3 gap-4">
        {state.items.map((d) => (
          <Panel key={d.key} className={d.active === false ? "opacity-60" : ""}>
            <div className="flex items-center gap-2 flex-wrap mb-1">
              <h3 className="font-heading text-lg font-bold text-[#2D3748]">{d.name_ar}</h3>
              {d.key === state.default_key && <Badge tone="gold">احتياطي</Badge>}
              {d.active === false && <Badge tone="red">متوقفة</Badge>}
            </div>
            <p className="font-body text-xs text-[#8A9AB0] mb-3" dir="ltr">{d.key} • v{d.version || 1}</p>
            <div className="font-body text-xs text-[#5A677D] mb-1 font-bold">توجيه الصوت</div>
            <p dir="ltr" className="font-mono text-xs bg-[#FDFBF7] border border-[#E2D8C9] rounded-xl p-2 mb-3 text-left">{d.tts_direction}</p>
            <div className="flex gap-2 mb-3 flex-wrap">
              <Badge>راوي: {d.voices?.male}</Badge>
              <Badge>راوية: {d.voices?.female}</Badge>
            </div>
            <div className="font-body text-xs text-[#5A677D] mb-4">
              خيار اللغة في الـ builder:{" "}
              {optionsFor(d.key).length
                ? optionsFor(d.key).map((o) => o.name_ar).join("، ")
                : <span className="text-[#B8612F] font-bold">مفيش خيار مربوط — العملاء مش هيقدروا يختاروها</span>}
            </div>
            <button onClick={() => setEditing({ isNew: false, original: d, draft: { ...d, voices: { ...d.voices } } })}
              className="w-full rounded-2xl bg-[#E8F0E1] px-3 py-2 text-sm font-body font-bold text-[#4F6B3B]"
              data-testid={`dialect-edit-${d.key}`}>
              تعديل
            </button>
          </Panel>
        ))}
      </div>

      <datalist id="gemini-voices">
        {(state.voice_suggestions || []).map((v) => <option key={v} value={v} />)}
      </datalist>

      {editing && (
        <DialectEditor editing={editing} defaultKey={state.default_key}
          onClose={() => setEditing(null)} onSaved={() => { setEditing(null); reload(); }} />
      )}
    </div>
  );
}

function DialectEditor({ editing, defaultKey, onClose, onSaved }) {
  const [draft, setDraft] = useState(editing.draft);
  const [busy, setBusy] = useState(false);
  const set = (patch) => setDraft((d) => ({ ...d, ...patch }));
  const changes = useMemo(() => diff(editing.original, draft, ["name_ar", "writing_rules", "tts_direction", "voices", "active"]),
    [editing.original, draft]);
  const dirLen = (draft.tts_direction || "").length;

  const save = async () => {
    setBusy(true);
    try {
      if (editing.isNew) {
        await api.post("/admin/engine/dialects", { ...draft, active: true });
        toast.success("اللهجة اتضافت — اربطها بخيار لغة في صفحة خيارات القصة (نفس المفتاح)");
      } else {
        if (!Object.keys(changes).length) { toast.info("مفيش تعديل"); setBusy(false); return; }
        const r = await api.patch(`/admin/engine/dialects/${editing.original.key}`, changes);
        toast.success(`اتحفظ — نسخة ${r.data.version}`);
      }
      onSaved();
    } catch (e) { toast.error(errText(e)); }
    finally { setBusy(false); }
  };

  return (
    <Drawer
      title={editing.isNew ? "لهجة جديدة" : `تعديل: ${editing.original.name_ar}`}
      onClose={onClose}
      footer={
        <button onClick={save} disabled={busy} className="btn-primary inline-flex items-center gap-2 disabled:opacity-50" data-testid="dialect-save-btn">
          <Save className="w-4 h-4" /> {busy ? "جاري الحفظ…" : "حفظ"}
        </button>
      }
    >
      {editing.isNew && (
        <Field label="المفتاح (بالإنجليزي)" hint="لازم يطابق قيمة (value) خيار اللغة في صفحة خيارات القصة — مثال: levantine.">
          <input value={draft.key} onChange={(e) => set({ key: e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, "") })}
            dir="ltr" className={`${inputCls} font-mono`} />
        </Field>
      )}
      <Field label="الاسم">
        <input value={draft.name_ar} onChange={(e) => set({ name_ar: e.target.value })} className={inputCls} />
      </Field>
      <Field label="تعليمات الكتابة (لخطة الإنتاج)" hint="إزاي يتكتب سطر السرد: مفردات اللهجة، التشكيل على الكلمات اللي ممكن تتنطق غلط، ممنوع الخلط بلهجة تانية.">
        <Text value={draft.writing_rules} onChange={(v) => set({ writing_rules: v })} rows={6} data-testid="dialect-writing" />
      </Field>
      <Field
        label="توجيه الصوت (لموديل الصوت)"
        hint="سطر واحد قصير بالإنجليزي. Gemini بيقرا التوجيهات الطويلة بصوت عالي جوه السرد، فالحد 160 حرف."
        counter={<span className={`font-body text-xs ${dirLen > 160 ? "text-[#B8612F] font-bold" : "text-[#8A9AB0]"}`}>{dirLen}/160</span>}
      >
        <input value={draft.tts_direction} onChange={(e) => set({ tts_direction: e.target.value.replace(/[\r\n]+/g, " ") })}
          dir="ltr" className={`${inputCls} font-mono text-xs`} data-testid="dialect-direction" />
      </Field>
      <div className="grid md:grid-cols-2 gap-x-4">
        <Field label="صوت الراوي" hint="لما العميل يختار راوي ولد، أو الطفل ولد.">
          <input list="gemini-voices" value={draft.voices?.male || ""} onChange={(e) => set({ voices: { ...draft.voices, male: e.target.value.trim() } })}
            dir="ltr" className={`${inputCls} font-mono`} />
        </Field>
        <Field label="صوت الراوية" hint="لما العميل يختار راوية بنت، أو الطفلة بنت.">
          <input list="gemini-voices" value={draft.voices?.female || ""} onChange={(e) => set({ voices: { ...draft.voices, female: e.target.value.trim() } })}
            dir="ltr" className={`${inputCls} font-mono`} />
        </Field>
      </div>
      {!editing.isNew && editing.original.key !== defaultKey && (
        <label className="flex items-center gap-2 font-body text-sm">
          <input type="checkbox" checked={draft.active !== false} onChange={(e) => set({ active: e.target.checked })} className="accent-[#87A96B]" />
          مفعّلة (لو اتوقفت، طلباتها بتتسرد بالفصحى)
        </label>
      )}
    </Drawer>
  );
}

// ============================================================================ pacing + quality
const PACING_FIELDS = [
  { k: "words_per_second", l: "سرعة الكلام (كلمة/ثانية)", step: 0.05, min: 1.2, max: 3,
    hint: "النماذج اللي عجبتك ≈ 1.95. بتحدد عدد كلمات كل سطر سرد وفحص طول الصوت." },
  { k: "shot_seconds", l: "طول اللقطة (ثانية)", step: 0.5, min: 3, max: 10,
    hint: "لقطة جديدة كل كام ثانية. أقل = لقطات أكتر = تكلفة صور أكتر." },
  { k: "line_gap_sec", l: "سكوت بعد كل جملة (ثانية)", step: 0.05, min: 0, max: 1.5,
    hint: "النفَس بين جملة والجملة اللي بعدها." },
  { k: "end_tail_sec", l: "ذيل آخر لقطة (ثانية)", step: 0.1, min: 0, max: 4,
    hint: "وقت زيادة بعد آخر جملة عشان القصة ما تخلصش فجأة." },
  { k: "five_second_stretch", l: "أقصى تبطيء لمقطع 5 ث", step: 0.05, min: 1, max: 1.6,
    hint: "Kling 2.5 بيطلّع 5 أو 10 ث بس. لو الجملة أطول شوية، المقطع بيتبطّأ لحد النسبة دي بدل ما ندفع 10 ث." },
];
const QUALITY_COST = { low: "≈ $0.02", medium: "≈ $0.06", high: "≈ $0.17" };

function PacingTab() {
  const [state, setState] = useState(null);
  const [draft, setDraft] = useState(null);
  const [busy, setBusy] = useState(false);

  const reload = () => api.get("/admin/engine/pacing").then((r) => { setState(r.data); setDraft(r.data.values); })
    .catch((e) => toast.error(errorMessage(e)));
  useEffect(() => { reload(); }, []);
  if (!state || !draft) return <p className="font-body text-[#8A9AB0]">جاري التحميل…</p>;

  const changes = diff(state.values, draft, PACING_FIELDS.map((f) => f.k));
  const qualityChanges = Object.fromEntries(Object.keys(state.image_stages).filter(
    (k) => (draft.image_quality?.[k] || "high") !== (state.values.image_quality?.[k] || "high"),
  ).map((k) => [k, draft.image_quality?.[k] || "high"]));
  const dirty = Object.keys(changes).length || Object.keys(qualityChanges).length;
  const wordsPerShot = Math.floor(draft.shot_seconds * draft.words_per_second) + 1;

  const save = async () => {
    setBusy(true);
    try {
      const body = { ...changes };
      Object.keys(body).forEach((k) => { body[k] = Number(body[k]); });
      if (Object.keys(qualityChanges).length) body.image_quality = qualityChanges;
      await api.patch("/admin/engine/pacing", body);
      toast.success("اتحفظ — هيتطبق على القصص الجاية");
      reload();
    } catch (e) { toast.error(errText(e)); }
    finally { setBusy(false); }
  };

  return (
    <div data-testid="engine-pacing" className="grid lg:grid-cols-3 gap-4">
      <Panel className="lg:col-span-2">
        <h3 className="font-heading text-lg font-bold text-[#2D3748] mb-4">إيقاع القصة</h3>
        <div className="grid md:grid-cols-2 gap-x-4">
          {PACING_FIELDS.map((f) => (
            <Field key={f.k} label={f.l} hint={`${f.hint} الافتراضي: ${state.defaults[f.k]}`}>
              <input type="number" step={f.step} min={f.min} max={f.max} value={draft[f.k]}
                onChange={(e) => setDraft({ ...draft, [f.k]: e.target.value === "" ? "" : Number(e.target.value) })}
                dir="ltr" className={inputCls} data-testid={`pacing-${f.k}`} />
            </Field>
          ))}
        </div>
        <div className="bg-[#E8F0E1] rounded-2xl p-4 font-body text-sm text-[#3F5B2E]">
          بالأرقام دي: سطر السرد ≤ <b>{wordsPerShot}</b> كلمات، وقصة 60 ث ≈ <b>{Math.round(60 / (draft.shot_seconds || 5))}</b> لقطة
          (90 ث ≈ <b>{Math.round(90 / (draft.shot_seconds || 5))}</b>).
        </div>
      </Panel>

      <Panel>
        <h3 className="font-heading text-lg font-bold text-[#2D3748] mb-1">جودة الصور لكل مرحلة</h3>
        <p className="font-body text-xs text-[#8A9AB0] mb-4">GPT Image 2 — السعر التقريبي للصورة جنب كل اختيار. الشيتات خليها عالية: كل الصور اللي بعدها بتورث الشبه منها.</p>
        {Object.entries(state.image_stages).map(([stage, label]) => (
          <Field key={stage} label={label}>
            <div className="flex gap-1.5">
              {["low", "medium", "high"].map((q) => {
                const active = (draft.image_quality?.[stage] || "high") === q;
                return (
                  <button key={q} type="button"
                    onClick={() => setDraft({ ...draft, image_quality: { ...draft.image_quality, [stage]: q } })}
                    className={`flex-1 rounded-xl px-2 py-1.5 text-xs font-body font-bold border transition ${
                      active ? "bg-[#87A96B] text-white border-[#87A96B]" : "bg-[#FDFBF7] border-[#E2D8C9] text-[#5A677D]"
                    }`}
                    data-testid={`quality-${stage}-${q}`}>
                    {{ low: "منخفضة", medium: "متوسطة", high: "عالية" }[q]}
                    <span className="block font-normal opacity-80" dir="ltr">{QUALITY_COST[q]}</span>
                  </button>
                );
              })}
            </div>
          </Field>
        ))}
      </Panel>

      <div className="lg:col-span-3 flex items-center gap-3 flex-wrap">
        <button onClick={save} disabled={!dirty || busy} className="btn-primary inline-flex items-center gap-2 disabled:opacity-50" data-testid="pacing-save-btn">
          <Save className="w-4 h-4" /> {busy ? "جاري الحفظ…" : "حفظ"}
        </button>
        <span className="inline-flex items-center gap-1 font-body text-xs text-[#8A9AB0]">
          <Info className="w-3 h-3" /> أسعار القصص لسه محسوبة على الإيقاع والجودة الافتراضيين — ربطها بالأرقام دي في مرحلة التسعير (M6).
        </span>
      </div>
    </div>
  );
}

// ============================================================================ system prompts
function SystemPromptsTab() {
  const [stages, setStages] = useState(null);
  const reload = () => api.get("/admin/engine/system-prompts").then((r) => setStages(r.data)).catch((e) => toast.error(errorMessage(e)));
  useEffect(() => { reload(); }, []);
  if (!stages) return <p className="font-body text-[#8A9AB0]">جاري التحميل…</p>;
  return (
    <div className="space-y-4" data-testid="engine-system-prompts">
      <p className="font-body text-sm text-[#5A677D] max-w-3xl">
        التعليمات الثابتة اللي بتتبعت للموديل في مرحلتي السيناريوهات وخطة الإنتاج (رسالة الـ system). لو مفيش نسخة من الأدمن،
        بيتبعت النص الأصلي اللي مع الكود — وده بيتحسّن مع تحديثات الكود. أول ما تحفظ نسخة، نسختك هي اللي بتتبعت لحد ما ترجع للأصلي.
      </p>
      {stages.map((s) => <SystemPromptCard key={s.stage} stage={s} onChanged={reload} />)}
    </div>
  );
}

function SystemPromptCard({ stage, onChanged }) {
  const current = stage.active?.template_text ?? stage.code_default;
  const [text, setText] = useState(current);
  const [busy, setBusy] = useState(false);
  useEffect(() => { setText(stage.active?.template_text ?? stage.code_default); }, [stage]);
  const missing = (stage.must_contain || []).filter((w) => !text.includes(w));
  const dirty = text !== current;

  const run = async (fn, ok) => {
    setBusy(true);
    try { await fn(); toast.success(ok); onChanged(); }
    catch (e) { toast.error(errText(e)); }
    finally { setBusy(false); }
  };

  return (
    <Panel>
      <div className="flex items-center justify-between gap-3 flex-wrap mb-3">
        <div className="flex items-center gap-2 flex-wrap">
          <h3 className="font-heading text-lg font-bold text-[#2D3748]">{stage.name_ar}</h3>
          {stage.active
            ? <Badge tone="green">نسخة الأدمن {stage.active.version}</Badge>
            : <Badge>النص الأصلي من الكود</Badge>}
        </div>
        <span className="font-body text-xs text-[#8A9AB0]">{text.length.toLocaleString("ar-EG")} حرف</span>
      </div>
      <Text value={text} onChange={setText} rows={16} data-testid={`system-text-${stage.stage}`} />
      {missing.length > 0 && (
        <p className="font-body text-xs text-[#B8612F] font-bold mt-2">
          لازم البرومبت يفضل فيه: {missing.join("، ")} — من غيرهم الخطة بتفشل في التحقق.
        </p>
      )}
      <div className="flex gap-2 flex-wrap mt-3">
        <button disabled={!dirty || missing.length > 0 || busy}
          onClick={() => run(() => api.post(`/admin/engine/system-prompts/${stage.stage}`, { template_text: text, activate: true }), "اتحفظت نسخة جديدة واتفعّلت")}
          className="btn-primary inline-flex items-center gap-2 disabled:opacity-50" data-testid={`system-save-${stage.stage}`}>
          <Save className="w-4 h-4" /> حفظ كنسخة جديدة وتفعيلها
        </button>
        {dirty && (
          <button onClick={() => setText(current)} className="rounded-2xl bg-[#F8F1E7] px-4 py-2 text-sm font-body font-bold text-[#8B5A2B]">
            تجاهل التعديل
          </button>
        )}
        {stage.active && (
          <button disabled={busy}
            onClick={() => window.confirm("ترجع للنص الأصلي اللي مع الكود؟ نسخك هتفضل محفوظة في السجل.") &&
              run(() => api.post(`/admin/engine/system-prompts/${stage.stage}/reset`), "رجع للنص الأصلي")}
            className="inline-flex items-center gap-1 rounded-2xl bg-white border border-[#E2D8C9] px-4 py-2 text-sm font-body font-bold text-[#5A677D]">
            <RotateCcw className="w-4 h-4" /> رجوع للنص الأصلي
          </button>
        )}
      </div>
      {stage.versions?.length > 0 && (
        <details className="mt-4">
          <summary className="font-body text-xs font-bold text-[#5A677D] cursor-pointer">النسخ ({stage.versions.length})</summary>
          <div className="mt-2 space-y-1.5">
            {stage.versions.map((v) => (
              <div key={v.id} className="flex items-center justify-between gap-2 bg-[#FDFBF7] border border-[#E2D8C9] rounded-xl px-3 py-2">
                <span className="font-body text-xs text-[#5A677D]">
                  نسخة {v.version} • {new Date(v.created_at).toLocaleString("ar-EG")} {v.created_by ? `• ${v.created_by}` : ""}
                </span>
                {v.active ? <Badge tone="green">مفعّلة</Badge> : (
                  <button disabled={busy}
                    onClick={() => run(() => api.post(`/admin/engine/system-prompts/${stage.stage}/activate/${v.id}`), `نسخة ${v.version} اتفعّلت`)}
                    className="text-xs font-body font-bold text-[#4F6B3B]">تفعيل</button>
                )}
              </div>
            ))}
          </div>
        </details>
      )}
    </Panel>
  );
}
