import React, { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { CheckCircle2, AlertTriangle, PlugZap, RotateCcw, Plus, Save, Layers, KeyRound, Info, Beaker } from "lucide-react";
import { api } from "../../lib/api";
import { Badge, Drawer, Field, Panel, diff, errText, inputCls } from "./engineUi";

// M4: which model each stage uses (only catalog models, only with a key), the
// premium video renderer, ready-made model sets, and the model catalog with
// what every model costs. Customer prices follow the chosen models.

const STATUS_TONE = { recommended: "green", available: "neutral", testing_only: "gold", retired: "red" };
const SOURCE_LABEL = { invoice: "من فاتورة fal", list: "قائمة الأسعار", estimate: "تقدير" };
const UNIT_SUFFIX = { "1m_tokens": "مليون توكن", image: "صورة", second: "ثانية", minute: "دقيقة" };
const QUALITY_AR = { low: "منخفضة", medium: "متوسطة", high: "عالية" };
const UNIT_FOR = { text: "1m_tokens", image: "image", tts: "minute", video: "second", music: "minute" };

const usd = (v) => (typeof v === "number" ? `$${Number(v.toFixed(3))}` : null);

export function priceText(price) {
  if (!price) return "السعر غير مقاس";
  const unit = UNIT_SUFFIX[price.unit] || price.unit;
  if (price.by_quality) {
    return Object.entries(price.by_quality).map(([q, v]) => `${QUALITY_AR[q] || q} ${usd(v)}`).join(" • ") + ` / ${unit}`;
  }
  if (price.unit === "1m_tokens" && (price.input_usd != null || price.output_usd != null)) {
    return `${usd(price.input_usd) ?? "?"} دخل • ${usd(price.output_usd) ?? "?"} خرج / ${unit}`;
  }
  return price.usd != null ? `${usd(price.usd)} / ${unit}` : "السعر غير مقاس";
}

function KeyBadge({ k }) {
  if (!k || k.source === "local") return <Badge>محلي — مش محتاج مفتاح</Badge>;
  if (!k.configured) return <Badge tone="red">المفتاح {k.env_key} ناقص</Badge>;
  if (k.source === "shared") return <Badge tone="green">مفتاح fal مشترك ({k.shared_from})</Badge>;
  return <Badge tone="green">المفتاح موجود</Badge>;
}

// ============================================================================ stages
export function StagesTab() {
  const [state, setState] = useState(null);
  const [prices, setPrices] = useState(null);
  const [busy, setBusy] = useState(null);
  const [tests, setTests] = useState({});

  const loadPrices = () => api.get("/public/story-price", { params: { seconds: 60, output_type: "both" } })
    .then((r) => setPrices(r.data.tiers)).catch(() => setPrices(null));
  const reload = () => {
    loadPrices();
    return api.get("/admin/engine/stages").then((r) => setState(r.data)).catch(() => setState({ stages: [] }));
  };
  useEffect(() => { reload(); }, []);

  const byCap = useMemo(() => {
    const out = {};
    (state?.catalog || []).forEach((m) => { (out[m.capability] = out[m.capability] || []).push(m); });
    return out;
  }, [state]);

  if (!state) return <p className="font-body text-[#8A9AB0]">جاري التحميل…</p>;

  const run = async (key, fn, ok) => {
    setBusy(key);
    try { await fn(); if (ok) toast.success(ok); await reload(); }
    catch (e) { toast.error(errText(e, "فشل")); }
    finally { setBusy(null); }
  };

  const choose = (row, value) => {
    const [provider, ...rest] = value.split("|");
    const model_name = rest.join("|");
    const entry = (byCap[row.capability] || []).find((m) => m.provider === provider && m.model_name === model_name);
    if (entry?.status === "testing_only" &&
        !window.confirm(`"${entry.label}" للتجربة بس — ${entry.notes_ar || ""}\nتستخدمه برضه؟`)) return;
    run(row.stage_key, () => api.patch(`/admin/engine/stages/${row.stage_key}`, { provider, model_name }),
      `${row.name_ar} ← ${entry?.label || model_name}`);
  };

  const test = async (row) => {
    setTests((t) => ({ ...t, [row.stage_key]: { loading: true } }));
    try {
      const { data } = await api.post(`/admin/engine/stages/${row.stage_key}/test`, null, { timeout: 30000 });
      setTests((t) => ({ ...t, [row.stage_key]: data }));
    } catch (e) {
      setTests((t) => ({ ...t, [row.stage_key]: { ok: false, error: errText(e, "فشل الاختبار") } }));
    }
  };

  const applyPreset = (p) => {
    if (!window.confirm(`تطبّق "${p.name}"؟ هتغيّر موديلات ${p.stages.length} مرحلة.\n${p.description || ""}`)) return;
    run(`preset-${p.id}`, () => api.post(`/admin/engine/presets/${p.id}/apply`), `اتطبّقت "${p.name}"`);
  };
  const savePreset = () => {
    const name = window.prompt("اسم المجموعة (مثلاً: اقتصادي — Haiku + CassetteAI)");
    if (!name || name.trim().length < 2) return;
    run("preset-save", () => api.post("/admin/engine/presets", { name: name.trim() }), `اتحفظت "${name.trim()}"`);
  };
  const deletePreset = (p) => {
    if (!window.confirm(`تمسح مجموعة "${p.name}"؟ (الإعداد الحالي مش هيتغيّر)`)) return;
    run(`preset-del-${p.id}`, () => api.delete(`/admin/engine/presets/${p.id}`), "اتمسحت");
  };

  const videoModels = byCap.video || [];
  const balanced = state.stages.find((s) => s.stage_key === "video_generation");

  return (
    <div className="space-y-4" data-testid="engine-stages">
      <Panel className="bg-[#E8F0E1] border-[#87A96B]/30">
        <div className="flex items-start gap-3 flex-wrap justify-between">
          <p className="font-body text-sm text-[#3F5B2E] max-w-2xl">
            كل مرحلة بتختار موديل من <b>الكتالوج</b> بس، ولازم مفتاحه يكون موجود — فمفيش مرحلة ممكن تقع على موديل
            مفيش حاجة تعرف تشغّله. سعر القصة للعميل بيتحسب من أسعار الموديلات دي، فأي تغيير هنا بيغيّر السعر.
          </p>
          {prices && (
            <div className="font-body text-sm text-[#2D3748] bg-white rounded-2xl px-4 py-2 border border-[#87A96B]/30" data-testid="stages-price-preview">
              قصة 60 ث دلوقتي:{" "}
              {prices.map((t) => (
                <span key={t.video_tier} className="ms-2">
                  {t.label_ar} <b>{t.price_sar} ر.س</b> <span className="text-xs text-[#8A9AB0]" dir="ltr">(cost ${t.cost_usd})</span>
                </span>
              ))}
            </div>
          )}
        </div>
      </Panel>

      <Panel>
        <div className="flex items-center gap-2 mb-3 flex-wrap">
          <Layers className="w-4 h-4 text-[#729352]" />
          <h3 className="font-heading font-bold text-[#2D3748]">مجموعات جاهزة</h3>
          <span className="font-body text-xs text-[#8A9AB0]">بتغيّر كذا مرحلة مرة واحدة — بتظهر هنا بس لو كل موديلاتها في الكتالوج</span>
          <button onClick={savePreset} disabled={!!busy}
            className="mr-auto inline-flex items-center gap-1 rounded-2xl bg-white border border-dashed border-[#87A96B] px-3 py-1.5 text-xs font-body font-bold text-[#4F6B3B]"
            data-testid="preset-save-current">
            <Plus className="w-3.5 h-3.5" /> احفظ الإعداد الحالي كمجموعة
          </button>
        </div>
        <div className="flex gap-2 flex-wrap">
          {(state.presets || []).length === 0 && <span className="font-body text-sm text-[#8A9AB0]">مفيش مجموعات لسه</span>}
          {(state.presets || []).map((p) => (
            <span key={p.id} className="inline-flex items-center rounded-2xl bg-[#FDFBF7] border border-[#E2D8C9] hover:border-[#87A96B]">
              <button onClick={() => applyPreset(p)} disabled={!!busy} title={p.description || ""}
                className="inline-flex items-center gap-2 px-4 py-2 text-sm font-body font-bold text-[#2D3748] disabled:opacity-50"
                data-testid={`preset-${p.id}`}>
                {p.name}
                {p.intended_use === "testing" && <Badge tone="gold">تجربة</Badge>}
                {p.is_active && <Badge tone="green">آخر واحدة اتطبّقت</Badge>}
              </button>
              {!p.is_seeded && (
                <button onClick={() => deletePreset(p)} disabled={!!busy} aria-label={`امسح ${p.name}`} title="امسح المجموعة"
                  className="px-2 py-2 text-[#B8612F] text-sm font-bold border-r border-[#E2D8C9]">×</button>
              )}
            </span>
          ))}
        </div>
      </Panel>

      <div className="space-y-3">
        {state.stages.map((row) => {
          const options = byCap[row.capability] || [];
          const current = `${row.provider}|${row.model_name}`;
          const t = tests[row.stage_key];
          return (
            <Panel key={row.stage_key} className={row.enabled ? "" : "opacity-70"}>
              <div className="flex items-start justify-between gap-3 flex-wrap mb-3">
                <div className="flex items-center gap-2 flex-wrap">
                  <h3 className="font-heading text-lg font-bold text-[#2D3748]">{row.name_ar}</h3>
                  <Badge>{row.capability_ar}</Badge>
                  {!row.in_catalog && <Badge tone="red">الموديل الحالي مش في الكتالوج</Badge>}
                  {row.selectable && <KeyBadge k={row.key} />}
                </div>
                {row.toggleable ? (
                  <label className="inline-flex items-center gap-2 font-body text-sm cursor-pointer" title={row.toggle_note_ar}>
                    <input type="checkbox" checked={row.enabled} disabled={!!busy}
                      onChange={(e) => run(row.stage_key, () => api.patch(`/admin/engine/stages/${row.stage_key}`, { enabled: e.target.checked }),
                        e.target.checked ? "اتفعّلت" : "اتقفلت")}
                      className="accent-[#87A96B] w-4 h-4" data-testid={`stage-toggle-${row.stage_key}`} />
                    {row.enabled ? "شغّالة" : "مقفولة"}
                  </label>
                ) : <span className="font-body text-xs text-[#8A9AB0]">أساسية — شغّالة دايماً</span>}
              </div>

              {row.selectable ? (
                <>
                  <div className="flex gap-2 flex-wrap items-center">
                    <select value={current} disabled={!!busy} onChange={(e) => choose(row, e.target.value)}
                      className={`${inputCls} md:max-w-md`} data-testid={`stage-model-${row.stage_key}`}>
                      {!options.some((m) => `${m.provider}|${m.model_name}` === current) && (
                        <option value={current}>{row.model_name} (مش في الكتالوج)</option>
                      )}
                      {options.map((m) => (
                        <option key={m.id} value={`${m.provider}|${m.model_name}`} disabled={m.status === "retired"}>
                          {m.label} — {state.statuses?.[m.status] || m.status}
                        </option>
                      ))}
                    </select>
                    <button onClick={() => test(row)} disabled={t?.loading}
                      className="inline-flex items-center gap-1 rounded-2xl bg-white border border-[#E2D8C9] px-3 py-2 text-xs font-body font-bold text-[#5A677D] hover:border-[#87A96B]"
                      data-testid={`stage-test-${row.stage_key}`}>
                      <PlugZap className="w-3.5 h-3.5" /> {t?.loading ? "جاري الاختبار…" : "اختبار المفتاح"}
                    </button>
                    <Link to={`/admin/lab?stage=${row.stage_key}`} title="جرّب المرحلة دي على بيانات حقيقية"
                      className="inline-flex items-center gap-1 rounded-2xl bg-white border border-[#E2D8C9] px-3 py-2 text-xs font-body font-bold text-[#5A677D] hover:border-[#87A96B]">
                      <Beaker className="w-3.5 h-3.5" /> المختبر
                    </Link>
                    {!row.is_default && (
                      <button onClick={() => run(row.stage_key, () => api.post(`/admin/engine/stages/${row.stage_key}/reset`), "رجعت للافتراضي")}
                        disabled={!!busy} title={`الافتراضي: ${row.default_label}`}
                        className="inline-flex items-center gap-1 rounded-2xl bg-[#F8F1E7] px-3 py-2 text-xs font-body font-bold text-[#8B5A2B]">
                        <RotateCcw className="w-3.5 h-3.5" /> الافتراضي
                      </button>
                    )}
                  </div>
                  {t && !t.loading && (
                    <p className={`font-body text-xs mt-2 inline-flex items-center gap-1 ${t.ok ? "text-[#3F5B2E]" : "text-[#B8612F]"}`}>
                      {t.ok ? <CheckCircle2 className="w-3.5 h-3.5" /> : <AlertTriangle className="w-3.5 h-3.5" />}
                      {t.ok ? `المفتاح شغّال${t.latency_ms ? ` (${t.latency_ms} ms)` : ""}` : (t.error || "فشل")}
                    </p>
                  )}
                  {row.catalog_entry && (
                    <div className="mt-3 font-body text-xs text-[#5A677D] space-y-1">
                      <div><span className="font-bold text-[#2D3748]">السعر:</span> {priceText(row.catalog_entry.price)}
                        {row.catalog_entry.price?.source && <span className="text-[#8A9AB0]"> ({SOURCE_LABEL[row.catalog_entry.price.source]})</span>}</div>
                      {row.catalog_entry.notes_ar && <div>{row.catalog_entry.notes_ar}</div>}
                      <div dir="ltr" className="text-left font-mono text-[11px] text-[#8A9AB0]">{row.provider} / {row.model_name}</div>
                    </div>
                  )}
                </>
              ) : (
                <p className="font-body text-xs text-[#5A677D]">بتشتغل على السيرفر نفسه ({row.model_name}) — مفيش موديل تختاره.</p>
              )}
            </Panel>
          );
        })}
      </div>

      <Panel>
        <h3 className="font-heading text-lg font-bold text-[#2D3748] mb-1">جودة الفيديو اللي العميل بيختارها</h3>
        <p className="font-body text-xs text-[#8A9AB0] mb-4">
          "متوازن" بيستخدم موديل مرحلة توليد الفيديو اللي فوق. "فاخر" بيستخدم الموديل ده — والعميل بيدفع سعره.
        </p>
        <div className="grid md:grid-cols-2 gap-4">
          <div className="bg-[#FDFBF7] border border-[#E2D8C9] rounded-2xl p-4">
            <div className="font-body text-sm font-bold text-[#2D3748] mb-1">متوازن</div>
            <div className="font-body text-sm text-[#5A677D]">{balanced?.catalog_entry?.label || balanced?.model_name}</div>
            <div className="font-body text-xs text-[#8A9AB0] mt-1">{priceText(balanced?.catalog_entry?.price)}</div>
          </div>
          <div className="bg-[#FDFBF7] border border-[#E2D8C9] rounded-2xl p-4">
            <div className="font-body text-sm font-bold text-[#2D3748] mb-2">فاخر</div>
            <select value={state.premium_video?.model_name || ""} disabled={!!busy}
              onChange={(e) => run("premium", () => api.put("/admin/engine/video-premium", { model_name: e.target.value }), "اتغيّر موديل الجودة الفاخرة")}
              className={inputCls} data-testid="premium-video-model">
              {videoModels.map((m) => <option key={m.id} value={m.model_name}>{m.label}</option>)}
            </select>
            <div className="font-body text-xs text-[#8A9AB0] mt-1">{priceText(state.premium_video?.entry?.price)}</div>
          </div>
        </div>
      </Panel>

      <p className="font-body text-xs text-[#8A9AB0] inline-flex items-center gap-1">
        <KeyRound className="w-3.5 h-3.5" /> المفاتيح نفسها بتتضاف من{" "}
        <Link to="/admin/secrets" className="text-[#4F6B3B] font-bold underline">المفاتيح والمزوّدين</Link>.
      </p>
    </div>
  );
}

// ============================================================================ catalog
const EMPTY_PRICE = (cap) => (cap === "image"
  ? { unit: "image", by_quality: { low: null, medium: null, high: null }, source: null }
  : cap === "text" ? { unit: "1m_tokens", input_usd: null, output_usd: null, source: null }
    : { unit: UNIT_FOR[cap], usd: null, source: null });

export function CatalogTab() {
  const [state, setState] = useState(null);
  const [cap, setCap] = useState("all");
  const [editing, setEditing] = useState(null);

  const reload = () => api.get("/admin/engine/catalog").then((r) => setState(r.data)).catch(() => setState({ items: [] }));
  useEffect(() => { reload(); }, []);
  if (!state) return <p className="font-body text-[#8A9AB0]">جاري التحميل…</p>;

  const items = state.items.filter((m) => cap === "all" || m.capability === cap);
  const inUse = (m) => state.in_use?.[`${m.provider}|${m.model_name}`] || [];

  const toggleActive = async (m) => {
    try {
      await api.patch(`/admin/engine/catalog/${m.id}`, { active: !m.active });
      toast.success(m.active ? "اتخفى من الاختيارات" : "رجع للاختيارات");
      reload();
    } catch (e) { toast.error(errText(e, "فشل")); }
  };

  return (
    <div data-testid="engine-catalog">
      <div className="flex items-start justify-between gap-4 mb-4 flex-wrap">
        <p className="font-body text-sm text-[#5A677D] max-w-2xl">
          الموديلات اللي المراحل تقدر تستخدمها. بيتضاف هنا بس موديل لمزوّد عندنا كود بيشغّله. الأسعار مكتوب جنبها مصدرها
          (فاتورة fal، قائمة أسعار المزوّد، أو تقدير من المقارنات) — وهي اللي بيتحسب منها سعر القصة.
        </p>
        <button onClick={() => setEditing({ isNew: true, original: {}, draft: { capability: "image", provider: "fal_image", model_name: "", label: "", status: "available", notes_ar: "", price: EMPTY_PRICE("image") } })}
          className="btn-primary inline-flex items-center gap-2" data-testid="catalog-new-btn">
          <Plus className="w-4 h-4" /> موديل جديد
        </button>
      </div>

      <div className="flex gap-2 mb-4 flex-wrap">
        {[["all", "الكل"], ...Object.entries(state.capability_labels || {})].map(([k, l]) => (
          <button key={k} onClick={() => setCap(k)}
            className={`rounded-full px-4 py-1.5 text-sm font-body font-bold ${cap === k ? "bg-[#87A96B] text-white" : "bg-white border border-[#E2D8C9] text-[#5A677D]"}`}>
            {l} ({k === "all" ? state.items.length : state.items.filter((m) => m.capability === k).length})
          </button>
        ))}
      </div>

      <div className="grid md:grid-cols-2 xl:grid-cols-3 gap-3">
        {items.map((m) => (
          <Panel key={m.id} className={m.active ? "" : "opacity-60"}>
            <div className="flex items-center gap-2 flex-wrap mb-1">
              <h3 className="font-heading font-bold text-[#2D3748]">{m.label}</h3>
              <Badge tone={STATUS_TONE[m.status]}>{state.statuses?.[m.status] || m.status}</Badge>
              {!m.active && <Badge tone="red">مخفي</Badge>}
            </div>
            <div dir="ltr" className="text-left font-mono text-[11px] text-[#8A9AB0] mb-2 break-all">{m.provider} / {m.model_name}</div>
            <div className="font-body text-xs text-[#2D3748] mb-1">
              <b>{state.capability_labels?.[m.capability]}</b> • {priceText(m.price)}
              {m.price?.source ? <span className="text-[#8A9AB0]"> ({SOURCE_LABEL[m.price.source]})</span> : null}
            </div>
            {m.notes_ar && <p className="font-body text-xs text-[#5A677D] mb-2">{m.notes_ar}</p>}
            {inUse(m).length > 0 && <p className="font-body text-xs text-[#3F5B2E] font-bold mb-2">مستخدم في: {inUse(m).join("، ")}</p>}
            <div className="flex gap-2">
              <button onClick={() => setEditing({ isNew: false, original: m, draft: JSON.parse(JSON.stringify(m)) })}
                className="flex-1 rounded-2xl bg-[#E8F0E1] px-3 py-1.5 text-sm font-body font-bold text-[#4F6B3B]" data-testid={`catalog-edit-${m.id}`}>
                تعديل
              </button>
              <button onClick={() => toggleActive(m)} disabled={m.active && inUse(m).length > 0}
                title={m.active && inUse(m).length ? "مستخدم دلوقتي — غيّره من المراحل الأول" : ""}
                className="rounded-2xl bg-[#F8F1E7] px-3 py-1.5 text-xs font-body font-bold text-[#8B5A2B] disabled:opacity-40">
                {m.active ? "إخفاء" : "إظهار"}
              </button>
            </div>
          </Panel>
        ))}
      </div>

      {editing && (
        <CatalogEditor editing={editing} meta={state} onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); reload(); }} />
      )}
    </div>
  );
}

