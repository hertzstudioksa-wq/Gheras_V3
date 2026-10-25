import React, { useState } from "react";
import { NavLink, Outlet, Link, useNavigate, useLocation } from "react-router-dom";
import { useAuth } from "../../contexts/AuthContext";
import ErrorBoundary from "../../components/ErrorBoundary";
import AdminPasswordGate from "./AdminPasswordGate";
import EngineHealthBanner from "../../components/admin/EngineHealthBanner";
import { Sheet, SheetContent, SheetTitle } from "../../components/ui/sheet";
import {
  LayoutDashboard, Users, BookOpen, Sprout, FileText, CreditCard, Settings, LogOut, Palette,
  Coins, Beaker, Lock, Package, ScrollText, Library, Hourglass, SlidersHorizontal, Menu,
} from "lucide-react";

const LOGO_URL = "/gheras-logo.png";

// Six sections (audit AF-24): what an operator does day to day first, the
// engine and settings last.
const SECTIONS = [
  { title: null, items: [
    { to: "/admin", label: "الرئيسية", icon: LayoutDashboard, end: true, tid: "admin-nav-overview" },
  ] },
  { title: "العمليات", items: [
    { to: "/admin/orders", label: "الطلبات", icon: BookOpen, tid: "admin-nav-orders" },
    { to: "/admin/assets", label: "مكتبة الأصول", icon: Library, tid: "admin-nav-assets" },
  ] },
  { title: "العملاء والمبيعات", items: [
    { to: "/admin/users", label: "المستخدمين", icon: Users, tid: "admin-nav-users" },
    { to: "/admin/bundles", label: "الباقات والرصيد", icon: Package, tid: "admin-nav-bundles" },
    { to: "/admin/payment", label: "المدفوعات", icon: CreditCard, tid: "admin-nav-payment" },
    { to: "/admin/pricing", label: "التسعير والهوامش", icon: Coins, tid: "admin-nav-pricing" },
  ] },
  { title: "الكتالوج والمحتوى", items: [
    { to: "/admin/categories", label: "التصنيفات والمواضيع", icon: Sprout, tid: "admin-nav-cats" },
    { to: "/admin/styles", label: "خيارات القصة", icon: Palette, tid: "admin-nav-styles" },
    { to: "/admin/content", label: "نصوص الموقع", icon: FileText, tid: "admin-nav-content" },
  ] },
  { title: "محرك الإنتاج", items: [
    { to: "/admin/engine", label: "المحرك والموديلات", icon: SlidersHorizontal, tid: "admin-nav-engine" },
    { to: "/admin/lab", label: "مختبر المراحل", icon: Beaker, tid: "admin-nav-lab" },
    { to: "/admin/secrets", label: "المفاتيح والمزوّدين", icon: Lock, tid: "admin-nav-secrets" },
  ] },
  { title: "الإعدادات", items: [
    { to: "/admin/retention", label: "سياسة الاحتفاظ", icon: Hourglass, tid: "admin-nav-retention" },
    { to: "/admin/audit", label: "سجل التدقيق", icon: ScrollText, tid: "admin-nav-audit" },
    { to: "/admin/settings", label: "إعدادات النظام", icon: Settings, tid: "admin-nav-settings" },
  ] },
];

function NavSections({ onNavigate }) {
  return (
    <nav className="p-3 space-y-4" aria-label="أقسام لوحة الإدارة">
      {SECTIONS.map((sec, i) => (
        <div key={sec.title || i}>
          {sec.title && <div className="px-4 pb-1 font-body text-[11px] font-bold text-[#8A9AB0] tracking-wide">{sec.title}</div>}
          <div className="space-y-0.5">
            {sec.items.map((it) => (
              <NavLink
                key={it.to}
                to={it.to}
                end={it.end}
                onClick={onNavigate}
                className={({ isActive }) =>
                  `flex items-center gap-3 px-4 py-2.5 rounded-2xl font-body text-[15px] transition ${
                    isActive ? "bg-[#E8F0E1] text-[#4F6B3B] font-bold" : "text-[#5A677D] hover:bg-[#F8F1E7]"
                  }`
                }
                data-testid={it.tid}
              >
                <it.icon className="w-[18px] h-[18px] shrink-0" />
                <span>{it.label}</span>
              </NavLink>
            ))}
          </div>
        </div>
      ))}
    </nav>
  );
}

