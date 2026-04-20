import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../lib/api";
import Navbar from "../components/gheras/Navbar";
import Footer from "../components/gheras/Footer";
import { Sprout, ArrowLeft, BookOpen, CheckCircle2 } from "lucide-react";

export default function HowItWorks() {
  const [content, setContent] = useState({});

  useEffect(() => {
    api.get("/public/content").then((r) => setContent(r.data)).catch(() => {});
  }, []);

  const steps = [
    { num: 1, titleKey: "how.step1.title", descKey: "how.step1.desc", color: "#87A96B" },
    { num: 2, titleKey: "how.step2.title", descKey: "how.step2.desc", color: "#D4A373" },
    { num: 3, titleKey: "how.step3.title", descKey: "how.step3.desc", color: "#E07A5F" },
    { num: 4, titleKey: "how.step4.title", descKey: "how.step4.desc", color: "#8B5A2B" },
  ];

  const features = [
    "قصة مخصصة باسم وشخصية طفلك",
    "هدف تربوي واضح في كل قصة",
    "أسلوب سردي يختاره الأهل",
    "مراجعة بشرية قبل التسليم",
    "محتوى آمن وملائم للأعمار",
    "إمكانية الطباعة ومشاركة العائلة",
  ];

  return (
    <div className="min-h-screen bg-[#FDFBF7]" data-testid="how-page">
      <Navbar />
      <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-16 md:py-24">
        <div className="text-center max-w-2xl mx-auto mb-16 animate-grow">
          <h1 className="font-heading text-4xl sm:text-5xl font-bold text-[#2D3748] mb-5">
            {content["how.title"] || "كيف تعمل غِراس؟"}
          </h1>
          <p className="font-body text-lg text-[#5A677D]">
            {content["how.subtitle"] || "أربع خطوات بسيطة تفصلك عن قصة لن ينساها طفلك"}
          </p>
        </div>

        <div className="space-y-6 mb-16">
          {steps.map((s, i) => (
            <div
              key={s.num}
              className="bg-white rounded-3xl p-8 md:p-10 border border-[#E2D8C9] shadow-sm flex flex-col md:flex-row gap-6 items-start animate-grow"
              style={{ animationDelay: `${i * 0.1}s` }}
              data-testid={`how-detail-${s.num}`}
            >
              <div
                className="shrink-0 w-20 h-20 rounded-2xl grid place-content-center font-heading text-4xl font-bold"
                style={{ backgroundColor: `${s.color}20`, color: s.color }}
              >
                {s.num}
              </div>
              <div className="flex-1">
                <h2 className="font-heading text-2xl md:text-3xl font-bold text-[#2D3748] mb-2">
                  {content[s.titleKey] || `الخطوة ${s.num}`}
                </h2>
                <p className="font-body text-[#5A677D] text-lg leading-relaxed">
                  {content[s.descKey] || ""}
                </p>
              </div>
            </div>
          ))}
        </div>

        <div className="bg-[#F8F1E7] rounded-3xl p-8 md:p-12 border border-[#E2D8C9] mb-16">
          <h3 className="font-heading text-2xl font-bold text-[#2D3748] mb-6 flex items-center gap-2">
            <BookOpen className="w-6 h-6 text-[#729352]" />
            ما الذي ستحصل عليه؟
          </h3>
          <div className="grid md:grid-cols-2 gap-4">
            {features.map((f, i) => (
              <div key={i} className="flex items-start gap-3">
                <CheckCircle2 className="w-5 h-5 text-[#87A96B] shrink-0 mt-0.5" />
                <p className="font-body text-[#2D3748]">{f}</p>
              </div>
            ))}
          </div>
        </div>

        <div className="text-center">
          <Link to="/story/new" className="btn-primary inline-flex items-center gap-2" data-testid="how-cta-btn">
            <Sprout className="w-5 h-5" /> ابدأ قصة طفلك
            <ArrowLeft className="w-4 h-4 -scale-x-100" />
          </Link>
        </div>
      </div>
      <Footer />
    </div>
  );
}