function num(v) {
  if (v === "" || v === null || v === undefined) return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

function CatalogEditor({ editing, meta, onClose, onSaved }) {
  const [d, setD] = useState(editing.draft);
  const [busy, setBusy] = useState(false);
  const set = (patch) => setD((x) => ({ ...x, ...patch }));
  const setPrice = (patch) => setD((x) => ({ ...x, price: { ...x.price, ...patch } }));
  const providers = meta.executors?.[d.capability] || [];

  const cleanPrice = (p) => {
    const out = { unit: p.unit, source: p.source || null };
    if (p.by_quality) out.by_quality = Object.fromEntries(Object.entries(p.by_quality).filter(([, v]) => num(v) !== null).map(([k, v]) => [k, num(v)]));
    if (p.unit === "1m_tokens") { out.input_usd = num(p.input_usd); out.output_usd = num(p.output_usd); }
    if (!p.by_quality && p.unit !== "1m_tokens") out.usd = num(p.usd);
    if (out.by_quality && !Object.keys(out.by_quality).length) { delete out.by_quality; out.usd = null; }
    return out;
  };

  const save = async () => {
    setBusy(true);
    try {
      if (editing.isNew) {
        await api.post("/admin/engine/catalog", { ...d, price: cleanPrice(d.price) });
        toast.success("الموديل اتضاف للكتالوج — اختاره من المراحل");
      } else {
        const changes = diff(editing.original, { ...d, price: cleanPrice(d.price) }, ["label", "status", "notes_ar", "price"]);
        if (!Object.keys(changes).length) { toast.info("مفيش تعديل"); setBusy(false); return; }
        await api.patch(`/admin/engine/catalog/${editing.original.id}`, changes);
        toast.success("اتحفظ");
      }
      onSaved();
    } catch (e) { toast.error(errText(e)); }
    finally { setBusy(false); }
  };

  const p = d.price || EMPTY_PRICE(d.capability);
  return (
    <Drawer title={editing.isNew ? "موديل جديد في الكتالوج" : `تعديل: ${editing.original.label}`} onClose={onClose}
      footer={<button onClick={save} disabled={busy} className="btn-primary inline-flex items-center gap-2 disabled:opacity-50" data-testid="catalog-save-btn">
        <Save className="w-4 h-4" /> {busy ? "جاري الحفظ…" : "حفظ"}</button>}>
      {editing.isNew ? (
        <>
          <div className="grid md:grid-cols-2 gap-x-4">
            <Field label="النوع">
              <select value={d.capability} onChange={(e) => {
                const cap = e.target.value;
                set({ capability: cap, provider: (meta.executors?.[cap] || [])[0] || "", price: EMPTY_PRICE(cap) });
              }} className={inputCls}>
                {Object.entries(meta.capability_labels || {}).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
              </select>
            </Field>
            <Field label="المزوّد" hint="بس المزوّدين اللي عندنا كود بيشغّلهم للنوع ده.">
              <select value={d.provider} onChange={(e) => set({ provider: e.target.value })} dir="ltr" className={`${inputCls} font-mono`}>
                {providers.map((x) => <option key={x} value={x}>{x}</option>)}
              </select>
            </Field>
          </div>
          <Field label="اسم الموديل عند المزوّد" hint="زي ما بيتكتب في الـ API بالظبط — مثال: fal-ai/kling-video/v3/standard/image-to-video">
            <input value={d.model_name} onChange={(e) => set({ model_name: e.target.value.trim() })} dir="ltr" className={`${inputCls} font-mono`} data-testid="catalog-model-name" />
          </Field>
        </>
      ) : (
        <p dir="ltr" className="text-left font-mono text-xs text-[#8A9AB0] mb-4">{d.provider} / {d.model_name}</p>
      )}
      <div className="grid md:grid-cols-2 gap-x-4">
        <Field label="الاسم في الأدمن">
          <input value={d.label} onChange={(e) => set({ label: e.target.value })} className={inputCls} data-testid="catalog-label" />
        </Field>
        <Field label="الحالة">
          <select value={d.status} onChange={(e) => set({ status: e.target.value })} className={inputCls}>
            {Object.entries(meta.statuses || {}).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
          </select>
        </Field>
      </div>

      <div className="bg-[#FDFBF7] border border-[#E2D8C9] rounded-2xl p-4 mb-4">
        <div className="font-body text-sm font-bold text-[#2D3748] mb-3">السعر (دولار / {UNIT_SUFFIX[p.unit]})</div>
        {p.by_quality ? (
          <div className="grid grid-cols-3 gap-2">
            {["low", "medium", "high"].map((q) => (
              <Field key={q} label={QUALITY_AR[q]}>
                <input type="number" step="0.001" min="0" value={p.by_quality[q] ?? ""} dir="ltr" className={inputCls}
                  onChange={(e) => setPrice({ by_quality: { ...p.by_quality, [q]: e.target.value } })} />
              </Field>
            ))}
          </div>
        ) : p.unit === "1m_tokens" ? (
          <div className="grid grid-cols-2 gap-2">
            <Field label="دخل (input)"><input type="number" step="0.01" min="0" value={p.input_usd ?? ""} dir="ltr" className={inputCls} onChange={(e) => setPrice({ input_usd: e.target.value })} /></Field>
            <Field label="خرج (output)"><input type="number" step="0.01" min="0" value={p.output_usd ?? ""} dir="ltr" className={inputCls} onChange={(e) => setPrice({ output_usd: e.target.value })} /></Field>
          </div>
        ) : (
          <Field label={`لكل ${UNIT_SUFFIX[p.unit]}`}>
            <input type="number" step="0.001" min="0" value={p.usd ?? ""} dir="ltr" className={inputCls} onChange={(e) => setPrice({ usd: e.target.value })} data-testid="catalog-price-usd" />
          </Field>
        )}
        <Field label="مصدر السعر">
          <select value={p.source || ""} onChange={(e) => setPrice({ source: e.target.value || null })} className={inputCls}>
            <option value="">غير مقاس</option>
            {Object.entries(SOURCE_LABEL).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
          </select>
        </Field>
        <p className="font-body text-xs text-[#8A9AB0] inline-flex items-center gap-1"><Info className="w-3 h-3" /> لو فاضي، الحاسبة بتستخدم السعر المقاس لموديلنا الحالي من نفس النوع.</p>
      </div>
      <Field label="ملاحظات">
        <textarea rows={3} value={d.notes_ar || ""} onChange={(e) => set({ notes_ar: e.target.value })} className={inputCls} />
      </Field>
    </Drawer>
  );
}
