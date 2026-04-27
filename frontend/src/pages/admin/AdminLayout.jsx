import React from "react";
import { NavLink, Outlet, Link, useNavigate } from "react-router-dom";
import { useAuth } from "../../contexts/AuthContext";
import {
  LayoutDashboard, Users, BookOpen, Sprout, FileText, Wand2,
  CreditCard, Settings, LogOut, Palette, Cpu, Workflow, ShieldCheck,
  Coins, Beaker, Lock, Package, ScrollText, Library, Hourglass, Layers,
} from "lucide-react";

const LOGO_URL = "/gheras-logo.png";

const items = [
  { to: "/admin", label: "نظرة عامة", icon: LayoutDashboard, end: true, tid: "admin-nav-overview" },
  { to: "/admin/orders", label: "الطلبات", icon: BookOpen, tid: "admin-nav-orders" },
  { to: "/admin/users", label: "المستخدمين", icon: Users, tid: "admin-nav-users" },
  { to: "/admin/categories", label: "التصنيفات", icon: Sprout, tid: "admin-nav-cats" },
  { to: "/admin/styles", label: "خيارات نمط القصة", icon: Palette, tid: "admin-nav-styles" },
  { to: "/admin/content", label: "محتوى الصفحة", icon: FileText, tid: "admin-nav-content" },
  { to: "/admin/prompts", label: "برومبتات AI", icon: Wand2, tid: "admin-nav-prompts" },
  { to: "/admin/models", label: "إعدادات النماذج", icon: Cpu, tid: "admin-nav-models" },
  { to: "/admin/pipeline", label: "إعدادات خط الإنتاج", icon: Workflow, tid: "admin-nav-pipeline" },
  { to: "/admin/stage-control", label: "مركز التحكم بالمراحل", icon: Layers, tid: "admin-nav-stage-control" },
  { to: "/admin/lab", label: "مختبر المراحل", icon: Beaker, tid: "admin-nav-lab" },
  { to: "/admin/pricing", label: "التسعير الداخلي", icon: Coins, tid: "admin-nav-pricing" },
  { to: "/admin/bundles", label: "الباقات", icon: Package, tid: "admin-nav-bundles" },
  { to: "/admin/payment", label: "الدفع و Stripe", icon: CreditCard, tid: "admin-nav-payment" },
  { to: "/admin/audit", label: "سجل التدقيق", icon: ScrollText, tid: "admin-nav-audit" },
  { to: "/admin/assets", label: "مكتبة الأصول", icon: Library, tid: "admin-nav-assets" },
  { to: "/admin/retention", label: "سياسة الاحتفاظ", icon: Hourglass, tid: "admin-nav-retention" },
  { to: "/admin/secrets", label: "المفاتيح والمزوّدين", icon: Lock, tid: "admin-nav-secrets" },
  { to: "/admin/presets", label: "Preset Stacks", icon: Layers, tid: "admin-nav-presets" },
  { to: "/admin/api-status", label: "حالة API", icon: ShieldCheck, tid: "admin-nav-api" },
  { to: "/admin/plans", label: "الأسعار والباقات (legacy)", icon: CreditCard, tid: "admin-nav-plans" },
  { to: "/admin/settings", label: "الإعدادات", icon: Settings, tid: "admin-nav-settings" },
];

export default function AdminLayout() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  const doLogout = () => {
    logout();
    navigate("/");
  };

  return (
    <div className="min-h-screen bg-[#FDFBF7] flex" data-testid="admin-layout">
      <aside className="w-72 bg-white border-l border-[#E2D8C9] h-screen sticky top-0 overflow-y-auto hidden md:block">
        <div className="p-6 border-b border-[#E2D8C9]">
          <Link to="/" className="flex items-center gap-2">
            <div className="logo-icon h-14 w-14 shrink-0">
              <img src={LOGO_URL} alt="غِراس" />
            </div>
            <div>
              <div className="font-heading text-xl font-bold text-[#729352] leading-tight">غِراس</div>
              <div className="font-body text-xs text-[#8A9AB0]">لوحة الإدارة</div>
            </div>
          </Link>
        </div>
        <nav className="p-4 space-y-1">
          {items.map((it) => (
            <NavLink
              key={it.to}
              to={it.to}
              end={it.end}
              className={({ isActive }) =>
                `flex items-center gap-3 px-4 py-3 rounded-2xl font-body transition ${
                  isActive
                    ? "bg-[#E8F0E1] text-[#4F6B3B] font-bold"
                    : "text-[#5A677D] hover:bg-[#F8F1E7]"
                }`
              }
              data-testid={it.tid}
            >
              <it.icon className="w-5 h-5" />
              <span>{it.label}</span>
            </NavLink>
          ))}
        </nav>
        <div className="p-4 border-t border-[#E2D8C9] mt-4">
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
      </aside>

      <main className="flex-1 min-w-0">
        {/* Mobile top bar */}
        <div className="md:hidden bg-white border-b border-[#E2D8C9] px-4 py-3 flex items-center justify-between sticky top-0 z-10">
          <Link to="/" className="flex items-center gap-2">
            <div className="logo-icon h-11 w-11 shrink-0">
              <img src={LOGO_URL} alt="غِراس" />
            </div>
            <span className="font-heading font-bold text-[#729352]">غِراس • الإدارة</span>
          </Link>
          <button onClick={doLogout} className="text-[#8B5A2B]"><LogOut className="w-5 h-5" /></button>
        </div>
        {/* Mobile nav pills */}
        <div className="md:hidden overflow-x-auto whitespace-nowrap px-4 py-3 border-b border-[#E2D8C9] bg-white">
          {items.map((it) => (
            <NavLink
              key={it.to}
              to={it.to}
              end={it.end}
              className={({ isActive }) =>
                `inline-flex items-center gap-1 rounded-full px-3 py-1.5 text-xs font-body ml-2 ${
                  isActive ? "bg-[#87A96B] text-white" : "bg-[#F8F1E7] text-[#5A677D]"
                }`
              }
            >
              <it.icon className="w-3 h-3" /> {it.label}
            </NavLink>
          ))}
        </div>

        <div className="p-6 md:p-10">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
