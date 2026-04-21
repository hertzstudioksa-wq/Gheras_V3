import React, { useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import { useAuth } from "../contexts/AuthContext";
import Navbar from "../components/gheras/Navbar";
import Footer from "../components/gheras/Footer";
import ImageUploader from "../components/gheras/ImageUploader";
import {
  ChevronRight, ChevronLeft, Check, Sprout, User, Users, Sparkles, BookOpen,
  PenTool, Heart, Sun, Award, Moon, Rocket, CheckCircle2, Plus, Trash2, X,
  PartyPopper, Palette, MapPin, Languages, Mic, FileText, Clock, Coins,
  Music, VolumeX,
} from "lucide-react";
import { toast } from "sonner";

const ICON_MAP = {
  sun: Sun, heart: Heart, award: Award, sparkles: Sparkles, moon: Moon,
  rocket: Rocket, "moon-star": Moon, "pen-tool": PenTool, sprout: Sprout,
};

const STEPS = [
  { id: 1, label: "الهدف", icon: Sprout },
  { id: 2, label: "طفلك", icon: User },
  { id: 3, label: "الشخصيات", icon: Users },
  { id: 4, label: "التخصيص", icon: Sparkles },
  { id: 5, label: "الأسلوب", icon: BookOpen },
  { id: 6, label: "المراجعة", icon: Check },
];

const CHAR_TYPES = [
  { v: "mother", l: "الأم", i: Heart },
  { v: "father", l: "الأب", i: Sprout },
  { v: "sibling", l: "أخ/أخت", i: Users },
  { v: "friend", l: "صديق", i: PartyPopper },
  { v: "teacher", l: "معلّم", i: Award },
  { v: "grandparent", l: "جد/جدة", i: Heart },
  { v: "other", l: "أخرى", i: Users },
];

const FAV_TYPES = [
  { v: "toy", l: "لعبة", i: PartyPopper },
  { v: "place", l: "مكان", i: MapPin },
  { v: "character", l: "شخصية", i: User },
  { v: "hobby", l: "هواية", i: Sparkles },
  { v: "other", l: "أخرى", i: PenTool },
];

// Duration snap points & mapping (must mirror backend models.duration_meta)
const DURATION_SNAPS = [30, 45, 60, 90, 120, 150, 180];
const DURATION_META = {
  30:  { label: "30 ثانية",     scene_target: 3, cost_tier: "low" },
  45:  { label: "45 ثانية",     scene_target: 4, cost_tier: "low" },
  60:  { label: "دقيقة",        scene_target: 5, cost_tier: "medium" },
  90:  { label: "دقيقة ونصف",   scene_target: 6, cost_tier: "medium" },
  120: { label: "دقيقتان",      scene_target: 7, cost_tier: "high" },
  150: { label: "دقيقتان ونصف", scene_target: 8, cost_tier: "high" },
  180: { label: "ثلاث دقائق",   scene_target: 9, cost_tier: "high" },
};
const COST_TIER_META = {
  low:    { label: "اقتصادي",  color: "bg-[#E8F0E1] text-[#4F6B3B] border-[#87A96B]/40" },
  medium: { label: "متوازن",   color: "bg-[#F8F1E7] text-[#8B5A2B] border-[#D4A373]/40" },
  high:   { label: "مميّز",    color: "bg-[#FCE6D4] text-[#B8612F] border-[#E07A5F]/40" },
};

const AUDIO_BG_OPTIONS = [
  { v: "music",         l: "موسيقى هادئة",              i: Music },
  { v: "human_rhythm",  l: "إيقاع صوتي بشري",           i: Mic },
  { v: "none",          l: "من دون خلفية صوتية",        i: VolumeX },
];

const blankData = () => ({
  goal: { category_id: "", subcategory_id: "", custom_subcategory: "", context: "" },
  child: { name: "", age: 5, gender: "male", image_url: "", appearance_notes: "", hijab: false },
  characters: [],
  personalization: { favorites: {}, toy_image_url: "", custom_notes: "" },
  style: { type_id: "", tone_id: "", setting_id: "", language_id: "", voice_id: "" },
  duration: { seconds: 90 },
  audio_background: { mode: "music" },
});

const LS_KEY = "gheras_story_draft_v2";

export default function StoryBuilder() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [step, setStep] = useState(1);
  const [submitting, setSubmitting] = useState(false);
  const [categories, setCategories] = useState([]);
  const [options, setOptions] = useState({ type: [], tone: [], setting: [], language: [], voice: [] });
  const [maxChars, setMaxChars] = useState(3);
  const [data, setData] = useState(blankData);
  const saveTimer = useRef(null);

  // Load reference data
  useEffect(() => {
    Promise.all([
      api.get("/public/categories"),
      api.get("/public/story-options"),
      api.get("/public/settings"),
    ]).then(([c, o, s]) => {
      setCategories(c.data);
      setOptions(o.data);
      if (s.data?.["characters.max_count"]) setMaxChars(Number(s.data["characters.max_count"]) || 3);
    });
  }, []);

  // Hydrate draft (server if logged in, else localStorage)
  useEffect(() => {
    (async () => {
      if (user) {
        try {
          const { data: d } = await api.get("/drafts/current");
          if (d?.data && Object.keys(d.data).length > 0) {
            setData({ ...blankData(), ...d.data });
            setStep(d.current_step || 1);
            return;
          }
        } catch {}
      }
      const raw = localStorage.getItem(LS_KEY);
      if (raw) {
        try {
          const parsed = JSON.parse(raw);
          setData({ ...blankData(), ...(parsed.data || {}) });
          setStep(parsed.step || 1);
        } catch {}
      }
      // preset category from categories page link
      if (location.state?.presetCategoryId) {
        setData((d) => ({ ...d, goal: { ...d.goal, category_id: location.state.presetCategoryId } }));
      }
    })();
    // eslint-disable-next-line
  }, [user]);

  // Auto-save (debounced)
  useEffect(() => {
    if (saveTimer.current) clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(() => {
      const payload = { step, data };
      localStorage.setItem(LS_KEY, JSON.stringify(payload));
      if (user) {
        api.put("/drafts/current", { current_step: step, data }).catch(() => {});
      }
    }, 600);
    return () => saveTimer.current && clearTimeout(saveTimer.current);
  }, [step, data, user]);

  const selectedCategory = useMemo(
    () => categories.find((c) => c.id === data.goal.category_id),
    [categories, data.goal.category_id]
  );

  const updateGoal = (patch) => setData((d) => ({ ...d, goal: { ...d.goal, ...patch } }));
  const updateChild = (patch) => setData((d) => ({ ...d, child: { ...d.child, ...patch } }));
  const updateStyle = (patch) => setData((d) => ({ ...d, style: { ...d.style, ...patch } }));
  const updatePers = (patch) => setData((d) => ({ ...d, personalization: { ...d.personalization, ...patch } }));
  const updateDuration = (seconds) => setData((d) => ({ ...d, duration: { seconds } }));
  const updateAudioBg = (mode) => setData((d) => ({ ...d, audio_background: { mode } }));

  const toggleFav = (key) => {
    const cur = data.personalization.favorites?.[key] || { selected: false, name: "" };
    updatePers({
      favorites: { ...data.personalization.favorites, [key]: { ...cur, selected: !cur.selected } },
    });
  };
  const setFavName = (key, name) => {
    const cur = data.personalization.favorites?.[key] || { selected: true, name: "" };
    updatePers({
      favorites: { ...data.personalization.favorites, [key]: { ...cur, selected: true, name } },
    });
  };

  const addCharacter = () => {
    if (data.characters.length >= maxChars) {
      toast.error(`الحد الأقصى ${maxChars} شخصيات`);
      return;
    }
    setData((d) => ({
      ...d,
      characters: [...d.characters, { type: "mother", name: "", role: "mentioned", image_url: "" }],
    }));
  };
  const updateChar = (idx, patch) =>
    setData((d) => ({
      ...d,
      characters: d.characters.map((c, i) => (i === idx ? { ...c, ...patch } : c)),
    }));
  const removeChar = (idx) =>
    setData((d) => ({ ...d, characters: d.characters.filter((_, i) => i !== idx) }));

  const canProceed = () => {
    if (step === 1) {
      if (!data.goal.category_id) return false;
      if (!data.goal.context || data.goal.context.trim().length < 3) return false;
      const cat = selectedCategory;
      if (cat && cat.subcategories?.length > 0) {
        if (!data.goal.subcategory_id && !data.goal.custom_subcategory) return false;
      }
      return true;
    }
    if (step === 2) {
      return (
        data.child.name.trim().length >= 1 &&
        data.child.age >= 1 &&
        data.child.age <= 14 &&
        !!data.child.image_url
      );
    }
    if (step === 3) return true; // optional
    if (step === 4) return true;
    if (step === 5) return !!data.style.type_id && !!data.style.tone_id; // require at least type + tone
    return true;
  };

  const next = () => {
    if (!canProceed()) {
      toast.error("الرجاء إكمال الحقول المطلوبة");
      return;
    }
    setStep((s) => Math.min(6, s + 1));
    window.scrollTo({ top: 0, behavior: "smooth" });
  };
  const back = () => {
    setStep((s) => Math.max(1, s - 1));
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const submit = async () => {
    if (!user) {
      toast("سجّل دخولك لإتمام الطلب 🌱");
      navigate("/login", { state: { from: { pathname: "/story/new" } } });
      return;
    }
    setSubmitting(true);
    try {
      const { data: created } = await api.post("/orders", { data });
      localStorage.removeItem(LS_KEY);
      toast.success("تم الإرسال — جاري إعداد السيناريوهات 🌱");
      navigate(`/orders/${created.id}/scenarios`);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "تعذّر إنشاء الطلب");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen bg-[#FDFBF7] pb-24 md:pb-0" data-testid="story-builder">
      <Navbar />

      <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-8 md:py-12">
        {/* Stepper */}
        <div className="mb-8" data-testid="wizard-stepper">
          <div className="flex items-center justify-between relative mb-3">
            <div className="absolute top-1/2 right-0 left-0 h-1 bg-[#E2D8C9] -translate-y-1/2 -z-0" />
            <div
              className="absolute top-1/2 right-0 h-1 bg-[#87A96B] -translate-y-1/2 -z-0 transition-all duration-500"
              style={{ width: `${((step - 1) / (STEPS.length - 1)) * 100}%` }}
            />
            {STEPS.map((s, idx) => {
              const done = idx + 1 < step;
              const active = idx + 1 === step;
              return (
                <div
                  key={s.id}
                  className={`relative z-10 w-9 h-9 md:w-10 md:h-10 rounded-full grid place-content-center font-bold font-body ring-4 ring-[#FDFBF7] transition ${
                    done ? "bg-[#87A96B] text-white"
                    : active ? "bg-[#87A96B] text-white shadow-md scale-110"
                    : "bg-white text-[#8A9AB0] border border-[#E2D8C9]"
                  }`}
                  data-testid={`step-indicator-${s.id}`}
                >
                  {done ? <Check className="w-5 h-5" /> : s.id}
                </div>
              );
            })}
          </div>
          <div className="hidden md:flex items-center justify-between text-xs text-[#5A677D] font-body">
            {STEPS.map((s) => (
              <span key={s.id} className={step === s.id ? "text-[#729352] font-bold" : ""}>{s.label}</span>
            ))}
          </div>
          <div className="md:hidden text-center text-sm font-body text-[#5A677D] mt-1">
            الخطوة {step} من {STEPS.length} — <span className="text-[#729352] font-bold">{STEPS[step-1].label}</span>
          </div>
        </div>

        <div className="bg-white rounded-[2rem] p-5 md:p-10 border border-[#E2D8C9] shadow-sm min-h-[400px] animate-grow">
          {/* STEP 1 */}
          {step === 1 && (
            <div data-testid="step-1-content">
              <h2 className="font-heading text-2xl md:text-3xl font-bold text-[#2D3748] mb-2">
                الهدف التربوي من القصة
              </h2>
              <p className="font-body text-[#5A677D] mb-6">اختر التصنيف والموضوع، ثم اكتب موقفاً حقيقياً</p>

              <div className="grid grid-cols-2 md:grid-cols-3 gap-3 md:gap-4 mb-6">
                {categories.map((c) => {
                  const Icon = ICON_MAP[c.icon] || BookOpen;
                  const sel = data.goal.category_id === c.id;
                  return (
                    <button
                      key={c.id}
                      type="button"
                      onClick={() => updateGoal({ category_id: c.id, subcategory_id: "", custom_subcategory: "" })}
                      className={`rounded-3xl p-4 md:p-5 border-2 text-right transition-all card-lift ${
                        sel ? "border-[#87A96B] bg-[#E8F0E1]"
                        : "border-transparent bg-[#FDFBF7] hover:border-[#E2D8C9]"
                      }`}
                      data-testid={`goal-cat-${c.slug}`}
                    >
                      <div className="w-10 h-10 md:w-12 md:h-12 rounded-2xl grid place-content-center mb-2" style={{ backgroundColor: `${c.color}20` }}>
                        <Icon className="w-5 h-5 md:w-6 md:h-6" style={{ color: c.color }} />
                      </div>
                      <h3 className="font-heading font-bold text-[#2D3748] text-sm md:text-base">{c.name_ar}</h3>
                      <p className="font-body text-xs text-[#8A9AB0]">{c.subcategories?.length || 0} مواضيع</p>
                    </button>
                  );
                })}
              </div>

              {selectedCategory?.subcategories?.length > 0 && (
                <div className="bg-[#FDFBF7] rounded-2xl p-4 border border-[#E2D8C9] mb-4">
                  <h3 className="font-heading font-bold text-[#2D3748] mb-3">اختر موضوعاً في "{selectedCategory.name_ar}"</h3>
                  <div className="flex flex-wrap gap-2">
                    {selectedCategory.subcategories.map((s) => (
                      <button
                        key={s.id}
                        type="button"
                        onClick={() => updateGoal({ subcategory_id: s.id, custom_subcategory: "" })}
                        className={`rounded-full px-4 py-2 text-sm font-body border-2 transition ${
                          data.goal.subcategory_id === s.id
                            ? "bg-[#87A96B] text-white border-[#87A96B]"
                            : "bg-white text-[#2D3748] border-[#E2D8C9] hover:border-[#87A96B]"
                        }`}
                        data-testid={`subcat-${s.id}`}
                      >
                        {s.name_ar}
                      </button>
                    ))}
                    <button
                      type="button"
                      onClick={() => updateGoal({ subcategory_id: "", custom_subcategory: data.goal.custom_subcategory || " " })}
                      className={`rounded-full px-4 py-2 text-sm font-body border-2 transition ${
                        data.goal.custom_subcategory && !data.goal.subcategory_id
                          ? "bg-[#D4A373] text-white border-[#D4A373]"
                          : "bg-white text-[#8B5A2B] border-[#E2D8C9]"
                      }`}
                    >
                      أخرى...
                    </button>
                  </div>
                  {!data.goal.subcategory_id && data.goal.custom_subcategory !== "" && (
                    <input
                      value={data.goal.custom_subcategory}
                      onChange={(e) => updateGoal({ custom_subcategory: e.target.value })}
                      placeholder="اكتب الموضوع بنفسك"
                      className="w-full mt-3 bg-white border border-[#E2D8C9] rounded-2xl px-4 py-2 font-body focus:outline-none focus:ring-2 focus:ring-[#87A96B]"
                      data-testid="custom-subcat"
                    />
                  )}
                </div>
              )}

              {selectedCategory?.slug === "custom" && (
                <input
                  value={data.goal.custom_subcategory}
                  onChange={(e) => updateGoal({ custom_subcategory: e.target.value })}
                  placeholder="اكتب الهدف بنفسك"
                  className="w-full mb-4 bg-[#FDFBF7] border border-[#E2D8C9] rounded-2xl px-5 py-3 font-body"
                  data-testid="custom-goal"
                />
              )}

              <div className="bg-gradient-to-br from-[#E8F0E1] to-[#F8F1E7] rounded-2xl p-5 border border-[#87A96B]/20">
                <label className="block text-sm font-bold text-[#2D3748] mb-2 font-body">
                  اكتب موقفاً حقيقياً عاشه طفلك <span className="text-[#E07A5F]">*</span>
                </label>
                <p className="font-body text-xs text-[#5A677D] mb-3">
                  هذه أهم معلومة — كلما كان الموقف محدداً كانت القصة أقوى وأعمق أثراً.
                </p>
                <textarea
                  value={data.goal.context}
                  onChange={(e) => updateGoal({ context: e.target.value })}
                  rows={4}
                  placeholder="مثال: أمس رفض يوسف مشاركة لعبته الجديدة مع أخيه الصغير، وبكى عندما طلبت منه ذلك."
                  className="w-full bg-white border border-[#E2D8C9] rounded-2xl px-5 py-3 font-body focus:outline-none focus:ring-2 focus:ring-[#87A96B]"
                  data-testid="goal-context"
                />
              </div>
            </div>
          )}

          {/* STEP 2 */}
          {step === 2 && (
            <div data-testid="step-2-content">
              <h2 className="font-heading text-2xl md:text-3xl font-bold text-[#2D3748] mb-2">أخبرنا عن طفلك</h2>
              <p className="font-body text-[#5A677D] mb-6">المعلومات التي تجعل القصة شخصية حقاً</p>

              <div className="flex flex-col md:flex-row gap-6 mb-6">
                <ImageUploader
                  value={data.child.image_url}
                  onChange={(url) => updateChild({ image_url: url })}
                  scope="child"
                  label="صورة الطفل"
                  required
                  size="lg"
                  testId="child-image"
                />
                <div className="flex-1 grid gap-4">
                  <div>
                    <label className="block text-sm font-bold text-[#2D3748] mb-2 font-body">اسم الطفل <span className="text-[#E07A5F]">*</span></label>
                    <input
                      value={data.child.name}
                      onChange={(e) => updateChild({ name: e.target.value })}
                      placeholder="مثلاً: يوسف"
                      className="w-full bg-[#FDFBF7] border border-[#E2D8C9] rounded-2xl px-5 py-3 font-body focus:outline-none focus:ring-2 focus:ring-[#87A96B]"
                      data-testid="child-name"
                    />
                  </div>
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="block text-sm font-bold text-[#2D3748] mb-2 font-body">العمر <span className="text-[#E07A5F]">*</span></label>
                      <input
                        type="number"
                        min={1}
                        max={14}
                        value={data.child.age}
                        onChange={(e) => updateChild({ age: parseInt(e.target.value || "0") })}
                        className="w-full bg-[#FDFBF7] border border-[#E2D8C9] rounded-2xl px-5 py-3 font-body"
                        data-testid="child-age"
                      />
                    </div>
                    <div>
                      <label className="block text-sm font-bold text-[#2D3748] mb-2 font-body">الجنس <span className="text-[#E07A5F]">*</span></label>
                      <div className="flex gap-2">
                        {[{ v: "male", l: "ولد" }, { v: "female", l: "بنت" }].map((g) => (
                          <button
                            key={g.v}
                            type="button"
                            onClick={() => updateChild({ gender: g.v })}
                            className={`flex-1 rounded-2xl py-3 font-body font-bold border-2 transition ${
                              data.child.gender === g.v
                                ? "bg-[#E8F0E1] border-[#87A96B] text-[#4F6B3B]"
                                : "bg-white border-[#E2D8C9] text-[#5A677D]"
                            }`}
                            data-testid={`child-gender-${g.v}`}
                          >
                            {g.l}
                          </button>
                        ))}
                      </div>
                    </div>
                  </div>
                  {data.child.gender === "female" && (
                    <label className="flex items-center gap-3 bg-[#F8F1E7] rounded-2xl p-4 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={!!data.child.hijab}
                        onChange={(e) => updateChild({ hijab: e.target.checked })}
                        className="w-5 h-5 accent-[#87A96B]"
                        data-testid="child-hijab"
                      />
                      <span className="font-body text-[#2D3748]">تظهر القصة البنت بالحجاب</span>
                    </label>
                  )}
                </div>
              </div>

              <label className="block text-sm font-bold text-[#2D3748] mb-2 font-body">ملاحظات إضافية عن المظهر (اختياري)</label>
              <textarea
                rows={2}
                value={data.child.appearance_notes || ""}
                onChange={(e) => updateChild({ appearance_notes: e.target.value })}
                placeholder="شعر أسود قصير، عيون بنية، يلبس نظارات..."
                className="w-full bg-[#FDFBF7] border border-[#E2D8C9] rounded-2xl px-5 py-3 font-body"
                data-testid="child-appearance"
              />
            </div>
          )}

          {/* STEP 3 — characters */}
          {step === 3 && (
            <div data-testid="step-3-content">
              <h2 className="font-heading text-2xl md:text-3xl font-bold text-[#2D3748] mb-2">شخصيات القصة</h2>
              <p className="font-body text-[#5A677D] mb-6">
                يمكنك إضافة حتى {maxChars} شخصيات إضافية (اختياري)
              </p>

              <div className="space-y-4 mb-4">
                {data.characters.map((c, idx) => {
                  const typeObj = CHAR_TYPES.find((t) => t.v === c.type) || CHAR_TYPES[0];
                  const TypeIcon = typeObj.i;
                  return (
                    <div key={idx} className="bg-[#FDFBF7] rounded-3xl p-5 border border-[#E2D8C9]" data-testid={`char-card-${idx}`}>
                      <div className="flex items-start justify-between mb-4">
                        <div className="flex items-center gap-3">
                          <div className="w-10 h-10 rounded-2xl bg-[#E8F0E1] grid place-content-center">
                            <TypeIcon className="w-5 h-5 text-[#729352]" />
                          </div>
                          <span className="font-heading font-bold text-[#2D3748]">شخصية {idx + 1}</span>
                        </div>
                        <button
                          type="button"
                          onClick={() => removeChar(idx)}
                          className="text-[#B8612F] hover:text-[#8B3A1F] p-1"
                          data-testid={`char-remove-${idx}`}
                        >
                          <Trash2 className="w-5 h-5" />
                        </button>
                      </div>

                      <label className="block text-xs font-bold text-[#5A677D] mb-2 font-body">النوع</label>
                      <div className="flex flex-wrap gap-2 mb-4">
                        {CHAR_TYPES.map((t) => (
                          <button
                            key={t.v}
                            type="button"
                            onClick={() => updateChar(idx, { type: t.v })}
                            className={`rounded-full px-3 py-1.5 text-xs font-body border-2 transition ${
                              c.type === t.v
                                ? "bg-[#87A96B] text-white border-[#87A96B]"
                                : "bg-white text-[#2D3748] border-[#E2D8C9]"
                            }`}
                          >
                            {t.l}
                          </button>
                        ))}
                      </div>

                      <div className="grid md:grid-cols-2 gap-3 mb-4">
                        <div>
                          <label className="block text-xs font-bold text-[#5A677D] mb-2 font-body">الاسم (اختياري)</label>
                          <input
                            value={c.name || ""}
                            onChange={(e) => updateChar(idx, { name: e.target.value })}
                            placeholder="مثلاً: سارة"
                            className="w-full bg-white border border-[#E2D8C9] rounded-2xl px-4 py-2 font-body"
                            data-testid={`char-name-${idx}`}
                          />
                        </div>
                        <div>
                          <label className="block text-xs font-bold text-[#5A677D] mb-2 font-body">نوع الظهور</label>
                          <div className="flex gap-2">
                            {[
                              { v: "mentioned", l: "ذكر فقط" },
                              { v: "visible", l: "ظهور في القصة" },
                            ].map((r) => (
                              <button
                                key={r.v}
                                type="button"
                                onClick={() => updateChar(idx, { role: r.v })}
                                className={`flex-1 rounded-2xl py-2 text-xs font-body font-bold border-2 transition ${
                                  c.role === r.v
                                    ? "bg-[#E8F0E1] border-[#87A96B] text-[#4F6B3B]"
                                    : "bg-white border-[#E2D8C9] text-[#5A677D]"
                                }`}
                              >
                                {r.l}
                              </button>
                            ))}
                          </div>
                        </div>
                      </div>

                      {/* Lazy-reveal image uploader only when visible role */}
                      {c.role === "visible" ? (
                        <ImageUploader
                          value={c.image_url}
                          onChange={(url) => updateChar(idx, { image_url: url })}
                          scope="character"
                          label="صورة الشخصية (اختياري — للمرجع)"
                          size="sm"
                          testId={`char-image-${idx}`}
                        />
                      ) : (
                        <button
                          type="button"
                          onClick={() => updateChar(idx, { role: "visible" })}
                          className="inline-flex items-center gap-2 text-[#729352] text-sm font-body font-bold hover:text-[#4F6B3B]"
                        >
                          <Plus className="w-4 h-4" /> إضافة صورة مرجعية للشخصية
                        </button>
                      )}
                    </div>
                  );
                })}
              </div>

              {data.characters.length < maxChars && (
                <button
                  type="button"
                  onClick={addCharacter}
                  className="w-full rounded-3xl border-2 border-dashed border-[#E2D8C9] hover:border-[#87A96B] py-6 font-body text-[#729352] font-bold inline-flex items-center justify-center gap-2 transition"
                  data-testid="char-add-btn"
                >
                  <Plus className="w-5 h-5" /> إضافة شخصية ({data.characters.length}/{maxChars})
                </button>
              )}
            </div>
          )}

          {/* STEP 4 — Personalization */}
          {step === 4 && (
            <div data-testid="step-4-content">
              <h2 className="font-heading text-2xl md:text-3xl font-bold text-[#2D3748] mb-2">التخصيص</h2>
              <p className="font-body text-[#5A677D] mb-6">المفضلات التي تجعل القصة تشبه طفلك تماماً</p>

              <div className="grid grid-cols-2 md:grid-cols-3 gap-3 mb-5">
                {FAV_TYPES.map((f) => {
                  const Icon = f.i;
                  const sel = data.personalization.favorites?.[f.v]?.selected;
                  return (
                    <button
                      key={f.v}
                      type="button"
                      onClick={() => toggleFav(f.v)}
                      className={`rounded-2xl p-4 border-2 transition flex flex-col items-center gap-2 ${
                        sel ? "bg-[#E8F0E1] border-[#87A96B]" : "bg-[#FDFBF7] border-transparent hover:border-[#E2D8C9]"
                      }`}
                      data-testid={`fav-${f.v}`}
                    >
                      <Icon className={`w-6 h-6 ${sel ? "text-[#4F6B3B]" : "text-[#8A9AB0]"}`} />
                      <span className="font-body font-bold text-sm">{f.l}</span>
                    </button>
                  );
                })}
              </div>

              <div className="space-y-3 mb-5">
                {FAV_TYPES.filter((f) => data.personalization.favorites?.[f.v]?.selected).map((f) => (
                  <div key={f.v}>
                    <label className="block text-sm font-bold text-[#2D3748] mb-2 font-body">
                      تفاصيل {f.l}
                    </label>
                    <input
                      value={data.personalization.favorites?.[f.v]?.name || ""}
                      onChange={(e) => setFavName(f.v, e.target.value)}
                      placeholder={
                        f.v === "toy" ? "اسم اللعبة: مثلاً دب صغير"
                        : f.v === "place" ? "المكان المفضل: مثلاً حديقة البيت"
                        : f.v === "character" ? "الشخصية المفضلة"
                        : f.v === "hobby" ? "الهواية"
                        : "اذكر التفاصيل"
                      }
                      className="w-full bg-[#FDFBF7] border border-[#E2D8C9] rounded-2xl px-5 py-3 font-body"
                      data-testid={`fav-name-${f.v}`}
                    />
                    {f.v === "toy" && data.personalization.favorites?.toy?.selected && (
                      <div className="mt-3">
                        <ImageUploader
                          value={data.personalization.toy_image_url}
                          onChange={(url) => updatePers({ toy_image_url: url })}
                          scope="toy"
                          label="صورة اللعبة (اختياري)"
                          size="sm"
                          testId="toy-image"
                        />
                      </div>
                    )}
                  </div>
                ))}
              </div>

              <label className="block text-sm font-bold text-[#2D3748] mb-2 font-body">
                هل هناك تفاصيل خاصة تريد إضافتها للقصة؟
              </label>
              <textarea
                rows={3}
                value={data.personalization.custom_notes || ""}
                onChange={(e) => updatePers({ custom_notes: e.target.value })}
                placeholder="أي تفصيل خاص يُحب طفلك سماعه داخل القصة..."
                className="w-full bg-[#FDFBF7] border border-[#E2D8C9] rounded-2xl px-5 py-3 font-body"
                data-testid="custom-notes"
              />
            </div>
          )}

          {/* STEP 5 — Style */}
          {step === 5 && (
            <div data-testid="step-5-content">
              <h2 className="font-heading text-2xl md:text-3xl font-bold text-[#2D3748] mb-2">أسلوب القصة</h2>
              <p className="font-body text-[#5A677D] mb-6">كيف تحب أن تُروى القصة لطفلك؟</p>

              <DurationPicker
                seconds={data.duration?.seconds || 90}
                onChange={updateDuration}
              />

              <AudioBackgroundPicker
                mode={data.audio_background?.mode || "music"}
                onChange={updateAudioBg}
              />

              <OptionGroup label="نوع القصة" icon={Palette} items={options.type} value={data.style.type_id} onChange={(v) => updateStyle({ type_id: v })} testId="style-type" required />
              <OptionGroup label="النبرة" icon={Heart} items={options.tone} value={data.style.tone_id} onChange={(v) => updateStyle({ tone_id: v })} testId="style-tone" required />
              <OptionGroup label="البيئة" icon={MapPin} items={options.setting} value={data.style.setting_id} onChange={(v) => updateStyle({ setting_id: v })} testId="style-setting" />
              <OptionGroup label="اللغة" icon={Languages} items={options.language} value={data.style.language_id} onChange={(v) => updateStyle({ language_id: v })} testId="style-language" />
              <OptionGroup label="صوت الراوي" icon={Mic} items={options.voice} value={data.style.voice_id} onChange={(v) => updateStyle({ voice_id: v })} testId="style-voice" />
            </div>
          )}

          {/* STEP 6 — Review */}
          {step === 6 && (
            <Review data={data} categories={categories} options={options} />
          )}

          {/* Desktop actions */}
          <div className="hidden md:flex items-center justify-between mt-10 pt-6 border-t border-[#E2D8C9]">
            <button
              type="button"
              onClick={back}
              disabled={step === 1}
              className="inline-flex items-center gap-2 px-6 py-3 rounded-full font-body font-bold text-[#5A677D] disabled:opacity-30 hover:bg-[#F8F1E7]"
              data-testid="wizard-back-btn"
            >
              <ChevronRight className="w-4 h-4" /> السابق
            </button>
            {step < 6 ? (
              <button type="button" onClick={next} className="btn-primary inline-flex items-center gap-2" data-testid="wizard-next-btn">
                التالي <ChevronLeft className="w-4 h-4" />
              </button>
            ) : (
              <button type="button" onClick={submit} disabled={submitting} className="btn-primary inline-flex items-center gap-2 disabled:opacity-70" data-testid="wizard-submit-btn">
                <Sprout className="w-4 h-4" />
                {submitting ? "جاري الإرسال..." : "إرسال الطلب"}
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Sticky mobile action bar */}
      <div className="md:hidden fixed bottom-0 inset-x-0 bg-white/95 backdrop-blur border-t border-[#E2D8C9] p-3 flex items-center gap-3 z-30" data-testid="mobile-actions">
        <button
          type="button"
          onClick={back}
          disabled={step === 1}
          className="flex-1 rounded-full border border-[#E2D8C9] py-3 font-body font-bold text-[#5A677D] disabled:opacity-30"
        >
          السابق
        </button>
        {step < 6 ? (
          <button onClick={next} className="flex-[2] btn-primary">التالي</button>
        ) : (
          <button onClick={submit} disabled={submitting} className="flex-[2] btn-primary">
            {submitting ? "جاري الإرسال..." : "إرسال"}
          </button>
        )}
      </div>

      <Footer />
    </div>
  );
}

function DurationPicker({ seconds, onChange }) {
  const snapped = DURATION_SNAPS.includes(seconds)
    ? seconds
    : DURATION_SNAPS.reduce((a, b) => (Math.abs(b - seconds) < Math.abs(a - seconds) ? b : a), 90);
  const meta = DURATION_META[snapped];
  const cost = COST_TIER_META[meta.cost_tier];
  const idx = DURATION_SNAPS.indexOf(snapped);

  return (
    <div className="mb-6" data-testid="duration-picker">
      <label className="flex items-center justify-between mb-3">
        <span className="text-sm font-bold text-[#2D3748] font-body inline-flex items-center gap-2">
          <Clock className="w-4 h-4 text-[#729352]" />
          مدة الفيديو
        </span>
        <span className="text-sm font-heading font-bold text-[#4F6B3B] bg-[#E8F0E1] rounded-full px-3 py-1" data-testid="duration-label">
          {meta.label}
        </span>
      </label>

      <input
        type="range"
        min={0}
        max={DURATION_SNAPS.length - 1}
        step={1}
        value={idx}
        onChange={(e) => onChange(DURATION_SNAPS[parseInt(e.target.value)])}
        className="w-full accent-[#87A96B] cursor-pointer"
        data-testid="duration-slider"
      />

      <div className="flex items-center justify-between text-[10px] md:text-xs text-[#8A9AB0] font-body mt-1 px-1">
        {DURATION_SNAPS.map((s) => (
          <button
            type="button"
            key={s}
            onClick={() => onChange(s)}
            className={`${snapped === s ? "text-[#4F6B3B] font-bold" : "hover:text-[#5A677D]"}`}
            data-testid={`duration-snap-${s}`}
          >
            {s}ث
          </button>
        ))}
      </div>

      <div className="mt-4 grid grid-cols-2 gap-3">
        <div className="bg-[#FDFBF7] rounded-2xl px-4 py-3 border border-[#E2D8C9]">
          <div className="text-[11px] text-[#8A9AB0] font-body mb-1 inline-flex items-center gap-1">
            <Sparkles className="w-3 h-3" /> عدد المشاهد التقريبي
          </div>
          <div className="font-heading font-bold text-[#2D3748]" data-testid="duration-scene-target">
            {meta.scene_target} مشاهد
          </div>
        </div>
        <div className={`rounded-2xl px-4 py-3 border ${cost.color}`}>
          <div className="text-[11px] opacity-80 font-body mb-1 inline-flex items-center gap-1">
            <Coins className="w-3 h-3" /> تصنيف التكلفة
          </div>
          <div className="font-heading font-bold" data-testid="duration-cost-tier">
            {cost.label}
          </div>
        </div>
      </div>
    </div>
  );
}

function AudioBackgroundPicker({ mode, onChange }) {
  return (
    <div className="mb-6" data-testid="audio-bg-picker">
      <label className="flex items-center gap-2 mb-3">
        <Music className="w-4 h-4 text-[#729352]" />
        <span className="text-sm font-bold text-[#2D3748] font-body">الخلفية الصوتية</span>
      </label>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
        {AUDIO_BG_OPTIONS.map((opt) => {
          const Icon = opt.i;
          const selected = mode === opt.v;
          return (
            <button
              key={opt.v}
              type="button"
              onClick={() => onChange(opt.v)}
              className={`rounded-2xl p-3 border-2 transition-all text-right flex items-center gap-3 ${
                selected
                  ? "border-[#87A96B] bg-[#E8F0E1]"
                  : "border-[#E2D8C9] bg-white hover:border-[#87A96B]/50"
              }`}
              data-testid={`audio-bg-${opt.v}`}
            >
              <div className={`w-9 h-9 rounded-xl grid place-content-center ${selected ? "bg-white" : "bg-[#FDFBF7]"}`}>
                <Icon className={`w-4 h-4 ${selected ? "text-[#4F6B3B]" : "text-[#5A677D]"}`} />
              </div>
              <span className={`font-body text-sm font-bold ${selected ? "text-[#4F6B3B]" : "text-[#2D3748]"}`}>
                {opt.l}
              </span>
            </button>
          );
        })}
      </div>
      <p className="text-xs text-[#8A9AB0] font-body mt-2">
        يمكنك اختيار ما يناسب أسرتك، وسيتم اعتماد ذلك في النسخة النهائية من القصة.
      </p>
    </div>
  );
}

function OptionGroup({ label, icon: Icon, items, value, onChange, testId, required }) {
  if (!items?.length) return null;
  return (
    <div className="mb-5" data-testid={testId}>
      <label className="block text-sm font-bold text-[#2D3748] mb-2 font-body">
        <Icon className="inline w-4 h-4 ms-1 text-[#729352]" />
        {label} {required && <span className="text-[#E07A5F]">*</span>}
      </label>
      <div className="flex flex-wrap gap-2">
        {items.map((o) => (
          <button
            key={o.id}
            type="button"
            onClick={() => onChange(o.id)}
            className={`rounded-full px-4 py-2 text-sm font-body border-2 transition ${
              value === o.id
                ? "bg-[#87A96B] text-white border-[#87A96B]"
                : "bg-[#FDFBF7] text-[#2D3748] border-[#E2D8C9] hover:border-[#87A96B]"
            }`}
            data-testid={`${testId}-${o.value}`}
          >
            {o.name_ar}
          </button>
        ))}
      </div>
    </div>
  );
}

function Review({ data, categories, options }) {
  const cat = categories.find((c) => c.id === data.goal.category_id);
  const sub = cat?.subcategories?.find((s) => s.id === data.goal.subcategory_id);
  const findOpt = (kind, id) => (options[kind] || []).find((o) => o.id === id)?.name_ar || "—";
  const durSec = data.duration?.seconds || 90;
  const durMeta = DURATION_META[durSec] || DURATION_META[90];
  const audioBgMode = data.audio_background?.mode || "music";
  const audioBgLabel = (AUDIO_BG_OPTIONS.find((o) => o.v === audioBgMode) || AUDIO_BG_OPTIONS[0]).l;

  return (
    <div data-testid="step-6-content">
      <h2 className="font-heading text-2xl md:text-3xl font-bold text-[#2D3748] mb-2">مراجعة الطلب</h2>
      <p className="font-body text-[#5A677D] mb-6">تأكد من التفاصيل ثم اضغط "إرسال"</p>

      <div className="grid md:grid-cols-2 gap-3 mb-4">
        <Field label="التصنيف" value={cat?.name_ar || "—"} />
        <Field label="الموضوع" value={sub?.name_ar || data.goal.custom_subcategory || "—"} />
        <Field label="الطفل" value={`${data.child.name} • ${data.child.age} سنة • ${data.child.gender === "male" ? "ولد" : "بنت"}${data.child.hijab ? " (حجاب)" : ""}`} />
        <Field label="عدد الشخصيات" value={data.characters.length} />
        <Field label="نوع القصة" value={findOpt("type", data.style.type_id)} />
        <Field label="النبرة" value={findOpt("tone", data.style.tone_id)} />
        <Field label="البيئة" value={findOpt("setting", data.style.setting_id)} />
        <Field label="اللغة" value={findOpt("language", data.style.language_id)} />
        <Field label="مدة الفيديو" value={`${durMeta.label} • ~${durMeta.scene_target} مشاهد`} />
        <Field label="الخلفية الصوتية" value={audioBgLabel} />
      </div>

      <div className="bg-[#E8F0E1] rounded-2xl p-4 border border-[#87A96B]/30 mb-4">
        <div className="font-body text-xs font-bold text-[#4F6B3B] mb-1">الموقف الحقيقي</div>
        <p className="font-body text-[#2D3748] whitespace-pre-wrap">{data.goal.context}</p>
      </div>

      {data.personalization.custom_notes && (
        <div className="bg-[#F8F1E7] rounded-2xl p-4 border border-[#D4A373]/30 mb-4">
          <div className="font-body text-xs font-bold text-[#8B5A2B] mb-1">تفاصيل خاصة</div>
          <p className="font-body text-[#2D3748] whitespace-pre-wrap">{data.personalization.custom_notes}</p>
        </div>
      )}

      <details className="bg-[#FDFBF7] rounded-2xl p-4 border border-[#E2D8C9]">
        <summary className="font-body text-sm font-bold text-[#5A677D] cursor-pointer flex items-center gap-2">
          <FileText className="w-4 h-4" /> عرض البيانات الكاملة (JSON)
        </summary>
        <pre className="mt-3 text-xs overflow-x-auto bg-white p-3 rounded-xl">
          {JSON.stringify(data, null, 2)}
        </pre>
      </details>
    </div>
  );
}

function Field({ label, value }) {
  return (
    <div className="bg-[#FDFBF7] rounded-2xl p-3 border border-[#E2D8C9]">
      <div className="text-xs text-[#8A9AB0] font-body">{label}</div>
      <div className="font-body font-bold text-[#2D3748] text-sm">{value}</div>
    </div>
  );
}
