import React, { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { ArrowRight, Gift, Loader2, Package, Sparkles, Wallet } from "lucide-react";
import { api } from "../lib/api";
import Navbar from "../components/gheras/Navbar";
import Footer from "../components/gheras/Footer";
import { usePageTitle } from "../lib/usePageTitle";

// My balance (M6): SAR wallet credit bought in top-ups (with a bonus) and spent
// on stories. Older per-story bundle credits still show while they last.

const sar = (v) => `${Number(v || 0).toLocaleString("en-US", { maximumFractionDigits: 2 })} ر.س`;

export default function MyBundles() {
  usePageTitle("رصيدي");
  const [wallet, setWallet] = useState(null);
  const [purchases, setPurchases] = useState([]);
  const [busy, setBusy] = useState(null);
  const [searchParams, setSearchParams] = useSearchParams();

  const load = () => Promise.all([api.get("/wallet/me"), api.get("/bundles/me?only_active=true")])
    .then(([w, p]) => { setWallet(w.data); setPurchases(p.data?.purchases || []); })
    .catch(() => toast.error("تعذّر التحميل"));

  useEffect(() => {
    const pid = searchParams.get("payment");
    if (pid) {
      // Back from the Moyasar page: confirm the top-up with the server.
      api.post(`/wallet/topup/refresh/${pid}`)
        .then((r) => (r.data.status === "paid" ? toast.success("تم شحن رصيدك 🎉") : toast("الدفع لسه ما اكتملش")))
        .catch(() => {})
        .finally(() => { setSearchParams({}, { replace: true }); load(); });
    } else {
      load();
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const topup = async (b) => {
    setBusy(b.id);
    try {
      const { data } = await api.post(`/wallet/topup/${b.id}`, null, { headers: { "X-Origin": window.location.origin } });
      window.location.assign(data.url);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "تعذّر فتح صفحة الدفع");
      setBusy(null);
    }
  };

  return (
    <div className="min-h-screen bg-[#FDFBF7]" data-testid="my-bundles-page">
      <Navbar />
      <div className="max-w-4xl mx-auto px-4 sm:px-6 py-8 md:py-12">
        <Link to="/dashboard" className="inline-flex items-center gap-2 text-[#5A677D] hover:text-[#2D3748] mb-6 font-body">
          <ArrowRight className="w-4 h-4" /> العودة إلى قصصي
        </Link>

        {!wallet ? (
          <div className="flex justify-center py-20"><Loader2 className="w-8 h-8 animate-spin text-[#87A96B]" /></div>
        ) : (
          <>
            <div className="bg-gradient-to-br from-[#E8F0E1] via-[#F8F1E7] to-[#FDFBF7] rounded-[2rem] p-6 md:p-8 border border-[#E2D8C9] mb-8">
              <div className="inline-flex items-center gap-2 bg-white rounded-full px-3 py-1 text-xs font-bold text-[#729352] mb-3">
                <Wallet className="w-3.5 h-3.5" /> رصيدي
              </div>
              <div className="font-heading text-4xl md:text-5xl font-bold text-[#2D3748]" data-testid="wallet-balance">{sar(wallet.balance_halalas / 100)}</div>
              <p className="font-body text-[#5A677D] mt-2">ادفع منه أي قصة بضغطة واحدة. الضريبة (لو فيه) بتتحسب وقت شراء القصة.</p>
            </div>

            <h2 className="font-heading text-xl font-bold text-[#2D3748] mb-3">اشحن رصيدك</h2>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-3">
              {wallet.topups.map((b) => {
                const bonus = (b.credit_sar || 0) - b.price;
                return (
                  <div key={b.id} className={`bg-white rounded-3xl p-5 border-2 ${bonus > 0 ? "border-[#87A96B]" : "border-[#E2D8C9]"} flex flex-col`} data-testid={`topup-${b.id}`}>
                    {bonus > 0 && (
                      <span className="self-start inline-flex items-center gap-1 text-xs font-bold rounded-full px-2.5 py-1 bg-[#E8F0E1] text-[#4F6B3B] mb-2">
                        <Gift className="w-3.5 h-3.5" /> {sar(bonus)} هدية
                      </span>
                    )}
                    <div className="font-body text-sm text-[#5A677D]">ادفع</div>
                    <div className="font-heading text-3xl font-bold text-[#2D3748]">{sar(b.price)}</div>
                    <div className="font-body text-sm text-[#4F6B3B] font-bold mb-4">رصيدك يزيد {sar(b.credit_sar)}</div>
                    <button onClick={() => topup(b)} disabled={!wallet.card_available || !!busy}
                      className="mt-auto w-full btn-primary inline-flex items-center justify-center gap-2 disabled:opacity-50" data-testid={`buy-topup-${b.id}`}>
                      {busy === b.id ? <Loader2 className="w-4 h-4 animate-spin" /> : <Sparkles className="w-4 h-4" />} اشحن
                    </button>
                  </div>
                );
              })}
            </div>
            {!wallet.card_available && (
              <p className="font-body text-sm text-[#8B5A2B] mb-8">الشحن بالبطاقة هيتفعّل قريب.</p>
            )}

            {purchases.length > 0 && (
              <>
                <h2 className="font-heading text-xl font-bold text-[#2D3748] mt-8 mb-3">باقات القصص</h2>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mb-8">
                  {purchases.map((p) => (
                    <div key={p.id} className="bg-white rounded-2xl p-5 border border-[#E2D8C9] flex items-center gap-4">
                      <Package className="w-8 h-8 text-[#87A96B] shrink-0" />
                      <div className="flex-1">
                        <div className="font-heading font-bold text-[#2D3748]">{p.bundle_snapshot?.name}</div>
                        <div className="font-body text-xs text-[#5A677D]">تنتهي {p.expires_at?.slice(0, 10)}</div>
                      </div>
                      <div className="font-heading text-2xl font-bold text-[#4F6B3B]">{p.quantity_remaining}<span className="text-sm text-[#8A9AB0]"> / {p.quantity_total}</span></div>
                    </div>
                  ))}
                </div>
              </>
            )}

            <h2 className="font-heading text-xl font-bold text-[#2D3748] mt-8 mb-3">الحركات</h2>
            <div className="bg-white rounded-3xl border border-[#E2D8C9] divide-y divide-[#F0E9DD]" data-testid="wallet-history">
              {wallet.history.length === 0 && <div className="p-6 text-center font-body text-[#8A9AB0]">مفيش حركات لسه</div>}
              {wallet.history.map((h) => (
                <div key={h.id} className="p-4 flex items-center justify-between gap-3 font-body">
                  <div className="min-w-0">
                    <div className="font-bold text-[#2D3748]">{h.kind_ar}</div>
                    <div className="text-xs text-[#8A9AB0] truncate">{h.note || ""} · {new Date(h.created_at).toLocaleDateString("ar-EG")}</div>
                  </div>
                  <div className={`font-heading font-bold shrink-0 ${h.amount_halalas > 0 ? "text-[#4F6B3B]" : "text-[#B8612F]"}`} dir="ltr">
                    {h.amount_halalas > 0 ? "+" : "−"}{(Math.abs(h.amount_halalas) / 100).toLocaleString("en-US", { maximumFractionDigits: 2 })}
                  </div>
                </div>
              ))}
            </div>
          </>
        )}
      </div>
      <Footer />
    </div>
  );
}
