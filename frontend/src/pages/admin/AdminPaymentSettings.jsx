import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { CheckCircle2, RefreshCw, ShieldAlert } from "lucide-react";
import { api } from "../../lib/api";
import { AdminPage, ConfirmAction, KpiCard, PageState, Pager, useDebounced } from "../../components/admin/AdminKit";
import { formatDate } from "../../lib/orderStatus";

// Payments (M6): Moyasar status and the "pay before production" switch, then
// every card payment (story or wallet top-up) with totals.

const STATUS = {
  pending: ["مستنية الدفع", "bg-[#FBEFD5] text-[#8B5A2B]"],
  paid: ["مدفوعة", "bg-[#E8F0E1] text-[#4F6B3B]"],
  failed: ["فشلت", "bg-[#FCE6D4] text-[#B8612F]"],
  expired: ["انتهت", "bg-[#F0E9DD] text-[#8A9AB0]"],
  canceled: ["اتلغت", "bg-[#F0E9DD] text-[#8A9AB0]"],
  mismatch: ["مبلغ مختلف!", "bg-[#FCE6D4] text-[#B8612F]"],
  refunded: ["مستردة", "bg-[#F0E9DD] text-[#5A677D]"],
};
const PURPOSE = { order: "قصة", topup: "شحن رصيد" };
const sar = (v) => `${Number(v || 0).toLocaleString("en-US", { maximumFractionDigits: 2 })} ر.س`;

