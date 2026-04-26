import React, { useEffect, useState } from "react";
import { api, fileSrc } from "../../lib/api";
import OrderStatusBadge from "../../components/gheras/OrderStatusBadge";
import { toast } from "sonner";
import { Eye, Filter, Wand2, Save, RefreshCw, X, Sparkles, Heart, BookOpen, Rocket, CheckCircle2, Trash2, Clock, ChevronDown, ChevronUp, Lightbulb, Coins, Film, ImageIcon, FileText as FileTextIcon, Users as UsersIcon, Palette } from "lucide-react";

const ANGLE_META = {
  emotional:   { label: "عاطفي", icon: Heart, bg: "bg-[#FCE6D4]", fg: "text-[#B8612F]" },
  educational: { label: "تعليمي هادئ", icon: BookOpen, bg: "bg-[#E8F0E1]", fg: "text-[#4F6B3B]" },
  adventure:   { label: "مغامرة", icon: Rocket, bg: "bg-[#F8F1E7]", fg: "text-[#8B5A2B]" },
};

const STATUSES = [
  { v: "pending", l: "بانتظار البدء" },
  { v: "in_review", l: "قيد المراجعة" },
  { v: "scenarios_generating", l: "جاري توليد السيناريوهات" },
  { v: "scenarios_ready", l: "السيناريوهات جاهزة" },
  { v: "scenario_selected", l: "تم اختيار سيناريو" },
  { v: "ready_for_ai", l: "جاهز للتوليد" },
  { v: "generating", l: "جاري التوليد" },
  { v: "completed", l: "مكتمل" },
  { v: "failed", l: "فشل" },
];

