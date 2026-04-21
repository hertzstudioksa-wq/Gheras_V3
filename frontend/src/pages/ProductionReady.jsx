import React, { useEffect, useRef, useState } from "react";
import { useNavigate, useParams, Link } from "react-router-dom";
import { api } from "../lib/api";
import Navbar from "../components/gheras/Navbar";
import Footer from "../components/gheras/Footer";
import {
  Sprout, Sparkles, CheckCircle2, Loader2, ArrowRight, Clock, BookOpen,
  Heart, RefreshCcw, ShieldAlert, AlertTriangle, Film, Award, Lightbulb,
  PartyPopper, Music, Mic, VolumeX, Download, Play,
} from "lucide-react";
import { fileSrc } from "../lib/api";
import { toast } from "sonner";

const audioBgLabel = (mode) => ({
  music: "موسيقى هادئة",
  human_rhythm: "إيقاع صوتي بشري",
  none: "من دون خلفية صوتية",
}[mode] || "موسيقى هادئة");

const audioBgIcon = (mode) => ({
  music: Music,
  human_rhythm: Mic,
  none: VolumeX,
}[mode] || Music);

export default function ProductionReady() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [state, setState] = useState(null);
  const [loading, setLoading] = useState(true);
  const [approving, setApproving] = useState(false);
  const [regenerating, setRegenerating] = useState(false);
  const [retrying, setRetrying] = useState(false);
  const pollRef = useRef(null);

  const errorShownRef = useRef(false);

  const fetchData = async (opts = {}) => {
    const { silent = false } = opts;
    try {
      const { data } = await api.get(`/orders/${id}/production-summary`);
      setState(data);
      setLoading(false);
      errorShownRef.current = false;
      // Poll while the pipeline is still active; stop on terminal delivered/failed.
      const stopStates = ["delivered", "failed", "completed"];
      if (stopStates.includes(data.status) && pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    } catch (e) {
      const status = e?.response?.status;
      // Only surface PERMANENT errors (not found, forbidden) — and only once.
      const isPermanent = status === 404 || status === 403 || status === 401;
      if (isPermanent && !silent && !errorShownRef.current) {
        toast.error(e?.response?.data?.detail || "تعذّر تحميل الخطة");
        errorShownRef.current = true;
      }
      // Transient errors (network/502/504): just let the polling retry silently.
      setLoading(false);
    }
  };

  useEffect(() => {
    // First call: surface errors (it's the initial load).
    fetchData();
    // Subsequent polls: silent so transient 502s/504s don't spam toasts.
    pollRef.current = setInterval(() => fetchData({ silent: true }), 3500);
    return () => pollRef.current && clearInterval(pollRef.current);
    // eslint-disable-next-line
  }, [id]);

  const approve = async () => {
    setApproving(true);
    try {
      await api.post(`/orders/${id}/production/approve`);
      toast.success("تم اعتماد الخطة 🌱");
      await fetchData();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "فشل الاعتماد");
    } finally {
      setApproving(false);
    }
  };

  const remaining = state?.production_regenerations_remaining ?? 0;
  const maxUser = state?.max_user_production_regenerations ?? 1;
  const used = state?.production_regeneration_count ?? 0;
  const limitReached = remaining <= 0;

  const status = state?.status;
  const isGeneratingMedia = status === "assets_generating";
  const isMediaReady = status === "assets_ready";
  const isMediaFailed = status === "media_failed";
  const isAssembling = status === "assembling";
  const isDelivered = status === "delivered";
  const isPlanning = ["pending", "ready_for_ai", "production_planning", "scenarios_generating",
                      "scenarios_ready", "scenario_selected"].includes(status);
  const isFailed = status === "failed";
  // Unified progress from backend (0..100 across the whole pipeline).
  const progress = state?.progress;
  const progressPercent = progress?.percent ?? 0;
  const progressStage = progress?.stage;
  const progressMessage = progress?.message_ar;
  const [delivery, setDelivery] = useState(null);

  useEffect(() => {
    let iv;
    if (isGeneratingMedia || isMediaReady || isMediaFailed || isAssembling || isDelivered) {
      const fetchMedia = async () => {
        try {
          const { data } = await api.get(`/orders/${id}/media-status`);
          setMediaProgress(data);
        } catch { /* ignore */ }
      };
      fetchMedia();
      iv = setInterval(fetchMedia, 4000);
    }
    return () => iv && clearInterval(iv);
    // eslint-disable-next-line
  }, [status, id]);

  useEffect(() => {
    let iv;
    if (isAssembling || isDelivered || isMediaFailed) {
      const fetchDelivery = async () => {
        try {
          const { data } = await api.get(`/orders/${id}/delivery`);
          setDelivery(data);
        } catch { /* ignore */ }
      };
      fetchDelivery();
      if (!isDelivered) iv = setInterval(fetchDelivery, 5000);
    }
    return () => iv && clearInterval(iv);
    // eslint-disable-next-line
  }, [status, id]);

  const regenerate = async () => {
    if (limitReached) {
      toast.error("لقد استخدمت محاولة إعادة التوليد المتاحة");
      return;
    }
    const ok = window.confirm(
      "هذه هي محاولتك الوحيدة لإعادة إعداد خطة الإنتاج. هل تريد المتابعة؟"
    );
    if (!ok) return;
    setRegenerating(true);
    try {
      await api.post(`/orders/${id}/production/regenerate`);
      setState((s) => ({ ...s, status: "production_planning" }));
      if (!pollRef.current) pollRef.current = setInterval(() => fetchData({ silent: true }), 3500);
      toast.success("جاري إعداد خطة جديدة...");
    } catch (e) {
      toast.error(e?.response?.data?.detail || "فشل");
    } finally {
      setRegenerating(false);
    }
  };

  // User-initiated retry when media failed (calls admin-like re-assembly through regular flow).
  const retryDelivery = async () => {
    setRetrying(true);
    try {
      // Ask backend to retry the pipeline — will resume from current state.
      await api.post(`/orders/${id}/retry-delivery`);
      toast.success("سنُعيد المحاولة الآن...");
      await fetchData();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "تعذّرت إعادة المحاولة");
    } finally {
      setRetrying(false);
    }
  };

  if (loading && !state) {
    return (
      <div className="min-h-screen bg-[#FDFBF7]" data-testid="production-ready">
        <Navbar />
        <div className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 py-10 md:py-14">
          <div className="bg-gradient-to-br from-[#E8F0E1] via-[#F8F1E7] to-[#FDFBF7] rounded-[2rem] p-6 md:p-10 border border-[#E2D8C9] mb-6">
            <div className="inline-flex items-center gap-2 bg-white rounded-full px-3 py-1 text-xs font-bold text-[#729352] mb-3">
              <Sparkles className="w-3 h-3" /> الخطوة 8 من 8
            </div>
            <h1 className="font-heading text-3xl md:text-4xl font-bold text-[#2D3748] mb-2">
              نُعِدّ خطة القصة لطفلك...
            </h1>
            <p className="font-body text-[#5A677D] max-w-xl">
              نُحوّل السيناريو إلى خطة كاملة: مشاهد، نصوص، وتوجيهات فنية.
            </p>
            <div className="mt-5 bg-white/70 backdrop-blur rounded-2xl p-4 border border-[#E2D8C9]" data-testid="hero-progress-indeterminate">
              <div className="flex items-center justify-between mb-2 text-xs font-body text-[#5A677D]">
                <span className="inline-flex items-center gap-2">
                  <Loader2 className="w-3.5 h-3.5 animate-spin text-[#87A96B]" />
                  إعداد خطة القصة
                </span>
                <span className="font-bold text-[#2D3748]">بدء...</span>
              </div>
              <div className="w-full bg-[#F2E8DA] rounded-full h-3 overflow-hidden relative">
                <div className="absolute inset-y-0 w-1/3 bg-gradient-to-r from-[#87A96B] to-[#4F6B3B] rounded-full animate-[shimmer_1.4s_ease-in-out_infinite]"
                     style={{ animation: "gheras-shimmer 1.4s ease-in-out infinite" }} />
              </div>
            </div>
          </div>
          <LoadingSkeleton />
        </div>
        <style>{`
          @keyframes gheras-shimmer {
            0%   { left: -33%; }
            100% { left: 100%; }
          }
        `}</style>
        <Footer />
      </div>
    );
  }

  const summary = state?.summary;
  const approved = !!state?.production_approved;

  return (
    <div className="min-h-screen bg-[#FDFBF7] pb-24 md:pb-0" data-testid="production-ready">
      <Navbar />

      <div className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 py-8 md:py-14">
        <Link
          to="/dashboard"
          className="inline-flex items-center gap-2 text-[#5A677D] hover:text-[#2D3748] mb-6 font-body"
          data-testid="back-link"
        >
          <ArrowRight className="w-4 h-4" /> العودة إلى قصصي
        </Link>

        {/* HERO */}
        <div className="bg-gradient-to-br from-[#E8F0E1] via-[#F8F1E7] to-[#FDFBF7] rounded-[2rem] p-6 md:p-10 border border-[#E2D8C9] mb-6 relative overflow-hidden">
          <div className="absolute -top-10 -right-10 w-40 h-40 bg-[#87A96B]/10 blob-shape" />
          <div className="absolute -bottom-10 -left-10 w-40 h-40 bg-[#D4A373]/15 blob-shape" />
          <div className="relative">
            <div className="inline-flex items-center gap-2 bg-white rounded-full px-3 py-1 text-xs font-bold text-[#729352] mb-3">
              <Sparkles className="w-3 h-3" /> الخطوة 8 من 8
            </div>
            <h1 className="font-heading text-3xl md:text-4xl font-bold text-[#2D3748] mb-2">
              {isDelivered
                ? "قصتك أصبحت جاهزة 🌱"
                : isAssembling
                ? "جاري تجميع قصة طفلك..."
                : isMediaReady
                ? "وسائط قصتك جاهزة"
                : isGeneratingMedia
                ? "جاري إعداد قصة طفلك..."
                : isMediaFailed
                ? "تعذّر إعداد بعض الوسائط"
                : approved
                ? "شكراً لك! تم اعتماد الخطة 🌱"
                : isFailed
                ? "تعذّر إعداد الخطة"
                : isPlanning
                ? "نُعِدّ خطة القصة لطفلك..."
                : "الخطة جاهزة لاعتمادك"}
            </h1>
            <p className="font-body text-[#5A677D] max-w-xl">
              {isDelivered
                ? "يمكنك الآن مشاهدة الفيديو وتحميل القصة المصوّرة."
                : isAssembling
                ? "نجمع الصور والسرد في فيديو وكتاب نهائيين."
                : isMediaReady
                ? "تم إعداد جميع الصور. جاري الآن التجميع النهائي."
                : isGeneratingMedia
                ? "نُنتج الصور والسرد الصوتي لكل مشهد. هذا يستغرق دقائق قليلة."
                : isMediaFailed
                ? "لم تكتمل بعض الوسائط. فريقنا سيُراجع الطلب."
                : approved
                ? "سنبدأ إعداد قصة طفلك قريباً وسنُعلمك فور جاهزيتها."
                : isFailed
                ? "حدث خلل بسيط أثناء إعداد الخطة. يمكنك إعادة المحاولة."
                : isPlanning
                ? "نُحوّل السيناريو إلى خطة كاملة: مشاهد، نصوص، وتوجيهات فنية."
                : "اطلع على ملخص الخطة، ثم اعتمدها لنبدأ إعداد قصة طفلك."}
            </p>

            {/* Unified pipeline progress bar — always visible from planning to delivery */}
            {progress && !isDelivered && !isFailed && !isMediaFailed && (
              <div className="mt-5 bg-white/70 backdrop-blur rounded-2xl p-4 border border-[#E2D8C9]" data-testid="hero-progress">
                <div className="flex items-center justify-between mb-2 text-xs font-body text-[#5A677D]">
                  <span className="inline-flex items-center gap-2">
                    <Loader2 className="w-3.5 h-3.5 animate-spin text-[#87A96B]" />
                    {progressMessage || progress.stage_ar}
                  </span>
                  <span className="font-bold text-[#2D3748]" data-testid="hero-progress-percent">
                    {progressPercent}%
                  </span>
                </div>
                <div className="w-full bg-[#F2E8DA] rounded-full h-3 overflow-hidden">
                  <div
                    className="h-full bg-gradient-to-r from-[#87A96B] to-[#4F6B3B] rounded-full transition-all duration-700"
                    style={{ width: `${Math.max(progressPercent, 3)}%` }}
                  />
                </div>
                <StagePill stage={progressStage} />
              </div>
            )}
          </div>
        </div>

        {/* PLANNING STATE */}
        {isPlanning && !summary && (
          <LoadingSkeleton message={progressMessage} />
        )}

        {/* FAILED STATE */}
        {isFailed && !approved && (
          <div className="bg-white rounded-3xl p-8 border border-[#E2D8C9] text-center" data-testid="failed-state">
            <div className="w-20 h-20 rounded-3xl bg-[#FCE6D4] grid place-content-center mx-auto mb-4">
              <AlertTriangle className="w-10 h-10 text-[#B8612F]" />
            </div>
            <h2 className="font-heading text-xl font-bold text-[#2D3748] mb-2">نحتاج إعادة المحاولة</h2>
            <p className="font-body text-[#5A677D] mb-5">
              لم نتمكن من إعداد الخطة هذه المرة. اضغط "إعادة المحاولة" لنجرّب مرة أخرى.
            </p>
            <button
              onClick={regenerate}
              disabled={regenerating || limitReached}
              className="btn-primary inline-flex items-center gap-2 disabled:opacity-50"
              data-testid="retry-btn"
            >
              <RefreshCcw className="w-4 h-4" />
              {limitReached ? "استُهلكت المحاولة" : "إعادة المحاولة"}
            </button>
          </div>
        )}

        {/* DELIVERED STATE — final outputs */}
        {isDelivered && delivery && (
          <div className="space-y-5" data-testid="delivered-state">
            {/* Video player */}
            {delivery.video?.video_url && (
              <div className="bg-white rounded-[2rem] p-5 md:p-6 border-2 border-[#87A96B] overflow-hidden" data-testid="final-video-card">
                <div className="flex items-center gap-3 mb-4">
                  <div className="w-12 h-12 rounded-2xl bg-[#E8F0E1] grid place-content-center">
                    <Film className="w-6 h-6 text-[#4F6B3B]" />
                  </div>
                  <div>
                    <h2 className="font-heading text-xl font-bold text-[#2D3748]">فيديو القصة</h2>
                    <p className="font-body text-xs text-[#5A677D]">
                      {Math.round(delivery.video.duration_seconds || 0)}ث •{" "}
                      {audioBgLabel(delivery.video.audio_background_mode)}
                    </p>
                  </div>
                </div>
                <div className="rounded-2xl overflow-hidden bg-black">
                  <video
                    controls
                    className="w-full aspect-video"
                    poster={delivery.video.thumbnail_url ? fileSrc(delivery.video.thumbnail_url) : undefined}
                    src={fileSrc(delivery.video.video_url)}
                    data-testid="final-video-player"
                  >
                    متصفحك لا يدعم تشغيل الفيديو.
                  </video>
                </div>
                <a
                  href={fileSrc(delivery.video.video_url)}
                  download
                  className="mt-3 inline-flex items-center gap-2 rounded-full bg-[#E8F0E1] text-[#4F6B3B] px-4 py-2 text-sm font-bold hover:bg-[#D4E3C1]"
                  data-testid="video-download-btn"
                >
                  <Download className="w-4 h-4" /> تحميل الفيديو
                </a>
              </div>
            )}

            {/* PDF download */}
            {delivery.pdf?.pdf_url && (
              <div className="bg-white rounded-[2rem] p-5 md:p-6 border-2 border-[#D4A373]" data-testid="final-pdf-card">
                <div className="flex items-center gap-3 mb-3">
                  <div className="w-12 h-12 rounded-2xl bg-[#F8F1E7] grid place-content-center">
                    <BookOpen className="w-6 h-6 text-[#8B5A2B]" />
                  </div>
                  <div>
                    <h2 className="font-heading text-xl font-bold text-[#2D3748]">القصة المصوّرة (PDF)</h2>
                    <p className="font-body text-xs text-[#5A677D]">
                      {delivery.pdf.page_count} صفحات • ملائم للقراءة مع طفلك
                    </p>
                  </div>
                </div>
                <a
                  href={fileSrc(delivery.pdf.pdf_url)}
                  download
                  className="btn-primary inline-flex items-center gap-2 w-full md:w-auto justify-center"
                  data-testid="pdf-download-btn"
                >
                  <Download className="w-4 h-4" /> تحميل القصة المصوّرة
                </a>
              </div>
            )}

            {/* WhatsApp share */}
            <WhatsAppShareCard />

            {/* Completion card */}
            <div className="bg-gradient-to-br from-[#E8F0E1] via-[#F8F1E7] to-[#FDFBF7] rounded-[2rem] p-6 border border-[#87A96B]/40 text-center">
              <PartyPopper className="w-10 h-10 text-[#4F6B3B] mx-auto mb-2" />
              <h3 className="font-heading text-xl font-bold text-[#2D3748] mb-1">
                {delivery.plan?.title || "قصة طفلك"}
              </h3>
              <p className="font-body text-sm text-[#5A677D]">
                نتمنى أن تترك القصة أثراً جميلاً في قلب طفلك 🌱
              </p>
            </div>
          </div>
        )}

        {/* MEDIA GENERATING / READY / FAILED / ASSEMBLING */}
        {(isGeneratingMedia || isMediaReady || isMediaFailed || isAssembling) && !isDelivered && (
          <div className="bg-white rounded-[2rem] p-6 md:p-8 border-2 border-[#87A96B] mb-5" data-testid="media-progress-card">
            <div className="flex items-center gap-3 mb-4">
              <div className={`w-12 h-12 rounded-2xl grid place-content-center ${isMediaReady ? "bg-[#E8F0E1]" : isMediaFailed ? "bg-[#FCE6D4]" : "bg-[#F8F1E7]"}`}>
                {isMediaReady ? <CheckCircle2 className="w-6 h-6 text-[#4F6B3B]" /> :
                 isMediaFailed ? <AlertTriangle className="w-6 h-6 text-[#B8612F]" /> :
                 <Loader2 className="w-6 h-6 text-[#8B5A2B] animate-spin" />}
              </div>
              <div>
                <h2 className="font-heading text-xl font-bold text-[#2D3748]">
                  {isAssembling ? "جاري التجميع النهائي" :
                   isMediaReady ? "الوسائط جاهزة" :
                   isMediaFailed ? "تعذّر إكمال الوسائط" :
                   "جاري إنتاج الوسائط"}
                </h2>
                <p className="font-body text-xs text-[#5A677D]" data-testid="progress-stage-label">
                  {progressMessage || (isAssembling ? "ندمج الصور والسرد في فيديو وكتاب..." :
                   isMediaReady ? "بانتظار خطوة التجميع النهائية" :
                   isMediaFailed ? "يُراجع فريقنا الطلب وسنُعيد المحاولة" :
                   "جاري إنتاج الوسائط...")}
                </p>
              </div>
            </div>
            {!isMediaFailed && (
              <p className="font-body text-sm text-[#5A677D]" data-testid="media-hint">
                {isAssembling ? "قد يستغرق هذا دقيقة إلى دقيقتين. يمكنك تصفح بقية التطبيق والعودة لاحقاً." :
                 isMediaReady ? "تمت هذه الخطوة. جارٍ تحضير الفيديو والكتاب..." :
                 "تصفح بقية التطبيق — سنحدّث هذه الصفحة تلقائياً حال الانتهاء."}
              </p>
            )}
            {isMediaFailed && (
              <div className="flex items-center gap-3 mt-3 flex-wrap">
                <button
                  type="button"
                  onClick={retryDelivery}
                  disabled={retrying}
                  className="inline-flex items-center gap-2 rounded-full bg-[#E8F0E1] text-[#4F6B3B] px-5 py-2.5 text-sm font-bold disabled:opacity-50"
                  data-testid="retry-delivery-btn"
                >
                  {retrying ? <Loader2 className="w-4 h-4 animate-spin" /> : <RefreshCcw className="w-4 h-4" />}
                  إعادة المحاولة
                </button>
                <span className="text-xs text-[#8A9AB0] font-body">
                  لا تحتاج إلى إعادة إنشاء أي شيء — سنواصل من حيث توقفنا.
                </span>
              </div>
            )}
          </div>
        )}

        {/* APPROVED (SUCCESS) STATE — only when NOT yet in media flow */}
        {approved && !isGeneratingMedia && !isMediaReady && !isMediaFailed && !isAssembling && !isDelivered && summary && (
          <div className="bg-white rounded-[2rem] p-6 md:p-8 border-2 border-[#87A96B] mb-6 relative overflow-hidden" data-testid="approved-state">
            <div className="flex items-center gap-3 mb-4">
              <div className="w-12 h-12 rounded-2xl bg-[#E8F0E1] grid place-content-center">
                <PartyPopper className="w-6 h-6 text-[#4F6B3B]" />
              </div>
              <div>
                <h2 className="font-heading text-xl font-bold text-[#2D3748]">الخطة معتمدة</h2>
                <p className="font-body text-xs text-[#5A677D]">
                  تم الاعتماد في {new Date(state.production_approved_at).toLocaleString("ar-EG")}
                </p>
              </div>
            </div>
            <div className="bg-[#FDFBF7] rounded-2xl p-4 border border-[#E2D8C9] mb-4">
              <h3 className="font-heading text-lg font-bold text-[#2D3748] mb-2">{summary.title}</h3>
              <p className="font-body text-sm text-[#5A677D]">{summary.story_summary}</p>
            </div>
            <div className="bg-gradient-to-br from-[#F8F1E7] to-[#E8F0E1] rounded-2xl p-4 border border-[#D4A373]/30">
              <div className="flex items-center gap-2 mb-1 text-[#8B5A2B] font-body font-bold text-sm">
                <Sprout className="w-4 h-4" /> الخطوة التالية
              </div>
              <p className="font-body text-sm text-[#2D3748]">
                سنبدأ إعداد قصة طفلك قريباً — الصور، الفيديو، والكتاب. سنُرسل لك إشعاراً فور جاهزيتها.
              </p>
            </div>
          </div>
        )}

        {/* READY — SUMMARY + ACTIONS */}
        {!approved && !isFailed && summary && status === "production_ready" && (
          <>
            {/* Summary card */}
            <div className="bg-white rounded-[2rem] p-6 md:p-8 border border-[#E2D8C9] mb-5" data-testid="summary-card">
              <div className="flex items-center gap-2 mb-3 text-[#729352] font-body text-sm font-bold">
                <BookOpen className="w-4 h-4" /> ملخص القصة
              </div>
              <h2 className="font-heading text-2xl md:text-3xl font-bold text-[#2D3748] mb-3 leading-tight" data-testid="plan-title">
                {summary.title}
              </h2>
              <p className="font-body text-[#5A677D] leading-relaxed whitespace-pre-wrap mb-5" data-testid="plan-summary">
                {summary.story_summary}
              </p>
              <div className="bg-[#E8F0E1]/60 rounded-2xl p-4 border border-[#87A96B]/20 flex items-start gap-3">
                <Lightbulb className="w-5 h-5 text-[#4F6B3B] shrink-0 mt-0.5" />
                <div>
                  <div className="text-xs font-bold text-[#4F6B3B] mb-1">الرسالة التربوية</div>
                  <p className="font-body text-[#2D3748]" data-testid="plan-message">{summary.main_message}</p>
                </div>
              </div>
            </div>

            {/* Details card */}
            <div className="bg-white rounded-[2rem] p-6 md:p-8 border border-[#E2D8C9] mb-5" data-testid="details-card">
              <div className="flex items-center gap-2 mb-4 text-[#729352] font-body text-sm font-bold">
                <Film className="w-4 h-4" /> تفاصيل القصة
              </div>
              <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
                <Detail
                  icon={Clock}
                  label="مدة الفيديو"
                  value={summary.duration_label}
                  testId="detail-duration"
                />
                <Detail
                  icon={Sparkles}
                  label="عدد المشاهد"
                  value={`${summary.target_scene_count} مشاهد`}
                  testId="detail-scenes"
                />
                <Detail
                  icon={Heart}
                  label="عناصر بصرية"
                  value={`${summary.estimated_image_count} صورة`}
                  testId="detail-images"
                />
                <Detail
                  icon={audioBgIcon(summary.audio_background?.mode)}
                  label="الخلفية الصوتية"
                  value={audioBgLabel(summary.audio_background?.mode)}
                  testId="detail-audio-bg"
                />
              </div>
              <div className="mt-4 text-xs font-body text-[#8A9AB0] inline-flex items-center gap-2 bg-[#FDFBF7] rounded-full px-3 py-1.5 border border-[#E2D8C9]">
                <Award className="w-3 h-3 text-[#729352]" />
                تم التحقق من مناسبة المحتوى لطفلك ({summary.safety_check === "ok" ? "آمن" : "قيد المراجعة"})
              </div>
            </div>

            {/* Regen warning banner */}
            {remaining === 1 && (
              <div className="mb-4 rounded-2xl bg-[#F8F1E7] border border-[#D4A373]/40 p-4 flex items-start gap-3" data-testid="regen-available-warning">
                <ShieldAlert className="w-5 h-5 text-[#8B5A2B] shrink-0 mt-0.5" />
                <p className="font-body text-sm text-[#8B5A2B]">
                  <b>ملاحظة:</b> لديك محاولة واحدة لإعادة إعداد الخطة إذا لم تكن مناسبة.
                </p>
              </div>
            )}
            {limitReached && (
              <div className="mb-4 rounded-2xl bg-[#FCE6D4] border border-[#E07A5F]/40 p-4 flex items-start gap-3" data-testid="regen-limit-reached">
                <AlertTriangle className="w-5 h-5 text-[#B8612F] shrink-0 mt-0.5" />
                <p className="font-body text-sm text-[#B8612F]">
                  لقد استخدمت محاولة إعادة التوليد. يمكنك اعتماد الخطة أو التواصل معنا للمساعدة.
                </p>
              </div>
            )}

            {/* Action section (desktop) */}
            <div className="hidden md:flex items-center justify-between gap-4 bg-white rounded-[2rem] p-5 border-2 border-[#87A96B] shadow-sm" data-testid="actions-card">
              <div>
                <div className="font-heading font-bold text-[#2D3748]">جاهز للاعتماد؟</div>
                <p className="font-body text-xs text-[#5A677D]">
                  بعد اعتمادك سنبدأ بإعداد قصة طفلك.
                </p>
              </div>
              <div className="flex items-center gap-3">
                <button
                  type="button"
                  onClick={regenerate}
                  disabled={limitReached || regenerating || approving}
                  title={limitReached ? "تم استهلاك محاولة إعادة التوليد" : "إعداد خطة بديلة"}
                  className="inline-flex items-center gap-2 rounded-full bg-[#F8F1E7] hover:bg-[#F2E8DA] text-[#8B5A2B] px-5 py-3 text-sm font-bold disabled:opacity-50 disabled:cursor-not-allowed"
                  data-testid="regenerate-plan-btn"
                >
                  <RefreshCcw className="w-4 h-4" />
                  {regenerating ? "جاري..." : "إعادة إعداد الخطة"}
                  <span className="text-[11px] text-[#A67C52] font-normal">
                    ({used}/{maxUser})
                  </span>
                </button>
                <button
                  type="button"
                  onClick={approve}
                  disabled={approving || regenerating}
                  className="btn-primary inline-flex items-center gap-2 disabled:opacity-70"
                  data-testid="approve-plan-btn"
                >
                  {approving ? <Loader2 className="w-4 h-4 animate-spin" /> : <CheckCircle2 className="w-4 h-4" />}
                  موافق على الخطة
                </button>
              </div>
            </div>
          </>
        )}
      </div>

      {/* Sticky mobile action bar (only on ready state) */}
      {!approved && !isFailed && summary && status === "production_ready" && (
        <div
          className="md:hidden fixed bottom-0 inset-x-0 bg-white/95 backdrop-blur border-t border-[#E2D8C9] p-3 flex items-center gap-2 z-30"
          data-testid="mobile-actions"
        >
          <button
            type="button"
            onClick={regenerate}
            disabled={limitReached || regenerating || approving}
            className="flex-1 rounded-full bg-[#F8F1E7] text-[#8B5A2B] py-3 px-3 text-sm font-bold disabled:opacity-50 inline-flex items-center justify-center gap-1"
          >
            <RefreshCcw className="w-4 h-4" />
            إعادة ({used}/{maxUser})
          </button>
          <button
            type="button"
            onClick={approve}
            disabled={approving || regenerating}
            className="flex-[2] btn-primary inline-flex items-center justify-center gap-2 disabled:opacity-70"
          >
            {approving ? <Loader2 className="w-4 h-4 animate-spin" /> : <CheckCircle2 className="w-4 h-4" />}
            موافق على الخطة
          </button>
        </div>
      )}

      <Footer />
    </div>
  );
}

