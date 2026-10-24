import React, { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { ArrowRight, KeyRound, Loader2, Trash2, UserRound } from "lucide-react";
import { api, setMediaToken } from "../lib/api";
import { useAuth } from "../contexts/AuthContext";
import Navbar from "../components/gheras/Navbar";
import Footer from "../components/gheras/Footer";

// My account (M7): change password and delete the account with all its data
// (privacy policy, audit CS-7).

const input = "w-full bg-[#FDFBF7] border border-[#E2D8C9] rounded-2xl px-4 py-2.5 font-body focus:outline-none focus:ring-2 focus:ring-[#87A96B]";

export default function Account() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [pw, setPw] = useState({ current: "", next: "", confirm: "" });
  const [saving, setSaving] = useState(false);
  const [del, setDel] = useState({ open: false, password: "", typed: "" });
  const [deleting, setDeleting] = useState(false);

  const changePassword = async (e) => {
    e.preventDefault();
    if (pw.next.length < 8) return toast.error("كلمة المرور الجديدة 8 أحرف على الأقل");
    if (pw.next !== pw.confirm) return toast.error("تأكيد كلمة المرور مش مطابق");
    setSaving(true);
    try {
      const { data } = await api.post("/auth/change-password", { current_password: pw.current, new_password: pw.next });
      localStorage.setItem("gheras_token", data.access_token);
      setMediaToken(data.media_token);
      setPw({ current: "", next: "", confirm: "" });
      toast.success("اتغيّرت كلمة المرور — أي جهاز تاني هيطلب دخول من جديد");
    } catch (err) {
      toast.error(err?.response?.data?.detail || "تعذّر تغيير كلمة المرور");
    } finally {
      setSaving(false);
    }
  };

  const deleteAccount = async () => {
    setDeleting(true);
    try {
      await api.post("/auth/delete-account", { password: del.password });
      toast.success("اتمسح حسابك وكل بياناته");
      logout();
      navigate("/");
    } catch (err) {
      toast.error(err?.response?.data?.detail || "تعذّر مسح الحساب");
      setDeleting(false);
    }
  };

  return (
    <div className="min-h-screen bg-[#FDFBF7]" data-testid="account-page">
      <Navbar />
      <main className="max-w-2xl mx-auto px-4 sm:px-6 py-8 md:py-12">
        <Link to="/dashboard" className="inline-flex items-center gap-2 text-[#5A677D] hover:text-[#2D3748] mb-6 font-body">
          <ArrowRight className="w-4 h-4" /> العودة إلى قصصي
        </Link>
        <h1 className="font-heading text-3xl font-bold text-[#2D3748] mb-6 flex items-center gap-2">
          <UserRound className="w-7 h-7 text-[#87A96B]" /> حسابي
        </h1>

        <section className="bg-white rounded-3xl border border-[#E2D8C9] p-5 mb-6 font-body">
          <div className="text-sm text-[#5A677D]">الاسم</div>
          <div className="font-bold text-[#2D3748] mb-3">{user?.full_name}</div>
          <div className="text-sm text-[#5A677D]">الإيميل</div>
          <div className="font-bold text-[#2D3748]" dir="ltr" style={{ textAlign: "right" }}>{user?.email}</div>
          <div className="mt-4 flex gap-4 text-sm">
            <Link to="/my-bundles" className="font-bold text-[#4F6B3B] underline">رصيدي</Link>
            <Link to="/privacy" className="font-bold text-[#4F6B3B] underline">سياسة الخصوصية</Link>
          </div>
        </section>

        <form onSubmit={changePassword} className="bg-white rounded-3xl border border-[#E2D8C9] p-5 mb-6 space-y-3" data-testid="change-password">
          <h2 className="font-heading text-xl font-bold text-[#2D3748] inline-flex items-center gap-2"><KeyRound className="w-5 h-5 text-[#87A96B]" /> تغيير كلمة المرور</h2>
          <input type="password" autoComplete="current-password" placeholder="كلمة المرور الحالية" className={input}
            value={pw.current} onChange={(e) => setPw({ ...pw, current: e.target.value })} />
          <input type="password" autoComplete="new-password" placeholder="كلمة المرور الجديدة (8 أحرف على الأقل)" className={input}
            value={pw.next} onChange={(e) => setPw({ ...pw, next: e.target.value })} />
          <input type="password" autoComplete="new-password" placeholder="أكّد كلمة المرور الجديدة" className={input}
            value={pw.confirm} onChange={(e) => setPw({ ...pw, confirm: e.target.value })} />
          <button type="submit" disabled={saving || !pw.current || !pw.next} className="btn-primary inline-flex items-center gap-2 disabled:opacity-50">
            {saving && <Loader2 className="w-4 h-4 animate-spin" />} حفظ
          </button>
        </form>

        {user?.role !== "admin" && (
        <section className="bg-white rounded-3xl border-2 border-[#F5D8C0] p-5" data-testid="delete-account">
          <h2 className="font-heading text-xl font-bold text-[#B8612F] inline-flex items-center gap-2"><Trash2 className="w-5 h-5" /> مسح الحساب</h2>
          <p className="font-body text-sm text-[#5A677D] mt-2">
            بيمسح اسمك وإيميلك، وكل الصور والقصص والملفات، وبيانات أطفالك من الطلبات. ما ينفعش يترجع.
            لو عندك رصيد أو قصة بتتجهّز، خلّصهم الأول.
          </p>
          {!del.open ? (
            <button onClick={() => setDel({ ...del, open: true })} className="mt-4 rounded-full bg-[#FCE6D4] text-[#B8612F] px-5 py-2 text-sm font-bold font-body">
              عايز أمسح حسابي
            </button>
          ) : (
            <div className="mt-4 space-y-3">
              <input type="password" autoComplete="current-password" placeholder="كلمة المرور" className={input}
                value={del.password} onChange={(e) => setDel({ ...del, password: e.target.value })} />
              <input placeholder='اكتب "امسح" للتأكيد' className={input}
                value={del.typed} onChange={(e) => setDel({ ...del, typed: e.target.value })} />
              <div className="flex gap-2">
                <button onClick={deleteAccount} disabled={deleting || !del.password || del.typed.trim() !== "امسح"}
                  className="rounded-full bg-[#B8612F] hover:bg-[#9C4F25] text-white px-5 py-2 text-sm font-bold font-body disabled:opacity-40 inline-flex items-center gap-2">
                  {deleting && <Loader2 className="w-4 h-4 animate-spin" />} امسح نهائياً
                </button>
                <button onClick={() => setDel({ open: false, password: "", typed: "" })} className="rounded-full bg-[#F8F1E7] text-[#8B5A2B] px-5 py-2 text-sm font-bold font-body">
                  إلغاء
                </button>
              </div>
            </div>
          )}
        </section>
        )}
      </main>
      <Footer />
    </div>
  );
}
