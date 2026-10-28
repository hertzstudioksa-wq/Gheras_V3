import React, { useEffect, useRef, useState } from "react";
import { useNavigate, useParams, Link, useSearchParams } from "react-router-dom";
import { api } from "../lib/api";
import Navbar from "../components/gheras/Navbar";
import Footer from "../components/gheras/Footer";
import {
  Sprout, Sparkles, CheckCircle2, Loader2, ArrowRight, Clock, BookOpen,
  Heart, RefreshCcw, ShieldAlert, AlertTriangle, Film, Award, Lightbulb,
  PartyPopper, Music, Mic, VolumeX, Download, Play,
} from "lucide-react";
import { fileSrc } from "../lib/api";
import OrderPayment from "../components/gheras/OrderPayment";
import FamilyShareCard from "../components/gheras/FamilyShareCard";
import {
  NotifyWhenReady, PreviewStrip, StepList, TimeChips, notifyReady, useLiveNumbers,
} from "../components/gheras/LiveProgress";
import { toast } from "sonner";
import JourneySteps from "../components/gheras/JourneySteps";
import StoryFeedbackCard from "../components/gheras/StoryFeedbackCard";
import PlanScriptCard from "../components/gheras/PlanScriptCard";
import PictureReview from "../components/gheras/PictureReview";
import { scenesLabel, imagesLabel, pagesLabel, countLabel } from "../lib/arabic";

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

// Privacy promise (CS-7): original photos go 30 days after delivery, or now.
function PhotoPrivacyCard({ orderId, deletedAt, onDeleted }) {
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const remove = async () => {
    setBusy(true);
    try {
      await api.post(`/orders/${orderId}/photos/delete`);
      toast.success("حُذفت الصور الأصلية — القصة والرسومات كما هي");
      onDeleted?.();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "تعذّر الحذف");
    } finally {
      setBusy(false);
      setConfirm(false);
    }
  };
  return (
    <div className="bg-white rounded-3xl p-5 border border-[#E2D8C9] font-body text-sm text-[#5A677D] flex items-center gap-3 flex-wrap justify-between" data-testid="photo-privacy-card">
      <span>
        {deletedAt
          ? "🔒 حُذفت الصور الأصلية التي رفعتها. القصة والرسومات محفوظة في حسابك."
          : "🔒 تُحذف الصور الأصلية التي رفعتها تلقائياً بعد 30 يوماً من التسليم."}
      </span>
      {!deletedAt && (confirm ? (
        <span className="flex gap-2">
          <button onClick={remove} disabled={busy} className="rounded-full bg-[#B8612F] text-white px-4 py-1.5 font-bold disabled:opacity-50">
            {busy ? "جارٍ الحذف..." : "تأكيد الحذف"}
          </button>
          <button onClick={() => setConfirm(false)} className="rounded-full bg-[#F8F1E7] text-[#8B5A2B] px-4 py-1.5 font-bold">إلغاء</button>
        </span>
      ) : (
        <button onClick={() => setConfirm(true)} className="rounded-full bg-[#FCE6D4] text-[#B8612F] px-4 py-1.5 font-bold" data-testid="delete-photos-btn">
          احذفها الآن
        </button>
      ))}
    </div>
  );
}

