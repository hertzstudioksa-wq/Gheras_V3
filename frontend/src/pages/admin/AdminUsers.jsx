import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { Ban, Check, Search, ShieldCheck, Trash2 } from "lucide-react";
import { api } from "../../lib/api";
import { useAuth } from "../../contexts/AuthContext";
import { AdminPage, ConfirmAction, PageState, Pager, useDebounced } from "../../components/admin/AdminKit";
import { formatDate } from "../../lib/orderStatus";

// Users (M5b): server-side search and pages; role and activation changes ask
// first, are audited, and an admin can't demote or deactivate themself.

const LIMIT = 25;
const ROLES = [{ k: "all", l: "الكل" }, { k: "user", l: "أولياء الأمور" }, { k: "admin", l: "الإدارة" }];

export default function AdminUsers() {
  const { user: me } = useAuth();
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [q, setQ] = useState("");
  const [role, setRole] = useState("all");
  const [page, setPage] = useState(1);
  const debouncedQ = useDebounced(q);

  const load = () => {
    setError(null);
    api.get("/admin/users", { params: { q: debouncedQ, role, page, limit: LIMIT } })
      .then((r) => setData(r.data)).catch(() => setError("تعذّر تحميل المستخدمين"));
  };
  useEffect(() => { setPage(1); }, [debouncedQ, role]);
  useEffect(load, [debouncedQ, role, page]); // eslint-disable-line react-hooks/exhaustive-deps

  const update = async (u, patch, ok) => {
    try {
      await api.patch(`/admin/users/${u.id}`, patch);
      toast.success(ok);
      load();
    } catch (e) { toast.error(e?.response?.data?.detail || "فشل"); }
  };

  const items = data?.items || [];
  return (
    <AdminPage title="المستخدمين" description="حسابات أولياء الأمور والإدارة." testId="admin-users">
      <div className="flex flex-col md:flex-row md:items-center gap-3 mb-5">
        <label className="relative md:w-80">
          <Search className="w-4 h-4 text-[#8A9AB0] absolute top-1/2 -translate-y-1/2 right-3" />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="الاسم أو الإيميل"
            className="w-full bg-white border border-[#E2D8C9] rounded-2xl pr-9 pl-4 py-2 font-body text-sm focus:outline-none focus:border-[#87A96B]"
            data-testid="users-search" />
        </label>
        <div className="flex gap-2">
          {ROLES.map((r) => (
            <button key={r.k} onClick={() => setRole(r.k)}
              className={`rounded-full px-4 py-1.5 text-sm font-body ${role === r.k ? "bg-[#87A96B] text-white" : "bg-white border border-[#E2D8C9] text-[#5A677D]"}`}>
              {r.l}
            </button>
          ))}
        </div>
      </div>

      <PageState loading={!data && !error} error={error} onRetry={load} empty={data && !items.length} emptyText="مفيش مستخدمين بالبحث ده">
        <div className="bg-white rounded-3xl border border-[#E2D8C9] overflow-x-auto">
          <table className="w-full text-right min-w-[720px]">
            <thead className="bg-[#F8F1E7] text-[#5A677D] text-xs font-body">
              <tr>
                <th className="px-5 py-3 font-bold">الاسم</th>
                <th className="px-5 py-3 font-bold">الإيميل</th>
                <th className="px-5 py-3 font-bold">الطلبات</th>
                <th className="px-5 py-3 font-bold">الدور</th>
                <th className="px-5 py-3 font-bold">الحالة</th>
                <th className="px-5 py-3 font-bold">التسجيل</th>
                <th className="px-5 py-3 font-bold">إجراءات</th>
              </tr>
            </thead>
            <tbody>
              {items.map((u) => {
                const isMe = u.id === me?.id;
                return (
                  <tr key={u.id} className="border-t border-[#E2D8C9]" data-testid={`user-row-${u.id}`}>
                    <td className="px-5 py-3 font-body font-bold">{u.full_name}{isMe && <span className="text-xs text-[#8A9AB0] font-normal"> (أنت)</span>}</td>
                    <td className="px-5 py-3 font-body text-sm text-[#5A677D]">{u.email}</td>
                    <td className="px-5 py-3 font-body text-sm">{u.orders_count || 0}</td>
                    <td className="px-5 py-3">
                      <span className={`rounded-full px-3 py-1 text-xs font-bold ${u.role === "admin" ? "bg-[#E8F0E1] text-[#4F6B3B]" : "bg-[#F8F1E7] text-[#8B5A2B]"}`}>
                        {u.role === "admin" ? "إدارة" : "ولي أمر"}
                      </span>
                    </td>
                    <td className="px-5 py-3">
                      <span className={`rounded-full px-3 py-1 text-xs font-bold ${u.is_active !== false ? "bg-[#DEEBCF] text-[#3F5B2E]" : "bg-[#FCE6D4] text-[#B8612F]"}`}>
                        {u.is_active !== false ? "مفعّل" : "موقوف"}
                      </span>
                    </td>
                    <td className="px-5 py-3 font-body text-xs text-[#8A9AB0]">{formatDate(u.created_at, false)}</td>
                    <td className="px-5 py-3">
                      {isMe ? <span className="font-body text-xs text-[#8A9AB0]">—</span> : (
                        <div className="flex gap-2">
                          <ConfirmAction
                            title={u.is_active !== false ? `توقف حساب ${u.full_name}؟` : `تفعّل حساب ${u.full_name}؟`}
                            description={u.is_active !== false ? "مش هيقدر يدخل لحد ما تفعّله تاني. طلباته بتفضل زي ما هي." : "هيقدر يدخل تاني."}
                            confirmLabel={u.is_active !== false ? "إيقاف" : "تفعيل"}
                            tone={u.is_active !== false ? "danger" : "cost"}
                            onConfirm={() => update(u, { is_active: u.is_active === false }, "اتحدّث")}
                            className="rounded-xl bg-[#F8F1E7] hover:bg-[#F2E8DA] text-[#8B5A2B] px-3 py-1.5 text-xs font-body font-bold inline-flex items-center gap-1"
                            testId={`user-toggle-${u.id}`}>
                            {u.is_active !== false ? <Ban className="w-3 h-3" /> : <Check className="w-3 h-3" />}
                            {u.is_active !== false ? "إيقاف" : "تفعيل"}
                          </ConfirmAction>
                          <ConfirmAction
                            title={u.role === "admin" ? `تشيل صلاحية الإدارة من ${u.full_name}؟` : `تدّي ${u.full_name} صلاحية الإدارة؟`}
                            description={u.role === "admin" ? "هيرجع ولي أمر عادي." : "هيقدر يشوف كل الطلبات ويغيّر كل الإعدادات والمفاتيح."}
                            confirmLabel={u.role === "admin" ? "شيل الصلاحية" : "اديله الصلاحية"}
                            onConfirm={() => update(u, { role: u.role === "admin" ? "user" : "admin" }, "اتحدّث")}
                            className="rounded-xl bg-[#E8F0E1] hover:bg-[#DEEBCF] text-[#4F6B3B] px-3 py-1.5 text-xs font-body font-bold inline-flex items-center gap-1"
                            testId={`user-role-${u.id}`}>
                            <ShieldCheck className="w-3 h-3" />
                            {u.role === "admin" ? "شيل الإدارة" : "خليه إدارة"}
                          </ConfirmAction>
                          {u.role !== "admin" && !u.deleted_at && (
                            <ConfirmAction
                              title={`تمسح كل بيانات ${u.full_name}؟`}
                              description="لما ولي الأمر يطلب: بيتمسح اسمه وإيميله وكل صوره وقصصه وبيانات أطفاله. سجل المدفوعات بيفضل من غير بيانات شخصية. ما ينفعش يترجع. اكتب مصدر الطلب."
                              confirmLabel="امسح البيانات" requireReason
                              onConfirm={async (reason) => {
                                try {
                                  const r = await api.post(`/admin/users/${u.id}/delete-data`, { reason });
                                  toast.success(`اتمسح: ${r.data.files} ملف، ${r.data.orders} طلب`);
                                  load();
                                } catch (e) { toast.error(e?.response?.data?.detail || "فشل"); }
                              }}
                              className="rounded-xl bg-[#FCE6D4] hover:bg-[#F5D8C0] text-[#B8612F] px-3 py-1.5 text-xs font-body font-bold inline-flex items-center gap-1"
                              testId={`user-delete-${u.id}`}>
                              <Trash2 className="w-3 h-3" /> مسح البيانات
                            </ConfirmAction>
                          )}
                        </div>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <Pager page={data?.page || 1} limit={LIMIT} total={data?.total || 0} onPage={setPage} />
      </PageState>
    </AdminPage>
  );
}
