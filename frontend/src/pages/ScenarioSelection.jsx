import React, { useEffect, useRef, useState } from "react";
import { useNavigate, useParams, Link } from "react-router-dom";
import { api } from "../lib/api";
import Navbar from "../components/gheras/Navbar";
import Footer from "../components/gheras/Footer";
import {
  Sprout, Heart, BookOpen, Rocket, CheckCircle2, RefreshCcw,
  Sparkles, Loader2, AlertTriangle, ArrowRight, Award,
  Lightbulb, ShieldAlert, Clock,
} from "lucide-react";
import { toast } from "sonner";

const ANGLE_META = {
  emotional:   { label: "عاطفي", icon: Heart, bg: "bg-[#FCE6D4]", fg: "text-[#B8612F]", ring: "border-[#E07A5F]" },
  educational: { label: "تعليمي هادئ", icon: BookOpen, bg: "bg-[#E8F0E1]", fg: "text-[#4F6B3B]", ring: "border-[#87A96B]" },
  adventure:   { label: "مغامرة مشوّقة", icon: Rocket, bg: "bg-[#F8F1E7]", fg: "text-[#8B5A2B]", ring: "border-[#D4A373]" },
};

export default function ScenarioSelection() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [state, setState] = useState({
    status: "scenarios_generating", scenarios: [], generation: null,
    selected_scenario_id: null, regeneration_count: 0, max_regenerations: 3,
    regenerations_remaining: 3, duration: null,
  });
  const [polling, setPolling] = useState(true);
  const [selectingId, setSelectingId] = useState(null);
  const [regenerating, setRegenerating] = useState(false);
  const pollRef = useRef(null);

  const fetchData = async () => {
    try {
      const { data } = await api.get(`/orders/${id}/scenarios`);
      setState(data);
      const terminal = ["scenarios_ready", "scenario_selected", "ready_for_ai", "generating", "completed", "failed"];
      if (terminal.includes(data.status)) setPolling(false);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "تعذّر تحميل السيناريوهات");
      setPolling(false);
    }
  };

  useEffect(() => {
    fetchData();
    pollRef.current = setInterval(() => {
      if (polling) fetchData();
    }, 2500);
    return () => clearInterval(pollRef.current);
    // eslint-disable-next-line
  }, [id, polling]);

  const remaining = state.regenerations_remaining ?? Math.max(0, (state.max_regenerations ?? 3) - (state.regeneration_count ?? 0));
  const limitReached = remaining <= 0;

  const regenerate = async () => {
    if (limitReached) {
      toast.error("تم استهلاك جميع محاولات إعادة التوليد");
      return;
    }
    // warning on last attempt
    if (remaining === 1) {
      const ok = window.confirm("هذه هي آخر محاولة لإعادة توليد الأفكار. هل تريد المتابعة؟");
      if (!ok) return;
    }
    setRegenerating(true);
    try {
      await api.post(`/orders/${id}/scenarios/regenerate`);
      setState((s) => ({ ...s, status: "scenarios_generating", scenarios: [], generation: null, selected_scenario_id: null }));
      setPolling(true);
      toast.success("جاري إعادة التوليد...");
    } catch (e) {
      toast.error(e?.response?.data?.detail || "فشل");
    } finally {
      setRegenerating(false);
    }
  };

  const select = async (sid) => {
    setSelectingId(sid);
    try {
      await api.post(`/orders/${id}/scenarios/${sid}/select`);
      toast.success("تم اختيار السيناريو 🌱");
      navigate(`/orders/${id}/production-ready`);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "فشل الاختيار");
    } finally {
      setSelectingId(null);
    }
  };

  const isLoading = state.status === "scenarios_generating" || (state.status === "pending");
  const isReady = state.status === "scenarios_ready" || state.status === "scenario_selected" || state.status === "ready_for_ai";
  const isFailed = state.status === "failed";
  const isLocked = state.status === "generating" || state.status === "completed";

  const regenBtnDisabled = isLocked || regenerating || limitReached;
  const regenTooltip = limitReached
    ? "تم استهلاك جميع محاولات إعادة التوليد"
    : remaining === 1
    ? "هذه هي آخر محاولة لإعادة التوليد"
    : "إنشاء 3 أفكار جديدة بديلة";

  return (
    <div className="min-h-screen bg-[#FDFBF7]" data-testid="scenario-selection">
      <Navbar />

      <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-10 md:py-14">
        <Link to="/dashboard" className="inline-flex items-center gap-2 text-[#5A677D] hover:text-[#2D3748] mb-6 font-body" data-testid="back-link">
          <ArrowRight className="w-4 h-4" /> العودة إلى قصصي
        </Link>

        {/* Progress hero */}
        <div className="bg-gradient-to-br from-[#E8F0E1] via-[#F8F1E7] to-[#FDFBF7] rounded-[2rem] p-6 md:p-10 border border-[#E2D8C9] mb-8 relative overflow-hidden">
          <div className="absolute -top-10 -right-10 w-40 h-40 bg-[#87A96B]/10 blob-shape" />
          <div className="absolute -bottom-10 -left-10 w-40 h-40 bg-[#D4A373]/15 blob-shape" />
          <div className="relative">
            <div className="inline-flex items-center gap-2 bg-white rounded-full px-3 py-1 text-xs font-bold text-[#729352] mb-3">
              <Sparkles className="w-3 h-3" /> الخطوة 7 من 8
            </div>
            <h1 className="font-heading text-3xl md:text-4xl font-bold text-[#2D3748] mb-2">
              {isLoading ? "نُعِدّ الآن 3 أفكار مناسبة لطفلك" : isFailed ? "حدث تعطّل بسيط" : "اختر السيناريو الذي يناسبك"}
            </h1>
            <p className="font-body text-[#5A677D] max-w-xl">
              {isLoading ? "كاتبنا يصمّم 3 زوايا مختلفة لقصة طفلك. هذا يستغرق ثوانٍ قليلة..."
              : isFailed ? "لم نتمكن من إنشاء السيناريوهات. جرّب إعادة التوليد."
              : "كل سيناريو له شخصية مختلفة. اختر الزاوية التي تشعر أنها الأقرب لطفلك."}
            </p>
            {state.duration?.label && (
              <div className="mt-4 inline-flex items-center gap-2 bg-white/80 backdrop-blur rounded-full px-3 py-1 text-xs font-body text-[#5A677D]" data-testid="hero-duration">
                <Clock className="w-3 h-3 text-[#729352]" />
                مدة الفيديو المطلوبة: <b className="text-[#2D3748]">{state.duration.label}</b>
                <span>•</span>
                <span>~{state.duration.scene_target} مشاهد</span>
              </div>
            )}
          </div>
        </div>

        {isLoading && <LoadingSkeleton />}

        {isFailed && (
          <div className="bg-white rounded-[2rem] p-10 border border-[#E2D8C9] text-center" data-testid="error-state">
            <div className="w-20 h-20 rounded-3xl bg-[#FCE6D4] grid place-content-center mx-auto mb-5">
              <AlertTriangle className="w-10 h-10 text-[#B8612F]" />
            </div>
            <h2 className="font-heading text-2xl font-bold text-[#2D3748] mb-2">تعذّر إنشاء السيناريوهات</h2>
            <p className="font-body text-[#5A677D] mb-6">يمكن أن يحدث هذا أحياناً. اضغط لإعادة المحاولة.</p>
            <button
              onClick={regenerate}
              disabled={regenBtnDisabled}
              title={regenTooltip}
              className="btn-primary inline-flex items-center gap-2 disabled:opacity-50"
              data-testid="retry-btn"
            >
              <RefreshCcw className="w-4 h-4" /> إعادة المحاولة
            </button>
          </div>
        )}

        {isReady && state.scenarios.length > 0 && (
          <>
            {/* Last-attempt warning banner */}
            {remaining === 1 && !limitReached && (
              <div className="mb-5 rounded-2xl bg-[#F8F1E7] border border-[#D4A373]/40 p-4 flex items-center gap-3" data-testid="last-attempt-warning">
                <ShieldAlert className="w-5 h-5 text-[#8B5A2B] shrink-0" />
                <p className="font-body text-sm text-[#8B5A2B]">
                  تنبيه: تبقّت لديك <b>محاولة واحدة</b> فقط لإعادة توليد الأفكار.
                </p>
              </div>
            )}
            {limitReached && (
              <div className="mb-5 rounded-2xl bg-[#FCE6D4] border border-[#E07A5F]/40 p-4 flex items-start gap-3" data-testid="limit-reached-warning">
                <AlertTriangle className="w-5 h-5 text-[#B8612F] shrink-0 mt-0.5" />
                <div>
                  <p className="font-body font-bold text-[#B8612F]">لقد وصلت للحد الأقصى من إعادة توليد الأفكار لهذه القصة.</p>
                  <p className="font-body text-sm text-[#8B3A1F] mt-1">يمكنك اختيار أحد الخيارات الحالية أو التواصل معنا لمساعدتك.</p>
                </div>
              </div>
            )}

            <div className="grid grid-cols-1 md:grid-cols-3 gap-5 mb-6" data-testid="scenarios-grid">
              {state.scenarios.map((s, i) => {
                const meta = ANGLE_META[s.emotional_angle] || ANGLE_META.educational;
                const Icon = meta.icon;
                const selected = state.selected_scenario_id === s.id || s.is_selected;
                return (
                  <div
                    key={s.id}
                    className={`bg-white rounded-3xl p-6 border-2 transition-all card-lift animate-grow flex flex-col ${
                      selected ? "border-[#87A96B] bg-[#E8F0E1]/30 shadow-lg" : "border-[#E2D8C9]"
                    }`}
                    style={{ animationDelay: `${i * 0.08}s` }}
                    data-testid={`scenario-card-${s.id}`}
                  >
                    <div className="flex items-center justify-between mb-4">
                      <div className={`w-12 h-12 rounded-2xl ${meta.bg} grid place-content-center`}>
                        <Icon className={`w-6 h-6 ${meta.fg}`} />
                      </div>
                      <span className={`rounded-full px-3 py-1 text-xs font-bold font-body ${meta.bg} ${meta.fg}`}>
                        {meta.label}
                      </span>
                    </div>

                    <div className="mb-2 inline-flex items-center gap-1 text-xs text-[#8A9AB0] font-body">
                      <span>سيناريو {s.scenario_index}</span>
                      <span>•</span>
                      <span>{s.estimated_scene_count} مشاهد</span>
                    </div>

                    <h3 className="font-heading text-xl font-bold text-[#2D3748] mb-2 leading-tight">
                      {s.title}
                    </h3>

                    <p className="font-body text-[#5A677D] text-sm leading-relaxed mb-4 flex-1">
                      {s.short_summary}
                    </p>

                    {s.why_this_fits && (
                      <div className="bg-[#F8F1E7] rounded-2xl p-3 border border-[#D4A373]/30 mb-3" data-testid={`why-fits-${s.id}`}>
                        <div className="flex items-center gap-2 text-xs font-bold text-[#8B5A2B] mb-1">
                          <Lightbulb className="w-3 h-3" /> لماذا هذا السيناريو يناسب طفلك؟
                        </div>
                        <p className="font-body text-sm text-[#2D3748]">{s.why_this_fits}</p>
                      </div>
                    )}

                    {s.learning_goal && (
                      <div className="bg-[#FDFBF7] rounded-2xl p-3 border border-[#E2D8C9] mb-4">
                        <div className="flex items-center gap-2 text-xs font-bold text-[#729352] mb-1">
                          <Award className="w-3 h-3" /> الرسالة
                        </div>
                        <p className="font-body text-sm text-[#2D3748]">{s.learning_goal}</p>
                      </div>
                    )}

                    {selected ? (
                      <div className="rounded-full bg-[#87A96B] text-white py-3 font-bold font-body text-center inline-flex items-center justify-center gap-2">
                        <CheckCircle2 className="w-4 h-4" /> تم اختياره
                      </div>
                    ) : (
                      <button
                        onClick={() => select(s.id)}
                        disabled={selectingId !== null || isLocked}
                        className="w-full btn-primary inline-flex items-center justify-center gap-2 disabled:opacity-60"
                        data-testid={`scenario-select-${s.id}`}
                      >
                        {selectingId === s.id ? <Loader2 className="w-4 h-4 animate-spin" /> : <Sprout className="w-4 h-4" />}
                        اختر هذا السيناريو
                      </button>
                    )}
                  </div>
                );
              })}
            </div>

            <div className="flex items-center justify-between flex-wrap gap-3 bg-white rounded-2xl p-4 border border-[#E2D8C9]">
              <div className="text-sm text-[#5A677D] font-body inline-flex items-center gap-3 flex-wrap">
                <span className="inline-flex items-center gap-1 bg-[#FDFBF7] rounded-full px-3 py-1 text-xs border border-[#E2D8C9]" data-testid="regen-counter">
                  محاولات التوليد: <b className="text-[#4F6B3B]">{state.regeneration_count ?? 0} / {state.max_regenerations ?? 3}</b>
                </span>
              </div>
              <button
                onClick={regenerate}
                disabled={regenBtnDisabled}
                title={regenTooltip}
                className="inline-flex items-center gap-2 rounded-full bg-[#F8F1E7] hover:bg-[#F2E8DA] text-[#8B5A2B] px-5 py-2 text-sm font-bold disabled:opacity-50 disabled:cursor-not-allowed"
                data-testid="regenerate-btn"
              >
                <RefreshCcw className="w-4 h-4" />
                {limitReached ? "استُهلكت المحاولات" : regenerating ? "جاري..." : "إعادة توليد 3 أفكار جديدة"}
              </button>
            </div>
          </>
        )}
      </div>
      <Footer />
    </div>
  );
}

