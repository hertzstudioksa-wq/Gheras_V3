import React, { useEffect, useState } from "react";
import { api, fileSrc } from "../../lib/api";
import OrderStatusBadge from "../../components/gheras/OrderStatusBadge";
import { toast } from "sonner";
import { Eye, Filter, Wand2, Save, RefreshCw, X, Sparkles, Heart, BookOpen, Rocket, CheckCircle2, Trash2, Clock } from "lucide-react";

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
              <button onClick={() => setDetail(null)} className="text-[#8A9AB0]"><X className="w-5 h-5" /></button>
            </div>

            <div className="flex gap-2 mb-5 border-b border-[#E2D8C9] overflow-x-auto">
              {[
                { k: "overview", l: "نظرة عامة" },
                { k: "scenarios", l: "السيناريوهات" },
                { k: "history", l: "سجل الحالات" },
                { k: "json", l: "JSON" },
                { k: "prompt", l: "البرومبت" },
              ].map((t) => (
                <button key={t.k} onClick={() => setTab(t.k)} className={`px-4 py-2 text-sm font-body font-bold border-b-2 whitespace-nowrap ${tab === t.k ? "border-[#87A96B] text-[#4F6B3B]" : "border-transparent text-[#8A9AB0]"}`}>
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
              <div data-testid="admin-scenarios-tab">
                <div className="flex items-center justify-between flex-wrap gap-3 mb-4">
                  <div className="text-sm text-[#5A677D] font-body">
                    {scenariosData?.generation?.source === "ai" && <span className="bg-[#E8F0E1] text-[#4F6B3B] rounded-full px-3 py-1 text-xs font-bold">AI</span>}
                    {scenariosData?.generation?.source === "fallback" && <span className="bg-[#F8F1E7] text-[#8B5A2B] rounded-full px-3 py-1 text-xs font-bold">Fallback</span>}
                    {scenariosData?.generation?.source === "error" && <span className="bg-[#FCE6D4] text-[#B8612F] rounded-full px-3 py-1 text-xs font-bold">Error</span>}
                    <span className="ms-2">عدد السيناريوهات: <b>{scenariosData?.scenarios?.length || 0}</b></span>
                  </div>
                  <div className="flex gap-2">
                    <button onClick={adminRegenerate} className="rounded-full bg-[#E8F0E1] text-[#4F6B3B] px-4 py-2 text-xs font-bold inline-flex items-center gap-1" data-testid="admin-regen-scenarios">
                      <RefreshCw className="w-3 h-3" /> إعادة توليد
                    </button>
                    {(scenariosData?.scenarios?.length || 0) > 0 && (
                      <button onClick={adminDeleteScenarios} className="rounded-full bg-[#FCE6D4] text-[#B8612F] px-4 py-2 text-xs font-bold inline-flex items-center gap-1">
                        <Trash2 className="w-3 h-3" /> حذف
                      </button>
                    )}
                  </div>
                </div>

                {(scenariosData?.scenarios || []).length === 0 ? (
                  <p className="text-center py-12 text-[#8A9AB0] font-body">لم يتم توليد سيناريوهات بعد</p>
                ) : (
                  <div className="space-y-3">
                    {scenariosData.scenarios.map((s) => {
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
                              <button onClick={() => adminSelectScenario(s.id)} className="text-xs font-bold text-[#729352] hover:text-[#4F6B3B] px-3 py-1">
                                اختر هذا
                              </button>
                            )}
                          </div>
                          <p className="font-body text-sm text-[#5A677D]">{s.short_summary}</p>
                          {s.learning_goal && (
                            <div className="mt-2 text-xs text-[#4F6B3B] font-body">🎯 {s.learning_goal}</div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
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
