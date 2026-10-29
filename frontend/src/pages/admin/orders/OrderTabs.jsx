import React, { useEffect, useState } from "react";
import { api, fileSrc } from "../../../lib/api";
import OrderStatusBadge from "../../../components/gheras/OrderStatusBadge";
import { ConfirmAction } from "../../../components/admin/AdminKit";
import { toast } from "sonner";
import { Eye, Filter, Save, RefreshCw, X, Sparkles, Heart, BookOpen, Rocket, CheckCircle2, Trash2, Clock, ChevronDown, ChevronUp, Lightbulb, Coins, Film, ImageIcon, FileText as FileTextIcon, Users as UsersIcon, Palette } from "lucide-react";

// The order page's tab bodies (scenarios, production plan, media & delivery,
// cost), moved out of the old orders modal (M5).

const ANGLE_META = {
  emotional:   { label: "عاطفي", icon: Heart, bg: "bg-[#FCE6D4]", fg: "text-[#B8612F]" },
  educational: { label: "تعليمي هادئ", icon: BookOpen, bg: "bg-[#E8F0E1]", fg: "text-[#4F6B3B]" },
  adventure:   { label: "مغامرة", icon: Rocket, bg: "bg-[#F8F1E7]", fg: "text-[#8B5A2B]" },
};

export function Field({ label, value }) {
  return (
    <div className="bg-[#FDFBF7] rounded-xl p-2 border border-[#E2D8C9]">
      <div className="text-xs text-[#8A9AB0] font-body">{label}</div>
      <div className="font-body font-bold text-[#2D3748] text-sm">{value || "—"}</div>
    </div>
  );
}