function LoadingSkeleton() {
  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-5" data-testid="loading-skeleton">
      {[1, 2, 3].map((i) => (
        <div key={i} className="bg-white rounded-3xl p-6 border border-[#E2D8C9]">
          <div className="flex items-center justify-between mb-4">
            <div className="w-12 h-12 rounded-2xl bg-[#F2E8DA] animate-pulse" />
            <div className="w-20 h-6 rounded-full bg-[#F2E8DA] animate-pulse" />
          </div>
          <div className="h-3 w-24 bg-[#F2E8DA] rounded animate-pulse mb-3" />
          <div className="h-6 w-3/4 bg-[#E2D8C9] rounded animate-pulse mb-3" />
          <div className="space-y-2 mb-4">
            <div className="h-3 w-full bg-[#F2E8DA] rounded animate-pulse" />
            <div className="h-3 w-full bg-[#F2E8DA] rounded animate-pulse" />
            <div className="h-3 w-2/3 bg-[#F2E8DA] rounded animate-pulse" />
          </div>
          <div className="h-16 w-full bg-[#FDFBF7] rounded-2xl animate-pulse mb-4 border border-[#E2D8C9]" />
          <div className="h-12 w-full bg-[#E8F0E1] rounded-full animate-pulse" />
        </div>
      ))}
      <div className="md:col-span-3 text-center text-[#5A677D] font-body text-sm mt-2 inline-flex items-center justify-center gap-2">
        <Loader2 className="w-4 h-4 animate-spin text-[#87A96B]" />
        جاري إعداد القصص لطفلك...
      </div>
    </div>
  );
}
