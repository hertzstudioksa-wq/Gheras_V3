import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, fileSrc } from "../lib/api";
import { useSiteContent, whatsappLink } from "../lib/siteContent";
import { usePageTitle } from "../lib/usePageTitle";
import { topicsLabel } from "../lib/arabic";
import Navbar from "../components/gheras/Navbar";
import Footer from "../components/gheras/Footer";
import {
  Sprout, Heart, Shield, Sparkles, ArrowLeft, PlayCircle, BookOpen, Sun, Award, Moon, Rocket,
  PenTool, Star, Clapperboard, Mic, Music, Clock, ShieldCheck, Lock, Trash2, Users, Play, ChevronDown,
  MessageCircle, CreditCard,
} from "lucide-react";

const ICON_MAP = {
  sun: Sun, heart: Heart, award: Award, sparkles: Sparkles,
  moon: Moon, rocket: Rocket, "moon-star": Moon, "pen-tool": PenTool,
  shield: Shield, sprout: Sprout, star: Star,
};

const LOGO_URL = "/gheras-logo.png";
// A made-up family drawn in the house style (no customer's photos).
const HERO_IMG = "/brand/hero-family.webp";

const DELIVERABLES = [
  { icon: Clapperboard, title: "فيلم كرتون قصير", desc: "من 30 ثانية إلى 3 دقائق، طفلك بطله بملامحه ولبسه، ومعه من تختار من العائلة.", color: "#E07A5F" },
  { icon: Mic, title: "صوت راوٍ وموسيقى", desc: "سرد دافئ بالفصحى المبسّطة أو باللهجة التي تختارها، وموسيقى هادئة تناسب الحكاية.", color: "#8B5A2B" },
  { icon: BookOpen, title: "كتاب مصوّر", desc: "صفحات بنص مشكول ورسوم من الفيلم، بصيغة PDF جاهزة للطباعة والقراءة قبل النوم.", color: "#729352" },
  { icon: Award, title: "شهادة باسمه", desc: "صفحة في آخر الكتاب تحتفي بالقيمة التي تعلّمها طفلك من قصته.", color: "#D4A373" },
];

const TRUST = [
  { icon: Trash2, title: "صور طفلك تُحذف تلقائياً", desc: "الصور الأصلية تُحذف بعد 30 يوماً من التسليم، ويمكنك حذفها بنفسك قبل ذلك." },
  { icon: Lock, title: "قصته لا يراها غيرك", desc: "لا نستخدم صور طفلك في أي إعلان، والمشاركة برابط خاص تلغيه متى شئت." },
  { icon: ShieldCheck, title: "محتوى آمن للأطفال", desc: "نفحص الطلب ونص الحكاية بقواعد أمان الأطفال، ونراجع كل مشهد آلياً قبل التسليم." },
  { icon: Shield, title: "دفع آمن", desc: "بيانات البطاقة تُدخل في صفحة ميسر مباشرة ولا تصل إلينا." },
];

const FAQ = [
  ["كم يستغرق تجهيز القصة؟",
    "الحكايات الثلاث المقترحة تجهز خلال دقيقة تقريباً. وبعد أن تعتمد خطة المشاهد، يجهز الفيلم والكتاب عادةً خلال 30 إلى 60 دقيقة حسب المدة، وتتابع التقدّم لحظة بلحظة."],
  ["هل ستشبه الشخصية طفلي فعلاً؟",
    "نرسم شخصية طفلك أولاً من صورته (الملامح والشعر ولون البشرة واللبس) ثم نستخدمها في كل المشاهد. الرسم مستوحى من الصورة وليس نسخة طبق الأصل."],
  ["ما الصورة المناسبة؟",
    "صورة حديثة يظهر فيها الوجه بوضوح وبإضاءة جيدة، بلا نظارة شمسية ولا فلاتر، ويفضّل أن يظهر فيها لبسه المعتاد."],
  ["بأي لغة يكون السرد؟",
    "بالعربية الفصحى المبسّطة أو باللهجة السعودية/الخليجية أو المصرية، وتختار صوت الراوي."],
  ["متى أدفع؟",
    "تبدأ مجاناً: تكتب لنا عن طفلك ونقترح عليك ثلاث حكايات. لا تدفع إلا بعد أن تختار الحكاية، ويظهر السعر كاملاً قبل الدفع."],
  ["ماذا لو وجدت خطأ في القصة؟",
    "إذا وجدت عيباً واضحاً في مشهد (مثل تكرار شخصية أو تشوّه) أبلغنا من صفحة القصة خلال 14 يوماً، وسنعيد المشهد دون مقابل أو نعيد المبلغ."],
  ["كيف أشارك القصة مع العائلة؟",
    "من صفحة القصة تنشئ رابط مشاهدة خاصاً ترسله على واتساب للجدّ والجدّة، وتلغيه متى أردت."],
];

