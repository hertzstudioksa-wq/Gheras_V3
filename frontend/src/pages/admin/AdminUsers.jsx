import React, { useEffect, useState } from "react";
import { api } from "../../lib/api";
import { toast } from "sonner";
import { ShieldCheck, Ban, Check } from "lucide-react";

export default function AdminUsers() {
  const [users, setUsers] = useState([]);

  const reload = () => api.get("/admin/users").then((r) => setUsers(r.data));
  useEffect(() => { reload(); }, []);

  const toggleActive = async (u) => {
    try {
      await api.patch(`/admin/users/${u.id}`, { is_active: !u.is_active });
      toast.success("تم التحديث");
      reload();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "فشل");
    }
  };

  const changeRole = async (u) => {
    try {
      await api.patch(`/admin/users/${u.id}`, { role: u.role === "admin" ? "user" : "admin" });
      toast.success("تم التحديث");
      reload();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "فشل");
    }
  };

  return (
    <div data-testid="admin-users">
      <h1 className="font-heading text-3xl font-bold text-[#2D3748] mb-2">المستخدمين</h1>
      <p className="font-body text-[#5A677D] mb-6">إدارة حسابات الأهل والإدارة</p>

      <div className="bg-white rounded-3xl border border-[#E2D8C9] overflow-x-auto">
        <table className="w-full text-right">
          <thead className="bg-[#F8F1E7] text-[#5A677D] text-xs font-body">
            <tr>
              <th className="px-5 py-3 font-bold">الاسم</th>
              <th className="px-5 py-3 font-bold">البريد</th>
              <th className="px-5 py-3 font-bold">الدور</th>
              <th className="px-5 py-3 font-bold">الحالة</th>
              <th className="px-5 py-3 font-bold">التسجيل</th>
              <th className="px-5 py-3 font-bold">إجراءات</th>
            </tr>
          </thead>
          <tbody>
            {users.map((u) => (
              <tr key={u.id} className="border-t border-[#E2D8C9]" data-testid={`user-row-${u.id}`}>
                <td className="px-5 py-3 font-body font-bold">{u.full_name}</td>
                <td className="px-5 py-3 font-body text-sm text-[#5A677D]">{u.email}</td>
                <td className="px-5 py-3">
                  <span className={`rounded-full px-3 py-1 text-xs font-bold ${
                    u.role === "admin" ? "bg-[#E8F0E1] text-[#4F6B3B]" : "bg-[#F8F1E7] text-[#8B5A2B]"
                  }`}>
                    {u.role === "admin" ? "مدير" : "مستخدم"}
                  </span>
                </td>
                <td className="px-5 py-3">
                  <span className={`rounded-full px-3 py-1 text-xs font-bold ${
                    u.is_active ? "bg-[#DEEBCF] text-[#3F5B2E]" : "bg-[#FCE6D4] text-[#B8612F]"
                  }`}>
                    {u.is_active ? "مفعّل" : "معطّل"}
                  </span>
                </td>
                <td className="px-5 py-3 font-body text-xs text-[#8A9AB0]">
                  {new Date(u.created_at).toLocaleDateString("ar-EG")}
                </td>
                <td className="px-5 py-3">
                  <div className="flex gap-2">
                    <button
                      onClick={() => toggleActive(u)}
                      className="rounded-xl bg-[#F8F1E7] hover:bg-[#F2E8DA] text-[#8B5A2B] px-3 py-1.5 text-xs font-body font-bold inline-flex items-center gap-1"
                      data-testid={`user-toggle-${u.id}`}
                    >
                      {u.is_active ? <Ban className="w-3 h-3" /> : <Check className="w-3 h-3" />}
                      {u.is_active ? "تعطيل" : "تفعيل"}
                    </button>
                    <button
                      onClick={() => changeRole(u)}
                      className="rounded-xl bg-[#E8F0E1] hover:bg-[#DEEBCF] text-[#4F6B3B] px-3 py-1.5 text-xs font-body font-bold inline-flex items-center gap-1"
                      data-testid={`user-role-${u.id}`}
                    >
                      <ShieldCheck className="w-3 h-3" />
                      {u.role === "admin" ? "نزع إدارة" : "ترقية"}
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