export default function AdminOrders() {
  const [orders, setOrders] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState("all");
  const [detail, setDetail] = useState(null);
  const [note, setNote] = useState("");
  const [promptEdit, setPromptEdit] = useState("");
  const [tab, setTab] = useState("overview"); // overview | scenarios | json | prompt | history
  const [scenariosData, setScenariosData] = useState(null);

  const reload = () => {
    setLoading(true);
    api.get("/admin/orders").then((r) => setOrders(r.data)).finally(() => setLoading(false));
  };
  useEffect(reload, []);

  const loadScenarios = async (oid) => {
    try {
      const { data } = await api.get(`/admin/orders/${oid}/scenarios`);
      setScenariosData(data);
    } catch {
      setScenariosData({ scenarios: [], generation: null, selected_scenario_id: null });
    }
  };

  const openDetail = async (id) => {
    const { data } = await api.get(`/admin/orders/${id}`);
    setDetail(data);
    setNote(data.admin_note || "");
    setPromptEdit(data.ai_prompt_snapshot || "");
    setTab("overview");
    loadScenarios(id);
  };

  const adminRegenerate = async () => {
    try {
      await api.post(`/admin/orders/${detail.id}/scenarios/regenerate`);
      toast.success("جاري إعادة التوليد...");
      setScenariosData({ scenarios: [], generation: null, selected_scenario_id: null });
      // poll briefly
      let i = 0;
      const poll = setInterval(async () => {
        i++;
        const { data } = await api.get(`/admin/orders/${detail.id}/scenarios`);
        setScenariosData(data);
        if (data.scenarios.length > 0 || i > 8) clearInterval(poll);
      }, 2500);
    } catch { toast.error("فشل"); }
  };

  const adminSelectScenario = async (sid) => {
    try {
      await api.post(`/admin/orders/${detail.id}/scenarios/${sid}/select`);
      toast.success("تم الاختيار نيابة عن العميل");
      loadScenarios(detail.id);
      reload();
      openDetail(detail.id);
    } catch { toast.error("فشل"); }
  };

  const adminDeleteScenarios = async () => {
    if (!window.confirm("حذف جميع السيناريوهات؟")) return;
    await api.delete(`/admin/orders/${detail.id}/scenarios`);
    toast.success("تم الحذف");
    loadScenarios(detail.id);
  };

  const changeStatus = async (id, status) => {
    try {
      await api.patch(`/admin/orders/${id}/status`, { status, admin_note: note || null });
      toast.success("تم تحديث الحالة");
      reload();
      openDetail(id);
    } catch {
      toast.error("فشل");
    }
  };

  const savePrompt = async () => {
    try {
      await api.patch(`/admin/orders/${detail.id}/prompt`, { ai_prompt_snapshot: promptEdit });
      toast.success("تم حفظ البرومبت");
      openDetail(detail.id);
    } catch {
      toast.error("فشل");
    }
  };

  const regeneratePrompt = async () => {
    try {
      const { data } = await api.post(`/admin/orders/${detail.id}/regenerate-prompt`);
      setPromptEdit(data.ai_prompt_snapshot);
      toast.success("تم إعادة التوليد من JSON");
    } catch {
      toast.error("فشل");
    }
  };

  const filtered = filter === "all" ? orders : orders.filter((o) => o.status === filter);

  return (
    <div data-testid="admin-orders">
      <h1 className="font-heading text-3xl font-bold text-[#2D3748] mb-2">الطلبات</h1>
      <p className="font-body text-[#5A677D] mb-6">إدارة طلبات القصص</p>

      <div className="flex items-center gap-2 mb-6 flex-wrap">
        <Filter className="w-4 h-4 text-[#8A9AB0]" />
        <button onClick={() => setFilter("all")} className={`rounded-full px-4 py-1.5 text-sm font-body ${filter === "all" ? "bg-[#87A96B] text-white" : "bg-white border border-[#E2D8C9] text-[#5A677D]"}`}>
          الكل ({orders.length})
        </button>
        {STATUSES.map((s) => (
          <button key={s.v} onClick={() => setFilter(s.v)} className={`rounded-full px-4 py-1.5 text-sm font-body ${filter === s.v ? "bg-[#87A96B] text-white" : "bg-white border border-[#E2D8C9] text-[#5A677D]"}`}>
            {s.l} ({orders.filter((o) => o.status === s.v).length})
          </button>
        ))}
      </div>

      <div className="bg-white rounded-3xl border border-[#E2D8C9] overflow-hidden">
        {loading ? <div className="py-20 text-center text-[#8A9AB0]">جاري التحميل...</div> : filtered.length === 0 ? <div className="py-20 text-center text-[#8A9AB0]">لا توجد طلبات</div> : (
          <div className="overflow-x-auto">
            <table className="w-full text-right">
              <thead className="bg-[#F8F1E7] text-[#5A677D] text-xs font-body">
                <tr>
                  <th className="px-5 py-3 font-bold">الطفل</th>
                  <th className="px-5 py-3 font-bold">العميل</th>
                  <th className="px-5 py-3 font-bold">التاريخ</th>
                  <th className="px-5 py-3 font-bold">الحالة</th>
                  <th className="px-5 py-3 font-bold">إجراء</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((o) => (
                  <tr key={o.id} className="border-t border-[#E2D8C9] hover:bg-[#FDFBF7]">
                    <td className="px-5 py-3 font-body font-bold">{o.child_name}</td>
                    <td className="px-5 py-3 font-body text-sm">{o.user_email}</td>
                    <td className="px-5 py-3 font-body text-xs text-[#8A9AB0]">{new Date(o.created_at).toLocaleDateString("ar-EG")}</td>
                    <td className="px-5 py-3"><OrderStatusBadge status={o.status} /></td>
                    <td className="px-5 py-3">
                      <button onClick={() => openDetail(o.id)} className="inline-flex items-center gap-1 text-[#729352] hover:text-[#4F6B3B] text-sm font-body">
                        <Eye className="w-4 h-4" /> عرض
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {detail && (
        <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4" onClick={() => setDetail(null)}>
          <div className="bg-white rounded-[2rem] p-6 md:p-8 max-w-3xl w-full max-h-[92vh] overflow-y-auto" onClick={(e) => e.stopPropagation()} data-testid="order-modal">
            <div className="flex items-start justify-between mb-4">
              <div>
                <h2 className="font-heading text-2xl font-bold text-[#2D3748]">قصة {detail.data?.child?.name}</h2>
                <p className="font-body text-xs text-[#8A9AB0]">{detail.id} • {detail.user_email}</p>
              </div>
              <div className="flex items-center gap-2">
                <a
                  href={`/admin/orders/${detail.id}/storyboard`}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-1 bg-[#F8F1E7] text-[#8B5A2B] rounded-full px-3 py-1.5 text-xs font-bold hover:bg-[#F2E8DA]"
                  data-testid="open-storyboard-btn"
                  title="افتح Storyboard (تتبّع خط الإنتاج) في تبويب جديد"
                >
                  <Lightbulb className="w-3 h-3" /> Storyboard
                </a>
                <button onClick={() => setDetail(null)} className="text-[#8A9AB0]"><X className="w-5 h-5" /></button>
              </div>
            </div>

            <div className="flex gap-2 mb-5 border-b border-[#E2D8C9] overflow-x-auto">
              {[
                { k: "overview", l: "نظرة عامة" },
                { k: "scenarios", l: "السيناريوهات" },
                { k: "production", l: "خطة الإنتاج" },
                { k: "media", l: "الوسائط" },
                { k: "pricing", l: "التسعير" },
                { k: "history", l: "سجل الحالات" },
                { k: "json", l: "JSON" },
                { k: "prompt", l: "البرومبت" },
              ].map((t) => (
                <button key={t.k} onClick={() => setTab(t.k)} className={`px-4 py-2 text-sm font-body font-bold border-b-2 whitespace-nowrap ${tab === t.k ? "border-[#87A96B] text-[#4F6B3B]" : "border-transparent text-[#8A9AB0]"}`} data-testid={`admin-order-tab-${t.k}`}>
                  {t.l}
                </button>
              ))}
            </div>

            {tab === "overview" && (
              <div>
                {detail.data?.child?.image_url && (
                  <img src={fileSrc(detail.data.child.image_url)} alt="" className="w-24 h-24 rounded-2xl object-cover border border-[#E2D8C9] mb-4" />
                )}
                <div className="grid grid-cols-2 gap-2 mb-4">
                  <Field label="التصنيف" value={detail.enriched?.category_name} />
                  <Field label="الموضوع" value={detail.enriched?.subcategory_name || detail.data?.goal?.custom_subcategory} />
                  <Field label="العمر" value={`${detail.data?.child?.age} سنة`} />
                  <Field label="الجنس" value={detail.data?.child?.gender === "male" ? "ولد" : "بنت"} />
                  <Field label="نوع القصة" value={detail.enriched?.type_name} />
                  <Field label="النبرة" value={detail.enriched?.tone_name} />
                  <Field label="البيئة" value={detail.enriched?.setting_name} />
                  <Field label="اللغة" value={detail.enriched?.language_name} />
                </div>
                <div className="bg-[#E8F0E1] rounded-2xl p-4 mb-4">
                  <div className="text-xs font-bold text-[#4F6B3B] mb-1">الموقف الحقيقي</div>
                  <p className="text-sm whitespace-pre-wrap">{detail.data?.goal?.context}</p>
                </div>

                <label className="block text-sm font-bold mb-2 font-body">ملاحظة للعميل</label>
                <textarea value={note} onChange={(e) => setNote(e.target.value)} rows={2} className="w-full bg-[#FDFBF7] border border-[#E2D8C9] rounded-2xl px-4 py-2 font-body mb-4" />

                <div className="flex flex-wrap gap-2">
                  {STATUSES.map((s) => (
                    <button key={s.v} onClick={() => changeStatus(detail.id, s.v)} className={`rounded-full px-4 py-2 text-xs font-body font-bold border ${detail.status === s.v ? "bg-[#87A96B] border-[#87A96B] text-white" : "bg-white border-[#E2D8C9] text-[#5A677D] hover:border-[#87A96B]"}`}>
                      {s.l}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {tab === "json" && (
              <pre className="bg-[#FDFBF7] rounded-2xl p-4 text-xs overflow-x-auto max-h-[500px] overflow-y-auto border border-[#E2D8C9]">
                {JSON.stringify(detail.data, null, 2)}
              </pre>
            )}

            {tab === "scenarios" && (
              <AdminScenariosTab
                scenariosData={scenariosData}
                onRegenerate={adminRegenerate}
                onDelete={adminDeleteScenarios}
                onSelect={adminSelectScenario}
              />
            )}

            {tab === "production" && (
              <AdminProductionTab orderId={detail.id} />
            )}

            {tab === "media" && (
              <AdminMediaTab orderId={detail.id} />
            )}

            {tab === "pricing" && (
              <AdminPricingTab orderId={detail.id} />
            )}

            {tab === "history" && (
              <div data-testid="admin-history-tab">
                <h4 className="font-heading font-bold text-[#2D3748] mb-3">سجل الحالات</h4>
                <div className="space-y-2">
                  {(detail.status_history || []).map((h, i) => (
                    <div key={i} className="bg-[#FDFBF7] rounded-2xl p-3 border border-[#E2D8C9] flex items-center gap-3">
                      <Clock className="w-4 h-4 text-[#87A96B] shrink-0" />
                      <div className="flex-1 text-sm font-body">
                        <div className="text-[#2D3748] font-bold">{h.from || "—"} ← {h.to}</div>
                        <div className="text-xs text-[#8A9AB0]">{new Date(h.at).toLocaleString("ar-EG")} • by {h.by}{h.reason ? ` • ${h.reason}` : ""}</div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {tab === "prompt" && (
              <div>
                <div className="flex items-center justify-between mb-3">
                  <div className="flex items-center gap-2 text-[#729352] font-body font-bold text-sm">
                    <Wand2 className="w-4 h-4" /> برومبت الذكاء الاصطناعي
                    {detail.prompt_edited && <span className="text-xs bg-[#D4A373]/20 text-[#8B5A2B] rounded-full px-2 py-0.5">معدّل يدوياً</span>}
                  </div>
                  <button onClick={regeneratePrompt} className="inline-flex items-center gap-1 text-xs font-body text-[#5A677D] hover:text-[#2D3748]">
                    <RefreshCw className="w-3 h-3" /> إعادة التوليد من JSON
                  </button>
                </div>
                <textarea
                  value={promptEdit}
                  onChange={(e) => setPromptEdit(e.target.value)}
                  rows={18}
                  className="w-full bg-[#FDFBF7] border border-[#E2D8C9] rounded-2xl p-4 font-body text-sm"
                  data-testid="admin-prompt-editor"
                />
                <button onClick={savePrompt} className="btn-primary inline-flex items-center gap-2 mt-3">
                  <Save className="w-4 h-4" /> حفظ البرومبت
                </button>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function Field({ label, value }) {
  return (
    <div className="bg-[#FDFBF7] rounded-xl p-2 border border-[#E2D8C9]">
      <div className="text-xs text-[#8A9AB0] font-body">{label}</div>
      <div className="font-body font-bold text-[#2D3748] text-sm">{value || "—"}</div>
    </div>
  );
}

function AdminScenariosTab({ scenariosData, onRegenerate, onDelete, onSelect }) {
  const batches = scenariosData?.batches || [];
  const regenUsed = scenariosData?.regeneration_count ?? 0;
  const regenMax = scenariosData?.max_regenerations ?? 3;
  const remaining = scenariosData?.regenerations_remaining ?? Math.max(0, regenMax - regenUsed);
  const limitReached = remaining <= 0;
  const duration = scenariosData?.duration;

  // Expand the current (latest) batch by default
  const currentBatchId = scenariosData?.current_scenario_batch_id;
  const [openBatches, setOpenBatches] = useState({});
  useEffect(() => {
    if (currentBatchId && openBatches[currentBatchId] === undefined) {
      setOpenBatches((p) => ({ ...p, [currentBatchId]: true }));
    }
    // eslint-disable-next-line
  }, [currentBatchId]);

  const toggleBatch = (bid) => setOpenBatches((p) => ({ ...p, [bid]: !p[bid] }));

  return (
    <div data-testid="admin-scenarios-tab">
      <div className="flex items-center justify-between flex-wrap gap-3 mb-4">
        <div className="text-sm text-[#5A677D] font-body flex items-center gap-2 flex-wrap">
          <span className="bg-[#FDFBF7] border border-[#E2D8C9] rounded-full px-3 py-1 text-xs inline-flex items-center gap-1" data-testid="admin-regen-counter">
            المحاولات: <b className="text-[#4F6B3B]">{regenUsed} / {regenMax}</b>
          </span>
          {limitReached && (
            <span className="bg-[#FCE6D4] text-[#B8612F] rounded-full px-3 py-1 text-xs font-bold inline-flex items-center gap-1" data-testid="admin-max-reached-badge">
              <AlertBadge /> Max reached
            </span>
          )}
          {duration?.label && (
            <span className="bg-[#E8F0E1] text-[#4F6B3B] rounded-full px-3 py-1 text-xs inline-flex items-center gap-1">
              <Clock className="w-3 h-3" /> {duration.label} • ~{duration.scene_target} مشاهد
            </span>
          )}
          {duration?.cost_tier && (
            <span className="bg-[#F8F1E7] text-[#8B5A2B] rounded-full px-3 py-1 text-xs inline-flex items-center gap-1">
              <Coins className="w-3 h-3" /> {duration.cost_tier}
            </span>
          )}
          {scenariosData?.output_type && (
            <span className="bg-[#FDFBF7] text-[#2D3748] rounded-full px-3 py-1 text-xs inline-flex items-center gap-1 border border-[#E2D8C9]" data-testid="admin-output-type-badge">
              نوع التسليم: <b>{
                {video: "فيديو", pdf: "كتاب PDF", both: "فيديو + كتاب"}[scenariosData.output_type] || scenariosData.output_type
              }</b>
            </span>
          )}
        </div>
        <div className="flex gap-2">
          <button
            onClick={onRegenerate}
            title={limitReached ? "تجاوز الحد — الأدمن فقط" : "إنشاء دفعة جديدة"}
            className="rounded-full bg-[#E8F0E1] text-[#4F6B3B] px-4 py-2 text-xs font-bold inline-flex items-center gap-1 hover:bg-[#D4E3C1]"
            data-testid="admin-regen-scenarios"
          >
            <RefreshCw className="w-3 h-3" /> {limitReached ? "إعادة توليد (تجاوز)" : "إعادة توليد"}
          </button>
          {batches.length > 0 && (
            <button onClick={onDelete} className="rounded-full bg-[#FCE6D4] text-[#B8612F] px-4 py-2 text-xs font-bold inline-flex items-center gap-1" data-testid="admin-delete-scenarios">
              <Trash2 className="w-3 h-3" /> حذف الكل
            </button>
          )}
        </div>
      </div>

      {batches.length === 0 ? (
        <p className="text-center py-12 text-[#8A9AB0] font-body">لم يتم توليد سيناريوهات بعد</p>
      ) : (
        <div className="space-y-3">
          {batches.map((b, bIdx) => {
            const open = !!openBatches[b.batch_id];
            const short = (b.batch_id || "").slice(0, 8);
            const when = b.created_at ? new Date(b.created_at).toLocaleString("ar-EG") : "";
            return (
              <div key={b.batch_id} className={`rounded-2xl border-2 overflow-hidden ${b.is_current ? "border-[#87A96B] bg-[#E8F0E1]/20" : "border-[#E2D8C9] bg-white"}`} data-testid={`admin-batch-${b.batch_id}`}>
                <button
                  onClick={() => toggleBatch(b.batch_id)}
                  className="w-full flex items-center justify-between gap-3 px-4 py-3 text-right hover:bg-[#FDFBF7] transition"
                  data-testid={`admin-batch-toggle-${b.batch_id}`}
                >
                  <div className="flex items-center gap-3 flex-wrap">
                    <span className="font-heading font-bold text-[#2D3748]">
                      الدفعة {batches.length - bIdx}
                    </span>
                    <code className="text-[10px] text-[#8A9AB0]">#{short}</code>
                    <span className="text-xs text-[#8A9AB0] font-body">{when}</span>
                    {b.is_current && (
                      <span className="bg-[#87A96B] text-white rounded-full px-2 py-0.5 text-[10px] font-bold">الحالية</span>
                    )}
                    {b.source === "ai" && <span className="bg-[#E8F0E1] text-[#4F6B3B] rounded-full px-2 py-0.5 text-[10px] font-bold">AI</span>}
                    {b.source === "fallback" && <span className="bg-[#F8F1E7] text-[#8B5A2B] rounded-full px-2 py-0.5 text-[10px] font-bold">Fallback</span>}
                    <span className="text-xs text-[#8A9AB0] font-body">{b.scenarios.length} سيناريوهات</span>
                  </div>
                  {open ? <ChevronUp className="w-4 h-4 text-[#8A9AB0]" /> : <ChevronDown className="w-4 h-4 text-[#8A9AB0]" />}
                </button>

                {open && (
                  <div className="px-3 pb-3 space-y-2">
                    {b.scenarios.map((s) => {
                      const meta = ANGLE_META[s.emotional_angle] || ANGLE_META.educational;
                      const Icon = meta.icon;
                      const sel = s.is_selected || scenariosData.selected_scenario_id === s.id;
                      return (
                        <div key={s.id} className={`rounded-2xl p-4 border-2 ${sel ? "border-[#87A96B] bg-[#E8F0E1]/40" : "border-[#E2D8C9] bg-[#FDFBF7]"}`} data-testid={`admin-scenario-${s.id}`}>
                          <div className="flex items-start justify-between gap-3 mb-2">
                            <div className="flex items-center gap-2">
                              <div className={`w-9 h-9 rounded-xl ${meta.bg} grid place-content-center`}><Icon className={`w-4 h-4 ${meta.fg}`} /></div>
                              <div>
                                <h4 className="font-heading font-bold text-[#2D3748]">{s.title}</h4>
                                <span className={`text-xs ${meta.fg}`}>{meta.label} • {s.estimated_scene_count} مشاهد</span>
                              </div>
                            </div>
                            {sel ? (
                              <span className="rounded-full bg-[#87A96B] text-white text-xs font-bold px-3 py-1 inline-flex items-center gap-1">
                                <CheckCircle2 className="w-3 h-3" /> مختار
                              </span>
                            ) : (
                              <button onClick={() => onSelect(s.id)} className="text-xs font-bold text-[#729352] hover:text-[#4F6B3B] px-3 py-1" data-testid={`admin-select-${s.id}`}>
                                اختر هذا
                              </button>
                            )}
                          </div>
                          <p className="font-body text-sm text-[#5A677D]">{s.short_summary}</p>
                          {s.why_this_fits && (
                            <div className="mt-2 text-xs text-[#8B5A2B] font-body inline-flex items-start gap-1">
                              <Lightbulb className="w-3 h-3 mt-0.5 shrink-0" />
                              <span>{s.why_this_fits}</span>
                            </div>
                          )}
                          {s.learning_goal && (
                            <div className="mt-1 text-xs text-[#4F6B3B] font-body">🎯 {s.learning_goal}</div>
                          )}
                        </div>
                      );
                    })}
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

function AlertBadge() {
  return <span className="w-2 h-2 rounded-full bg-[#B8612F]" />;
}

function AdminMediaTab({ orderId }) {
  const [data, setData] = useState(null);
  const [delivery, setDelivery] = useState(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const pollRef = React.useRef(null);

  const load = async () => {
    try {
      const [mediaRes, deliveryRes] = await Promise.all([
        api.get(`/admin/orders/${orderId}/media`),
        api.get(`/admin/orders/${orderId}/delivery`).catch(() => ({ data: null })),
      ]);
      setData(mediaRes.data);
      setDelivery(deliveryRes.data);
      const terminal = !["assets_generating", "assembling"].includes(mediaRes.data.status);
      if (terminal && pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    } catch {
      toast.error("تعذّر تحميل بيانات الوسائط");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    pollRef.current = setInterval(load, 4000);
    return () => pollRef.current && clearInterval(pollRef.current);
    // eslint-disable-next-line
  }, [orderId]);

  const triggerFull = async () => {
    if (!window.confirm("سيتم حذف جميع الوسائط الحالية وإعادة توليد كل شيء من الصفر. هل تريد المتابعة؟")) return;
    setBusy(true);
    try {
      await api.post(`/admin/orders/${orderId}/media/regenerate`);
      toast.success("بدأ توليد الوسائط");
      if (!pollRef.current) pollRef.current = setInterval(load, 4000);
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "فشل");
    } finally {
      setBusy(false);
    }
  };

  const retryJob = async (jobId) => {
    try {
      await api.post(`/admin/jobs/${jobId}/retry`);
      toast.success("أُعيد تشغيل الوظيفة");
      setTimeout(load, 2000);
    } catch {
      toast.error("فشل");
    }
  };

  if (loading) return <p className="text-center py-8 text-[#8A9AB0] font-body">جاري التحميل...</p>;
  if (!data) return null;

  const c = data.counts || {};
  const jobs = data.jobs || [];
  const scenes = (data.scene_images || []).filter((s) => s.kind === "scene").sort((a, b) => a.scene_index - b.scene_index);
  const cover = (data.scene_images || []).find((s) => s.kind === "cover");
  const narration = data.narration_assets || [];
  const book = data.book_assets || [];
  const status = data.status;

  return (
    <div data-testid="admin-media-tab" className="space-y-5">
      {/* Final delivery (when assembled) */}
      {delivery && (delivery.video || delivery.pdf || (delivery.jobs || []).length > 0) && (
        <section className="bg-[#E8F0E1]/40 rounded-2xl p-4 border-2 border-[#87A96B]/40" data-testid="admin-final-delivery">
          <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
            <h4 className="font-heading font-bold text-[#2D3748] inline-flex items-center gap-2">
              <Sparkles className="w-4 h-4 text-[#4F6B3B]" /> التسليم النهائي
            </h4>
            <div className="flex gap-2 items-center">
              {(delivery.jobs || []).map((j) => (
                <span key={j.id} className={
                  j.status === "completed" ? "bg-[#DEEBCF] text-[#3F5B2E] rounded-full px-2 py-0.5 text-[10px] font-bold" :
                  j.status === "failed" ? "bg-[#FCE6D4] text-[#B8612F] rounded-full px-2 py-0.5 text-[10px] font-bold" :
                  "bg-[#F8F1E7] text-[#8B5A2B] rounded-full px-2 py-0.5 text-[10px] font-bold"
                }>
                  {j.job_type === "final_video_assembly" ? "فيديو" : "PDF"}: {j.status}
                </span>
              ))}
              <button
                onClick={async () => {
                  if (!window.confirm("إعادة تجميع الفيديو والـ PDF من الأصول الحالية؟")) return;
                  try {
                    await api.post(`/admin/orders/${orderId}/delivery/regenerate`);
                    toast.success("بدأ التجميع النهائي");
                    if (!pollRef.current) pollRef.current = setInterval(load, 4000);
                    load();
                  } catch (e) {
                    toast.error(e?.response?.data?.detail || "فشل");
                  }
                }}
                className="rounded-full bg-[#F8F1E7] text-[#8B5A2B] px-3 py-1 text-xs font-bold inline-flex items-center gap-1 hover:bg-[#F2E8DA]"
                data-testid="admin-regen-delivery-btn"
              >
                <RefreshCw className="w-3 h-3" /> إعادة تجميع
              </button>
            </div>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {delivery.video && (
              <div className="bg-white rounded-xl p-2 border border-[#E2D8C9]" data-testid="admin-final-video">
                <video
                  controls
                  className="w-full aspect-video rounded-lg bg-black"
                  poster={delivery.video.thumbnail_url ? fileSrc(delivery.video.thumbnail_url) : undefined}
                  src={fileSrc(delivery.video.video_url)}
                />
                <div className="flex items-center justify-between mt-2 text-[11px] text-[#5A677D] font-body">
                  <span>⏱ {Math.round(delivery.video.duration_seconds || 0)}ث • 🎵 {delivery.video.audio_background_mode}</span>
                  <span className="bg-[#E8F0E1] text-[#4F6B3B] rounded-full px-2 py-0.5 font-bold">{delivery.video.provider} / {delivery.video.source_type}</span>
                </div>
              </div>
            )}
            {delivery.pdf && (
              <div className="bg-white rounded-xl p-3 border border-[#E2D8C9] flex flex-col gap-2" data-testid="admin-final-pdf">
                <div className="flex items-center gap-2">
                  <FileTextIcon className="w-5 h-5 text-[#8B5A2B]" />
                  <div className="font-heading font-bold text-sm text-[#2D3748]">قصة مصوّرة PDF</div>
                </div>
                <div className="text-[11px] text-[#5A677D] font-body">{delivery.pdf.page_count} صفحة</div>
                <a href={fileSrc(delivery.pdf.pdf_url)} target="_blank" rel="noreferrer"
                  className="rounded-full bg-[#F8F1E7] text-[#8B5A2B] px-3 py-1.5 text-xs font-bold inline-flex items-center gap-1 self-start">
                  فتح PDF
                </a>
              </div>
            )}
          </div>
        </section>
      )}

      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-2 flex-wrap text-sm font-body">
          <span className="bg-[#FDFBF7] border border-[#E2D8C9] rounded-full px-3 py-1 inline-flex items-center gap-1">
            <Film className="w-3 h-3 text-[#729352]" />
            الحالة: <b className="text-[#2D3748]">{data.status_ar}</b>
          </span>
          {status === "assets_generating" && (
            <span className="bg-[#E8F0E1] text-[#4F6B3B] rounded-full px-3 py-1 text-xs font-bold inline-flex items-center gap-1">
              <div className="w-2 h-2 rounded-full bg-[#87A96B] animate-pulse" />
              يعمل الآن
            </span>
          )}
        </div>
        <button
          onClick={triggerFull}
          disabled={busy || status === "assets_generating"}
          className="rounded-full bg-[#F8F1E7] text-[#8B5A2B] px-4 py-2 text-xs font-bold inline-flex items-center gap-1 disabled:opacity-50 hover:bg-[#F2E8DA]"
          data-testid="admin-regen-media-btn"
        >
          <RefreshCw className="w-3 h-3" /> إعادة توليد كامل
        </button>
      </div>

      {/* Counts */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-2" data-testid="admin-media-counts">
        <Stat label="الكلي" value={c.total || 0} color="bg-[#FDFBF7] border-[#E2D8C9] text-[#2D3748]" />
        <Stat label="في الانتظار" value={c.queued || 0} color="bg-[#F8F1E7] border-[#D4A373]/40 text-[#8B5A2B]" />
        <Stat label="تعمل الآن" value={c.processing || 0} color="bg-[#E8F0E1] border-[#87A96B]/40 text-[#4F6B3B]" />
        <Stat label="مكتملة" value={c.completed || 0} color="bg-[#DEEBCF] border-[#87A96B] text-[#3F5B2E]" />
        <Stat label="فشلت" value={c.failed || 0} color="bg-[#FCE6D4] border-[#E07A5F]/40 text-[#B8612F]" />
      </div>

      {/* Child Character (Phase C) */}
      <ChildCharacterCard orderId={orderId} />

      {/* Cover */}
      {cover && (
        <section>
          <h4 className="font-heading font-bold text-[#2D3748] mb-2 inline-flex items-center gap-2">
            <ImageIcon className="w-4 h-4 text-[#729352]" /> صورة الغلاف
          </h4>
          <div className="flex items-start gap-3 bg-[#FDFBF7] rounded-2xl p-3 border border-[#E2D8C9]" data-testid="admin-cover-preview">
            <img src={fileSrc(cover.image_url)} alt="cover" className="w-32 h-32 rounded-xl object-cover border border-[#E2D8C9]" />
            <div className="text-xs font-body text-[#5A677D] flex-1">
              <div className="mb-1">
                <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold ${cover.provider === 'ai' ? 'bg-[#E8F0E1] text-[#4F6B3B]' : 'bg-[#F8F1E7] text-[#8B5A2B]'}`}>
                  {cover.provider}
                </span>
              </div>
              <details className="cursor-pointer">
                <summary className="font-bold">Prompt المستخدم</summary>
                <p className="mt-1 font-mono text-[11px] text-[#2D3748] leading-relaxed">{cover.prompt_used}</p>
              </details>
            </div>
          </div>
        </section>
      )}

      {/* Scene images */}
      <section>
        <h4 className="font-heading font-bold text-[#2D3748] mb-2 inline-flex items-center gap-2">
          <Film className="w-4 h-4 text-[#729352]" /> صور المشاهد ({scenes.length})
        </h4>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3" data-testid="admin-scene-images">
          {scenes.map((s) => (
            <div key={s.id} className="bg-[#FDFBF7] rounded-2xl p-2 border border-[#E2D8C9]" data-testid={`scene-image-${s.scene_index}`}>
              <div className="relative aspect-square rounded-xl overflow-hidden bg-[#F2E8DA] mb-2">
                <img src={fileSrc(s.image_url)} alt={`scene ${s.scene_index}`} className="w-full h-full object-cover" />
                <span className="absolute top-1 right-1 bg-[#87A96B] text-white rounded-full w-6 h-6 grid place-content-center text-xs font-bold">
                  {s.scene_index}
                </span>
              </div>
              <div className="flex items-center justify-between text-[10px]">
                <span className={`rounded-full px-2 py-0.5 font-bold ${s.provider === 'ai' ? 'bg-[#E8F0E1] text-[#4F6B3B]' : 'bg-[#F8F1E7] text-[#8B5A2B]'}`}>
                  {s.provider}
                </span>
                <details className="text-[10px] text-[#8A9AB0]">
                  <summary className="cursor-pointer">prompt</summary>
                  <p className="mt-1 font-mono text-[10px] text-[#2D3748] leading-tight max-h-24 overflow-auto">{s.prompt_used}</p>
                </details>
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* Narration */}
      <section>
        <h4 className="font-heading font-bold text-[#2D3748] mb-2 inline-flex items-center gap-2">
          <Sparkles className="w-4 h-4 text-[#729352]" /> السرد الصوتي ({narration.length})
        </h4>
        <div className="space-y-2" data-testid="admin-narration-list">
          {narration.map((n) => (
            <div key={n.id} className="bg-[#FDFBF7] rounded-2xl p-3 border border-[#E2D8C9] flex items-start gap-3 text-sm" data-testid={`narration-${n.scene_index}`}>
              <span className="bg-[#D4A373] text-white rounded-full w-8 h-8 grid place-content-center text-xs font-bold shrink-0">
                {n.scene_index}
              </span>
              <div className="flex-1">
                <div className="flex items-center gap-2 mb-1 flex-wrap">
                  <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold ${n.provider === 'mock' ? 'bg-[#F8F1E7] text-[#8B5A2B]' : 'bg-[#E8F0E1] text-[#4F6B3B]'}`}>
                    {n.provider}
                  </span>
                  <span className="text-[10px] text-[#8A9AB0]">{n.voice_type} • {n.language}</span>
                  <span className="text-[10px] text-[#8A9AB0]">~{n.duration_seconds}s</span>
                  {n.audio_url ? (
                    <audio controls src={fileSrc(n.audio_url)} className="h-8" />
                  ) : (
                    <span className="text-[10px] text-[#B8612F]">(audio mocked — TTS provider not connected)</span>
                  )}
                </div>
                <p className="font-body text-[#2D3748] text-xs leading-relaxed">{n.text}</p>
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* Book assets */}
      <section>
        <h4 className="font-heading font-bold text-[#2D3748] mb-2 inline-flex items-center gap-2">
          <FileTextIcon className="w-4 h-4 text-[#729352]" /> صفحات الكتاب ({book.length})
        </h4>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3" data-testid="admin-book-assets">
          {book.map((b) => (
            <div key={b.id} className="bg-[#FDFBF7] rounded-2xl p-3 border border-[#E2D8C9] flex gap-3" data-testid={`book-asset-${b.page_number}`}>
              {b.illustration_url ? (
                <img src={fileSrc(b.illustration_url)} alt="" className="w-16 h-16 rounded-xl object-cover border border-[#E2D8C9] shrink-0" />
              ) : (
                <div className="w-16 h-16 rounded-xl bg-[#F2E8DA] shrink-0" />
              )}
              <div className="flex-1 text-sm">
                <div className="flex items-center gap-2 mb-1">
                  <span className="bg-[#D4A373] text-white rounded-full w-6 h-6 grid place-content-center text-[10px] font-bold">{b.page_number}</span>
                  <span className="text-[10px] text-[#8A9AB0]">{b.provider}</span>
                </div>
                <p className="font-body text-[#2D3748] text-xs">{b.page_text}</p>
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* Jobs log */}
      <section>
        <h4 className="font-heading font-bold text-[#2D3748] mb-2">سجل الوظائف ({jobs.length})</h4>
        <div className="bg-[#FDFBF7] rounded-2xl border border-[#E2D8C9] overflow-hidden" data-testid="admin-jobs-list">
          <div className="max-h-96 overflow-auto">
            <table className="w-full text-xs font-body">
              <thead className="bg-white sticky top-0">
                <tr className="text-[#5A677D]">
                  <th className="text-start px-2 py-2">النوع</th>
                  <th className="text-start px-2 py-2">الحالة</th>
                  <th className="text-start px-2 py-2">المحاولات</th>
                  <th className="text-start px-2 py-2">Provider</th>
                  <th className="text-start px-2 py-2">خطأ</th>
                  <th className="px-2 py-2"></th>
                </tr>
              </thead>
              <tbody>
                {jobs.map((j) => (
                  <tr key={j.id} className="border-t border-[#E2D8C9]" data-testid={`job-row-${j.id}`}>
                    <td className="px-2 py-2 font-bold text-[#2D3748]">{j.job_type}</td>
                    <td className="px-2 py-2">
                      <span className={
                        j.status === "completed" ? "bg-[#DEEBCF] text-[#3F5B2E] rounded-full px-2 py-0.5" :
                        j.status === "failed" ? "bg-[#FCE6D4] text-[#B8612F] rounded-full px-2 py-0.5" :
                        j.status === "processing" ? "bg-[#E8F0E1] text-[#4F6B3B] rounded-full px-2 py-0.5" :
                        "bg-[#F8F1E7] text-[#8B5A2B] rounded-full px-2 py-0.5"
                      }>{j.status}</span>
                    </td>
                    <td className="px-2 py-2">{j.attempt_count}/{j.max_attempts}</td>
                    <td className="px-2 py-2 text-[#8A9AB0]">{j.provider || "—"}</td>
                    <td className="px-2 py-2 text-[#B8612F] max-w-xs truncate" title={j.error_message || ""}>{j.error_message || "—"}</td>
                    <td className="px-2 py-2">
                      {j.status === "failed" && (
                        <button onClick={() => retryJob(j.id)} className="text-[10px] bg-[#E8F0E1] text-[#4F6B3B] rounded-full px-2 py-0.5 font-bold" data-testid={`retry-job-${j.id}`}>
                          أعِد
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </section>
    </div>
  );
}

function Stat({ label, value, color }) {
  return (
    <div className={`rounded-2xl px-3 py-2 border text-center ${color}`}>
      <div className="text-[11px] font-body opacity-80">{label}</div>
      <div className="font-heading font-bold text-xl">{value}</div>
    </div>
  );
}

function ChildCharacterCard({ orderId }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);

  const load = async () => {
    try {
      const { data: d } = await api.get(`/admin/orders/${orderId}/child-character`);
      setData(d);
    } catch {
      // silent — card is optional; never block media tab
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { load(); }, [orderId]);

  const regenerate = async () => {
    setBusy(true);
    try {
      await api.post(`/admin/orders/${orderId}/child-character/regenerate`);
      toast.success("بدأت إعادة توليد الشخصية");
      setTimeout(load, 1500);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "فشل");
    } finally {
      setBusy(false);
    }
  };

  if (loading) return null;
  if (!data) return null;

  const asset = data.asset;
  const enabled = data.stage_enabled;
  const status = asset?.status || (enabled ? "not_run" : "disabled");
  const statusMap = {
    completed: { label: "مكتمل", bg: "bg-[#DEEBCF]", fg: "text-[#3F5B2E]" },
    processing: { label: "جاري المعالجة", bg: "bg-[#E8F0E1]", fg: "text-[#4F6B3B]" },
    queued: { label: "في الانتظار", bg: "bg-[#F8F1E7]", fg: "text-[#8B5A2B]" },
    failed: { label: "فشل", bg: "bg-[#FCE6D4]", fg: "text-[#B8612F]" },
    not_run: { label: "لم يُشغّل بعد", bg: "bg-[#F8F1E7]", fg: "text-[#8B5A2B]" },
    disabled: { label: "معطّل", bg: "bg-[#EEE9E0]", fg: "text-[#5A677D]" },
  };
  const sm = statusMap[status] || statusMap.disabled;

  return (
    <section
      className="bg-[#FDFBF7] rounded-2xl p-4 border border-[#E2D8C9]"
      data-testid="admin-child-character-card"
    >
      <div className="flex items-center justify-between flex-wrap gap-2 mb-3">
        <h4 className="font-heading font-bold text-[#2D3748] inline-flex items-center gap-2">
          <UsersIcon className="w-4 h-4 text-[#729352]" />
          شخصية الطفل (Phase C — I2I)
        </h4>
        <div className="flex items-center gap-2">
          <span
            className={`rounded-full px-2 py-0.5 text-[10px] font-bold ${sm.bg} ${sm.fg}`}
            data-testid="child-character-status"
          >
            {sm.label}
          </span>
          {!enabled && (
            <span className="rounded-full px-2 py-0.5 text-[10px] font-bold bg-[#F8F1E7] text-[#8B5A2B]">
              المرحلة معطّلة في الإعدادات
            </span>
          )}
          {asset?.provider && (
            <span
              className={`rounded-full px-2 py-0.5 text-[10px] font-bold ${
                asset.mock
                  ? "bg-[#F8F1E7] text-[#8B5A2B]"
                  : "bg-[#DEEBCF] text-[#3F5B2E]"
              }`}
              data-testid="child-character-mode-badge"
            >
              {asset.mock ? `MOCK · ${asset.provider}` : `REAL · ${asset.provider}`}
              {asset.model_name && ` / ${asset.model_name}`}
            </span>
          )}
          <button
            onClick={regenerate}
            disabled={busy}
            className="rounded-full bg-[#F8F1E7] text-[#8B5A2B] px-3 py-1 text-xs font-bold inline-flex items-center gap-1 hover:bg-[#F2E8DA] disabled:opacity-50"
            data-testid="child-character-regen-btn"
          >
            <RefreshCw className="w-3 h-3" /> إعادة توليد
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div>
          <div className="text-[11px] font-body text-[#8A9AB0] mb-1">الصورة الأصلية</div>
          {data.source_image_url ? (
            <img
              src={fileSrc(data.source_image_url)}
              alt="source"
              className="w-32 h-32 rounded-2xl object-cover border border-[#E2D8C9]"
              data-testid="child-character-source-image"
            />
          ) : (
            <div className="w-32 h-32 rounded-2xl bg-[#F2E8DA] grid place-content-center text-[11px] text-[#8A9AB0]">
              لا توجد صورة
            </div>
          )}
        </div>
        <div>
          <div className="text-[11px] font-body text-[#8A9AB0] mb-1">شخصية الكرتون المُولّدة</div>
          {asset?.generated_image_url ? (
            <img
              src={fileSrc(asset.generated_image_url)}
              alt="generated"
              className="w-32 h-32 rounded-2xl object-cover border border-[#E2D8C9]"
              data-testid="child-character-generated-image"
            />
          ) : (
            <div className="w-32 h-32 rounded-2xl bg-[#F2E8DA] grid place-content-center text-[11px] text-[#8A9AB0] text-center px-2">
              {enabled ? "لم تُولَّد بعد" : "المرحلة غير مفعّلة"}
            </div>
          )}
        </div>
      </div>

      {asset?.prompt_used && (
        <details className="mt-3 cursor-pointer" data-testid="child-character-prompt-details">
          <summary className="text-xs font-bold text-[#5A677D]">Prompt المستخدم</summary>
          <p className="mt-1 font-mono text-[11px] text-[#2D3748] leading-relaxed bg-white rounded-xl p-2 border border-[#E2D8C9] whitespace-pre-wrap">
            {asset.prompt_used}
          </p>
        </details>
      )}

      {asset?.error_message && (
        <div className="mt-3 text-[11px] bg-[#FCE6D4] text-[#B8612F] rounded-xl p-2 border border-[#E07A5F]/40">
          {asset.error_message}
        </div>
      )}
    </section>
  );
}

function AdminProductionTab({ orderId }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [editing, setEditing] = useState(null); // scene_id currently being edited
  const [form, setForm] = useState({});

  const load = async () => {
    setLoading(true);
    try {
      const { data: d } = await api.get(`/admin/orders/${orderId}/production`);
      setData(d);
    } catch {
      toast.error("تعذّر تحميل خطة الإنتاج");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); /* eslint-disable-next-line */ }, [orderId]);

  const regenerate = async () => {
    try {
      await api.post(`/admin/orders/${orderId}/production/regenerate`);
      toast.success("جاري إعادة توليد خطة الإنتاج...");
      // Poll briefly
      let i = 0;
      const iv = setInterval(async () => {
        i++;
        await load();
        if (i > 20) clearInterval(iv);
        const { data: latest } = await api.get(`/admin/orders/${orderId}/production`);
        if (["production_ready", "failed", "production_approved"].includes(latest.status)) {
          clearInterval(iv);
        }
      }, 3500);
    } catch {
      toast.error("فشل");
    }
  };

  const startEditScene = (s) => {
    setEditing(s.id);
    setForm({
      narration_text: s.narration_text || "",
      book_text: s.book_text || "",
      visual_description: s.visual_description || "",
      image_prompt_text: s.image_prompt?.prompt_text || "",
      animation_motion_hint: s.animation_prompt?.motion_hint || "",
      animation_camera_style: s.animation_prompt?.camera_style || "",
    });
  };

  const saveScene = async () => {
    try {
      await api.patch(`/admin/scene-plans/${editing}`, form);
      toast.success("تم حفظ التعديلات");
      setEditing(null);
      setForm({});
      load();
    } catch {
      toast.error("فشل الحفظ");
    }
  };

  if (loading) return <p className="text-center py-8 text-[#8A9AB0] font-body">جاري التحميل...</p>;
  if (!data) return null;

  const { plan, scenes = [], book_pages = [], character_profiles = [] } = data;
  const status = data.status;
  const approved = data.production_approved;
  const src = data.production_generation?.source;

  return (
    <div data-testid="admin-production-tab">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3 mb-4">
        <div className="flex items-center gap-2 flex-wrap text-sm font-body">
          <span className="bg-[#FDFBF7] border border-[#E2D8C9] rounded-full px-3 py-1 inline-flex items-center gap-1">
            <Film className="w-3 h-3 text-[#729352]" />
            الحالة: <b className="text-[#2D3748]">{data.status_ar}</b>
          </span>
          {src === "ai" && <span className="bg-[#E8F0E1] text-[#4F6B3B] rounded-full px-3 py-1 text-xs font-bold">AI</span>}
          {src === "fallback" && <span className="bg-[#F8F1E7] text-[#8B5A2B] rounded-full px-3 py-1 text-xs font-bold">Fallback</span>}
          {approved && (
            <span className="bg-[#87A96B] text-white rounded-full px-3 py-1 text-xs font-bold inline-flex items-center gap-1">
              <CheckCircle2 className="w-3 h-3" /> معتمدة من المستخدم
            </span>
          )}
          <span className="bg-[#FDFBF7] border border-[#E2D8C9] rounded-full px-3 py-1 text-xs">
            إعادات المستخدم: <b>{data.production_regeneration_count} / {data.max_user_production_regenerations}</b>
          </span>
        </div>
        <button onClick={regenerate} className="rounded-full bg-[#E8F0E1] text-[#4F6B3B] px-4 py-2 text-xs font-bold inline-flex items-center gap-1 hover:bg-[#D4E3C1]" data-testid="admin-regen-production">
          <RefreshCw className="w-3 h-3" /> إعادة توليد الخطة
        </button>
      </div>

      {!plan ? (
        <p className="text-center py-12 text-[#8A9AB0] font-body">
          {status === "production_planning" ? "جاري توليد خطة الإنتاج..." : "لم يتم توليد خطة بعد"}
        </p>
      ) : (
        <>
          {/* Plan summary */}
          <div className="bg-[#FDFBF7] rounded-3xl p-5 border border-[#E2D8C9] mb-5">
            <h3 className="font-heading text-xl font-bold text-[#2D3748] mb-1">{plan.title}</h3>
            <p className="font-body text-sm text-[#5A677D] mb-3 whitespace-pre-wrap">{plan.story_summary}</p>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-2 mb-3">
              <Field label="الرسالة" value={plan.main_message} />
              <Field label="المدة" value={plan.duration_label} />
              <Field label="المشاهد" value={plan.target_scene_count} />
              <Field label="صور مقدّرة" value={plan.estimated_image_count} />
              <Field label="كلمات السرد" value={plan.total_word_count} />
              <Field label="safety" value={plan.safety_check} />
              <Field label="النبرة" value={plan.tone} />
              <Field label="البيئة" value={plan.setting} />
              <Field label="الخلفية الصوتية" value={
                { music: "موسيقى هادئة", human_rhythm: "إيقاع صوتي بشري", none: "بدون خلفية" }[
                  (plan.audio_background || {}).mode || "music"
                ]
              } />
            </div>
            {plan.style_guide && (
              <div className="bg-white rounded-2xl p-3 border border-[#E2D8C9] mt-2" data-testid="plan-style-guide">
                <div className="text-xs font-bold text-[#729352] mb-1 inline-flex items-center gap-1">
                  <Palette className="w-3 h-3" /> Style Guide
                </div>
                <div className="text-xs font-body text-[#2D3748]">
                  <div><b>Palette:</b> {plan.style_guide.palette}</div>
                  <div><b>Lighting:</b> {plan.style_guide.lighting}</div>
                  <div><b>Art direction:</b> {plan.style_guide.art_direction}</div>
                </div>
              </div>
            )}
            {plan.cover_prompt && (
              <div className="bg-white rounded-2xl p-3 border border-[#E2D8C9] mt-2" data-testid="plan-cover-prompt">
                <div className="text-xs font-bold text-[#729352] mb-1 inline-flex items-center gap-1">
                  <ImageIcon className="w-3 h-3" /> Cover Prompt
                </div>
                <p className="text-xs font-mono text-[#2D3748] leading-relaxed">{plan.cover_prompt}</p>
              </div>
            )}
          </div>

          {/* Characters */}
          {character_profiles.length > 0 && (
            <div className="mb-5">
              <h4 className="font-heading font-bold text-[#2D3748] mb-2 inline-flex items-center gap-2">
                <UsersIcon className="w-4 h-4 text-[#729352]" /> الشخصيات ({character_profiles.length})
              </h4>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                {character_profiles.map((c) => (
                  <div key={c.id} className="bg-[#FDFBF7] rounded-2xl p-3 border border-[#E2D8C9] text-xs font-body" data-testid={`character-profile-${c.id}`}>
                    <div className="flex items-center gap-2 mb-1">
                      <span className="bg-[#E8F0E1] text-[#4F6B3B] rounded-full px-2 py-0.5 text-[10px] font-bold">{c.type}</span>
                      {c.name && <span className="font-bold">{c.name}</span>}
                      {c.name_en && <span className="text-[#8A9AB0]">({c.name_en})</span>}
                    </div>
                    <div className="text-[#5A677D]">
                      <div><b>Look:</b> {c.visual_description}</div>
                      {c.clothing_style && <div><b>Clothing:</b> {c.clothing_style}</div>}
                      {c.key_features && <div><b>Features:</b> {c.key_features}</div>}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Scenes */}
          <h4 className="font-heading font-bold text-[#2D3748] mb-2 inline-flex items-center gap-2">
            <Film className="w-4 h-4 text-[#729352]" /> المشاهد ({scenes.length})
          </h4>
          <div className="space-y-3 mb-5">
            {scenes.map((s) => (
              <div key={s.id} className="bg-white rounded-2xl p-4 border-2 border-[#E2D8C9]" data-testid={`scene-plan-${s.id}`}>
                <div className="flex items-center justify-between gap-2 mb-2 flex-wrap">
                  <div className="flex items-center gap-2">
                    <span className="bg-[#87A96B] text-white rounded-full w-7 h-7 grid place-content-center text-xs font-bold">
                      {s.scene_index}
                    </span>
                    <div>
                      <div className="font-heading font-bold text-[#2D3748]">{s.title}</div>
                      <div className="text-[11px] text-[#8A9AB0]">{s.arc_beat} • {s.emotional_tone} • {s.word_count} كلمة</div>
                    </div>
                  </div>
                  {editing === s.id ? (
                    <div className="flex gap-1">
                      <button onClick={saveScene} className="rounded-full bg-[#87A96B] text-white px-3 py-1 text-xs font-bold inline-flex items-center gap-1">
                        <Save className="w-3 h-3" /> حفظ
                      </button>
                      <button onClick={() => { setEditing(null); setForm({}); }} className="rounded-full bg-[#F8F1E7] text-[#8B5A2B] px-3 py-1 text-xs font-bold">
                        إلغاء
                      </button>
                    </div>
                  ) : (
                    <button onClick={() => startEditScene(s)} className="text-xs font-bold text-[#729352] hover:text-[#4F6B3B]" data-testid={`edit-scene-${s.id}`}>
                      تعديل
                    </button>
                  )}
                </div>

                {editing === s.id ? (
                  <div className="space-y-2">
                    <div>
                      <label className="text-[11px] font-bold text-[#5A677D]">نص السرد (عربي)</label>
                      <textarea rows={3} value={form.narration_text} onChange={(e) => setForm({ ...form, narration_text: e.target.value })}
                        className="w-full bg-[#FDFBF7] border border-[#E2D8C9] rounded-xl p-2 text-sm font-body" />
                    </div>
                    <div>
                      <label className="text-[11px] font-bold text-[#5A677D]">نص الكتاب (عربي)</label>
                      <textarea rows={2} value={form.book_text} onChange={(e) => setForm({ ...form, book_text: e.target.value })}
                        className="w-full bg-[#FDFBF7] border border-[#E2D8C9] rounded-xl p-2 text-sm font-body" />
                    </div>
                    <div>
                      <label className="text-[11px] font-bold text-[#5A677D]">Image Prompt (EN)</label>
                      <textarea rows={3} value={form.image_prompt_text} onChange={(e) => setForm({ ...form, image_prompt_text: e.target.value })}
                        className="w-full bg-[#FDFBF7] border border-[#E2D8C9] rounded-xl p-2 text-xs font-mono" />
                    </div>
                    <div className="grid grid-cols-2 gap-2">
                      <input value={form.animation_motion_hint} onChange={(e) => setForm({ ...form, animation_motion_hint: e.target.value })}
                        placeholder="Motion hint" className="bg-[#FDFBF7] border border-[#E2D8C9] rounded-xl p-2 text-xs font-mono" />
                      <input value={form.animation_camera_style} onChange={(e) => setForm({ ...form, animation_camera_style: e.target.value })}
                        placeholder="Camera style" className="bg-[#FDFBF7] border border-[#E2D8C9] rounded-xl p-2 text-xs font-mono" />
                    </div>
                  </div>
                ) : (
                  <div className="space-y-2 text-sm">
                    <div className="bg-[#FDFBF7] rounded-xl p-2 border border-[#E2D8C9]">
                      <div className="text-[11px] font-bold text-[#729352]">السرد</div>
                      <p className="font-body text-[#2D3748]">{s.narration_text}</p>
                    </div>
                    <div className="bg-[#FDFBF7] rounded-xl p-2 border border-[#E2D8C9]">
                      <div className="text-[11px] font-bold text-[#729352]">نص الكتاب</div>
                      <p className="font-body text-[#2D3748]">{s.book_text}</p>
                    </div>
                    <details className="bg-[#FDFBF7] rounded-xl p-2 border border-[#E2D8C9]">
                      <summary className="text-[11px] font-bold text-[#729352] cursor-pointer inline-flex items-center gap-1">
                        <ImageIcon className="w-3 h-3" /> Image Prompt (EN)
                      </summary>
                      <p className="mt-1 text-xs font-mono text-[#2D3748] leading-relaxed">{s.image_prompt?.prompt_text}</p>
                    </details>
                    <details className="bg-[#FDFBF7] rounded-xl p-2 border border-[#E2D8C9]">
                      <summary className="text-[11px] font-bold text-[#729352] cursor-pointer inline-flex items-center gap-1">
                        <Film className="w-3 h-3" /> Animation Prompt
                      </summary>
                      <div className="mt-1 text-xs font-mono text-[#2D3748] space-y-1">
                        <div><b>Start:</b> {s.animation_prompt?.start_frame_description}</div>
                        <div><b>End:</b> {s.animation_prompt?.end_frame_description}</div>
                        <div><b>Motion:</b> {s.animation_prompt?.motion_hint}</div>
                        <div><b>Camera:</b> {s.animation_prompt?.camera_style}</div>
                      </div>
                    </details>
                    {s.edited_by_admin && (
                      <span className="text-[10px] bg-[#D4A373]/20 text-[#8B5A2B] rounded-full px-2 py-0.5 inline-block">معدّل يدوياً</span>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>

          {/* Book pages */}
          {book_pages.length > 0 && (
            <div className="mb-3">
              <h4 className="font-heading font-bold text-[#2D3748] mb-2 inline-flex items-center gap-2">
                <FileTextIcon className="w-4 h-4 text-[#729352]" /> صفحات الكتاب ({book_pages.length})
              </h4>
              <div className="space-y-2">
                {book_pages.map((p) => (
                  <div key={p.id} className="bg-[#FDFBF7] rounded-2xl p-3 border border-[#E2D8C9] text-sm flex gap-3" data-testid={`book-page-${p.id}`}>
                    <span className="bg-[#D4A373] text-white rounded-full w-7 h-7 grid place-content-center text-xs font-bold shrink-0">
                      {p.page_number}
                    </span>
                    <div className="flex-1">
                      <p className="font-body text-[#2D3748]">{p.text}</p>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}


function AdminPricingTab({ orderId }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [snapshotting, setSnapshotting] = useState(null);

  const load = async () => {
    setLoading(true);
    try {
      const { data } = await api.get(`/admin/orders/${orderId}/pricing`);
      setData(data);
    } catch {
      toast.error("تعذّر تحميل التسعير");
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { load(); }, [orderId]);

  const doSnapshot = async (kind) => {
    setSnapshotting(kind);
    try {
      await api.post(`/admin/orders/${orderId}/pricing/snapshot?kind=${kind}`);
      toast.success(`تم حفظ snapshot (${kind === "estimate" ? "تقديري" : "نهائي"})`);
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "فشل");
    } finally {
      setSnapshotting(null);
    }
  };

  if (loading || !data) {
    return <div className="py-8 text-center font-body text-[#8A9AB0]">جاري التحميل...</div>;
  }

  return (
    <div data-testid="admin-pricing-tab" className="space-y-5">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <PricingCard
          title="تقديري (عند production_ready)"
          subtitle="estimate — قبل بدء توليد الوسائط"
          stored={data?.snapshots?.estimate}
          fresh={data?.fresh?.estimate}
          color="amber"
          onSnapshot={() => doSnapshot("estimate")}
          busy={snapshotting === "estimate"}
        />
        <PricingCard
          title="نهائي (عند delivered)"
          subtitle="actual — بعد تنفيذ كل المراحل"
          stored={data?.snapshots?.actual}
          fresh={data?.fresh?.actual}
          color="green"
          onSnapshot={() => doSnapshot("actual")}
          busy={snapshotting === "actual"}
        />
      </div>

      <p className="text-xs text-[#8A9AB0] font-body" data-testid="pricing-tab-help">
        Internal Cost = تكلفة الموارد الفعلية | Sell Price = السعر للعميل (مع هامش الربح والحد الأدنى) | Margin = الربح.
      </p>
    </div>
  );
}

function PricingCard({ title, subtitle, stored, fresh, color, onSnapshot, busy }) {
  const tone = color === "amber"
    ? { bg: "bg-[#F8F1E7]", border: "border-[#D4A373]/40", chip: "text-[#8B5A2B]" }
    : { bg: "bg-[#E8F0E1]", border: "border-[#87A96B]/40", chip: "text-[#4F6B3B]" };
  return (
    <div className={`rounded-2xl p-4 border-2 ${tone.bg} ${tone.border}`}>
      <div className="flex items-start justify-between gap-2 mb-3">
        <div>
          <h4 className={`font-heading font-bold ${tone.chip}`}>{title}</h4>
          <p className="text-xs text-[#5A677D] font-body">{subtitle}</p>
        </div>
        <button
          onClick={onSnapshot}
          disabled={busy}
          className="text-xs bg-white hover:bg-[#FDFBF7] border border-[#E2D8C9] rounded-full px-3 py-1 font-body font-bold text-[#5A677D] disabled:opacity-50"
          data-testid={`snapshot-${color === "amber" ? "estimate" : "actual"}-btn`}
        >
          {busy ? "..." : "حفظ snapshot"}
        </button>
      </div>

      {stored ? (
        <div className="space-y-1 text-sm font-body bg-white rounded-2xl p-3 border border-[#E2D8C9]" data-testid={`stored-${color === "amber" ? "estimate" : "actual"}`}>
          <Row label="Internal cost" value={`${stored.internal_cost} ${stored.currency}`} />
          <Row label="Sell price" value={`${stored.sell_price} ${stored.currency}`} bold />
          <Row label="Margin" value={`${stored.margin} ${stored.currency}`} />
          <Row label="Output type" value={stored.output_type} small />
          <Row label="At" value={(stored.created_at || "").slice(0, 16)} small />
        </div>
      ) : (
        <div className="text-xs text-[#8A9AB0] font-body italic mb-2">لم يُحفظ snapshot بعد.</div>
      )}

      {fresh && (
        <details className="mt-3 bg-white rounded-2xl border border-[#E2D8C9]">
          <summary className="cursor-pointer px-3 py-2 text-xs font-body text-[#5A677D] font-bold">
            إعادة الحساب الآن: {fresh.sell_price} {fresh.currency} (تفاصيل {fresh.items?.length || 0} مرحلة)
          </summary>
          <div className="p-3 text-xs font-body space-y-1">
            <div className="text-[#5A677D]">base: {fresh.base_cost} → ×{fresh.modifiers?.output} (output) ×{fresh.modifiers?.cost_tier} (tier) = <b>{fresh.internal_cost}</b></div>
            <table className="w-full text-xs mt-2">
              <tbody>
                {(fresh.items || []).map((it, i) => (
                  <tr key={i} className="border-t border-[#E2D8C9]">
                    <td className="py-1 text-[#2D3748]">{it.label || it.stage}</td>
                    <td className="py-1 text-[#5A677D]">×{it.quantity}</td>
                    <td className="py-1 text-[#5A677D]">@{it.unit_cost}</td>
                    <td className="py-1 text-[#2D3748] font-bold">{it.line_cost}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      )}
    </div>
  );
}

function Row({ label, value, bold, small }) {
  return (
    <div className={`flex items-center justify-between ${small ? "text-xs" : ""}`}>
      <span className={`text-[#5A677D] font-body ${bold ? "font-bold" : ""}`}>{label}</span>
      <span className={`text-[#2D3748] font-body ${bold ? "font-bold" : ""}`}>{value}</span>
    </div>
  );
}
