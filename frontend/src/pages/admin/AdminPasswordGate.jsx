import React, { useState } from "react";
import { api } from "../../lib/api";
import { useAuth } from "../../contexts/AuthContext";
import { toast } from "sonner";
import { Lock } from "lucide-react";

/**
 * Shown instead of any admin page while the account still has a temporary
 * password (must_change_password). The backend blocks admin APIs until then.
 */
export default function AdminPasswordGate() {
  const { refresh } = useAuth();
  const [form, setForm] = useState({ current: "", next: "", confirm: "" });
  const [saving, setSaving] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    if (form.next.length < 10) return toast.error("كلمة المرور الجديدة يجب ألا تقل عن 10 أحرف");
    if (form.next !== form.confirm) return toast.error("تأكيد كلمة المرور غير مطابق");
    setSaving(true);
    try {
      await api.post("/auth/change-password", { current_password: form.current, new_password: form.next });
      toast.success("تم تحديث كلمة المرور");
      await refresh();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "تعذّر تحديث كلمة المرور");
    } finally {
      setSaving(false);
    }
  };

  const field = (key, label, autoComplete) => (
    <label className="block">
      <span className="font-body text-sm text-[#5A677D]">{label}</span>
      <input
        type="password"
        autoComplete={autoComplete}
        value={form[key]}
        onChange={(e) => setForm({ ...form, [key]: e.target.value })}
        className="mt-1 w-full bg-[#FDFBF7] border border-[#E2D8C9] rounded-2xl px-4 py-2 font-body"
        required
      />
    </label>
  );

  return (
    <div className="max-w-md" data-testid="admin-password-gate">
      <h1 className="font-heading text-3xl font-bold text-[#2D3748] mb-2 flex items-center gap-2">
        <Lock className="w-7 h-7 text-[#729352]" /> تغيير كلمة المرور
      </h1>
      <p className="font-body text-[#5A677D] mb-6">
        حسابك يستخدم كلمة مرور مؤقتة. غيّرها أولاً لتتمكن من استخدام لوحة الإدارة.
      </p>
      <form onSubmit={submit} className="bg-white rounded-3xl p-6 border border-[#E2D8C9] space-y-4">
        {field("current", "كلمة المرور الحالية", "current-password")}
        {field("next", "كلمة المرور الجديدة (10 أحرف على الأقل)", "new-password")}
        {field("confirm", "تأكيد كلمة المرور الجديدة", "new-password")}
        <button type="submit" disabled={saving} className="btn-primary w-full disabled:opacity-60">
          {saving ? "جارٍ الحفظ…" : "حفظ كلمة المرور"}
        </button>
      </form>
    </div>
  );
}