export default function AdminPaymentSettings() {
  const [status, setStatus] = useState(null);
  const [error, setError] = useState(null);
  const [list, setList] = useState(null);
  const [filters, setFilters] = useState({ status: "", purpose: "", q: "", page: 1 });
  const q = useDebounced(filters.q);

  const loadStatus = () => {
    setError(null);
    api.get("/admin/payment/status").then((r) => setStatus(r.data)).catch(() => setError("تعذّر تحميل حالة الدفع"));
  };
  const loadList = () => {
    api.get("/admin/payment/payments", { params: { status: filters.status || undefined, purpose: filters.purpose || undefined, q: q || undefined, page: filters.page, limit: 30 } })
      .then((r) => setList(r.data)).catch(() => setList({ items: [], total: 0, totals: {} }));
  };
  useEffect(loadStatus, []);
  useEffect(loadList, [filters.status, filters.purpose, q, filters.page]); // eslint-disable-line react-hooks/exhaustive-deps

  const setRequired = async (value) => {
    try {
      const r = await api.put("/admin/payment/settings", { payment_required: value });
      setStatus(r.data);
      toast.success(value ? "الدفع بقى مطلوب قبل الإنتاج" : "الإنتاج بيبدأ من غير دفع");
    } catch (e) { toast.error(e?.response?.data?.detail || "فشل"); }
  };
  const testKey = async () => {
    const r = await api.post("/admin/payment/test");
    if (r.data.ok) toast.success(`المفتاح شغّال (${r.data.mode === "live" ? "حقيقي" : "تجربة"})`);
    else toast.error(r.data.error);
  };
  const refresh = async (p) => {
    try { await api.post(`/admin/payment/payments/${p.id}/refresh`); loadList(); toast.success("اتحدّثت من ميسر"); }
    catch (e) { toast.error(e?.response?.data?.detail || "فشل"); }
  };

  const t = list?.totals || {};
  const th = "px-3 py-2 font-body text-xs font-bold text-[#5A677D] text-right whitespace-nowrap";
  const td = "px-3 py-2 font-body text-sm whitespace-nowrap";
  return (
    <AdminPage title="المدفوعات" testId="admin-payment-page"
      description="الدفع عن طريق ميسر (مدى، فيزا/ماستركارد، Apple Pay). العميل بيدفع سعر القصة اللي شافه، أو من رصيده.">
      <PageState loading={!status && !error} error={error} onRetry={loadStatus}>
        {status && (
          <section className="bg-white rounded-3xl border border-[#E2D8C9] p-5 mb-6" data-testid="payment-status">
            <div className="flex items-start gap-3 flex-wrap justify-between">
              <div className="flex items-start gap-3">
                {status.configured ? <CheckCircle2 className="w-7 h-7 text-[#4F6B3B] shrink-0" /> : <ShieldAlert className="w-7 h-7 text-[#B8612F] shrink-0" />}
                <div>
                  <div className="font-heading text-lg font-bold text-[#2D3748]">
                    {status.configured ? `ميسر متوصّل — ${status.mode === "live" ? "وضع حقيقي" : "وضع تجربة"}` : "ميسر مش متوصّل"}
                  </div>
                  <p className="font-body text-sm text-[#5A677D]">
                    {status.configured
                      ? <>المفتاح {status.key_masked}. </>
                      : <>سجّل الـ Secret Key من <Link to="/admin/secrets" className="underline font-bold">صفحة المفاتيح</Link> (ابدأ بـ sk_test للتجربة). </>}
                    {status.callback_url
                      ? <>ميسر بيبلّغنا بالدفع على <span dir="ltr">{status.callback_url}</span>.</>
                      : <>تأكيد الدفع بيتم لما العميل يرجع للموقع (عشان ميسر يبلّغنا مباشرة لازم PUBLIC_API_URL بـ https على السيرفر).</>}
                  </p>
                </div>
              </div>
              {status.configured && (
                <button onClick={testKey} className="rounded-full bg-[#F8F1E7] text-[#8B5A2B] px-4 py-2 text-sm font-bold font-body">اختبار المفتاح</button>
              )}
            </div>
            <div className="mt-5 pt-4 border-t border-[#F0E9DD] flex items-center justify-between gap-3 flex-wrap">
              <div className="font-body">
                <div className="font-bold text-[#2D3748]">الدفع قبل الإنتاج</div>
                <div className="text-sm text-[#5A677D]">
                  {status.payment_required
                    ? "مطلوب: بعد اختيار السيناريو العميل بيدفع، وبعدها بس الإنتاج بيبدأ."
                    : "مش مطلوب: الإنتاج بيبدأ على طول من غير دفع (مناسب للتجربة بس)."}
                </div>
              </div>
              <ConfirmAction
                title={status.payment_required ? "توقف الدفع قبل الإنتاج؟" : "تطلب الدفع قبل الإنتاج؟"}
                description={status.payment_required ? "أي طلب جديد هيدخل الإنتاج من غير ما يدفع." : "أي طلب جديد هيستنى الدفع (رصيد أو بطاقة) قبل ما نصرف على توليده."}
                tone={status.payment_required ? "danger" : "cost"} confirmLabel={status.payment_required ? "أوقفه" : "فعّله"}
                onConfirm={() => setRequired(!status.payment_required)} testId="toggle-payment-required"
                className={`rounded-full px-5 py-2 text-sm font-bold font-body ${status.payment_required ? "bg-[#FCE6D4] text-[#B8612F]" : "bg-[#87A96B] text-white"}`}>
                {status.payment_required ? "إيقاف" : "تفعيل"}
              </ConfirmAction>
            </div>
          </section>
        )}

        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-4">
          <KpiCard label="قصص مدفوعة بالبطاقة" value={sar(t.card_orders?.sar)} hint={`${t.card_orders?.n || 0} عملية`} />
          <KpiCard label="قصص مدفوعة من الرصيد" value={sar(t.wallet_orders?.sar)} hint={`${t.wallet_orders?.n || 0} طلب`} />
          <KpiCard label="شحن رصيد" value={sar(t.topups?.sar)} hint={`${t.topups?.n || 0} عملية`} />
        </div>

        <div className="flex gap-2 flex-wrap mb-3">
          <input value={filters.q} onChange={(e) => setFilters({ ...filters, q: e.target.value, page: 1 })} placeholder="إيميل، رقم الطلب أو الفاتورة"
            className="flex-1 min-w-[200px] bg-white border border-[#E2D8C9] rounded-2xl px-4 py-2 font-body text-sm" />
          <select value={filters.purpose} onChange={(e) => setFilters({ ...filters, purpose: e.target.value, page: 1 })}
            className="bg-white border border-[#E2D8C9] rounded-2xl px-3 py-2 font-body text-sm">
            <option value="">كل الأنواع</option><option value="order">قصص</option><option value="topup">شحن رصيد</option>
          </select>
          <select value={filters.status} onChange={(e) => setFilters({ ...filters, status: e.target.value, page: 1 })}
            className="bg-white border border-[#E2D8C9] rounded-2xl px-3 py-2 font-body text-sm">
            <option value="">كل الحالات</option>
            {Object.entries(STATUS).map(([k, [label]]) => <option key={k} value={k}>{label}</option>)}
          </select>
        </div>
        <div className="bg-white rounded-3xl border border-[#E2D8C9] overflow-x-auto" data-testid="payments-table">
          <table className="w-full">
            <thead className="bg-[#FDFBF7] border-b border-[#E2D8C9]">
              <tr><th className={th}>التاريخ</th><th className={th}>العميل</th><th className={th}>النوع</th><th className={th}>المبلغ</th><th className={th}>الحالة</th><th className={th}>الطريقة</th><th className={th}></th></tr>
            </thead>
            <tbody className="divide-y divide-[#F0E9DD]">
              {list && list.items.length === 0 && <tr><td colSpan={7} className="px-3 py-6 text-center font-body text-sm text-[#8A9AB0]">مفيش عمليات دفع لسه</td></tr>}
              {(list?.items || []).map((p) => {
                const [label, cls] = STATUS[p.status] || [p.status, "bg-[#F0E9DD] text-[#5A677D]"];
                return (
                  <tr key={p.id}>
                    <td className={td}>{formatDate(p.created_at)}</td>
                    <td className={td}>{p.user_email}</td>
                    <td className={td}>
                      {PURPOSE[p.purpose] || p.purpose}
                      {p.order_id && <Link to={`/admin/orders/${p.order_id}`} className="mr-1 text-xs text-[#4F6B3B] underline" dir="ltr">{p.order_id.slice(0, 8)}</Link>}
                      {p.mode === "test" && <span className="mr-1 text-[10px] font-bold rounded-full px-1.5 py-0.5 bg-[#F0E9DD] text-[#8A9AB0]">تجربة</span>}
                    </td>
                    <td className={`${td} font-bold`}>{sar(p.amount_sar)}</td>
                    <td className={td}><span className={`text-xs font-bold rounded-full px-2 py-0.5 ${cls}`}>{label}</span></td>
                    <td className={td}>{p.source || "—"}</td>
                    <td className={td}>
                      {p.status === "pending" && (
                        <button onClick={() => refresh(p)} title="اسأل ميسر عن الحالة" aria-label="تحديث من ميسر" className="p-1.5 rounded-lg border border-[#E2D8C9] bg-white"><RefreshCw className="w-3.5 h-3.5" /></button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        {list && <Pager page={list.page} limit={list.limit} total={list.total} onPage={(page) => setFilters({ ...filters, page })} />}
      </PageState>
    </AdminPage>
  );
}
