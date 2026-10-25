import React from "react";
import { Link } from "react-router-dom";
import { Compass, Sprout } from "lucide-react";
import Navbar from "../components/gheras/Navbar";
import Footer from "../components/gheras/Footer";
import { usePageTitle } from "../lib/usePageTitle";

/** A wrong link: say so (instead of silently landing on the home page). */
export default function NotFound({ admin = false }) {
  usePageTitle("الصفحة غير موجودة");
  const body = (
    <div className="max-w-lg mx-auto text-center py-16 px-4" data-testid="not-found">
      <div className="w-20 h-20 rounded-3xl bg-[#F8F1E7] grid place-content-center mx-auto mb-6">
        <Compass className="w-10 h-10 text-[#D4A373]" />
      </div>
      <h1 className="font-heading text-3xl font-bold text-[#2D3748] mb-3">لم نجد هذه الصفحة</h1>
      <p className="font-body text-[#5A677D] mb-8">ربما تغيّر الرابط أو كُتب بشكل غير صحيح.</p>
      <Link to={admin ? "/admin" : "/"} className="btn-primary inline-flex items-center gap-2">
        <Sprout className="w-5 h-5" /> {admin ? "رئيسية الإدارة" : "الصفحة الرئيسية"}
      </Link>
    </div>
  );
  if (admin) return body;
  return (
    <div className="min-h-screen bg-[#FDFBF7]">
      <Navbar />
      {body}
      <Footer />
    </div>
  );
}
