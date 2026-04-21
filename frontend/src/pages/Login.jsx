import React, { useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../contexts/AuthContext";
import { Sprout, LogIn, AlertCircle } from "lucide-react";
import { toast } from "sonner";

const LOGO_URL = "/gheras-logo.png";

export default function Login() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const redirectTo = location.state?.from?.pathname || "/dashboard";

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");

  const submit = async (e) => {
    e.preventDefault();
    setErr("");
    setLoading(true);
    // eslint-disable-next-line no-console
    console.debug("[auth] login:start email=", email.trim().toLowerCase());
    try {
      const u = await login(email.trim().toLowerCase(), password);
      // eslint-disable-next-line no-console
      console.debug("[auth] login:success user=", u?.email);
      toast.success(`أهلاً ${u.full_name} 🌱`);
      navigate(u.role === "admin" ? "/admin" : redirectTo, { replace: true });
    } catch (e) {
      const status = e?.response?.status;
      const detail = e?.response?.data?.detail;
      // eslint-disable-next-line no-console
      console.debug("[auth] login:failure status=", status, "detail=", detail, "code=", e?.code);
      // Map to precise user-facing Arabic message.
      let msg;
      if (status === 401 || status === 403) {
        msg = "بيانات تسجيل الدخول غير صحيحة";
      } else if (status === 400 && detail) {
        msg = detail; // backend already returns a clear validation message
      } else if (status === 429) {
        msg = "محاولات كثيرة. يُرجى الانتظار قليلاً.";
      } else if (status && status >= 500) {
        msg = "تعذر تسجيل الدخول الآن، حاول مرة أخرى بعد قليل";
      } else if (!e?.response) {
        // No response — network / CORS / timeout.
        msg = e?.code === "ECONNABORTED"
          ? "انتهى وقت الاتصال. تحقّق من الشبكة وحاول مجدداً"
          : "تعذّر الوصول إلى الخادم. تحقّق من الإنترنت وحاول مجدداً";
      } else {
        msg = detail || "تعذر تسجيل الدخول، حاول مرة أخرى";
      }
      setErr(msg);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-[#FDFBF7] flex items-center justify-center py-16 px-4" data-testid="login-page">
      <div className="max-w-md w-full">
        <Link to="/" className="flex flex-col items-center gap-1 mb-4">
          <img src={LOGO_URL} alt="غِراس" className="logo-img h-40 w-40 shrink-0 hover:scale-105 transition-transform duration-500" />
        </Link>

        <div className="bg-white rounded-[2rem] p-8 md:p-10 border border-[#E2D8C9] shadow-sm animate-grow">
          <h1 className="font-heading text-3xl font-bold text-[#2D3748] mb-2 text-center">
            أهلاً بعودتك
          </h1>
          <p className="font-body text-[#5A677D] text-center mb-8">
            سجّل دخولك لمتابعة قصص طفلك
          </p>

          <form onSubmit={submit} className="space-y-4" data-testid="login-form">
            <div>
              <label className="block text-sm font-bold text-[#2D3748] mb-2 font-body">البريد الإلكتروني</label>
              <input
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@example.com"
                className="w-full bg-[#FDFBF7] border border-[#E2D8C9] rounded-2xl px-5 py-3 font-body focus:outline-none focus:ring-2 focus:ring-[#87A96B]"
                data-testid="login-email"
              />
            </div>
            <div>
              <label className="block text-sm font-bold text-[#2D3748] mb-2 font-body">كلمة المرور</label>
              <input
                type="password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                className="w-full bg-[#FDFBF7] border border-[#E2D8C9] rounded-2xl px-5 py-3 font-body focus:outline-none focus:ring-2 focus:ring-[#87A96B]"
                data-testid="login-password"
              />
            </div>

            {err && (
              <div className="flex items-start gap-2 bg-[#FCE6D4] text-[#B8612F] rounded-2xl p-3 text-sm font-body">
                <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />
                <span>{err}</span>
              </div>
            )}

            <button
              type="submit"
              disabled={loading}
              className="w-full btn-primary inline-flex items-center justify-center gap-2 disabled:opacity-70"
              data-testid="login-submit"
            >
              <LogIn className="w-4 h-4" />
              {loading ? "جاري الدخول..." : "تسجيل الدخول"}
            </button>
          </form>

          <p className="text-center text-sm text-[#5A677D] mt-6 font-body">
            ليس لديك حساب؟{" "}
            <Link to="/signup" className="text-[#729352] font-bold" data-testid="login-to-signup">
              أنشئ حساباً جديداً
            </Link>
          </p>
        </div>

        <p className="text-center text-xs text-[#8A9AB0] mt-6 font-body flex items-center justify-center gap-1">
          <Sprout className="w-3 h-3" />
          نزرع القيم قبل أن نكتب الكلمات
        </p>
      </div>
    </div>
  );
}
