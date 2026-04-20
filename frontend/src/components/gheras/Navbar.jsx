import React, { useState } from "react";
import { Link, NavLink, useNavigate } from "react-router-dom";
import { useAuth } from "../../contexts/AuthContext";
import { Menu, X, Sprout, LogOut, LayoutDashboard, Shield } from "lucide-react";

const LOGO_URL = "/gheras-logo.png";

export default function Navbar() {
  const { user, logout } = useAuth();
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();

  const linkCls = ({ isActive }) =>
    `text-base font-body transition-colors ${
      isActive ? "text-[#87A96B] font-bold" : "text-[#2D3748] hover:text-[#729352]"
    }`;

  const doLogout = () => {
    logout();
    navigate("/");
    setOpen(false);
  };

  return (
    <header className="sticky top-0 z-50 bg-[#FDFBF7]/85 backdrop-blur-md border-b border-[#E2D8C9]/60" data-testid="main-navbar">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-24 flex items-center justify-between">
        <Link to="/" className="flex items-center gap-2" data-testid="nav-logo">
          <div className="logo-icon h-14 w-14 md:h-16 md:w-16 shrink-0">
            <img src={LOGO_URL} alt="غِراس" />
          </div>
          <span className="font-heading text-2xl md:text-3xl font-bold text-[#729352] hidden sm:block">غِراس</span>
        </Link>

        <nav className="hidden md:flex items-center gap-10">
          <NavLink to="/" end className={linkCls} data-testid="nav-home">الرئيسية</NavLink>
          <NavLink to="/how-it-works" className={linkCls} data-testid="nav-how">كيف تعمل</NavLink>
          <NavLink to="/categories" className={linkCls} data-testid="nav-categories">التصنيفات</NavLink>
          {user && (
            <NavLink to="/dashboard" className={linkCls} data-testid="nav-dashboard">قصصي</NavLink>
          )}
          {user?.role === "admin" && (
            <NavLink to="/admin" className={linkCls} data-testid="nav-admin">
              <span className="inline-flex items-center gap-1"><Shield className="w-4 h-4" /> الإدارة</span>
            </NavLink>
          )}
        </nav>

        <div className="hidden md:flex items-center gap-3">
          {user ? (
            <>
              <span className="text-sm text-[#5A677D]">مرحباً، {user.full_name}</span>
              <button
                onClick={doLogout}
                className="inline-flex items-center gap-2 rounded-full bg-[#F8F1E7] hover:bg-[#F2E8DA] text-[#8B5A2B] px-5 py-2 text-sm font-bold transition"
                data-testid="nav-logout-btn"
              >
                <LogOut className="w-4 h-4" /> خروج
              </button>
            </>
          ) : (
            <>
              <Link to="/login" className="text-[#5A677D] hover:text-[#2D3748] text-sm font-bold px-4 py-2" data-testid="nav-login-btn">
                دخول
              </Link>
              <Link
                to="/story/new"
                className="inline-flex items-center gap-2 btn-primary text-sm"
                data-testid="nav-cta-btn"
              >
                <Sprout className="w-4 h-4" /> ابدأ قصة
              </Link>
            </>
          )}
        </div>

        <button
          className="md:hidden p-2 rounded-lg hover:bg-[#F8F1E7]"
          onClick={() => setOpen((v) => !v)}
          data-testid="nav-mobile-toggle"
          aria-label="Menu"
        >
          {open ? <X className="w-6 h-6" /> : <Menu className="w-6 h-6" />}
        </button>
      </div>

      {open && (
        <div className="md:hidden border-t border-[#E2D8C9] bg-[#FDFBF7]" data-testid="mobile-menu">
          <div className="px-6 py-5 flex flex-col gap-4">
            <NavLink to="/" end onClick={() => setOpen(false)} className={linkCls}>الرئيسية</NavLink>
            <NavLink to="/how-it-works" onClick={() => setOpen(false)} className={linkCls}>كيف تعمل</NavLink>
            <NavLink to="/categories" onClick={() => setOpen(false)} className={linkCls}>التصنيفات</NavLink>
            {user && <NavLink to="/dashboard" onClick={() => setOpen(false)} className={linkCls}>قصصي</NavLink>}
            {user?.role === "admin" && (
              <NavLink to="/admin" onClick={() => setOpen(false)} className={linkCls}>لوحة الإدارة</NavLink>
            )}
            <div className="border-t border-[#E2D8C9] pt-4 flex gap-3">
              {user ? (
                <button onClick={doLogout} className="btn-primary text-sm w-full">
                  تسجيل الخروج
                </button>
              ) : (
                <>
                  <Link to="/login" onClick={() => setOpen(false)} className="flex-1 text-center px-4 py-2 rounded-full border border-[#E2D8C9] text-[#2D3748]">دخول</Link>
                  <Link to="/story/new" onClick={() => setOpen(false)} className="flex-1 btn-primary text-sm text-center">ابدأ قصة</Link>
                </>
              )}
            </div>
          </div>
        </div>
      )}
    </header>
  );
}
