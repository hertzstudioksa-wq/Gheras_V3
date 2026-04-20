import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../lib/api";
import { Sprout, Instagram, Twitter } from "lucide-react";

const LOGO_URL = "/gheras-logo.png";

export default function Footer() {
  const [content, setContent] = useState({});

  useEffect(() => {
    api.get("/public/content").then((r) => setContent(r.data)).catch(() => {});
  }, []);

  return (
    <footer className="bg-[#F8F1E7] border-t border-[#E2D8C9] mt-24" data-testid="site-footer">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-14">
        <div className="grid grid-cols-1 md:grid-cols-4 gap-10 mb-10">
          <div className="md:col-span-2">
            <div className="flex items-center gap-3 mb-4">
              <div className="logo-icon h-16 w-16 shrink-0">
                <img src={LOGO_URL} alt="غِراس" />
              </div>
              <span className="font-heading text-3xl font-bold text-[#729352]">غِراس</span>
            </div>
            <p className="text-[#5A677D] font-body text-base leading-relaxed max-w-md">
              {content["footer.tagline"] || "نَغرِس القيَم بقِصصٍ بَطلُها طِفلُك"}
            </p>
          </div>

          <div>
            <h4 className="font-heading font-bold text-[#2D3748] text-lg mb-4">روابط سريعة</h4>
            <ul className="space-y-2 font-body text-[#5A677D]">
              <li><Link to="/how-it-works" className="hover:text-[#87A96B]">كيف تعمل</Link></li>
              <li><Link to="/categories" className="hover:text-[#87A96B]">التصنيفات</Link></li>
              <li><Link to="/story/new" className="hover:text-[#87A96B]">ابدأ قصة</Link></li>
            </ul>
          </div>

          <div>
            <h4 className="font-heading font-bold text-[#2D3748] text-lg mb-4">تابعنا</h4>
            <div className="flex items-center gap-3">
              <a href="#" aria-label="Instagram" className="w-10 h-10 rounded-full bg-white border border-[#E2D8C9] grid place-content-center text-[#8B5A2B] hover:bg-[#87A96B] hover:text-white transition">
                <Instagram className="w-4 h-4" />
              </a>
              <a href="#" aria-label="Twitter" className="w-10 h-10 rounded-full bg-white border border-[#E2D8C9] grid place-content-center text-[#8B5A2B] hover:bg-[#87A96B] hover:text-white transition">
                <Twitter className="w-4 h-4" />
              </a>
              <a href="#" aria-label="Sprout" className="w-10 h-10 rounded-full bg-white border border-[#E2D8C9] grid place-content-center text-[#8B5A2B] hover:bg-[#87A96B] hover:text-white transition">
                <Sprout className="w-4 h-4" />
              </a>
            </div>
          </div>
        </div>
        <div className="border-t border-[#E2D8C9] pt-6 text-center text-sm text-[#8A9AB0] font-body">
          {content["footer.copyright"] || "© غِراس ٢٠٢٦ — جميع الحقوق محفوظة"}
        </div>
      </div>
    </footer>
  );
}
