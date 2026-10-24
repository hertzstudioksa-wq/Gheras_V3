import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { Pencil, RotateCcw, Save, X } from "lucide-react";
import { api } from "../../lib/api";
import { AdminPage, KpiCard, PageState } from "../../components/admin/AdminKit";
import { formatDate } from "../../lib/orderStatus";

// Pricing (M6): the story price by length × deliverable × video tier, built from
// the catalog's unit prices plus buffer, fees and margin; any cell can be pinned
// by hand. Below it, what delivered orders actually cost against their price.

const OUTPUT_LABEL = { both: "فيديو + كتاب", video: "فيديو", pdf: "كتاب PDF" };
const TIER_LABEL = { balanced: "متوازن", premium: "فاخر" };
// Shown as percentages, stored as fractions.
const PERCENT = new Set(["target_margin", "retry_buffer", "payment_fee", "vat_rate"]);
const FIELDS = [
  ["target_margin", "%", "من السعر بعد التكلفة والرسوم"],
  ["retry_buffer", "%", "فوق التكلفة: لقطات بتتعاد"],
  ["payment_fee", "%", "مدى / بطاقات"],
  ["min_price_sar", "ر.س", "أي قصة مش أقل من كده"],
  ["usd_to_sar", "ر.س", "أسعار الموديلات بالدولار"],
  ["vat_rate", "%", "صفر لحد التسجيل في الضريبة"],
];

const sar = (v) => (v == null ? "—" : `${Number(v).toLocaleString("en-US", { maximumFractionDigits: 2 })} ر.س`);
const marginTone = (m) => (m == null ? "text-[#8A9AB0]" : m >= 45 ? "text-[#4F6B3B]" : m >= 30 ? "text-[#8B5A2B]" : "text-[#B8612F]");

export default function AdminPricing() {
  const [data, setData] = useState(null);
  const [margins, setMargins] = useState(null);
  const [error, setError] = useState(null);
  const [form, setForm] = useState({});
  const [saving, setSaving] = useState(false);

  const load = () => {
    setError(null);
    api.get("/admin/pricing/story").then((r) => apply(r.data)).catch(() => setError("تعذّر تحميل التسعير"));
    api.get("/admin/pricing/margins?limit=30").then((r) => setMargins(r.data)).catch(() => setMargins({ rows: [], summary: {} }));
  };
  const apply = (d) => {
    setData(d);
    setForm(Object.fromEntries(FIELDS.map(([k]) => [k, PERCENT.has(k) ? +(d.settings[k] * 100).toFixed(2) : d.settings[k]])));
  };
  useEffect(load, []);

  const dirty = data && FIELDS.some(([k]) => Number(form[k]) !== (PERCENT.has(k) ? +(data.settings[k] * 100).toFixed(2) : data.settings[k]));

  const save = async () => {
    setSaving(true);
    try {
      const payload = Object.fromEntries(FIELDS.map(([k]) => [k, PERCENT.has(k) ? Number(form[k]) / 100 : Number(form[k])]));
      const r = await api.put("/admin/pricing/story/settings", payload);
      apply(r.data);
      toast.success("اتحفظ — الأسعار الجديدة ظاهرة للعملاء دلوقتي");
    } catch (e) {
      toast.error(e?.response?.data?.detail || "فشل الحفظ");
    } finally {
      setSaving(false);
    }
  };

  const setOverride = async (row, price) => {
    try {
      const r = await api.put("/admin/pricing/story/override", {
        seconds: row.seconds, output_type: row.output_type, video_tier: row.video_tier, price_sar: price,
      });
      apply(r.data);
      toast.success(price == null ? "رجع للسعر المحسوب" : `السعر بقى ${price} ر.س`);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "فشل الحفظ");
    }
  };

  return (
    <AdminPage title="التسعير والهوامش" testId="admin-pricing"
      description="سعر القصة حسب المدة ونوع المخرج والجودة. التكلفة جاية من أسعار الموديلات المختارة في المحرك، وفوقها الاحتياطي والرسوم والهامش. أي خانة تقدر تثبّت سعرها بإيدك.">
      <PageState loading={!data && !error} error={error} onRetry={load}>
        {data && (
          <>
            <section className="bg-white rounded-3xl border border-[#E2D8C9] p-5 mb-6" data-testid="pricing-settings">
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                {FIELDS.map(([key, unit, hint]) => (
                  <label key={key} className="block">
                    <span className="block font-body text-sm font-bold text-[#2D3748] mb-1">{data.labels[key]}</span>
                    <div className="flex items-center gap-2">
                      <input type="number" step="any" value={form[key] ?? ""} data-testid={`pricing-${key}`}
                        onChange={(e) => setForm({ ...form, [key]: e.target.value })}
                        className="w-full bg-[#FDFBF7] border border-[#E2D8C9] rounded-2xl px-4 py-2 font-body" dir="ltr" />
                      <span className="font-body text-sm text-[#5A677D] shrink-0">{unit}</span>
                    </div>
                    <span className="block font-body text-xs text-[#8A9AB0] mt-1">{hint}</span>
                  </label>
                ))}
              </div>
              <div className="flex items-center justify-between gap-3 flex-wrap mt-5">
                <span className="font-body text-xs text-[#8A9AB0]">
                  {data.settings.updated_at ? `آخر تعديل ${formatDate(data.settings.updated_at)} — ${data.settings.updated_by || ""}` : "القيم الافتراضية"}
                </span>
                <button onClick={save} disabled={!dirty || saving} data-testid="pricing-save"
                  className="rounded-full bg-[#87A96B] hover:bg-[#729352] text-white px-5 py-2 text-sm font-bold font-body inline-flex items-center gap-2 disabled:opacity-40">
                  <Save className="w-4 h-4" /> حفظ
                </button>
              </div>
            </section>

            <PriceTable rows={data.table} onOverride={setOverride} />
            <UnitPrices prices={data.unit_prices} assumptions={data.assumptions} />
            <MarginsReport data={margins} />
          </>
        )}
      </PageState>
    </AdminPage>
  );
}

