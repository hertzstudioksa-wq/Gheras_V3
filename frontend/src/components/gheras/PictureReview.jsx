import React, { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { CheckCircle2, Loader2, RefreshCcw, Sparkles, X, ZoomIn } from "lucide-react";
import { api, errorMessage, fileSrc } from "@/lib/api";
import { countLabel, imagesLabel } from "@/lib/arabic";

const redrawsLabel = (n) => countLabel(n, ["إعادة واحدة", "إعادتان", "إعادات", "إعادة"]);

/**
 * Every shot's picture, before any is animated (services/picture_review.py): the
 * parent sends back the ones they don't like (a few redraws per story) and approves
 * the rest; only then are the pictures turned into the video.
 */
export default function PictureReview({ orderId, childName, onApproved }) {
  const [data, setData] = useState(null);
  const [picked, setPicked] = useState([]);
  const [reason, setReason] = useState("likeness");
  const [busy, setBusy] = useState(false);
  const [zoom, setZoom] = useState(null);

  const load = useCallback(async () => {
    try {
      const { data: d } = await api.get(`/orders/${orderId}/pictures`);
      setData(d);
    } catch { /* the page's own poll shows connection trouble */ }
  }, [orderId]);

  useEffect(() => { load(); }, [load]);
  const redrawing = data?.state === "redrawing";
  useEffect(() => {
    if (!redrawing) return undefined;
    const iv = setInterval(load, 4000);
    return () => clearInterval(iv);
  }, [redrawing, load]);

  if (!data) {
    return (
      <div className="bg-white rounded-[2rem] p-6 border border-[#E2D8C9] flex items-center gap-2 font-body text-[#5A677D]">
        <Loader2 className="w-4 h-4 animate-spin" /> نجهّز الصور...
      </div>
    );
  }

  const key = (s) => `${s.scene_index}-${s.shot_index}`;
  const left = data.redraws_left || 0;
  const toggle = (s) => {
    if (redrawing || !s.picture_url) return;
    const k = key(s);
    if (picked.includes(k)) setPicked(picked.filter((x) => x !== k));
    else if (picked.length < left) setPicked([...picked, k]);
    else toast.error(left ? `متبقي لك ${redrawsLabel(left)} فقط` : "استخدمت كل إعادات الرسم المتاحة");
  };

  const redraw = async () => {
    setBusy(true);
    try {
      const shots = data.shots.filter((s) => picked.includes(key(s)))
        .map((s) => ({ scene_index: s.scene_index, shot_index: s.shot_index }));
      await api.post(`/orders/${orderId}/pictures/redraw`, { shots, reason });
      setPicked([]);
      toast.success("نعيد رسمها الآن 🖌️");
      await load();
    } catch (e) {
      toast.error(errorMessage(e, "تعذّر طلب إعادة الرسم"));
    } finally {
      setBusy(false);
    }
  };

  const approve = async () => {
    setBusy(true);
    try {
      await api.post(`/orders/${orderId}/pictures/approve`);
      toast.success("رائع! بدأنا تحريك الصور 🎬");
      onApproved?.();
    } catch (e) {
      toast.error(errorMessage(e, "تعذّر الاعتماد، حاول مرة أخرى"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-4" data-testid="picture-review">
      <div className="bg-white rounded-[2rem] p-5 md:p-6 border-2 border-[#D4A373]">
        <h2 className="font-heading text-xl md:text-2xl font-bold text-[#2D3748] mb-1 flex items-center gap-2">
          <Sparkles className="w-5 h-5 text-[#D4A373]" /> صور قصة {childName || "طفلك"} جاهزة
        </h2>
        <p className="font-body text-sm text-[#5A677D] leading-relaxed">
          هذه صورة كل لقطة قبل أن نحرّكها. إن لم تعجبك صورة اضغط «أعد رسمها»، ثم اعتمد الصور لنبدأ الفيديو.
          {" "}
          <span className="font-bold text-[#8B5A2B]" data-testid="redraws-left">
            {left ? `متبقي لك ${redrawsLabel(left)} مجاناً.` : "استخدمت كل إعادات الرسم."}
          </span>
        </p>
        {redrawing && (
          <div className="mt-3 flex items-center gap-2 rounded-2xl bg-[#FBEFD5] px-4 py-3 font-body text-sm text-[#8B5A2B]"
               data-testid="redrawing-banner">
            <Loader2 className="w-4 h-4 animate-spin shrink-0" />
            نعيد رسم الصور التي اخترتها — تستغرق دقيقة أو اثنتين، وستظهر هنا تلقائياً.
          </div>
        )}
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        {data.shots.map((s) => {
          const k = key(s);
          const on = picked.includes(k);
          return (
            <div key={k} data-testid={`review-shot-${k}`}
                 className={`bg-white rounded-[1.5rem] p-3 border-2 transition ${on ? "border-[#E07A5F]" : "border-[#E2D8C9]"}`}>
              <div className="relative rounded-2xl overflow-hidden bg-[#F2E8DA] aspect-video">
                {s.picture_url && (
                  <button type="button" onClick={() => setZoom(fileSrc(s.picture_url))} className="block w-full h-full"
                          aria-label="تكبير الصورة">
                    <img src={fileSrc(s.picture_url)} alt="" loading="lazy" className="w-full h-full object-cover" />
                    <ZoomIn className="absolute top-2 left-2 w-7 h-7 p-1.5 rounded-full bg-white/80 text-[#2D3748]" />
                  </button>
                )}
                {(s.redrawing || !s.picture_url) && (
                  <div className="absolute inset-0 grid place-content-center bg-white/75 font-body text-sm text-[#5A677D] gap-1 text-center">
                    <Loader2 className="w-6 h-6 animate-spin mx-auto text-[#87A96B]" /> نعيد رسمها...
                  </div>
                )}
                {s.redrawn && s.picture_url && !s.redrawing && (
                  <span className="absolute bottom-2 right-2 rounded-full bg-white/90 px-2 py-0.5 text-[11px] font-bold text-[#4F6B3B]">
                    رُسمت من جديد
                  </span>
                )}
              </div>
              <div className="flex items-start justify-between gap-2 mt-2">
                <div className="min-w-0">
                  <div className="font-body text-xs text-[#8A9AB0]">المشهد {s.scene_index} · لقطة {s.shot_index}</div>
                  {s.narration_line && (
                    <p className="font-body text-sm text-[#2D3748] leading-relaxed">«{s.narration_line}»</p>
                  )}
                </div>
                <button type="button" onClick={() => toggle(s)} disabled={redrawing || !s.picture_url}
                        data-testid={`redraw-toggle-${k}`}
                        className={`shrink-0 inline-flex items-center gap-1 rounded-full px-3 py-1.5 text-xs font-bold transition disabled:opacity-40 ${
                          on ? "bg-[#E07A5F] text-white" : "bg-[#F8F1E7] text-[#8B5A2B] hover:bg-[#FBEFD5]"}`}>
                  <RefreshCcw className="w-3.5 h-3.5" /> {on ? "ستُعاد" : "أعد رسمها"}
                </button>
              </div>
            </div>
          );
        })}
      </div>

      <div className="sticky bottom-3 z-10 bg-white/95 backdrop-blur rounded-[1.5rem] p-4 border border-[#E2D8C9] shadow-sm space-y-3">
        {picked.length > 0 && (
          <div>
            <div className="font-body text-xs text-[#5A677D] mb-2">ما المشكلة في الصور التي اخترتها؟</div>
            <div className="flex flex-wrap gap-2 mb-3">
              {Object.entries(data.reasons || {}).map(([k, label]) => (
                <button key={k} type="button" onClick={() => setReason(k)} data-testid={`reason-${k}`}
                        className={`rounded-full px-3 py-1.5 text-xs font-bold border ${
                          reason === k ? "bg-[#2D3748] text-white border-[#2D3748]" : "bg-white text-[#5A677D] border-[#E2D8C9]"}`}>
                  {label}
                </button>
              ))}
            </div>
            <button type="button" onClick={redraw} disabled={busy} data-testid="redraw-btn"
                    className="w-full inline-flex items-center justify-center gap-2 rounded-full bg-[#E07A5F] text-white px-5 py-3 font-bold disabled:opacity-60">
              {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <RefreshCcw className="w-4 h-4" />}
              أعد رسم {imagesLabel(picked.length)}
            </button>
          </div>
        )}
        <button type="button" onClick={approve} disabled={busy || redrawing || picked.length > 0} data-testid="approve-pictures-btn"
                className="btn-primary w-full inline-flex items-center justify-center gap-2 disabled:opacity-50">
          {busy && !picked.length ? <Loader2 className="w-4 h-4 animate-spin" /> : <CheckCircle2 className="w-4 h-4" />}
          الصور تمام — ابدأ الفيديو
        </button>
        {picked.length > 0 && (
          <p className="font-body text-[11px] text-center text-[#8A9AB0]">أعد رسم ما اخترته أولاً، أو ألغِ اختياره لتعتمد الصور.</p>
        )}
      </div>

      {zoom && (
        <div className="fixed inset-0 z-50 bg-black/80 grid place-content-center p-3" onClick={() => setZoom(null)}
             role="dialog" aria-label="الصورة مكبّرة">
          <img src={zoom} alt="" className="max-w-[96vw] max-h-[88vh] rounded-2xl" />
          <button type="button" className="absolute top-4 left-4 w-10 h-10 rounded-full bg-white grid place-content-center"
                  aria-label="إغلاق"><X className="w-5 h-5" /></button>
        </div>
      )}
    </div>
  );
}
