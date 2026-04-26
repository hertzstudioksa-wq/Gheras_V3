import React, { useEffect, useState } from "react";
import { api } from "../lib/api";
import { Package, Loader2, Sparkles, Clock, CheckCircle2, XCircle, AlertCircle } from "lucide-react";
import { toast } from "sonner";
import { useNavigate } from "react-router-dom";

const OUTPUT_LABEL = { video: "فيديو", pdf: "كتاب PDF", both: "فيديو + PDF" };
const STATUS_LABEL = {
  active:    { label: "نشطة",    bg: "bg-[#E8F0E1]", fg: "text-[#4F6B3B]", icon: CheckCircle2 },
  exhausted: { label: "مستهلكة", bg: "bg-[#F8F1E7]", fg: "text-[#8B5A2B]", icon: AlertCircle },
  expired:   { label: "منتهية",  bg: "bg-[#FCE6D4]", fg: "text-[#B8612F]", icon: XCircle },
};

export default function MyBundles() {
  const [purchases, setPurchases] = useState([]);
  const [available, setAvailable] = useState([]);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  useEffect(() => {
    Promise.all([
      api.get("/bundles/me?only_active=false"),
      api.get("/bundles"),
    ]).then(([p, b]) => {
      setPurchases(p.data?.purchases || []);
      setAvailable(b.data?.bundles || []);
    }).catch(() => toast.error("تعذّر التحميل"))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return <div className="min-h-screen bg-[#FDFBF7] flex items-center justify-center"><Loader2 className="w-8 h-8 animate-spin text-[#87A96B]" /></div>;
  }

  const buy = async (bundleId) => {
    try {
      const { data } = await api.post(`/checkout/bundle/${bundleId}`, {}, { headers: { "X-Origin": window.location.origin } });
      if (data?.url) window.location.href = data.url;
    } catch (e) {
      const status = e?.response?.status;
      if (status === 503) toast.error("الدفع غير مفعّل بعد. يمكنك متابعة استخدام الباقات الممنوحة من قِبل الإدارة.");
      else toast.error(e?.response?.data?.detail || "تعذّر إتمام الشراء");
    }
  };

  return (
    <div className="min-h-screen bg-[#FDFBF7] py-10 px-4" data-testid="my-bundles-page">
      <div className="max-w-4xl mx-auto">
        <h1 className="font-heading text-3xl font-bold text-[#2D3748] inline-flex items-center gap-2 mb-2">
          <Package className="w-7 h-7 text-[#87A96B]" /> باقاتي
        </h1>
        <p className="font-body text-sm text-[#5A677D] mb-6">رصيدك من القصص + الباقات المتاحة للشراء.</p>

        <h2 className="font-heading text-xl font-bold text-[#2D3748] mb-3">رصيدي الحالي</h2>
        {purchases.length === 0 ? (
          <div className="bg-white rounded-2xl p-6 border border-[#E2D8C9] text-center text-[#8A9AB0] font-body mb-8">
            لا توجد باقات نشطة. اختر إحدى الباقات أدناه.
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mb-8">
            {purchases.map((p) => {
              const stt = STATUS_LABEL[p.status] || STATUS_LABEL.active;
              const Icon = stt.icon;
              const total = p.quantity_total;
              const used = p.quantity_consumed;
              const reserved = p.quantity_reserved;
              return (
                <div key={p.id} className="bg-white rounded-2xl p-5 border border-[#E2D8C9]" data-testid={`my-purchase-${p.id}`}>
                  <div className="flex items-center justify-between mb-2">
                    <h3 className="font-heading font-bold text-[#2D3748]">{p.bundle_snapshot?.name}</h3>
                    <span className={`inline-flex items-center gap-1 text-xs font-bold rounded-full px-2 py-0.5 ${stt.bg} ${stt.fg}`}><Icon className="w-3 h-3" />{stt.label}</span>
                  </div>
                  <p className="text-xs text-[#5A677D] font-body mb-3">{p.bundle_snapshot?.description}</p>
                  <div className="bg-[#FDFBF7] rounded-xl p-3 mb-3">
                    <div className="text-xs text-[#5A677D] mb-1">المتبقّي</div>
                    <div className="text-2xl font-heading font-bold text-[#4F6B3B]">{p.quantity_remaining}<span className="text-sm text-[#8A9AB0] font-body"> / {total}</span></div>
                    <div className="text-[10px] text-[#8A9AB0] font-body mt-1">مستخدمة: {used} • محجوزة: {reserved}</div>
                  </div>
                  <div className="text-xs text-[#5A677D] font-body inline-flex items-center gap-1"><Clock className="w-3 h-3" /> تنتهي في {p.expires_at?.slice(0, 10)}</div>
                </div>
              );
            })}
          </div>
        )}

        <h2 className="font-heading text-xl font-bold text-[#2D3748] mb-3">الباقات المتاحة</h2>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-8">
          {available.map((b) => (
            <div key={b.id} className="bg-white rounded-2xl p-5 border border-[#E2D8C9]" data-testid={`available-bundle-${b.id}`}>
              <h3 className="font-heading font-bold text-[#2D3748] mb-1">{b.name}</h3>
              <p className="text-xs text-[#5A677D] font-body mb-3 min-h-[36px]">{b.description}</p>
              <div className="text-3xl font-heading font-bold text-[#4F6B3B] mb-1">{b.price} <span className="text-sm font-body text-[#8A9AB0]">{b.currency}</span></div>
              <div className="text-xs text-[#5A677D] font-body mb-4">{b.quantity}× {OUTPUT_LABEL[b.output_type]} • صالحة لـ {b.validity_days} يوم</div>
              <button onClick={() => buy(b.id)} className="w-full btn-primary inline-flex items-center justify-center gap-2" data-testid={`buy-bundle-${b.id}`}><Sparkles className="w-4 h-4" /> اشترِ الآن</button>
            </div>
          ))}
        </div>

        <button onClick={() => navigate("/dashboard")} className="text-sm text-[#5A677D] hover:text-[#2D3748] font-body">← رجوع</button>
      </div>
    </div>
  );
}
