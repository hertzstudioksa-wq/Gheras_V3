import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { Copy, Link2, Loader2, Share2, XCircle } from "lucide-react";
import { api } from "../../lib/api";

// A private link the family can watch the story from (30 days, can be switched
// off). WhatsApp sends that link; without one it invites friends to the site.
export default function FamilyShareCard({ orderId, childName }) {
  const [share, setShare] = useState(null);
  const [busy, setBusy] = useState(false);

  // The server knows the site's address only when PUBLIC_APP_URL is set.
  const absolute = (data) => (data?.url && data.url.startsWith("/")
    ? { ...data, url: `${window.location.origin}${data.url}` } : data);

  useEffect(() => {
    api.get(`/orders/${orderId}/share`).then(({ data }) => setShare(absolute(data))).catch(() => setShare({ active: false }));
  }, [orderId]);

  const make = async () => {
    setBusy(true);
    try {
      const { data } = await api.post(`/orders/${orderId}/share`);
      setShare(absolute(data));
      toast.success("الرابط جاهز 💚");
    } catch (e) {
      toast.error(e?.response?.data?.detail || "تعذّر عمل الرابط");
    } finally {
      setBusy(false);
    }
  };

  const revoke = async () => {
    setBusy(true);
    try {
      const { data } = await api.delete(`/orders/${orderId}/share`);
      setShare(data);
      toast.success("الرابط اتقفل — محدش هيقدر يفتحه تاني");
    } catch (e) {
      toast.error(e?.response?.data?.detail || "تعذّر قفل الرابط");
    } finally {
      setBusy(false);
    }
  };

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(share.url);
      toast.success("اتنسخ");
    } catch {
      toast.error("انسخه يدوي من الخانة");
    }
  };

  const whatsapp = () => {
    const name = childName || "طفلي";
    const message = share?.active
      ? `شوفوا قصة ${name} ✨\n${name} بقى بطل حكاية خاصة بيه 😍\n${share.url}`
      : `شوفوا القصة الجميلة دي ✨\nطفلي بقى بطل حكاية خاصة بيه 😍\nجربوا تعملوا قصة لأطفالكم من هنا:\n${window.location.origin}/`;
    window.open(`https://wa.me/?text=${encodeURIComponent(message)}`, "_blank", "noopener,noreferrer");
  };

  return (
    <div className="bg-white rounded-[2rem] p-5 md:p-6 border-2 border-[#25D366]/40" data-testid="family-share-card">
      <div className="flex items-center gap-3 mb-3">
        <div className="w-12 h-12 rounded-2xl bg-[#25D366]/10 grid place-content-center">
          <Share2 className="w-6 h-6 text-[#25D366]" />
        </div>
        <div>
          <h2 className="font-heading text-xl font-bold text-[#2D3748]">شارك القصة مع العيلة</h2>
          <p className="font-body text-xs text-[#5A677D]">
            رابط خاص يشوفوا منه الفيديو بس — شغّال 30 يوم، وتقدر تقفله في أي وقت.
          </p>
        </div>
      </div>

      {share?.active ? (
        <div className="space-y-3">
          <div className="flex items-center gap-2 bg-[#FDFBF7] rounded-xl border border-[#E2D8C9] p-2">
            <Link2 className="w-4 h-4 text-[#87A96B] shrink-0" />
            <input readOnly value={share.url} dir="ltr" onFocus={(e) => e.target.select()}
                   className="flex-1 bg-transparent text-xs font-mono text-[#2D3748] outline-none min-w-0" data-testid="share-url" />
            <button type="button" onClick={copy} className="text-[#4F6B3B] p-1" aria-label="نسخ"><Copy className="w-4 h-4" /></button>
          </div>
          <p className="text-[11px] text-[#8A9AB0] font-body">
            شغّال لحد {new Date(share.expires_at).toLocaleDateString("ar-EG")} · اتفتح {share.views || 0} مرة
          </p>
        </div>
      ) : null}

      <div className="flex flex-wrap gap-2 mt-3">
        {!share?.active && (
          <button type="button" onClick={make} disabled={busy || !share} data-testid="share-create-btn"
                  className="inline-flex items-center gap-2 rounded-full bg-[#87A96B] text-white px-5 py-2.5 text-sm font-bold disabled:opacity-50">
            {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Link2 className="w-4 h-4" />} اعمل رابط للعيلة
          </button>
        )}
        <button type="button" onClick={whatsapp} data-testid="whatsapp-share-btn"
                className="inline-flex items-center gap-2 rounded-full bg-[#25D366] hover:bg-[#1EBE57] text-white px-5 py-2.5 text-sm font-bold">
          <Share2 className="w-4 h-4" /> {share?.active ? "ابعته على واتساب" : "ادعُ أصحابك على واتساب"}
        </button>
        {share?.active && (
          <button type="button" onClick={revoke} disabled={busy} data-testid="share-revoke-btn"
                  className="inline-flex items-center gap-2 rounded-full bg-white border border-[#E2D8C9] text-[#B8612F] px-4 py-2.5 text-sm font-bold disabled:opacity-50">
            <XCircle className="w-4 h-4" /> اقفل الرابط
          </button>
        )}
      </div>
    </div>
  );
}
