import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { CreditCard, Loader2, ShieldCheck, Wallet } from "lucide-react";
import { api } from "../../lib/api";

// Paying for a story (M6): shown after the parent picks a scenario when the
// store asks for payment before production. Wallet credit pays instantly; the
// card goes through Moyasar's hosted page (mada, Visa/Mastercard, Apple Pay)
// and comes back to the order page, which confirms the payment with the server.

const sar = (v) => `${Number(v || 0).toLocaleString("en-US", { maximumFractionDigits: 2 })} ر.س`;

export default function OrderPayment({ orderId, onPaid }) {
  const [info, setInfo] = useState(null);
  const [busy, setBusy] = useState(null);

  const load = () => api.get(`/orders/${orderId}/payment`).then((r) => setInfo(r.data)).catch(() => setInfo(false));
  useEffect(() => { load(); }, [orderId]); // eslint-disable-line react-hooks/exhaustive-deps

  const payWallet = async () => {
    setBusy("wallet");
    try {
      await api.post(`/orders/${orderId}/payment/wallet`);
      toast.success("تم الدفع من رصيدك — بدأنا نجهّز القصة 🌱");
      onPaid?.();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "تعذّر الدفع");
      load();
    } finally {
      setBusy(null);
    }
  };

  const payCard = async () => {
    setBusy("card");
    try {
      const { data } = await api.post(`/orders/${orderId}/payment/card`, null, { headers: { "X-Origin": window.location.origin } });
      if (data.paid) {
        toast.success("الطلب مدفوع بالفعل");
        onPaid?.();
        return;
      }
      window.location.assign(data.url);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "تعذّر فتح صفحة الدفع");
      setBusy(null);
    }
  };

  if (info === null) {
    return <div className="bg-white rounded-3xl p-8 border border-[#E2D8C9] flex justify-center"><Loader2 className="w-5 h-5 animate-spin text-[#87A96B]" /></div>;
  }
  if (!info) {
    return <div className="bg-white rounded-3xl p-6 border border-[#E2D8C9] font-body text-[#5A677D]">تعذّر تحميل بيانات الدفع. حدّث الصفحة.</div>;
  }

  const balance = info.wallet_halalas / 100;
  const enough = balance >= info.total_sar;
  return (
    <div className="bg-white rounded-3xl p-6 md:p-8 border border-[#E2D8C9]" data-testid="order-payment">
      <h2 className="font-heading text-2xl font-bold text-[#2D3748] mb-1">ادفع لنبدأ قصة طفلك</h2>
      <p className="font-body text-[#5A677D] mb-5">فور إتمام الدفع نبدأ تجهيز الخطة والرسومات والفيديو.</p>

      <div className="bg-[#FDFBF7] rounded-2xl border border-[#E2D8C9] p-4 mb-5 font-body">
        <div className="flex justify-between py-1"><span className="text-[#5A677D]">سعر القصة</span><span className="font-bold">{sar(info.amount_sar)}</span></div>
        {info.vat_sar > 0 && (
          <div className="flex justify-between py-1"><span className="text-[#5A677D]">ضريبة القيمة المضافة ({Math.round(info.vat_rate * 100)}%)</span><span>{sar(info.vat_sar)}</span></div>
        )}
        <div className="flex justify-between pt-2 mt-1 border-t border-[#E2D8C9] text-lg">
          <span className="font-bold text-[#2D3748]">الإجمالي</span><span className="font-heading font-bold text-[#4F6B3B]" data-testid="payment-total">{sar(info.total_sar)}</span>
        </div>
      </div>

      <div className="grid gap-3">
        <button onClick={payWallet} disabled={!enough || !!busy} data-testid="pay-wallet"
          className="w-full rounded-2xl border-2 border-[#87A96B] bg-[#E8F0E1] hover:bg-[#DCE9D0] px-5 py-4 text-right flex items-center gap-3 disabled:opacity-50 disabled:cursor-not-allowed">
          {busy === "wallet" ? <Loader2 className="w-6 h-6 animate-spin text-[#4F6B3B]" /> : <Wallet className="w-6 h-6 text-[#4F6B3B]" />}
          <span className="flex-1">
            <span className="block font-heading font-bold text-[#2D3748]">ادفع من رصيدك</span>
            <span className="block font-body text-sm text-[#5A677D]">
              رصيدك {sar(balance)}{!enough && " — غير كافٍ"}
            </span>
          </span>
        </button>
        {!enough && (
          <Link to="/my-bundles" className="font-body text-sm font-bold text-[#4F6B3B] underline text-center">اشحن رصيدك واحصل على هدية</Link>
        )}

        <button onClick={payCard} disabled={!info.card_available || !!busy} data-testid="pay-card"
          className="w-full rounded-2xl bg-[#2D3748] hover:bg-[#1F2937] text-white px-5 py-4 text-right flex items-center gap-3 disabled:opacity-50 disabled:cursor-not-allowed">
          {busy === "card" ? <Loader2 className="w-6 h-6 animate-spin" /> : <CreditCard className="w-6 h-6" />}
          <span className="flex-1">
            <span className="block font-heading font-bold">ادفع بالبطاقة</span>
            <span className="block font-body text-sm text-white/75">
              {info.card_available ? "مدى، فيزا، ماستركارد، Apple Pay" : "الدفع بالبطاقة غير متاح حالياً"}
            </span>
          </span>
        </button>
      </div>

      <p className="mt-4 font-body text-xs text-[#8A9AB0] flex items-center gap-1 justify-center">
        <ShieldCheck className="w-4 h-4" /> يتم الدفع في صفحة ميسر الآمنة — لا نطّلع على بيانات بطاقتك.
      </p>
    </div>
  );
}