export default function ProductionReady() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [state, setState] = useState(null);
  const [loading, setLoading] = useState(true);
  const [approving, setApproving] = useState(false);
  const [regenerating, setRegenerating] = useState(false);
  const [retrying, setRetrying] = useState(false);
  const pollRef = useRef(null);

  const errorShownRef = useRef(false);
  const prevStatusRef = useRef(null);
  const lastUpdateRef = useRef(Date.now());
  const startRef = useRef(Date.now());
  const [stuckHint, setStuckHint] = useState(false);
  const [loadError, setLoadError] = useState(null);  // persistent error for render
  // Consecutive-failure tracking so a single 502/timeout doesn't flash the
  // "connection error" card. Only surface the error UI after N failures in a row.
  const consecutiveFailuresRef = useRef(0);
  const INITIAL_FAILURE_THRESHOLD = 3;   // attempts before showing error during initial load
  const backoffTimersRef = useRef([]);

  const fetchData = async (opts = {}) => {
    const { silent = false } = opts;
    // eslint-disable-next-line no-console
    console.debug("[prod-ready] fetch:start silent=", silent, "consecutive_failures=", consecutiveFailuresRef.current);
    try {
      const { data } = await api.get(`/orders/${id}/production-summary`);
      // eslint-disable-next-line no-console
      console.debug("[prod-ready] fetch:success status=", data.status, "summary_present=", !!data.summary, "progress=", data.progress?.percent);
      setState(data);
      setLoading(false);
      setLoadError(null);
      consecutiveFailuresRef.current = 0;
      lastUpdateRef.current = Date.now();
      errorShownRef.current = false;
      // Poll while the pipeline is still active; stop on terminal delivered/failed.
      if (data.status === "delivered" && prevStatusRef.current && prevStatusRef.current !== "delivered") {
        notifyReady(data.summary?.child_name);
      }
      prevStatusRef.current = data.status;
      // A story paused by our engine keeps polling: it resumes on its own.
      const stopStates = ["delivered", "failed", "completed"];
      if (stopStates.includes(data.status) && !data.progress?.paused && pollRef.current) {
        // eslint-disable-next-line no-console
        console.debug("[prod-ready] poll:stopped reason=terminal-", data.status);
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    } catch (e) {
      const status = e?.response?.status;
      const isNetworkLike = !e?.response; // true for timeouts, ERR_NETWORK, 502/504 at ingress
      consecutiveFailuresRef.current += 1;
      // eslint-disable-next-line no-console
      console.debug(
        "[prod-ready] fetch:failure status=", status,
        "code=", e?.code, "network=", isNetworkLike,
        "consecutive=", consecutiveFailuresRef.current,
      );
      // Truly permanent client-side errors → show error immediately.
      // 401 is permanent only when NOT network-like (interceptor already handles real auth failure).
      const isPermanent = status === 404 || status === 403 || (status === 401 && !isNetworkLike);
      if (isPermanent) {
        setLoadError({ permanent: true, status, detail: e?.response?.data?.detail });
        if (!silent && !errorShownRef.current) {
          toast.error(e?.response?.data?.detail || "تعذّر تحميل الخطة");
          errorShownRef.current = true;
        }
        setLoading(false);
      } else if (!state) {
        // Transient failure during INITIAL load — keep the loading skeleton
        // visible and silently retry. Only flip to the "connection error" UI
        // after N consecutive failures.
        if (consecutiveFailuresRef.current >= INITIAL_FAILURE_THRESHOLD) {
          setLoadError({ permanent: false, status, detail: e?.response?.data?.detail });
          setLoading(false);
        } else {
          // eslint-disable-next-line no-console
          console.debug(
            "[prod-ready] transient — staying in loading state; retries left before showing error:",
            INITIAL_FAILURE_THRESHOLD - consecutiveFailuresRef.current,
          );
          // Keep loading=true so the skeleton stays visible.
        }
      }
      // else: we already have state → the page keeps rendering; next poll retries.
    }
  };

  useEffect(() => {
    // eslint-disable-next-line no-console
    console.debug("[prod-ready] mount order_id=", id);
    // Back from the Moyasar page: confirm the payment with the server first.
    if (searchParams.get("payment")) {
      api.post(`/orders/${id}/payment/refresh`).catch(() => {}).finally(() => {
        setSearchParams({}, { replace: true });
        fetchData({ silent: true });
      });
    }
    fetchData();
    // Quick backoff retries (1s, 3s) for the initial load — shortens the
    // "connection error" window if the very first request hiccups.
    backoffTimersRef.current = [1000, 3000].map((ms) =>
      setTimeout(() => {
        // Only retry if we still don't have state AND no permanent error.
        // State is read via closure — a successful first fetch will have
        // already cleared loading; the retry is effectively a no-op after that.
        fetchData({ silent: true });
      }, ms),
    );
    // eslint-disable-next-line no-console
    console.debug("[prod-ready] poll:start interval=3000 (quick-retries at 1s,3s)");
    pollRef.current = setInterval(() => fetchData({ silent: true }), 3000);
    return () => {
      if (pollRef.current) {
        // eslint-disable-next-line no-console
        console.debug("[prod-ready] poll:stopped reason=unmount");
        clearInterval(pollRef.current);
      }
      backoffTimersRef.current.forEach(clearTimeout);
      backoffTimersRef.current = [];
    };
    // eslint-disable-next-line
  }, [id]);

  // Detect "stuck" feeling for assets_generating lasting >120s
  useEffect(() => {
    if (state?.status !== "assets_generating") {
      setStuckHint(false);
      return;
    }
    const iv = setInterval(() => {
      const elapsed = Date.now() - startRef.current;
      if (elapsed > 120000) setStuckHint(true);
    }, 5000);
    return () => clearInterval(iv);
  }, [state?.status]);

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
  const summary = state?.summary;
  // Frontend guard: treat "production_ready" without a summary as still planning.
  // The backend already does this, but we defend in depth to prevent any flicker.
  const planReady = status === "production_ready" && !!summary;
  const isPlanStillLoading = status === "production_ready" && !summary;
  const isGeneratingMedia = status === "assets_generating";
  // Every picture is drawn: the parent checks them before any is animated.
  const isPictureReview = status === "pictures_review";
  const isMediaReady = status === "assets_ready";
  const isMediaFailed = status === "media_failed";
  const isAssembling = status === "assembling";
  const isDelivered = status === "delivered";
  const isPlanning = isPlanStillLoading || ["pending", "ready_for_ai", "production_planning", "scenarios_generating",
                      "scenarios_ready", "scenario_selected"].includes(status);
  const isFailed = status === "failed";
  const isAwaitingPayment = status === "awaiting_payment";
  // A plan the model marked as sensitive waits for our team's review (PL-13).
  const needsReview = !!summary && summary.safety_check && summary.safety_check !== "ok" && summary.safety_review !== "approve";
  // Unified progress from backend (0..100 across the whole pipeline).
  const progress = state?.progress;
  const live = useLiveNumbers(progress);
  const isPaused = !!progress?.paused;
  // UX override: when the plan is ready (waiting for approval) or delivered,
  // show 100% instead of the backend's internal stage weight.
  const progressPercent = (planReady || isDelivered) ? 100 : live.percent;
  const progressStage = progress?.stage;
  const progressMessage = progress?.message_ar;

  // The tab shows how far along the story is while the parent browses elsewhere.
  useEffect(() => {
    const base = "غِراس";
    const working = ["production_planning", "assets_generating", "assets_ready", "assembling"].includes(status);
    document.title = working ? `${progressPercent}% · ${base}`
      : isDelivered ? `🎉 جاهزة · ${base}`
      : isPictureReview ? `🎨 الصور جاهزة · ${base}` : `قصة طفلك | ${base}`;
    return () => { document.title = base; };
  }, [status, progressPercent, isDelivered, isPictureReview]);
  const [delivery, setDelivery] = useState(null);

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
            <JourneySteps status="production_planning" className="mb-4" />
            <h1 className="font-heading text-3xl md:text-4xl font-bold text-[#2D3748] mb-2">
              نُعِدّ خطة القصة لطفلك...
            </h1>
            <p className="font-body text-[#5A677D] max-w-xl">
              نحوّل الحكاية التي اخترتها إلى خطة كاملة: مشاهد ونصوص وتوجيهات للرسم.
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
          @keyframes gheras-shimmer-move {
            0%   { background-position: 200% 0; }
            100% { background-position: -200% 0; }
          }
        `}</style>
        <Footer />
      </div>
    );
  }

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
            <JourneySteps status={status} approved={approved} className="mb-4" />
            <h1 className="font-heading text-3xl md:text-4xl font-bold text-[#2D3748] mb-2">
              {isPaused
                ? "تأخير بسيط في تجهيز قصتك ⏳"
                : isAwaitingPayment
                ? "اخترت الحكاية 🌱 بقيت خطوة الدفع"
                : isDelivered
                ? (delivery?.plan?.title ? `«${delivery.plan.title}» 🎉` : "🎉 قصتك أصبحت جاهزة!")
                : isAssembling
                ? "جاري تجميع قصة طفلك..."
                : isPictureReview
                ? "صور القصة جاهزة لمراجعتك 🎨"
                : isMediaReady
                ? "وسائط قصتك جاهزة"
                : isGeneratingMedia
                ? "نقوم الآن بصناعة قصة مميزة لطفلك..."
                : isMediaFailed
                ? "تعذّر إعداد بعض الوسائط"
                : approved
                ? "شكراً لك! تم اعتماد الخطة 🌱"
                : isFailed
                ? "تعذّر إعداد الخطة"
                : isPlanning
                ? "نُعِدّ خطة القصة لطفلك..."
                : planReady
                ? "الخطة جاهزة لاعتمادك"
                : "نُعِدّ خطة القصة لطفلك..."}
            </h1>
            <p className="font-body text-[#5A677D] max-w-xl">
              {isPaused
                ? progressMessage
                : isAwaitingPayment
                ? "ادفع السعر الذي ظهر لك أثناء تجهيز القصة، وسنبدأ فوراً."
                : isDelivered
                ? `قصة ${summary?.child_name || "طفلك"} جاهزة — شاهدها معه الآن، وحمّل الكتاب المصوّر لتقرآه معاً.`
                : isAssembling
                ? "نجمع الصور والسرد في فيديو وكتاب نهائيين."
                : isPictureReview
                ? "رسمنا كل لقطات القصة. راجعها، وأعد رسم ما لا يعجبك، ثم اعتمدها لنبدأ تحريكها."
                : isMediaReady
                ? "تم إعداد جميع الصور. جاري الآن التجميع النهائي."
                : isGeneratingMedia
                ? "نُنتج الصور والسرد الصوتي لكل مشهد. هذا يستغرق دقائق قليلة."
                : isMediaFailed
                ? "لم تكتمل بعض الوسائط. جرّب «إعادة المحاولة»، والطلب يظهر لفريقنا في قائمة المتابعة."
                : approved
                ? "بدأنا تجهيز قصة طفلك. يمكنك إغلاق الصفحة والعودة إليها من «قصصي» في أي وقت."
                : isFailed
                ? "حدث خلل بسيط أثناء إعداد الخطة. يمكنك إعادة المحاولة."
                : isPlanning
                ? "نحوّل الحكاية التي اخترتها إلى خطة كاملة: مشاهد ونصوص وتوجيهات للرسم."
                : planReady
                ? "اطلع على ملخص الخطة، ثم اعتمدها لنبدأ إعداد قصة طفلك."
                : "نحوّل الحكاية التي اخترتها إلى خطة كاملة: مشاهد ونصوص وتوجيهات للرسم."}
            </p>

            {/* Unified pipeline progress bar — always visible from planning to delivery */}
            {progress && !isDelivered && !isFailed && !isMediaFailed && !isAwaitingPayment && !isPictureReview
              && !(planReady && !approved) && (
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
                <div className="w-full bg-[#F2E8DA] rounded-full h-3 overflow-hidden relative">
                  <div
                    className="h-full bg-gradient-to-r from-[#87A96B] to-[#4F6B3B] rounded-full transition-all duration-700 relative"
                    style={{ width: `${Math.max(progressPercent, 3)}%` }}
                  >
                    {/* Shimmer overlay — always animating, so the user sees motion
                        even when the numeric percent is temporarily stable. */}
                    <div
                      className="absolute inset-0 rounded-full opacity-50"
                      style={{
                        background: "linear-gradient(90deg, transparent 0%, rgba(255,255,255,0.55) 50%, transparent 100%)",
                        backgroundSize: "200% 100%",
                        animation: "gheras-shimmer-move 1.6s linear infinite",
                      }}
                    />
                  </div>
                </div>
                <StagePill stage={progressStage} />
                <TimeChips elapsed={live.elapsed} eta={live.eta} />
                {stuckHint && live.eta == null && (
                  <p className="mt-2 text-[11px] font-body text-[#8A9AB0] text-center" data-testid="stuck-hint">
                    ما زلنا نعمل على قصتك، قد يستغرق الأمر وقتاً أطول من المعتاد 💚
                  </p>
                )}
              </div>
            )}
          </div>
        </div>

        {isAwaitingPayment && <OrderPayment orderId={id} onPaid={() => fetchData({ silent: true })} />}

        {/* PLANNING STATE */}
        {isPlanning && !summary && (
          <LoadingSkeleton message={progressMessage} />
        )}

        {/* FAILED STATE */}
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
                      {pagesLabel(delivery.pdf.page_count)} • جاهز للطباعة والقراءة مع طفلك
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

            {/* Family watch link + WhatsApp */}
            <FamilyShareCard orderId={id} childName={summary?.child_name} />

            <StoryFeedbackCard orderId={id} />

            {/* Completion card */}
            <div
              className="bg-gradient-to-br from-[#E8F0E1] via-[#F8F1E7] to-[#FDFBF7] rounded-[2rem] p-6 border border-[#87A96B]/40 text-center relative overflow-hidden"
              style={{ animation: "gheras-pop 0.7s cubic-bezier(0.2,0.9,0.3,1.15) both" }}
              data-testid="completion-card"
            >
              <div className="absolute -top-8 -right-8 w-28 h-28 bg-[#87A96B]/10 rounded-full blur-2xl" />
              <div className="absolute -bottom-8 -left-8 w-28 h-28 bg-[#D4A373]/15 rounded-full blur-2xl" />
              <div className="relative">
                <div className="w-16 h-16 rounded-full bg-white grid place-content-center mx-auto mb-3 shadow-sm ring-2 ring-[#87A96B]/30">
                  <PartyPopper className="w-8 h-8 text-[#4F6B3B]" />
                </div>
                <h3 className="font-heading text-2xl font-bold text-[#2D3748] mb-1">
                  نتمنى أن تترك القصة أثراً جميلاً في قلب طفلك 🌱
                </h3>
                <p className="font-body text-sm text-[#5A677D] mb-4">
                  قيمة جديدة تريد غرسها؟ ابدأ قصته التالية.
                </p>
                <div className="flex flex-wrap justify-center gap-3">
                  <Link to="/story/new" className="btn-primary inline-flex items-center gap-2" data-testid="new-story-btn">
                    <Sprout className="w-4 h-4" /> قصة جديدة
                  </Link>
                  <Link to="/dashboard" className="inline-flex items-center gap-2 rounded-full border-2 border-[#87A96B] text-[#729352] px-5 py-2.5 font-bold hover:bg-[#E8F0E1]">
                    قصصي
                  </Link>
                </div>
              </div>
            </div>
            <PhotoPrivacyCard orderId={id} deletedAt={state?.photos_deleted_at} onDeleted={() => fetchData({ silent: true })} />
            <style>{`
              @keyframes gheras-pop {
                0%   { opacity: 0; transform: translateY(8px) scale(0.97); }
                100% { opacity: 1; transform: translateY(0)   scale(1); }
              }
            `}</style>
          </div>
        )}

        {isPictureReview && (
          <div className="mb-6">
            <PictureReview orderId={id} childName={summary?.child_name} onApproved={() => fetchData({ silent: true })} />
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
                   isMediaFailed ? (isPaused ? "متوقفة مؤقتاً — سنكملها نحن" : "تعذّر إكمال الوسائط") :
                   "جاري إنتاج الوسائط"}
                </h2>
                <p className="font-body text-xs text-[#5A677D]" data-testid="progress-stage-label">
                  {progressMessage || (isAssembling ? "ندمج الصور والسرد في فيديو وكتاب..." :
                   isMediaReady ? "بانتظار خطوة التجميع النهائية" :
                   isMediaFailed ? "جرّب إعادة المحاولة — والطلب ظاهر لفريقنا" :
                   "جاري إنتاج الوسائط...")}
                </p>
              </div>
            </div>
            {!isMediaFailed && (
              <p className="font-body text-sm text-[#5A677D]" data-testid="media-hint">
                {isAssembling ? "قد يستغرق هذا دقيقة إلى دقيقتين. يمكنك تصفح بقية التطبيق والعودة لاحقاً." :
                 isMediaReady ? "تمت هذه الخطوة. جارٍ تحضير الفيديو والكتاب..." :
                 "يمكنك إغلاق الصفحة والعودة إليها من «قصصي» — تتحدّث تلقائياً."}
              </p>
            )}
            {!isMediaFailed && <StepList steps={progress?.steps} />}
            {!isMediaFailed && <PreviewStrip previews={progress?.previews} />}
            {(isGeneratingMedia || isAssembling) && <NotifyWhenReady />}
            {isMediaFailed && isPaused && (
              <p className="font-body text-sm text-[#5A677D] mt-2" data-testid="paused-hint">
                سيكمل فريقنا القصة من حيث توقفت، وستتحدّث هذه الصفحة تلقائياً.
              </p>
            )}
            {isMediaFailed && !isPaused && (
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
        {approved && !isGeneratingMedia && !isPictureReview && !isMediaReady && !isMediaFailed && !isAssembling && !isDelivered && summary && (
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
              {state?.queue ? (
                <p className="font-body text-sm text-[#2D3748]" data-testid="queue-position">
                  {state.queue.position <= 1
                    ? "قصتك التالية في الطابور — سنبدأ رسمها خلال دقائق."
                    : `قصتك في الطابور — أمامها ${countLabel(state.queue.position - 1, ["قصة واحدة", "قصتان", "قصص", "قصة"])}، وسنبدأ فور وصول دورها.`}
                  {" "}يمكنك إغلاق الصفحة، وستجدها في «قصصي».
                </p>
              ) : (
                <p className="font-body text-sm text-[#2D3748]">
                  سنبدأ إعداد قصة طفلك قريباً — الصور والفيديو والكتاب. يمكنك إغلاق الصفحة والعودة إليها من «قصصي» عند اكتمالها.
                </p>
              )}
            </div>
          </div>
        )}

        {/* READY — SUMMARY + ACTIONS */}
        {!approved && !isFailed && planReady && (
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
                  value={scenesLabel(summary.target_scene_count)}
                  testId="detail-scenes"
                />
                <Detail
                  icon={Heart}
                  label="عناصر بصرية"
                  value={imagesLabel(summary.estimated_image_count)}
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
                {summary.safety_check === "ok" ? "فُحصت الخطة بقواعد أمان الأطفال"
                  : needsReview ? "يراجع فريقنا الخطة قبل الرسم" : "راجع فريقنا الخطة"}
              </div>
            </div>

            <PlanScriptCard orderId={id} summary={summary} editable={planReady && !approved && !needsReview}
              onSaved={() => fetchData({ silent: true })} />

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

            {needsReview && (
              <div className="mb-4 rounded-2xl bg-[#FBEFD5] border border-[#D4A373]/40 p-4 flex items-start gap-3" data-testid="safety-review-wait">
                <ShieldAlert className="w-5 h-5 text-[#8B5A2B] shrink-0 mt-0.5" />
                <p className="font-body text-sm text-[#8B5A2B]">
                  في القصة موضوع حسّاس، لذلك يراجعها فريقنا قبل الرسم. ستتمكن من اعتمادها من هنا بعد المراجعة.
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
                  disabled={approving || regenerating || needsReview}
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

        {/* =================== UNIVERSAL FALLBACK GUARD ===================
            If NONE of the above branches rendered (e.g. unknown server status,
            permanent load error), we must NEVER leave the page hero-only. */}
        {(() => {
          const ctxRendered =
            isAwaitingPayment ||
            isDelivered ||
            isGeneratingMedia || isPictureReview || isMediaReady || isMediaFailed || isAssembling ||
            (!approved && !isFailed && planReady) ||
            (isPlanning && !summary) ||
            (approved && !isMediaFailed && !isAssembling && !isMediaReady && !isGeneratingMedia && !isDelivered) ||
            isFailed;
          // Failed status — explicit retry card instead of a blank page.
          if (isFailed && isPaused) {
            return (
              <div className="bg-white rounded-[2rem] p-6 md:p-8 border-2 border-[#D4A373]/50 text-center" data-testid="plan-paused-card">
                <Clock className="w-10 h-10 text-[#D4A373] mx-auto mb-2" />
                <h2 className="font-heading text-xl font-bold text-[#2D3748] mb-2">قصتك في الطابور</h2>
                <p className="font-body text-sm text-[#5A677D]">{progressMessage}</p>
              </div>
            );
          }
          if (isFailed) {
            return (
              <div className="bg-white rounded-[2rem] p-6 md:p-8 border-2 border-[#E07A5F] text-center" data-testid="plan-failed-card">
                <AlertTriangle className="w-10 h-10 text-[#B8612F] mx-auto mb-2" />
                <h2 className="font-heading text-xl font-bold text-[#2D3748] mb-2">تعذّر إعداد الخطة</h2>
                <p className="font-body text-sm text-[#5A677D] mb-4">
                  حدث خطأ مؤقت أثناء إعداد خطة القصة. يمكنك المحاولة مرة أخرى.
                </p>
                <button
                  type="button"
                  onClick={regenerate}
                  disabled={regenerating}
                  className="inline-flex items-center gap-2 rounded-full bg-[#E8F0E1] text-[#4F6B3B] px-5 py-2.5 text-sm font-bold disabled:opacity-50"
                  data-testid="retry-plan-btn"
                >
                  {regenerating ? <Loader2 className="w-4 h-4 animate-spin" /> : <RefreshCcw className="w-4 h-4" />}
                  إعادة المحاولة
                </button>
              </div>
            );
          }
          if (!ctxRendered) {
            // Unknown status OR permanent load error — show explicit error/retry.
            return (
              <div className="bg-white rounded-[2rem] p-6 md:p-8 border-2 border-[#E2D8C9] text-center" data-testid="unknown-status-card">
                <AlertTriangle className="w-10 h-10 text-[#B8612F] mx-auto mb-2" />
                <h2 className="font-heading text-xl font-bold text-[#2D3748] mb-2">
                  {loadError?.permanent ? "لا يمكن الوصول إلى هذا الطلب" : "جاري تحميل حالة الطلب..."}
                </h2>
                <p className="font-body text-sm text-[#5A677D] mb-4">
                  {loadError?.permanent
                    ? (loadError?.detail || "قد يكون الطلب غير موجود أو لا تملك صلاحية الوصول.")
                    : (loadError
                        ? "هناك تعطّل مؤقت في الاتصال. سنعيد المحاولة تلقائياً..."
                        : "نستعيد آخر حالة لطلبك، لحظات من فضلك.")}
                </p>
                <button
                  type="button"
                  onClick={() => fetchData()}
                  className="inline-flex items-center gap-2 rounded-full bg-[#E8F0E1] text-[#4F6B3B] px-5 py-2.5 text-sm font-bold"
                  data-testid="retry-load-btn"
                >
                  <RefreshCcw className="w-4 h-4" />
                  إعادة المحاولة
                </button>
              </div>
            );
          }
          return null;
        })()}
      </div>

      {/* Sticky mobile action bar (only on ready state) */}
      {!approved && !isFailed && planReady && (
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
            disabled={approving || regenerating || needsReview}
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
