import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../lib/api";
import Navbar from "../components/gheras/Navbar";
import Footer from "../components/gheras/Footer";
import {
  Sprout, Heart, Shield, Sparkles, ArrowLeft, PlayCircle, BookOpen,
  Sun, Award, Moon, Rocket, PenTool, Star,
} from "lucide-react";

const ICON_MAP = {
  sun: Sun, heart: Heart, award: Award, sparkles: Sparkles,
  moon: Moon, rocket: Rocket, "moon-star": Moon, "pen-tool": PenTool,
  shield: Shield, sprout: Sprout, star: Star,
};

const LOGO_URL =
  "https://customer-assets.emergentagent.com/job_63d63889-ac7b-41d8-b7a7-55c098ae2162/artifacts/47jyw57s_Gheras_3-Final.png";

const HERO_IMG =
  "https://images.unsplash.com/photo-1758598737999-e5b659b3d65c?crop=entropy&cs=srgb&fm=jpg&q=85&w=1200";

export default function Landing() {
  const [content, setContent] = useState({});
  const [categories, setCategories] = useState([]);

  useEffect(() => {
    Promise.all([api.get("/public/content"), api.get("/public/categories")])
      .then(([c, cats]) => {
        setContent(c.data);
        setCategories(cats.data);
      })
      .catch(() => {});
  }, []);

  const values = content["values.items"] || [
    { icon: "heart", title: "مصممة بحب", desc: "كل تفصيلة تراعي قلب طفلك" },
    { icon: "shield", title: "محتوى آمن", desc: "نراجع كل قصة بعناية" },
    { icon: "sprout", title: "تربية بالقصة", desc: "القيم تُغرس بحنان" },
    { icon: "sparkles", title: "تجربة فريدة", desc: "طفلك بطل القصة" },
  ];

  return (
    <div className="min-h-screen bg-[#FDFBF7]" data-testid="landing-page">
      <Navbar />

      {/* HERO */}
      <section className="relative overflow-hidden" data-testid="hero-section">
        <div className="absolute top-20 -left-20 w-72 h-72 bg-[#E8F0E1] blob-shape opacity-60 -z-10" />
        <div className="absolute bottom-10 -right-20 w-80 h-80 bg-[#F2E8DA] blob-shape opacity-60 -z-10" />

        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-16 md:py-28 grid md:grid-cols-2 gap-12 items-center">
          <div className="animate-grow">
            <div className="inline-flex items-center gap-2 bg-[#E8F0E1] text-[#4F6B3B] px-4 py-2 rounded-full text-sm font-bold mb-6">
              <Sparkles className="w-4 h-4" />
              <span>منصة عربية أولى بالذكاء الاصطناعي</span>
            </div>
            <h1 className="font-heading text-4xl sm:text-5xl lg:text-6xl font-bold text-[#2D3748] leading-tight mb-6">
              {content["hero.title"] || "نَغرِس القِيَم بقِصصٍ بَطلُها طِفلُك"}
            </h1>
            <p className="font-body text-lg text-[#5A677D] leading-relaxed mb-10 max-w-lg">
              {content["hero.subtitle"] ||
                "منصة غِراس تصنع لطفلك قصصاً شخصيّة، تعلّمه القيم وتعدّل سلوكياته بحب."}
            </p>
            <div className="flex flex-wrap gap-4">
              <Link to="/story/new" className="btn-primary inline-flex items-center gap-2 animate-ring" data-testid="hero-cta-primary">
                <Sprout className="w-5 h-5" />
                {content["hero.cta_primary"] || "ابدأ أول قصة لطفلك"}
              </Link>
              <Link
                to="/how-it-works"
                className="inline-flex items-center gap-2 px-8 py-3 rounded-full border-2 border-[#87A96B] text-[#729352] font-bold hover:bg-[#E8F0E1] transition"
                data-testid="hero-cta-secondary"
              >
                <PlayCircle className="w-5 h-5" />
                {content["hero.cta_secondary"] || "كيف تعمل غِراس؟"}
              </Link>
            </div>
          </div>

          <div className="relative animate-grow delay-2">
            <div className="absolute -inset-4 bg-[#E8F0E1] blob-shape opacity-50 -z-10" />
            <div className="relative rounded-[2.5rem] overflow-hidden shadow-2xl border-8 border-white">
              <img src={HERO_IMG} alt="أهل وأطفال" className="w-full h-[460px] object-cover" />
              <div className="absolute bottom-5 right-5 bg-white/95 backdrop-blur rounded-2xl p-3 shadow-lg flex items-center gap-3 animate-float">
                <div className="logo-badge h-12 w-12 shrink-0 overflow-hidden">
                  <img src={LOGO_URL} alt="غِراس" />
                </div>
                <div>
                  <p className="font-heading font-bold text-[#2D3748] text-sm">قصة مصمّمة لطفلك</p>
                  <p className="font-body text-xs text-[#5A677D]">بطلها اسمه ومواصفاته</p>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* VALUES */}
      <section className="py-20 md:py-28 bg-white" data-testid="values-section">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="text-center max-w-2xl mx-auto mb-16">
            <h2 className="font-heading text-3xl sm:text-4xl font-bold text-[#2D3748] mb-4">
              {content["values.title"] || "لماذا غِراس؟"}
            </h2>
            <p className="font-body text-lg text-[#5A677D]">
              نؤمن أن القصة أقوى وسيلة لغرس القيم في قلب طفلك
            </p>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-6">
            {values.map((v, i) => {
              const Icon = ICON_MAP[v.icon] || Heart;
              return (
                <div
                  key={i}
                  className="bg-[#FDFBF7] rounded-3xl p-6 md:p-8 border border-[#E2D8C9] text-center card-lift animate-grow"
                  style={{ animationDelay: `${i * 0.1}s` }}
                  data-testid={`value-card-${i}`}
                >
                  <div className="w-14 h-14 rounded-2xl bg-[#E8F0E1] grid place-content-center mx-auto mb-4">
                    <Icon className="w-7 h-7 text-[#729352]" />
                  </div>
                  <h3 className="font-heading text-xl font-bold text-[#2D3748] mb-2">{v.title}</h3>
                  <p className="font-body text-sm text-[#5A677D]">{v.desc}</p>
                </div>
              );
            })}
          </div>
        </div>
      </section>

      {/* HOW IT WORKS preview */}
      <section className="py-20 md:py-28" data-testid="how-it-works-preview">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="text-center max-w-2xl mx-auto mb-16">
            <h2 className="font-heading text-3xl sm:text-4xl font-bold text-[#2D3748] mb-4">
              {content["how.title"] || "كيف تعمل غِراس؟"}
            </h2>
            <p className="font-body text-lg text-[#5A677D]">
              {content["how.subtitle"] || "أربع خطوات بسيطة تفصلك عن قصة لن ينساها طفلك"}
            </p>
          </div>
          <div className="grid md:grid-cols-4 gap-6 relative">
            {[1, 2, 3, 4].map((i) => (
              <div
                key={i}
                className="bg-white rounded-3xl p-8 border border-[#E2D8C9] card-lift relative animate-grow"
                style={{ animationDelay: `${i * 0.1}s` }}
                data-testid={`how-step-${i}`}
              >
                <div className="absolute -top-6 right-8 w-12 h-12 rounded-full bg-[#87A96B] text-white grid place-content-center font-heading text-xl font-bold shadow-lg">
                  {i}
                </div>
                <h3 className="font-heading text-xl font-bold text-[#2D3748] mb-2 mt-2">
                  {content[`how.step${i}.title`] || `الخطوة ${i}`}
                </h3>
                <p className="font-body text-[#5A677D] text-sm leading-relaxed">
                  {content[`how.step${i}.desc`] || ""}
                </p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* CATEGORIES preview */}
      <section className="py-20 md:py-28 bg-[#F8F1E7]" data-testid="categories-preview">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex items-end justify-between mb-12 flex-wrap gap-4">
            <div>
              <h2 className="font-heading text-3xl sm:text-4xl font-bold text-[#2D3748] mb-3">
                تصنيفات القصص
              </h2>
              <p className="font-body text-[#5A677D] text-lg">اختر الهدف التربوي وابدأ</p>
            </div>
            <Link to="/categories" className="inline-flex items-center gap-2 text-[#729352] hover:text-[#4F6B3B] font-bold">
              جميع التصنيفات <ArrowLeft className="w-4 h-4 -scale-x-100" />
            </Link>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-5">
            {categories.slice(0, 8).map((c, i) => {
              const Icon = ICON_MAP[c.icon] || BookOpen;
              return (
                <Link
                  key={c.id}
                  to="/story/new"
                  className="group bg-white rounded-3xl p-6 border border-[#E2D8C9] card-lift animate-grow"
                  style={{ animationDelay: `${i * 0.05}s` }}
                  data-testid={`category-card-${c.slug}`}
                >
                  <div
                    className="w-12 h-12 rounded-2xl grid place-content-center mb-4"
                    style={{ backgroundColor: `${c.color}20` }}
                  >
                    <Icon className="w-6 h-6" style={{ color: c.color }} />
                  </div>
                  <h3 className="font-heading text-lg font-bold text-[#2D3748] mb-1 group-hover:text-[#729352]">
                    {c.name_ar}
                  </h3>
                  <p className="font-body text-xs text-[#8A9AB0]">
                    {(c.subcategories?.length || 0)} مواضيع
                  </p>
                </Link>
              );
            })}
          </div>
        </div>
      </section>

      {/* CTA */}
      <section className="py-20 md:py-28" data-testid="final-cta">
        <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 text-center">
          <div className="relative bg-gradient-to-br from-[#E8F0E1] via-[#F8F1E7] to-[#FDFBF7] rounded-[3rem] p-12 md:p-16 border border-[#E2D8C9] overflow-hidden">
            <div className="absolute -top-10 -right-10 w-40 h-40 bg-[#D4A373]/20 blob-shape" />
            <div className="absolute -bottom-10 -left-10 w-40 h-40 bg-[#87A96B]/20 blob-shape" />
            <div className="logo-badge h-28 w-28 mx-auto mb-4 overflow-hidden">
              <img src={LOGO_URL} alt="غِراس" />
            </div>
            <h2 className="font-heading text-3xl md:text-4xl font-bold text-[#2D3748] mb-4">
              جاهز لغرس قيمة في قلب طفلك؟
            </h2>
            <p className="font-body text-[#5A677D] text-lg mb-8 max-w-xl mx-auto">
              اصنع قصة شخصية مميزة لطفلك الآن — مجاناً كبداية
            </p>
            <Link to="/story/new" className="btn-primary inline-flex items-center gap-2" data-testid="final-cta-btn">
              <Sprout className="w-5 h-5" />
              ابدأ أول قصة
            </Link>
          </div>
        </div>
      </section>

      <Footer />
    </div>
  );
}