/** The sample story: its cover with a play button; it plays with sound on tap
 * (the narration is the point — a muted autoplay showed silent slides) and the
 * file only downloads once the visitor asks for it. */
function ShowcaseVideo({ src, poster }) {
  const [playing, setPlaying] = useState(false);
  return (
    <div className="relative rounded-[2rem] overflow-hidden border-8 border-white shadow-2xl bg-[#2D3748] max-w-3xl mx-auto mb-10 aspect-video"
      data-testid="showcase-player">
      {playing ? (
        <video src={src} poster={poster || undefined} className="absolute inset-0 w-full h-full" controls playsInline autoPlay
          data-testid="showcase-video" />
      ) : (
        <button type="button" onClick={() => setPlaying(true)} className="group absolute inset-0 w-full h-full"
          aria-label="شغّل قصة يمان بالصوت" data-testid="showcase-play">
          {poster && <img src={poster} alt="" className="absolute inset-0 w-full h-full object-cover" />}
          <span className="absolute inset-0 group-hover:bg-black/10 transition" />
          {/* bottom-left, clear of the faces and of the title baked into the cover */}
          <span className="absolute left-3 bottom-3 sm:left-5 sm:bottom-5 inline-flex items-center gap-2 rounded-full bg-white/95 shadow-xl
            pl-4 pr-1.5 py-1.5 sm:pl-5 sm:pr-2 sm:py-2 group-hover:scale-105 transition" dir="rtl">
            <span className="w-9 h-9 sm:w-11 sm:h-11 rounded-full bg-[#87A96B] grid place-content-center">
              {/* ▶ points right in every language (a media convention, not text direction) */}
              <Play className="w-4 h-4 sm:w-5 sm:h-5 text-white fill-white ml-0.5" />
            </span>
            <span className="font-heading font-bold text-[#2D3748] text-sm sm:text-base">شاهد بالصوت</span>
          </span>
        </button>
      )}
    </div>
  );
}

function useStartingPrices() {
  const [prices, setPrices] = useState(null);
  useEffect(() => {
    const quote = (seconds, output) => api.get("/public/story-price", { params: { seconds, output_type: output } })
      .then((r) => r.data.tiers || []);
    Promise.all([quote(30, "pdf"), quote(30, "both"), quote(60, "both")])
      .then(([book, short, long]) => setPrices({ book: book[0], short: short[0], long: long[0] }))
      .catch(() => setPrices(null));
  }, []);
  return prices;
}

function Price({ quote }) {
  if (!quote) return <span className="font-heading text-3xl font-bold text-[#2D3748]">—</span>;
  return (
    <span className="font-heading text-4xl font-bold text-[#2D3748]">
      {Math.round(quote.total_sar)} <span className="text-lg text-[#5A677D] font-body">ر.س</span>
    </span>
  );
}

