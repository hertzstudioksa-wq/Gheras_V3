import React from "react";
import { Link } from "react-router-dom";
import { Instagram, Twitter, Mail, MessageCircle } from "lucide-react";
import { useSiteContent, businessDetails, whatsappLink } from "../../lib/siteContent";

const LOGO_URL = "/gheras-logo.png";

export default function Footer() {
  const content = useSiteContent();
  // Social links appear once an admin fills them in (no dead "#" links).
  const social = [
    ["Instagram", content["footer.instagram"], Instagram],
    ["X", content["footer.x"], Twitter],
    ["البريد", content["footer.contact_email"] && `mailto:${content["footer.contact_email"]}`, Mail],
    ["واتساب", whatsappLink(content["business.phone"]), MessageCircle],
  ].filter(([, href]) => href);
  const business = businessDetails(content).filter(([label]) => label !== "البريد الإلكتروني");

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
              <li><Link to="/privacy" className="hover:text-[#87A96B]">سياسة الخصوصية</Link></li>
              <li><Link to="/terms" className="hover:text-[#87A96B]">الشروط والاسترجاع</Link></li>
            </ul>
          </div>

          {social.length > 0 && (
            <div>
              <h4 className="font-heading font-bold text-[#2D3748] text-lg mb-4">تواصل معنا</h4>
              <div className="flex items-center gap-3">
                {social.map(([label, href, Icon]) => (
                  <a key={label} href={href} aria-label={label} target={href.startsWith("http") ? "_blank" : undefined} rel="noreferrer"
                    className="w-10 h-10 rounded-full bg-white border border-[#E2D8C9] grid place-content-center text-[#8B5A2B] hover:bg-[#87A96B] hover:text-white transition">
                    <Icon className="w-4 h-4" />
                  </a>
                ))}
              </div>
            </div>
          )}
        </div>
        <div className="border-t border-[#E2D8C9] pt-6 text-center text-sm text-[#8A9AB0] font-body space-y-1">
          <div>{content["footer.copyright"] || "© غِراس ٢٠٢٦ — جميع الحقوق محفوظة"}</div>
          {business.length > 0 && (
            <div className="text-xs" data-testid="footer-business">
              {business.map(([label, value]) => `${label}: ${value}`).join(" · ")}
            </div>
          )}
        </div>
      </div>
    </footer>
  );
}