function Detail({ icon: Icon, label, value, testId }) {
  return (
    <div className="bg-[#FDFBF7] rounded-2xl p-4 border border-[#E2D8C9]" data-testid={testId}>
      <div className="inline-flex items-center gap-2 text-xs text-[#729352] font-body mb-1">
        <Icon className="w-3 h-3" /> {label}
      </div>
      <div className="font-heading font-bold text-[#2D3748]">{value || "—"}</div>
    </div>
  );
}

function StagePill({ stage }) {
  const stages = [
    { key: "plan", label: "الخطة" },
    { key: "assets", label: "الوسائط" },
    { key: "assembly", label: "التجميع" },
    { key: "delivered", label: "جاهز" },
  ];
  const order = ["plan", "assets", "assembly", "delivered"];
  const idx = Math.max(0, order.indexOf(stage));
  return (
    <div className="flex items-center justify-between mt-3 text-[11px] font-body" data-testid="stage-pills">
      {stages.map((s, i) => (
        <div
          key={s.key}
          className={`flex-1 text-center ${i <= idx ? "text-[#4F6B3B] font-bold" : "text-[#8A9AB0]"}`}
        >
          <div
            className={`mx-auto w-2 h-2 rounded-full mb-1 ${
              i < idx ? "bg-[#4F6B3B]" :
              i === idx ? "bg-[#87A96B] ring-2 ring-[#87A96B]/30 animate-pulse" :
              "bg-[#E2D8C9]"
            }`}
          />
          {s.label}
        </div>
      ))}
    </div>
  );
}