function PriceTable({ rows, onOverride }) {
  const [editing, setEditing] = useState(null);
  const [value, setValue] = useState("");
  const th = "px-3 py-2 font-body text-xs font-bold text-[#5A677D] text-right whitespace-nowrap";
  const td = "px-3 py-2 font-body text-sm whitespace-nowrap";
  return (
    <section className="mb-6">
      <h2 className="font-heading text-xl font-bold text-[#729352] mb-1">جدول الأسعار</h2>
      <p className="font-body text-xs text-[#8A9AB0] mb-3">
        الأسعار قبل الضريبة. التكلفة المحمّلة = تكلفة التوليد بالريال + احتياطي إعادة المحاولة + رسوم الدفع. الهامش = اللي فاضل من السعر بعدها.
      </p>
      <div className="bg-white rounded-3xl border border-[#E2D8C9] overflow-x-auto" data-testid="price-table">
        <table className="w-full">
          <thead className="bg-[#FDFBF7] border-b border-[#E2D8C9]">
            <tr>
              <th className={th}>المدة</th><th className={th}>المخرج</th>
              <th className={th}>التكلفة المحمّلة</th><th className={th}>السعر للعميل</th><th className={th}>الهامش</th><th className={th}></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[#F0E9DD]">
            {rows.map((r, i) => {
              const first = i === 0 || rows[i - 1].seconds !== r.seconds;
              return (
                <tr key={r.key} className={first && i ? "border-t-2 border-[#E2D8C9]" : ""} data-testid={`price-row-${r.key}`}>
                  <td className={`${td} font-bold`}>{first ? `${r.seconds} ث` : ""}</td>
                  <td className={td}>
                    {OUTPUT_LABEL[r.output_type]}
                    {r.video_tier && <span className="text-xs text-[#8A9AB0]"> · {TIER_LABEL[r.video_tier]}</span>}
                  </td>
                  <td className={td}>
                    {sar(r.loaded_cost_sar)}
                    <div className="text-[11px] text-[#8A9AB0]">توليد ${r.cost_usd.toFixed(2)}</div>
                  </td>
                  <td className={td}>
                    {editing === r.key ? (
                      <span className="inline-flex items-center gap-1">
                        <input type="number" value={value} onChange={(e) => setValue(e.target.value)} autoFocus dir="ltr"
                          className="w-20 bg-[#FDFBF7] border border-[#E2D8C9] rounded-xl px-2 py-1 font-body text-sm" />
                        <button aria-label="حفظ" className="p-1 rounded-lg bg-[#87A96B] text-white"
                          onClick={() => { onOverride(r, Number(value)); setEditing(null); }}><Save className="w-3.5 h-3.5" /></button>
                        <button aria-label="إلغاء" className="p-1 rounded-lg bg-[#F0E9DD]" onClick={() => setEditing(null)}><X className="w-3.5 h-3.5" /></button>
                      </span>
                    ) : (
                      <span className="font-bold text-[#2D3748]">
                        {sar(r.price_sar)}
                        {r.override_sar != null && <span className="mr-1 text-[10px] font-bold rounded-full px-2 py-0.5 bg-[#FBEFD5] text-[#8B5A2B]">يدوي</span>}
                        {r.override_sar != null && <div className="text-[11px] font-normal text-[#8A9AB0]">المحسوب {sar(r.computed_price_sar)}</div>}
                      </span>
                    )}
                  </td>
                  <td className={`${td} font-bold ${marginTone(r.margin_pct)}`}>{r.margin_pct}%</td>
                  <td className={td}>
                    {editing !== r.key && (
                      <span className="inline-flex gap-1">
                        <button title="ثبّت سعر بإيدك" aria-label="تعديل السعر" className="p-1.5 rounded-lg border border-[#E2D8C9] bg-white"
                          onClick={() => { setEditing(r.key); setValue(r.price_sar); }}><Pencil className="w-3.5 h-3.5" /></button>
                        {r.override_sar != null && (
                          <button title="رجوع للسعر المحسوب" aria-label="رجوع للسعر المحسوب" className="p-1.5 rounded-lg border border-[#E2D8C9] bg-white"
                            onClick={() => onOverride(r, null)}><RotateCcw className="w-3.5 h-3.5" /></button>
                        )}
                      </span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function UnitPrices({ prices, assumptions }) {
  const usd = (v) => (v ? `$${v}` : "مش مسعّر");
  const items = [
    ["النصوص (سيناريو + خطة) للقصة", usd(prices.text)],
    ["شيت شخصية / غلاف", `${usd(prices.image_sheet)} للصورة`],
    ["صورة لقطة", `${usd(prices.image_shot)} للصورة`],
    ["فيديو — متوازن", `${usd(prices.video_per_second?.balanced)} للثانية`],
    ["فيديو — فاخر", `${usd(prices.video_per_second?.premium)} للثانية`],
    ["الموسيقى", `${usd(prices.music_per_minute)} للدقيقة`],
    ["السرد الصوتي", prices.narration_per_minute ? `$${prices.narration_per_minute} للدقيقة` : "مش مسعّر (محسوب صفر)"],
  ];
  return (
    <section className="mb-6">
      <div className="flex items-end justify-between gap-3 flex-wrap mb-3">
        <h2 className="font-heading text-xl font-bold text-[#729352]">أسعار الوحدة الحالية</h2>
        <Link to="/admin/engine" className="font-body text-sm font-bold text-[#4F6B3B] underline">غيّر الموديلات وأسعارها من المحرك</Link>
      </div>
      <div className="bg-white rounded-3xl border border-[#E2D8C9] p-5 grid grid-cols-1 sm:grid-cols-2 gap-x-8 gap-y-2">
        {items.map(([label, value]) => (
          <div key={label} className="flex justify-between gap-3 font-body text-sm border-b border-[#F0E9DD] py-1.5">
            <span className="text-[#5A677D]">{label}</span><span className="font-bold text-[#2D3748]" dir="auto">{value}</span>
          </div>
        ))}
        <p className="sm:col-span-2 font-body text-xs text-[#8A9AB0] mt-2">
          افتراضات القصة: {assumptions.cast_sheets} شيتات شخصيات + الغلاف، لقطة كل {prices.shot_seconds} ث،
          ثواني الفيديو المدفوعة = المدة × {assumptions.clip_seconds_factor} (فواصل الجمل وتقريب المقاطع).
        </p>
      </div>
    </section>
  );
}

function MarginsReport({ data }) {
  if (!data) return null;
  const s = data.summary || {};
  const th = "px-3 py-2 font-body text-xs font-bold text-[#5A677D] text-right whitespace-nowrap";
  const td = "px-3 py-2 font-body text-sm whitespace-nowrap";
  return (
    <section data-testid="margins-report">
      <h2 className="font-heading text-xl font-bold text-[#729352] mb-1">الهوامش الفعلية</h2>
      <p className="font-body text-xs text-[#8A9AB0] mb-3">
        الطلبات المتسلّمة: السعر مقابل التكلفة الفعلية من اللي اتولّد فعلاً (شامل إعادة الرسم). الطلبات القديمة من قبل التسعير مالهاش سعر.
      </p>
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-4">
        <KpiCard label="طلبات متسلّمة" value={s.orders ?? 0} hint={`${s.priced_orders ?? 0} ليها سعر`} />
        <KpiCard label="الإيراد (قبل الضريبة)" value={sar(s.revenue_sar)} />
        <KpiCard label="التكلفة الفعلية" value={sar(s.cost_sar)} />
        <KpiCard label="الهامش" value={s.margin_pct == null ? "—" : `${s.margin_pct}%`}
          tone={s.margin_pct == null ? "neutral" : s.margin_pct >= 45 ? "good" : s.margin_pct >= 30 ? "warn" : "bad"} />
      </div>
      <div className="bg-white rounded-3xl border border-[#E2D8C9] overflow-x-auto">
        <table className="w-full">
          <thead className="bg-[#FDFBF7] border-b border-[#E2D8C9]">
            <tr>
              <th className={th}>الطلب</th><th className={th}>المدة / المخرج</th><th className={th}>السعر</th>
              <th className={th}>التكلفة المقدّرة</th><th className={th}>التكلفة الفعلية</th><th className={th}>الهامش</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[#F0E9DD]">
            {data.rows.length === 0 && (
              <tr><td colSpan={6} className="px-3 py-6 text-center font-body text-sm text-[#8A9AB0]">مفيش طلبات متسلّمة لسه</td></tr>
            )}
            {data.rows.map((r) => (
              <tr key={r.order_id}>
                <td className={td}>
                  <Link to={`/admin/orders/${r.order_id}`} className="font-bold text-[#4F6B3B] hover:underline">{r.child_name || r.order_id.slice(0, 8)}</Link>
                  <div className="text-xs text-[#8A9AB0]">{formatDate(r.created_at)}</div>
                </td>
                <td className={td}>{r.seconds} ث · {OUTPUT_LABEL[r.output_type] || "—"}{r.video_tier ? ` · ${TIER_LABEL[r.video_tier]}` : ""}</td>
                <td className={td}>{sar(r.price_sar)}{r.paid ? "" : r.price_sar ? <span className="text-xs text-[#8A9AB0]"> (عرض سعر)</span> : ""}</td>
                <td className={td}>{sar(r.estimate_sar)}</td>
                <td className={`${td} font-bold`}>{sar(r.cost_sar)}</td>
                <td className={`${td} font-bold ${marginTone(r.margin_pct)}`}>{r.margin_pct == null ? "—" : `${r.margin_pct}%`}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