export default function Landing() {
  usePageTitle();
  const content = useSiteContent();
  const [categories, setCategories] = useState([]);
  const prices = useStartingPrices();
  const [cardPayments, setCardPayments] = useState(false);

  useEffect(() => {
    api.get("/public/categories").then((r) => setCategories(r.data)).catch(() => {});
    api.get("/public/payment-methods").then((r) => setCardPayments(!!r.data?.card)).catch(() => {});
  }, []);

  const values = content["values.items"] || [
    { icon: "heart", title: "مصممة بحب", desc: "كل تفصيلة تراعي قلب طفلك" },
    { icon: "shield", title: "محتوى آمن", desc: "نفحص طلبك ونص القصة بقواعد أمان الأطفال قبل ما نرسمها" },
    { icon: "sprout", title: "تربية بالقصة", desc: "القيم تُغرس بحنان" },
    { icon: "sparkles", title: "تجربة فريدة", desc: "طفلك بطل القصة" },
  ];
  const vatNote = prices?.short?.vat_rate > 0 && !prices.short.vat_included ? " شاملة ضريبة القيمة المضافة" : "";
  // The admin's sample (نصوص الموقع ← عينة الصفحة الرئيسية); hidden while empty.
  const sampleVideo = content["showcase.video_url"];
  const sampleSteps = ["step1_image", "step2_image", "step3_image"].map((k) => content[`showcase.${k}`]).filter(Boolean);
  const whatsapp = whatsappLink(content["business.phone"]);
  // A real story's cover when the admin set one, else the house-style sample.
  const heroImage = content["hero.image_url"] ? fileSrc(content["hero.image_url"]) : HERO_IMG;
  const heroCaption = content["hero.image_url"] ? content["hero.image_caption"] : "";

  return (
    <div className="min-h-screen bg-[#FDFBF7]" data-testid="landing-page">
      <Navbar />

      {/* HERO */}
      <section className="relative overflow-hidden" data-testid="hero-section">
        <div className="absolute top-20 -left-20 w-72 h-72 bg-[#E8F0E1] blob-shape opacity-60 -z-10" />
        <div className="absolute bottom-10 -right-20 w-80 h-80 bg-[#F2E8DA] blob-shape opacity-60 -z-10" />

        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 pt-10 pb-16 md:py-24 grid md:grid-cols-2 gap-10 md:gap-12 items-center">
          <div className="animate-grow">
            <div className="inline-flex items-center gap-2 bg-[#E8F0E1] text-[#4F6B3B] px-4 py-2 rounded-full text-sm font-bold mb-6">
              <Sparkles className="w-4 h-4" />
              <span>فيلم كرتون + كتاب مصوّر بطلهما طفلك</span>
            </div>
            <h1 className="font-heading text-4xl sm:text-5xl lg:text-6xl font-bold text-[#2D3748] leading-tight mb-6">
              {content["hero.title"] || "نَغرِس القِيَم بقِصصٍ بَطلُها طِفلُك"}
            </h1>
            <p className="font-body text-lg text-[#5A677D] leading-relaxed mb-8 max-w-lg">
              {content["hero.subtitle"] ||
                "منصة غِراس تصنع لطفلك قصصاً شخصيّة، تعلّمه القيم وتعدّل سلوكياته بحب."}
            </p>
            <div className="flex flex-wrap gap-3 sm:gap-4 mb-6">
              <Link to="/story/new" className="btn-primary inline-flex items-center gap-2 animate-ring" data-testid="hero-cta-primary">
                <Sprout className="w-5 h-5" />
                {content["hero.cta_primary"] || "ابدأ أول قصة لطفلك"}
              </Link>
              <a
                href="#what-you-get"
                className="inline-flex items-center gap-2 px-7 py-3 rounded-full border-2 border-[#87A96B] text-[#729352] font-bold hover:bg-[#E8F0E1] transition"
                data-testid="hero-cta-secondary"
              >
                <PlayCircle className="w-5 h-5" />
                ماذا ستستلم؟
              </a>
            </div>
            <ul className="flex flex-wrap gap-x-5 gap-y-2 font-body text-sm text-[#5A677D]">
              <li className="inline-flex items-center gap-1.5"><Clock className="w-4 h-4 text-[#87A96B]" /> جاهزة خلال ساعة تقريباً</li>
              <li className="inline-flex items-center gap-1.5"><Sparkles className="w-4 h-4 text-[#87A96B]" /> تبدأ مجاناً وتدفع بعد اختيار الحكاية</li>
            </ul>
          </div>

          <div className="relative animate-grow delay-2">
            <div className="absolute -inset-4 bg-[#E8F0E1] blob-shape opacity-50 -z-10" />
            {/* A real story's cover (admin: نصوص الموقع ← hero.image_url), one caption and a real
                link to the sample video — no fake player bar or floating notes. */}
            <a href={sampleVideo ? "#showcase" : "#what-you-get"} data-testid="hero-visual"
              className="group block relative rounded-[2.25rem] overflow-hidden shadow-2xl border-8 border-white bg-white">
              <img src={heroImage} alt={heroCaption || "رسم كرتوني لعائلة بأسلوب غِراس"} className="w-full aspect-[16/10] object-cover" />
              {heroCaption && (
                <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/65 via-black/30 to-transparent pt-20 pb-4 px-4 sm:px-6 flex items-end justify-between gap-3">
                  <div className="text-white min-w-0">
                    <p className="font-body text-xs sm:text-sm opacity-90">قصة حقيقية من غِراس</p>
                    <p className="font-heading font-bold text-xl sm:text-2xl leading-tight truncate">{heroCaption}</p>
                  </div>
                  {sampleVideo && (
                    <span className="shrink-0 inline-flex items-center gap-2 rounded-full bg-white/95 shadow-lg pl-4 pr-1.5 py-1.5 group-hover:scale-105 transition">
                      <span className="w-8 h-8 rounded-full bg-[#87A96B] grid place-content-center">
                        <Play className="w-4 h-4 text-white fill-white ml-0.5" />
                      </span>
                      <span className="font-heading font-bold text-[#2D3748] text-sm">شاهد</span>
                    </span>
                  )}
                </div>
              )}
            </a>
            <ul className="mt-5 flex flex-wrap justify-center gap-2 font-body text-sm text-[#2D3748]" data-testid="hero-includes">
              {[[Clapperboard, "فيلم كرتون"], [BookOpen, "كتاب مصوّر"], [Music, "صوت راوٍ وموسيقى"]].map(([Icon, label]) => (
                <li key={label} className="inline-flex items-center gap-1.5 rounded-full bg-white border border-[#E2D8C9] px-3.5 py-1.5 shadow-sm">
                  <Icon className="w-4 h-4 text-[#729352]" /> {label}
                </li>
              ))}
            </ul>
          </div>
        </div>
      </section>

      {/* SAMPLE — what the admin uploaded */}
      {(sampleVideo || sampleSteps.length === 3) && (
        <section id="showcase" className="py-14 md:py-20 scroll-mt-20" data-testid="showcase-section">
          <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 text-center">
            <h2 className="font-heading text-3xl sm:text-4xl font-bold text-[#2D3748] mb-3">
              {content["showcase.title"] || "شاهد قصة من غِراس"}
            </h2>
            {content["showcase.caption"] && (
              <p className="font-body text-lg text-[#5A677D] mb-8 max-w-2xl mx-auto">{content["showcase.caption"]}</p>
            )}
            {sampleVideo && (
              <ShowcaseVideo src={fileSrc(sampleVideo)}
                poster={content["showcase.poster_url"] ? fileSrc(content["showcase.poster_url"]) : ""} />
            )}
            {sampleSteps.length === 3 && (
              <div className="grid grid-cols-[1fr_auto_1fr_auto_1fr] items-center gap-1.5 sm:gap-4" data-testid="showcase-steps">
                {sampleSteps.map((src, i) => (
                  <React.Fragment key={src}>
                    <figure className="bg-white rounded-2xl sm:rounded-3xl p-1.5 sm:p-3 border border-[#E2D8C9]">
                      <img src={fileSrc(src)} alt="" loading="lazy" className="w-full aspect-square object-cover rounded-xl sm:rounded-2xl" />
                      <figcaption className="font-heading font-bold text-[#2D3748] mt-2 sm:mt-3 text-xs sm:text-base leading-tight">
                        {["صورة الطفل", "شخصيته الكرتونية", "مشهد من قصته"][i]}
                      </figcaption>
                    </figure>
                    {i < 2 && <ArrowLeft className="w-4 h-4 sm:w-6 sm:h-6 text-[#87A96B] mx-auto" />}
                  </React.Fragment>
                ))}
              </div>
            )}
          </div>
        </section>
      )}

      {/* WHAT YOU GET */}
      <section id="what-you-get" className="py-16 md:py-24 bg-white scroll-mt-20" data-testid="deliverables-section">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="text-center max-w-2xl mx-auto mb-12">
            <h2 className="font-heading text-3xl sm:text-4xl font-bold text-[#2D3748] mb-4">ماذا ستستلم؟</h2>
            <p className="font-body text-lg text-[#5A677D]">قصة واحدة، تُشاهَد وتُقرأ وتُحفظ للذكرى</p>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5">
            {DELIVERABLES.map(({ icon: Icon, title, desc, color }, i) => (
              <div key={title} className="bg-[#FDFBF7] rounded-3xl p-6 border border-[#E2D8C9] card-lift animate-grow" style={{ animationDelay: `${i * 0.08}s` }}>
                <div className="w-12 h-12 rounded-2xl grid place-content-center mb-4" style={{ backgroundColor: `${color}22` }}>
                  <Icon className="w-6 h-6" style={{ color }} />
                </div>
                <h3 className="font-heading text-xl font-bold text-[#2D3748] mb-2">{title}</h3>
                <p className="font-body text-sm text-[#5A677D] leading-relaxed">{desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* HOW IT WORKS */}
      <section className="py-16 md:py-24" data-testid="how-it-works-preview">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="text-center max-w-2xl mx-auto mb-14">
            <h2 className="font-heading text-3xl sm:text-4xl font-bold text-[#2D3748] mb-4">
              {content["how.title"] || "كيف تعمل غِراس؟"}
            </h2>
            <p className="font-body text-lg text-[#5A677D]">
              {content["how.subtitle"] || "أربع خطوات بسيطة تفصلك عن قصة لن ينساها طفلك"}
            </p>
          </div>
          <div className="grid sm:grid-cols-2 md:grid-cols-4 gap-x-6 gap-y-10">
            {[1, 2, 3, 4].map((i) => (
              <div key={i} className="bg-white rounded-3xl p-7 border border-[#E2D8C9] card-lift relative animate-grow"
                style={{ animationDelay: `${i * 0.1}s` }} data-testid={`how-step-${i}`}>
                <div className="absolute -top-6 right-7 w-12 h-12 rounded-full bg-[#87A96B] text-white grid place-content-center font-heading text-xl font-bold shadow-lg">
                  {i}
                </div>
                <h3 className="font-heading text-xl font-bold text-[#2D3748] mb-2 mt-2">
                  {content[`how.step${i}.title`] || `الخطوة ${i}`}
                </h3>
                <p className="font-body text-[#5A677D] text-sm leading-relaxed">{content[`how.step${i}.desc`] || ""}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* PRICING */}
      <section className="py-16 md:py-24 bg-[#F8F1E7]" data-testid="pricing-section">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="text-center max-w-2xl mx-auto mb-12">
            <h2 className="font-heading text-3xl sm:text-4xl font-bold text-[#2D3748] mb-4">الأسعار</h2>
            <p className="font-body text-lg text-[#5A677D]">تبدأ مجاناً، ولا تدفع إلا بعد اختيار الحكاية. السعر يظهر كاملاً قبل الدفع{vatNote}.</p>
          </div>
          <div className="grid md:grid-cols-3 gap-5">
            {[
              { key: "book", title: "الكتاب المصوّر", sub: "كتاب PDF مشكول ومصوّر، جاهز للطباعة", from: false,
                items: ["رسوم بأسلوب كرتوني دافئ", "نص مشكول مناسب للعمر", "شهادة باسم طفلك"] },
              { key: "short", title: "فيلم قصير + الكتاب", sub: "فيلم 30 ثانية مع الكتاب المصوّر", from: true, featured: true,
                items: ["فيلم كرتون بصوت راوٍ وموسيقى", "الكتاب المصوّر معه", "رابط خاص لمشاركة العائلة"] },
              { key: "long", title: "حكاية أطول", sub: "فيلم دقيقة كاملة مع الكتاب", from: true,
                items: ["مشاهد أكثر وتفاصيل أغنى", "حتى 3 دقائق حسب اختيارك", "جودة فاخرة لحركة أنعم (اختياري)"] },
            ].map((plan) => (
              <div key={plan.key} className={`rounded-3xl p-7 border flex flex-col ${plan.featured ? "bg-white border-[#87A96B] border-2 shadow-xl md:-translate-y-2" : "bg-white/80 border-[#E2D8C9]"}`}
                data-testid={`price-${plan.key}`}>
                <h3 className="font-heading text-2xl font-bold text-[#2D3748] mb-1">{plan.title}</h3>
                <p className="font-body text-sm text-[#5A677D] mb-5">{plan.sub}</p>
                <div className="mb-5">
                  {plan.from && <span className="font-body text-sm text-[#5A677D] ml-1">من</span>}
                  <Price quote={prices?.[plan.key]} />
                </div>
                <ul className="space-y-2 font-body text-sm text-[#2D3748] mb-6 flex-1">
                  {plan.items.map((it) => (
                    <li key={it} className="flex items-start gap-2"><Sparkles className="w-4 h-4 text-[#87A96B] shrink-0 mt-0.5" />{it}</li>
                  ))}
                </ul>
                <Link to="/story/new" className={plan.featured ? "btn-primary text-center" : "text-center rounded-full border-2 border-[#87A96B] text-[#729352] font-bold py-2.5 hover:bg-[#E8F0E1]"}>
                  ابدأ مجاناً
                </Link>
              </div>
            ))}
          </div>
        </div>
      </section>

      {cardPayments && (
        <div className="bg-[#F8F1E7] pb-14 -mt-6 text-center" data-testid="payment-badges">
          <div className="inline-flex flex-wrap items-center justify-center gap-2 font-body text-sm text-[#5A677D] px-4">
            <CreditCard className="w-4 h-4 text-[#729352]" /> ادفع بأمان:
            {["مدى", "Visa", "Mastercard", "Apple Pay"].map((m) => (
              <span key={m} className="rounded-full bg-white border border-[#E2D8C9] px-3 py-1 font-bold text-[#2D3748]" dir="auto">{m}</span>
            ))}
            <span>أو من رصيدك في غِراس</span>
          </div>
        </div>
      )}

      {/* VALUES */}
      <section className="py-16 md:py-24 bg-white" data-testid="values-section">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="text-center max-w-2xl mx-auto mb-12">
            <h2 className="font-heading text-3xl sm:text-4xl font-bold text-[#2D3748] mb-4">
              {content["values.title"] || "لماذا غِراس؟"}
            </h2>
            <p className="font-body text-lg text-[#5A677D]">نؤمن أن القصة أقوى وسيلة لغرس القيم في قلب طفلك</p>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 md:gap-6">
            {values.map((v, i) => {
              const Icon = ICON_MAP[v.icon] || Heart;
              return (
                <div key={i} className="bg-[#FDFBF7] rounded-3xl p-5 md:p-8 border border-[#E2D8C9] text-center card-lift animate-grow"
                  style={{ animationDelay: `${i * 0.1}s` }} data-testid={`value-card-${i}`}>
                  <div className="w-14 h-14 rounded-2xl bg-[#E8F0E1] grid place-content-center mx-auto mb-4">
                    <Icon className="w-7 h-7 text-[#729352]" />
                  </div>
                  <h3 className="font-heading text-lg md:text-xl font-bold text-[#2D3748] mb-2">{v.title}</h3>
                  <p className="font-body text-sm text-[#5A677D]">{v.desc}</p>
                </div>
              );
            })}
          </div>
        </div>
      </section>

      {/* CATEGORIES preview */}
      <section className="py-16 md:py-24" data-testid="categories-preview">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex items-end justify-between mb-10 flex-wrap gap-4">
            <div>
              <h2 className="font-heading text-3xl sm:text-4xl font-bold text-[#2D3748] mb-3">تصنيفات القصص</h2>
              <p className="font-body text-[#5A677D] text-lg">اختر الهدف التربوي وابدأ</p>
            </div>
            <Link to="/categories" className="inline-flex items-center gap-2 text-[#729352] hover:text-[#4F6B3B] font-bold">
              جميع التصنيفات <ArrowLeft className="w-4 h-4" />
            </Link>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 md:gap-5">
            {categories.slice(0, 8).map((c, i) => {
              const Icon = ICON_MAP[c.icon] || BookOpen;
              return (
                <Link key={c.id} to="/story/new" className="group bg-white rounded-3xl p-5 md:p-6 border border-[#E2D8C9] card-lift animate-grow"
                  style={{ animationDelay: `${i * 0.05}s` }} data-testid={`category-card-${c.slug}`}>
                  <div className="w-12 h-12 rounded-2xl grid place-content-center mb-4" style={{ backgroundColor: `${c.color}20` }}>
                    <Icon className="w-6 h-6" style={{ color: c.color }} />
                  </div>
                  <h3 className="font-heading text-lg font-bold text-[#2D3748] mb-1 group-hover:text-[#729352]">{c.name_ar}</h3>
                  <p className="font-body text-xs text-[#8A9AB0]">{topicsLabel(c.subcategories?.length || 0)}</p>
                </Link>
              );
            })}
          </div>
        </div>
      </section>

      {/* TRUST */}
      <section className="py-16 md:py-24 bg-[#E8F0E1]/60" data-testid="trust-section">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="text-center max-w-2xl mx-auto mb-12">
            <h2 className="font-heading text-3xl sm:text-4xl font-bold text-[#2D3748] mb-4">طفلك في أمان معنا</h2>
            <p className="font-body text-lg text-[#5A677D]">صور أطفالنا أمانة، وهكذا نتعامل معها</p>
          </div>
          <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-5">
            {TRUST.map(({ icon: Icon, title, desc }) => (
              <div key={title} className="bg-white rounded-3xl p-6 border border-[#E2D8C9]">
                <Icon className="w-7 h-7 text-[#729352] mb-3" />
                <h3 className="font-heading text-lg font-bold text-[#2D3748] mb-2">{title}</h3>
                <p className="font-body text-sm text-[#5A677D] leading-relaxed">{desc}</p>
              </div>
            ))}
          </div>
          <p className="text-center mt-8 font-body text-sm">
            <Link to="/privacy" className="text-[#4F6B3B] font-bold underline">اقرأ سياسة الخصوصية كاملة</Link>
          </p>
        </div>
      </section>

      {/* FAQ */}
      <section className="py-16 md:py-24" data-testid="faq-section">
        <div className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8">
          <h2 className="font-heading text-3xl sm:text-4xl font-bold text-[#2D3748] mb-10 text-center">أسئلة يسألها الأهل</h2>
          <div className="space-y-3">
            {FAQ.map(([q, a]) => (
              <details key={q} className="group bg-white rounded-2xl border border-[#E2D8C9] px-5 py-4 open:shadow-sm">
                <summary className="flex items-center justify-between gap-3 cursor-pointer list-none font-heading font-bold text-[#2D3748] text-lg">
                  {q}
                  <ChevronDown className="w-5 h-5 text-[#87A96B] shrink-0 transition group-open:rotate-180" />
                </summary>
                <p className="font-body text-[#5A677D] leading-relaxed mt-3">{a}</p>
              </details>
            ))}
          </div>
        </div>
      </section>

      {/* CTA */}
      <section className="pb-8 md:pb-16" data-testid="final-cta">
        <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 text-center">
          <div className="relative bg-gradient-to-br from-[#E8F0E1] via-[#F8F1E7] to-[#FDFBF7] rounded-[3rem] p-10 md:p-16 border border-[#E2D8C9] overflow-hidden">
            <div className="absolute -top-10 -right-10 w-40 h-40 bg-[#D4A373]/20 blob-shape" />
            <div className="absolute -bottom-10 -left-10 w-40 h-40 bg-[#87A96B]/20 blob-shape" />
            <img src={LOGO_URL} alt="غِراس" className="logo-img h-36 w-36 md:h-44 md:w-44 mx-auto mb-2 drop-shadow-lg" />
            <h2 className="font-heading text-3xl md:text-4xl font-bold text-[#2D3748] mb-4">جاهز لغرس قيمة في قلب طفلك؟</h2>
            <p className="font-body text-[#5A677D] text-lg mb-8 max-w-xl mx-auto">
              اكتب لنا عن طفلك واختر من ثلاث حكايات — مجاناً حتى تختار حكايتك.
            </p>
            <Link to="/story/new" className="btn-primary inline-flex items-center gap-2" data-testid="final-cta-btn">
              <Sprout className="w-5 h-5" /> ابدأ أول قصة
            </Link>
            <p className="mt-5 font-body text-sm text-[#5A677D] inline-flex items-center gap-1.5 justify-center w-full">
              <Users className="w-4 h-4" /> أضف من تحب من العائلة ليكونوا معه في القصة
            </p>
          </div>
        </div>
      </section>

      {whatsapp && (
        <a href={whatsapp} target="_blank" rel="noreferrer" aria-label="تواصل معنا على واتساب" data-testid="whatsapp-fab"
          className="fixed bottom-5 left-5 z-40 w-14 h-14 rounded-full bg-[#25D366] text-white grid place-content-center shadow-xl hover:scale-105 transition">
          <MessageCircle className="w-7 h-7" />
        </a>
      )}

      <Footer />
    </div>
  );
}
