import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../lib/api";
import Navbar from "../components/gheras/Navbar";
import Footer from "../components/gheras/Footer";
import {
  Sun, Heart, Award, Sparkles, Moon, Rocket, PenTool, BookOpen, Sprout,
} from "lucide-react";

const ICON_MAP = {
  sun: Sun, heart: Heart, award: Award, sparkles: Sparkles,
  moon: Moon, rocket: Rocket, "moon-star": Moon, "pen-tool": PenTool,
  sprout: Sprout,
};

export default function Categories() {
  const [categories, setCategories] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.get("/public/categories").then((r) => {
      setCategories(r.data);
    }).finally(() => setLoading(false));
  }, []);

  return (
    <div className="min-h-screen bg-[#FDFBF7]" data-testid="categories-page">
      <Navbar />
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-16 md:py-24">
        <div className="text-center max-w-2xl mx-auto mb-16 animate-grow">
          <h1 className="font-heading text-4xl sm:text-5xl font-bold text-[#2D3748] mb-5">
            تصنيفات القصص
          </h1>
          <p className="font-body text-lg text-[#5A677D]">
            اختر القيمة التي تريد أن تغرسها في قلب طفلك، ودعنا نصنع قصة خاصة له
          </p>
        </div>

        {loading ? (
          <div className="text-center text-[#8A9AB0]">جاري التحميل...</div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6" data-testid="categories-grid">
            {categories.map((c, i) => {
              const Icon = ICON_MAP[c.icon] || BookOpen;
              return (
                <div
                  key={c.id}
                  className="bg-white rounded-3xl p-8 border border-[#E2D8C9] card-lift animate-grow"
                  style={{ animationDelay: `${i * 0.05}s` }}
                  data-testid={`cat-${c.slug}`}
                >
                  <div
                    className="w-14 h-14 rounded-2xl grid place-content-center mb-5"
                    style={{ backgroundColor: `${c.color}20` }}
                  >
                    <Icon className="w-7 h-7" style={{ color: c.color }} />
                  </div>
                  <h2 className="font-heading text-2xl font-bold text-[#2D3748] mb-2">{c.name_ar}</h2>
                  <p className="font-body text-[#5A677D] text-sm mb-5 leading-relaxed">
                    {c.description}
                  </p>

                  {c.subcategories?.length > 0 && (
                    <div className="flex flex-wrap gap-2 mb-6">
                      {c.subcategories.slice(0, 4).map((s) => (
                        <span
                          key={s.id}
                          className="px-3 py-1 rounded-full bg-[#F8F1E7] text-[#8B5A2B] text-xs font-body"
                        >
                          {s.name_ar}
                        </span>
                      ))}
                      {c.subcategories.length > 4 && (
                        <span className="px-3 py-1 rounded-full bg-[#E8F0E1] text-[#4F6B3B] text-xs font-body">
                          +{c.subcategories.length - 4}
                        </span>
                      )}
                    </div>
                  )}

                  <Link
                    to="/story/new"
                    state={{ presetCategoryId: c.id }}
                    className="inline-flex items-center gap-2 text-[#729352] font-bold hover:text-[#4F6B3B]"
                    data-testid={`cat-start-${c.slug}`}
                  >
                    <Sprout className="w-4 h-4" /> ابدأ قصة في هذا التصنيف
                  </Link>
                </div>
              );
            })}
          </div>
        )}
      </div>
      <Footer />
    </div>
  );
}