function WhatsAppShareCard() {
  const handleShare = () => {
    const landingUrl = window.location.origin + "/";
    const message =
      "شوفوا القصة الجميلة دي ✨\n" +
      "طفلي بقى بطل حكاية خاصة بيه 😍\n" +
      "جربوا تعملوا قصة لأطفالكم من هنا:\n" +
      landingUrl;
    const url = `https://wa.me/?text=${encodeURIComponent(message)}`;
    window.open(url, "_blank", "noopener,noreferrer");
  };
  return (
    <div
      className="bg-white rounded-[2rem] p-5 md:p-6 border-2 border-[#25D366]/40"
      data-testid="whatsapp-share-card"
    >
      <div className="flex items-center gap-3 mb-3">
        <div className="w-12 h-12 rounded-2xl bg-[#25D366]/10 grid place-content-center">
          <svg className="w-6 h-6 text-[#25D366]" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
            <path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51l-.57-.01c-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.095 3.2 5.076 4.487.709.306 1.263.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347m-5.421 7.403h-.004a9.87 9.87 0 01-5.031-1.378l-.361-.214-3.741.982.998-3.648-.235-.374a9.86 9.86 0 01-1.51-5.26c.001-5.45 4.436-9.884 9.888-9.884 2.64 0 5.122 1.03 6.988 2.898a9.825 9.825 0 012.893 6.994c-.003 5.45-4.437 9.884-9.885 9.884m8.413-18.297A11.815 11.815 0 0012.05 0C5.495 0 .16 5.335.157 11.892c0 2.096.547 4.142 1.588 5.945L.057 24l6.305-1.654a11.882 11.882 0 005.683 1.448h.005c6.554 0 11.89-5.335 11.893-11.893a11.821 11.821 0 00-3.48-8.413Z"/>
          </svg>
        </div>
        <div>
          <h2 className="font-heading text-xl font-bold text-[#2D3748]">شارك القصة مع العائلة</h2>
          <p className="font-body text-xs text-[#5A677D]">
            ادعُ أقاربك وأصدقاءك لإنشاء قصة خاصة بأطفالهم
          </p>
        </div>
      </div>
      <button
        type="button"
        onClick={handleShare}
        className="inline-flex items-center justify-center gap-2 w-full md:w-auto rounded-full bg-[#25D366] hover:bg-[#1EBE57] text-white px-6 py-3 text-sm font-bold transition-colors"
        data-testid="whatsapp-share-btn"
      >
        <svg className="w-4 h-4" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
          <path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51l-.57-.01c-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.095 3.2 5.076 4.487.709.306 1.263.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347m-5.421 7.403h-.004a9.87 9.87 0 01-5.031-1.378l-.361-.214-3.741.982.998-3.648-.235-.374a9.86 9.86 0 01-1.51-5.26c.001-5.45 4.436-9.884 9.888-9.884 2.64 0 5.122 1.03 6.988 2.898a9.825 9.825 0 012.893 6.994c-.003 5.45-4.437 9.884-9.885 9.884m8.413-18.297A11.815 11.815 0 0012.05 0C5.495 0 .16 5.335.157 11.892c0 2.096.547 4.142 1.588 5.945L.057 24l6.305-1.654a11.882 11.882 0 005.683 1.448h.005c6.554 0 11.89-5.335 11.893-11.893a11.821 11.821 0 00-3.48-8.413Z"/>
        </svg>
        مشاركة عبر واتساب
      </button>
    </div>
  );
}