function Brand() {
  return (
    <Link to="/" className="flex items-center gap-2">
      <div className="logo-icon h-12 w-12 shrink-0">
        <img src={LOGO_URL} alt="غِراس" />
      </div>
      <div>
        <div className="font-heading text-xl font-bold text-[#729352] leading-tight">غِراس</div>
        <div className="font-body text-xs text-[#8A9AB0]">لوحة الإدارة</div>
      </div>
    </Link>
  );
}

export default function AdminLayout() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [menuOpen, setMenuOpen] = useState(false);

  const doLogout = () => {
    logout();
    navigate("/");
  };

  const userBox = (
    <div className="p-4 border-t border-[#E2D8C9]">
      <div className="flex items-center gap-3 mb-3">
        <div className="w-10 h-10 rounded-full bg-[#E8F0E1] grid place-content-center text-[#729352] font-bold font-heading">
          {user?.full_name?.[0] || "A"}
        </div>
        <div className="flex-1 min-w-0">
          <div className="font-body text-sm font-bold text-[#2D3748] truncate">{user?.full_name}</div>
          <div className="font-body text-xs text-[#8A9AB0] truncate">{user?.email}</div>
        </div>
      </div>
      <button
        onClick={doLogout}
        className="w-full inline-flex items-center justify-center gap-2 rounded-2xl bg-[#F8F1E7] hover:bg-[#F2E8DA] text-[#8B5A2B] px-4 py-2 text-sm font-bold"
        data-testid="admin-logout-btn"
      >
        <LogOut className="w-4 h-4" /> خروج
      </button>
    </div>
  );

  return (
    <div className="min-h-screen bg-[#FDFBF7] flex" data-testid="admin-layout">
      <aside className="w-64 bg-white border-l border-[#E2D8C9] h-screen sticky top-0 overflow-y-auto hidden md:flex md:flex-col">
        <div className="p-5 border-b border-[#E2D8C9]"><Brand /></div>
        <div className="flex-1"><NavSections /></div>
        {userBox}
      </aside>

      <main className="flex-1 min-w-0">
        {/* Mobile top bar + the same grouped menu in a drawer */}
        <div className="md:hidden bg-white border-b border-[#E2D8C9] px-4 py-3 flex items-center justify-between sticky top-0 z-20">
          <button onClick={() => setMenuOpen(true)} className="text-[#2D3748] p-1" aria-label="القائمة" data-testid="admin-menu-btn">
            <Menu className="w-6 h-6" />
          </button>
          <span className="font-heading font-bold text-[#729352]">غِراس • الإدارة</span>
          <button onClick={doLogout} className="text-[#8B5A2B] p-1" aria-label="خروج"><LogOut className="w-5 h-5" /></button>
        </div>
        <Sheet open={menuOpen} onOpenChange={setMenuOpen}>
          <SheetContent side="right" className="p-0 w-72 flex flex-col" dir="rtl">
            <SheetTitle className="sr-only">قائمة الإدارة</SheetTitle>
            <div className="p-5 border-b border-[#E2D8C9]"><Brand /></div>
            <div className="flex-1 overflow-y-auto"><NavSections onNavigate={() => setMenuOpen(false)} /></div>
            {userBox}
          </SheetContent>
        </Sheet>

        <div className="p-4 md:p-8 lg:p-10">
          <ErrorBoundary resetKey={location.pathname}>
            {!user?.must_change_password && <EngineHealthBanner />}
            {user?.must_change_password ? <AdminPasswordGate /> : <Outlet />}
          </ErrorBoundary>
        </div>
      </main>
    </div>
  );
}