export function AdminScenariosTab({ scenariosData, onRegenerate, onDelete, onSelect }) {
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

export function AdminMediaTab({ orderId }) {
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

  // For a parent who asked us by phone: their pictures are approved and the story goes on.
  const approvePictures = async () => {
    if (!window.confirm("اعتماد صور القصة بدل ولي الأمر؟ بعدها تبدأ الصور تتحرّك.")) return;
    setBusy(true);
    try {
      await api.post(`/admin/orders/${orderId}/pictures/approve`);
      toast.success("اتعتمدت الصور والقصة بتكمل");
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
          {status === "pictures_review" && (
            <button onClick={approvePictures} disabled={busy} data-testid="admin-approve-pictures-btn"
              className="rounded-full bg-[#E8F0E1] text-[#4F6B3B] px-3 py-1 text-xs font-bold inline-flex items-center gap-1 disabled:opacity-50">
              <CheckCircle2 className="w-3 h-3" /> اعتماد الصور بدل ولي الأمر
            </button>
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
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-1 flex-wrap">
                  <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold ${n.provider === 'mock' ? 'bg-[#F8F1E7] text-[#8B5A2B]' : 'bg-[#E8F0E1] text-[#4F6B3B]'}`}>
                    {n.provider}
                  </span>
                  <span className="text-[10px] text-[#8A9AB0]">{n.voice_type} • {n.language}</span>
                  <span className="text-[10px] text-[#8A9AB0]">~{n.duration_seconds}s</span>
                  {n.audio_url ? (
                    <audio controls src={fileSrc(n.audio_url)} className="h-8 w-full max-w-xs" />
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
                        <ConfirmAction tone="cost" title="تعيد تشغيل الخطوة دي؟"
                          description="إعادة التشغيل بتنادي الموديل تاني، يعني بتصرف من الرصيد (صورة ≈ $0.06–0.17، مقطع فيديو ≈ $0.35–1.1)."
                          confirmLabel="أعِد التشغيل" onConfirm={() => retryJob(j.id)}
                          className="text-[10px] bg-[#E8F0E1] text-[#4F6B3B] rounded-full px-2 py-0.5 font-bold" testId={`retry-job-${j.id}`}>
                          أعِد
                        </ConfirmAction>
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
          شخصية الطفل
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
          <ConfirmAction tone="cost" title="ترسم شخصية الطفل من جديد؟"
            description="صورة جديدة بجودة عالية (≈ $0.17). الصور اللي اترسمت قبل كده مش هتتغير لوحدها."
            confirmLabel="ارسمها من جديد" onConfirm={regenerate} disabled={busy}
            className="rounded-full bg-[#F8F1E7] text-[#8B5A2B] px-3 py-1 text-xs font-bold inline-flex items-center gap-1 hover:bg-[#F2E8DA] disabled:opacity-50"
            testId="child-character-regen-btn">
            <RefreshCw className="w-3 h-3" /> إعادة توليد
          </ConfirmAction>
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

export function AdminProductionTab({ orderId }) {
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
        <ConfirmAction tone="cost" title="تعمل خطة إنتاج جديدة؟"
          description="خطة جديدة من موديل النصوص (≈ $0.3 على Claude Opus)، والخطة الحالية بتتأرشف. الصور والفيديو اللي اتعملوا من الخطة القديمة مش هيتعادوا لوحدهم."
          confirmLabel="اعمل خطة جديدة" onConfirm={regenerate}
          className="rounded-full bg-[#E8F0E1] text-[#4F6B3B] px-4 py-2 text-xs font-bold inline-flex items-center gap-1 hover:bg-[#D4E3C1]"
          testId="admin-regen-production">
          <RefreshCw className="w-3 h-3" /> إعادة توليد الخطة
        </ConfirmAction>
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


const PAYMENT_STATUS = { awaiting: "مستني الدفع", paid: "مدفوع", refunded: "مسترد للرصيد" };
const PAYMENT_METHOD = { wallet: "الرصيد", card: "بطاقة (ميسر)", bundle_credit: "باقة قديمة", admin: "مجاناً (الإدارة)" };
const money = (v) => (v == null ? "—" : `${Number(v).toLocaleString("en-US", { maximumFractionDigits: 2 })} ر.س`);

// Cost tab (M6): the price the parent saw, the payment, and what the order
// actually cost so far (from the records each stage wrote), with the margin.
export function AdminPricingTab({ orderId }) {
  const [data, setData] = useState(null);

  const load = () => api.get(`/admin/orders/${orderId}/pricing`).then((r) => setData(r.data)).catch(() => toast.error("تعذّر تحميل التكلفة"));
  useEffect(() => { load(); }, [orderId]); // eslint-disable-line react-hooks/exhaustive-deps

  const act = async (path, reason, ok) => {
    try {
      await api.post(`/admin/orders/${orderId}/payment/${path}`, { reason });
      toast.success(ok);
      load();
    } catch (e) { toast.error(e?.response?.data?.detail || "فشل"); }
  };

  if (!data) return <div className="py-8 text-center font-body text-[#8A9AB0]">جاري التحميل...</div>;
  const { quote, payment, actual } = data;
  const tone = actual.margin_pct == null ? "text-[#8A9AB0]" : actual.margin_pct >= 45 ? "text-[#4F6B3B]" : actual.margin_pct >= 30 ? "text-[#8B5A2B]" : "text-[#B8612F]";
  return (
    <div data-testid="admin-pricing-tab" className="space-y-5">
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="rounded-2xl p-4 bg-[#FDFBF7] border border-[#E2D8C9] font-body">
          <div className="text-xs text-[#5A677D] mb-1">السعر للعميل (قبل الضريبة)</div>
          <div className="font-heading text-2xl font-bold text-[#2D3748]">{money(actual.price_sar)}</div>
          {quote && <div className="text-xs text-[#8A9AB0] mt-1">عرض السعر: {quote.seconds} ث · تكلفة مقدّرة {money(actual.estimate_sar)}{quote.overridden ? " · سعر يدوي" : ""}</div>}
        </div>
        <div className="rounded-2xl p-4 bg-[#FDFBF7] border border-[#E2D8C9] font-body">
          <div className="text-xs text-[#5A677D] mb-1">التكلفة الفعلية لحد دلوقتي</div>
          <div className="font-heading text-2xl font-bold text-[#2D3748]">{money(actual.total_sar)}</div>
          <div className="text-xs text-[#8A9AB0] mt-1" dir="ltr" style={{ textAlign: "right" }}>
            ${actual.total_usd}{actual.vs_estimate_pct != null ? ` · ${actual.vs_estimate_pct > 0 ? "+" : ""}${actual.vs_estimate_pct}% vs estimate` : ""}
          </div>
        </div>
        <div className="rounded-2xl p-4 bg-[#FDFBF7] border border-[#E2D8C9] font-body">
          <div className="text-xs text-[#5A677D] mb-1">الهامش (بعد رسوم الدفع)</div>
          <div className={`font-heading text-2xl font-bold ${tone}`}>{actual.margin_pct == null ? "—" : `${actual.margin_pct}%`}</div>
          {actual.margin_sar != null && <div className="text-xs text-[#8A9AB0] mt-1">{money(actual.margin_sar)}</div>}
        </div>
      </div>

      <div className="rounded-2xl border border-[#E2D8C9] p-4 font-body" data-testid="order-payment-admin">
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <div>
            <div className="font-bold text-[#2D3748]">الدفع: {payment ? PAYMENT_STATUS[payment.status] || payment.status : "مفيش (الدفع مكانش مطلوب)"}</div>
            {payment && (
              <div className="text-sm text-[#5A677D]">
                {money(payment.total_sar)}{payment.vat_sar ? ` شامل ضريبة ${money(payment.vat_sar)}` : ""}
                {payment.method ? ` · ${PAYMENT_METHOD[payment.method] || payment.method}` : ""}
                {payment.paid_at ? ` · ${payment.paid_at.slice(0, 16).replace("T", " ")}` : ""}
                {payment.note ? ` · ${payment.note}` : ""}
                {payment.refund_reason ? ` · سبب الاسترداد: ${payment.refund_reason}` : ""}
              </div>
            )}
          </div>
          <div className="flex gap-2 flex-wrap">
            {payment?.status === "awaiting" && (
              <ConfirmAction title="تعدّي الطلب من غير دفع؟" description="الطلب هيدخل الإنتاج على طول ومش هيتحسب له إيراد. اكتب السبب."
                requireReason tone="cost" confirmLabel="عدّيه مجاناً" onConfirm={(reason) => act("waive", reason, "الطلب اتعدّى مجاناً")}
                className="rounded-full bg-[#F8F1E7] text-[#8B5A2B] px-4 py-1.5 text-sm font-bold">
                تعدية مجانية
              </ConfirmAction>
            )}
            {payment?.status === "paid" && ["wallet", "card"].includes(payment.method) && (
              <ConfirmAction title={`ترجّع ${money(payment.total_sar)} لرصيد العميل؟`} description="المبلغ بيتضاف لرصيده في غِراس (مش للبطاقة). الإنتاج مش بيقف. اكتب السبب."
                requireReason confirmLabel="رجّع للرصيد" onConfirm={(reason) => act("refund", reason, "اترجع للرصيد")}
                className="rounded-full bg-[#FCE6D4] text-[#B8612F] px-4 py-1.5 text-sm font-bold">
                استرداد للرصيد
              </ConfirmAction>
            )}
          </div>
        </div>
      </div>

      <div className="rounded-2xl border border-[#E2D8C9] overflow-x-auto">
        <table className="w-full font-body text-sm">
          <thead className="bg-[#FDFBF7] border-b border-[#E2D8C9]">
            <tr>{["البند", "الكمية", "سعر الوحدة", "التكلفة", "الموديل"].map((h) => <th key={h} className="px-3 py-2 text-xs font-bold text-[#5A677D] text-right">{h}</th>)}</tr>
          </thead>
          <tbody className="divide-y divide-[#F0E9DD]">
            {actual.items.length === 0 && <tr><td colSpan={5} className="px-3 py-4 text-center text-[#8A9AB0]">لسه مفيش توليد</td></tr>}
            {actual.items.map((it, i) => (
              <tr key={i}>
                <td className="px-3 py-2 font-bold text-[#2D3748]">{it.label_ar}</td>
                <td className="px-3 py-2">{it.quantity} {it.unit}</td>
                <td className="px-3 py-2" dir="ltr" style={{ textAlign: "right" }}>{it.priced ? `$${it.unit_usd}` : "مش مسعّر"}</td>
                <td className="px-3 py-2 font-bold" dir="ltr" style={{ textAlign: "right" }}>${it.cost_usd}</td>
                <td className="px-3 py-2 text-xs text-[#8A9AB0]" dir="ltr" style={{ textAlign: "right" }}>{it.note || ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-[#8A9AB0] font-body">
        محسوبة من اللي اتولّد فعلاً (شامل إعادة الرسم) × سعر الموديل في الكتالوج. المحاولات اللي فشلت قبل ما تتسجّل مش محسوبة — الاحتياطي في التسعير بيغطيها.
        {actual.unpriced.length > 0 && ` موديلات من غير سعر في الكتالوج: ${actual.unpriced.join("، ")}.`}
      </p>
    </div>
  );
}