function LoadingSkeleton({ message }) {
  return (
    <div className="space-y-4" data-testid="loading-skeleton">
      <div className="bg-white rounded-3xl p-6 border border-[#E2D8C9]">
        <div className="h-4 w-32 bg-[#F2E8DA] rounded animate-pulse mb-3" />
        <div className="h-6 w-3/4 bg-[#E2D8C9] rounded animate-pulse mb-3" />
        <div className="space-y-2">
          <div className="h-3 w-full bg-[#F2E8DA] rounded animate-pulse" />
          <div className="h-3 w-full bg-[#F2E8DA] rounded animate-pulse" />
          <div className="h-3 w-2/3 bg-[#F2E8DA] rounded animate-pulse" />
        </div>
      </div>
      <div className="grid grid-cols-3 gap-3">
        {[1, 2, 3].map((i) => (
          <div key={i} className="h-20 bg-[#FDFBF7] rounded-2xl animate-pulse border border-[#E2D8C9]" />
        ))}
      </div>
      <div className="text-center text-[#5A677D] font-body text-sm inline-flex items-center gap-2 bg-white rounded-full px-4 py-2 border border-[#E2D8C9] mx-auto">
        <Loader2 className="w-4 h-4 animate-spin text-[#87A96B]" />
        {message || "جاري إعداد الخطة..."}
      </div>
    </div>
  );
}
