import React, { useEffect, useMemo, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import { useAuth } from "../contexts/AuthContext";
import Navbar from "../components/gheras/Navbar";
import Footer from "../components/gheras/Footer";
import {
  ChevronRight, ChevronLeft, Check, Sprout, User, Sparkles, BookOpen,
  PenTool, Heart, Sun, Award, Moon, Rocket, CheckCircle2,
} from "lucide-react";
import { toast } from "sonner";

const ICON_MAP = {
  sun: Sun, heart: Heart, award: Award, sparkles: Sparkles,
  moon: Moon, rocket: Rocket, "moon-star": Moon, "pen-tool": PenTool,
  sprout: Sprout,
};

const STEPS = [
  { id: 1, label: "الهدف", icon: Sprout },
  { id: 2, label: "طفلك", icon: User },
  { id: 3, label: "التخصيص", icon: Sparkles },
  { id: 4, label: "الأسلوب", icon: BookOpen },
  { id: 5, label: "المراجعة", icon: Check },
];

export default function StoryBuilder() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [step, setStep] = useState(1);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);

  const [categories, setCategories] = useState([]);
  const [styles, setStyles] = useState([]);

  const [categoryId, setCategoryId] = useState(location.state?.presetCategoryId || "");
  const [subcategoryId, setSubcategoryId] = useState("");
  const [customGoal, setCustomGoal] = useState("");

  const [child, setChild] = useState({
    name: "", age: 5, gender: "male", personality: "", interests: "", appearance: "",
  });
  const [personalization, setPersonalization] = useState({
    favorite_color: "", favorite_toy: "", parent_message: "", include_sibling: false,
  });
  const [styleId, setStyleId] = useState("");
  const [notes, setNotes] = useState("");

  useEffect(() => {
    Promise.all([api.get("/public/categories"), api.get("/public/styles")])
      .then(([c, s]) => {
        setCategories(c.data);
        setStyles(s.data);
      })
      .finally(() => setLoading(false));
  }, []);

  const selectedCategory = useMemo(
    () => categories.find((c) => c.id === categoryId),
    [categories, categoryId]
  );
  const selectedSubcat = useMemo(
    () => selectedCategory?.subcategories?.find((s) => s.id === subcategoryId),
    [selectedCategory, subcategoryId]
  );
  const selectedStyle = useMemo(
    () => styles.find((s) => s.id === styleId),
    [styles, styleId]
  );

  const canProceed = () => {
    if (step === 1) {
      if (!categoryId) return false;
      if (selectedCategory?.slug === "custom") return customGoal.trim().length >= 3;
      return !!subcategoryId || (selectedCategory?.subcategories?.length === 0 && customGoal.trim().length >= 3);
    }
    if (step === 2) return child.name.trim().length >= 1 && child.age >= 1 && child.age <= 14;
    if (step === 3) return true; // optional
    if (step === 4) return !!styleId;
    if (step === 5) return true;
    return false;
  };

  const next = () => {
    if (!canProceed()) {
      toast.error("الرجاء إكمال الحقول المطلوبة");
      return;
    }
    setStep((s) => Math.min(5, s + 1));
  };
  const back = () => setStep((s) => Math.max(1, s - 1));

  const submit = async () => {
    if (!user) {
      // save partial draft to localStorage
      localStorage.setItem("gheras_story_draft", JSON.stringify({
        categoryId, subcategoryId, customGoal, child, personalization, styleId, notes,
      }));
      toast("سجّل دخولك لإتمام الطلب 🌱");
      navigate("/login", { state: { from: { pathname: "/story/new" } } });
      return;
    }
    setSubmitting(true);
    try {
      const payload = {
        category_id: categoryId,
        subcategory_id: subcategoryId || null,
        custom_goal: customGoal || null,
        child,
        personalization,
        style_id: styleId,
        notes,
      };
      const { data } = await api.post("/orders", payload);
      toast.success("تم إرسال طلب القصة بنجاح 🌱");
      localStorage.removeItem("gheras_story_draft");
      navigate(`/orders/${data.id}`);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "تعذّر إنشاء الطلب");
    } finally {
      setSubmitting(false);
    }
  };

  // hydrate draft
  useEffect(() => {
    const raw = localStorage.getItem("gheras_story_draft");
    if (!raw) return;
    try {
      const d = JSON.parse(raw);
      if (d.categoryId) setCategoryId(d.categoryId);
      if (d.subcategoryId) setSubcategoryId(d.subcategoryId);
      if (d.customGoal) setCustomGoal(d.customGoal);
      if (d.child) setChild(d.child);
      if (d.personalization) setPersonalization(d.personalization);
      if (d.styleId) setStyleId(d.styleId);
      if (d.notes) setNotes(d.notes);
    } catch {}
  }, []);

  return (
    <div className="min-h-screen bg-[#FDFBF7]" data-testid="story-builder">
      <Navbar />

      <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-10 md:py-14">
        {/* Stepper */}
        <div className="mb-10" data-testid="wizard-stepper">
          <div className="flex items-center justify-between relative mb-4">
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
                  className={`relative z-10 w-10 h-10 rounded-full grid place-content-center font-bold font-body ring-4 ring-[#FDFBF7] transition ${
                    done
                      ? "bg-[#87A96B] text-white"
                      : active
                      ? "bg-[#87A96B] text-white shadow-md scale-110"
                      : "bg-white text-[#8A9AB0] border border-[#E2D8C9]"
                  }`}
                  data-testid={`step-indicator-${s.id}`}
                >
                  {done ? <Check className="w-5 h-5" /> : s.id}
                </div>
              );
            })}
          </div>
          <div className="flex items-center justify-between text-xs md:text-sm text-[#5A677D] font-body px-1">
            {STEPS.map((s) => (
              <span key={s.id} className={step === s.id ? "text-[#729352] font-bold" : ""}>
                {s.label}
              </span>
            ))}
          </div>
        </div>

        <div className="bg-white rounded-[2rem] p-6 md:p-10 border border-[#E2D8C9] shadow-sm min-h-[400px] animate-grow">
          {loading ? (
            <div className="text-center py-20 text-[#8A9AB0]">جاري التحميل...</div>
          ) : (
            <>
              {/* STEP 1 */}
              {step === 1 && (
                <div data-testid="step-1-content">
                  <h2 className="font-heading text-2xl md:text-3xl font-bold text-[#2D3748] mb-2">
                    اختر الهدف التربوي للقصة
                  </h2>
                  <p className="font-body text-[#5A677D] mb-8">
                    حدّد القيمة أو السلوك الذي تريد أن تغرسه في قلب طفلك
                  </p>

                  <div className="grid grid-cols-2 md:grid-cols-3 gap-4 mb-8">
                    {categories.map((c) => {
                      const Icon = ICON_MAP[c.icon] || BookOpen;
                      const sel = categoryId === c.id;
                      return (
                        <button
                          key={c.id}
                          type="button"
                          onClick={() => {
                            setCategoryId(c.id);
                            setSubcategoryId("");
                          }}
                          className={`rounded-3xl p-5 border-2 text-right transition-all card-lift ${
                            sel
                              ? "border-[#87A96B] bg-[#E8F0E1]"
                              : "border-transparent bg-[#FDFBF7] hover:border-[#E2D8C9]"
                          }`}
                          data-testid={`goal-cat-${c.slug}`}
                        >
                          <div
                            className="w-12 h-12 rounded-2xl grid place-content-center mb-3"
                            style={{ backgroundColor: `${c.color}20` }}
                          >
                            <Icon className="w-6 h-6" style={{ color: c.color }} />
                          </div>
                          <h3 className="font-heading font-bold text-[#2D3748] mb-1">{c.name_ar}</h3>
                          <p className="font-body text-xs text-[#8A9AB0]">
                            {c.subcategories?.length || 0} مواضيع
                          </p>
                        </button>
                      );
                    })}
                  </div>

                  {selectedCategory?.subcategories?.length > 0 && (
                    <div className="bg-[#FDFBF7] rounded-2xl p-5 border border-[#E2D8C9]">
                      <h3 className="font-heading text-lg font-bold text-[#2D3748] mb-4">
                        اختر موضوعاً في "{selectedCategory.name_ar}"
                      </h3>
                      <div className="flex flex-wrap gap-2">
                        {selectedCategory.subcategories.map((s) => (
                          <button
                            key={s.id}
                            type="button"
                            onClick={() => setSubcategoryId(s.id)}
                            className={`rounded-full px-4 py-2 text-sm font-body border-2 transition ${
                              subcategoryId === s.id
                                ? "bg-[#87A96B] text-white border-[#87A96B]"
                                : "bg-white text-[#2D3748] border-[#E2D8C9] hover:border-[#87A96B]"
                            }`}
                            data-testid={`subcat-${s.id}`}
                          >
                            {s.name_ar}
                          </button>
                        ))}
                      </div>
                    </div>
                  )}

                  {(selectedCategory?.slug === "custom" ||
                    selectedCategory?.subcategories?.length === 0) && selectedCategory && (
                    <div className="mt-5">
                      <label className="block text-sm font-bold text-[#2D3748] mb-2 font-body">
                        اكتب الهدف بنفسك
                      </label>
                      <textarea
                        value={customGoal}
                        onChange={(e) => setCustomGoal(e.target.value)}
                        rows={3}
                        placeholder="مثال: تعليم طفلي كيف يتعامل مع خوفه من الظلام"
                        className="w-full bg-[#FDFBF7] border border-[#E2D8C9] rounded-2xl px-5 py-3 font-body focus:outline-none focus:ring-2 focus:ring-[#87A96B]"
                        data-testid="custom-goal-textarea"
                      />
                    </div>
                  )}
                </div>
              )}

              {/* STEP 2 */}
              {step === 2 && (
                <div data-testid="step-2-content">
                  <h2 className="font-heading text-2xl md:text-3xl font-bold text-[#2D3748] mb-2">
                    أخبرنا عن طفلك
                  </h2>
                  <p className="font-body text-[#5A677D] mb-8">
                    هذه المعلومات تجعل القصة شخصية حقاً
                  </p>
                  <div className="grid md:grid-cols-2 gap-5">
                    <div>
                      <label className="block text-sm font-bold text-[#2D3748] mb-2 font-body">اسم الطفل *</label>
                      <input
                        value={child.name}
                        onChange={(e) => setChild({ ...child, name: e.target.value })}
                        placeholder="مثلاً: يوسف"
                        className="w-full bg-[#FDFBF7] border border-[#E2D8C9] rounded-2xl px-5 py-3 font-body focus:outline-none focus:ring-2 focus:ring-[#87A96B]"
                        data-testid="child-name"
                      />
                    </div>
                    <div>
                      <label className="block text-sm font-bold text-[#2D3748] mb-2 font-body">العمر *</label>
                      <input
                        type="number"
                        min={1}
                        max={14}
                        value={child.age}
                        onChange={(e) => setChild({ ...child, age: parseInt(e.target.value || "0") })}
                        className="w-full bg-[#FDFBF7] border border-[#E2D8C9] rounded-2xl px-5 py-3 font-body focus:outline-none focus:ring-2 focus:ring-[#87A96B]"
                        data-testid="child-age"
                      />
                    </div>
                    <div className="md:col-span-2">
                      <label className="block text-sm font-bold text-[#2D3748] mb-2 font-body">الجنس *</label>
                      <div className="flex gap-3">
                        {[
                          { v: "male", l: "ولد" },
                          { v: "female", l: "بنت" },
                        ].map((g) => (
                          <button
                            key={g.v}
                            type="button"
                            onClick={() => setChild({ ...child, gender: g.v })}
                            className={`flex-1 rounded-2xl py-3 font-body font-bold border-2 transition ${
                              child.gender === g.v
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
                    <div>
                      <label className="block text-sm font-bold text-[#2D3748] mb-2 font-body">شخصية الطفل</label>
                      <input
                        value={child.personality}
                        onChange={(e) => setChild({ ...child, personality: e.target.value })}
                        placeholder="خجول، مرح، فضولي..."
                        className="w-full bg-[#FDFBF7] border border-[#E2D8C9] rounded-2xl px-5 py-3 font-body focus:outline-none focus:ring-2 focus:ring-[#87A96B]"
                        data-testid="child-personality"
                      />
                    </div>
                    <div>
                      <label className="block text-sm font-bold text-[#2D3748] mb-2 font-body">الاهتمامات</label>
                      <input
                        value={child.interests}
                        onChange={(e) => setChild({ ...child, interests: e.target.value })}
                        placeholder="كرة قدم، ديناصورات..."
                        className="w-full bg-[#FDFBF7] border border-[#E2D8C9] rounded-2xl px-5 py-3 font-body focus:outline-none focus:ring-2 focus:ring-[#87A96B]"
                        data-testid="child-interests"
                      />
                    </div>
                    <div className="md:col-span-2">
                      <label className="block text-sm font-bold text-[#2D3748] mb-2 font-body">وصف ملامح الطفل (اختياري)</label>
                      <input
                        value={child.appearance}
                        onChange={(e) => setChild({ ...child, appearance: e.target.value })}
                        placeholder="شعر أسود قصير، عيون بنية..."
                        className="w-full bg-[#FDFBF7] border border-[#E2D8C9] rounded-2xl px-5 py-3 font-body focus:outline-none focus:ring-2 focus:ring-[#87A96B]"
                        data-testid="child-appearance"
                      />
                    </div>
                  </div>
                </div>
              )}

              {/* STEP 3 */}
              {step === 3 && (
                <div data-testid="step-3-content">
                  <h2 className="font-heading text-2xl md:text-3xl font-bold text-[#2D3748] mb-2">
                    تخصيصات إضافية (اختياري)
                  </h2>
                  <p className="font-body text-[#5A677D] mb-8">
                    تفاصيل صغيرة تجعل القصة أكثر دفئاً
                  </p>
                  <div className="grid md:grid-cols-2 gap-5">
                    <div>
                      <label className="block text-sm font-bold text-[#2D3748] mb-2 font-body">اللون المفضل</label>
                      <input
                        value={personalization.favorite_color}
                        onChange={(e) => setPersonalization({ ...personalization, favorite_color: e.target.value })}
                        placeholder="أخضر، أزرق..."
                        className="w-full bg-[#FDFBF7] border border-[#E2D8C9] rounded-2xl px-5 py-3 font-body focus:outline-none focus:ring-2 focus:ring-[#87A96B]"
                        data-testid="fav-color"
                      />
                    </div>
                    <div>
                      <label className="block text-sm font-bold text-[#2D3748] mb-2 font-body">اللعبة/الرفيق المفضل</label>
                      <input
                        value={personalization.favorite_toy}
                        onChange={(e) => setPersonalization({ ...personalization, favorite_toy: e.target.value })}
                        placeholder="دمية دب، سيارة حمراء..."
                        className="w-full bg-[#FDFBF7] border border-[#E2D8C9] rounded-2xl px-5 py-3 font-body focus:outline-none focus:ring-2 focus:ring-[#87A96B]"
                        data-testid="fav-toy"
                      />
                    </div>
                    <div className="md:col-span-2">
                      <label className="block text-sm font-bold text-[#2D3748] mb-2 font-body">رسالة من الأهل (داخل القصة)</label>
                      <textarea
                        value={personalization.parent_message}
                        onChange={(e) => setPersonalization({ ...personalization, parent_message: e.target.value })}
                        rows={3}
                        placeholder="كلمة أو درس تحب أن يسمعه طفلك في نهاية القصة"
                        className="w-full bg-[#FDFBF7] border border-[#E2D8C9] rounded-2xl px-5 py-3 font-body focus:outline-none focus:ring-2 focus:ring-[#87A96B]"
                        data-testid="parent-message"
                      />
                    </div>
                    <div className="md:col-span-2">
                      <label className="flex items-center gap-3 cursor-pointer">
                        <input
                          type="checkbox"
                          checked={personalization.include_sibling}
                          onChange={(e) => setPersonalization({ ...personalization, include_sibling: e.target.checked })}
                          className="w-5 h-5 accent-[#87A96B]"
                          data-testid="include-sibling"
                        />
                        <span className="font-body text-[#2D3748]">أضِف أخاً أو أختاً للبطل</span>
                      </label>
                    </div>
                  </div>
                </div>
              )}

              {/* STEP 4 */}
              {step === 4 && (
                <div data-testid="step-4-content">
                  <h2 className="font-heading text-2xl md:text-3xl font-bold text-[#2D3748] mb-2">
                    اختر أسلوب القصة
                  </h2>
                  <p className="font-body text-[#5A677D] mb-8">الأسلوب الذي يناسب طفلك أكثر</p>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    {styles.map((s) => {
                      const sel = styleId === s.id;
                      return (
                        <button
                          key={s.id}
                          type="button"
                          onClick={() => setStyleId(s.id)}
                          className={`text-right rounded-3xl p-6 border-2 transition card-lift ${
                            sel
                              ? "bg-[#E8F0E1] border-[#87A96B]"
                              : "bg-[#FDFBF7] border-transparent hover:border-[#E2D8C9]"
                          }`}
                          data-testid={`style-${s.id}`}
                        >
                          <div className="w-12 h-12 rounded-2xl bg-white border border-[#E2D8C9] grid place-content-center mb-4">
                            <BookOpen className="w-6 h-6 text-[#729352]" />
                          </div>
                          <h3 className="font-heading text-xl font-bold text-[#2D3748] mb-1">{s.name_ar}</h3>
                          <p className="font-body text-sm text-[#5A677D]">{s.description}</p>
                          {sel && (
                            <div className="mt-3 inline-flex items-center gap-1 text-[#4F6B3B] text-xs font-bold">
                              <CheckCircle2 className="w-4 h-4" /> مختار
                            </div>
                          )}
                        </button>
                      );
                    })}
                  </div>
                </div>
              )}

              {/* STEP 5 */}
              {step === 5 && (
                <div data-testid="step-5-content">
                  <h2 className="font-heading text-2xl md:text-3xl font-bold text-[#2D3748] mb-2">
                    مراجعة الطلب
                  </h2>
                  <p className="font-body text-[#5A677D] mb-8">
                    راجع التفاصيل قبل الإرسال — ستصل لفريقنا لبدء العمل
                  </p>

                  <div className="space-y-4">
                    <SummaryRow label="التصنيف" value={selectedCategory?.name_ar || "—"} testId="sum-cat" />
                    <SummaryRow
                      label="الموضوع"
                      value={selectedSubcat?.name_ar || customGoal || "—"}
                      testId="sum-sub"
                    />
                    <SummaryRow label="اسم الطفل" value={child.name} testId="sum-child-name" />
                    <SummaryRow label="العمر" value={`${child.age} سنة`} testId="sum-child-age" />
                    <SummaryRow label="الجنس" value={child.gender === "male" ? "ولد" : "بنت"} testId="sum-child-gender" />
                    {child.personality && <SummaryRow label="الشخصية" value={child.personality} />}
                    {child.interests && <SummaryRow label="الاهتمامات" value={child.interests} />}
                    <SummaryRow label="الأسلوب" value={selectedStyle?.name_ar || "—"} testId="sum-style" />
                    {personalization.parent_message && (
                      <SummaryRow label="رسالة الأهل" value={personalization.parent_message} />
                    )}
                  </div>

                  <div className="mt-6">
                    <label className="block text-sm font-bold text-[#2D3748] mb-2 font-body">
                      ملاحظات إضافية (اختياري)
                    </label>
                    <textarea
                      value={notes}
                      onChange={(e) => setNotes(e.target.value)}
                      rows={3}
                      placeholder="أي تفاصيل تحب أن تصل للفريق"
                      className="w-full bg-[#FDFBF7] border border-[#E2D8C9] rounded-2xl px-5 py-3 font-body focus:outline-none focus:ring-2 focus:ring-[#87A96B]"
                      data-testid="final-notes"
                    />
                  </div>
                </div>
              )}
            </>
          )}

          {/* Actions */}
          <div className="flex items-center justify-between mt-10 pt-6 border-t border-[#E2D8C9]">
            <button
              type="button"
              onClick={back}
              disabled={step === 1}
              className="inline-flex items-center gap-2 px-6 py-3 rounded-full font-body font-bold text-[#5A677D] disabled:opacity-30 hover:bg-[#F8F1E7]"
              data-testid="wizard-back-btn"
            >
              <ChevronRight className="w-4 h-4" /> السابق
            </button>

            {step < 5 ? (
              <button
                type="button"
                onClick={next}
                className="btn-primary inline-flex items-center gap-2"
                data-testid="wizard-next-btn"
              >
                التالي <ChevronLeft className="w-4 h-4" />
              </button>
            ) : (
              <button
                type="button"
                onClick={submit}
                disabled={submitting}
                className="btn-primary inline-flex items-center gap-2 disabled:opacity-70"
                data-testid="wizard-submit-btn"
              >
                <Sprout className="w-4 h-4" />
                {submitting ? "جاري الإرسال..." : "إرسال الطلب"}
              </button>
            )}
          </div>
        </div>
      </div>
      <Footer />
    </div>
  );
}

function SummaryRow({ label, value, testId }) {
  return (
    <div className="flex items-center justify-between bg-[#FDFBF7] rounded-2xl px-5 py-3 border border-[#E2D8C9]" data-testid={testId}>
      <span className="font-body text-sm text-[#5A677D]">{label}</span>
      <span className="font-body font-bold text-[#2D3748] text-right">{value}</span>
    </div>
  );
}
