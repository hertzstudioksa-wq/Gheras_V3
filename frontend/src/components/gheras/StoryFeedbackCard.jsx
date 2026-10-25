import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { Star, Flag, Send, CheckCircle2, Loader2 } from "lucide-react";
import { api, errorMessage } from "@/lib/api";

/**
 * Under a delivered story: a star rating with an optional comment, and a
 * "report a problem" path (the terms promise to redo a clearly broken scene
 * reported within 14 days). The admin sees both on the order page.
 */
export default function StoryFeedbackCard({ orderId }) {
  const [saved, setSaved] = useState(null);
  const [rating, setRating] = useState(0);
  const [hover, setHover] = useState(0);
  const [comment, setComment] = useState("");
  const [problem, setProblem] = useState(false);
  const [problemNote, setProblemNote] = useState("");
  const [sending, setSending] = useState(false);

  useEffect(() => {
    api.get(`/orders/${orderId}`).then((r) => {
      const f = r.data?.feedback;
      if (f) {
        setSaved(f);
        setRating(f.rating || 0);
      }
    }).catch(() => {});
  }, [orderId]);

  const send = async () => {
    setSending(true);
    try {
      const { data } = await api.post(`/orders/${orderId}/feedback`, {
        rating: rating || null, comment, problem, problem_note: problem ? problemNote : null,
      });
      setSaved(data.feedback);
      toast.success(problem ? "وصلنا بلاغك، وسنتواصل معك قريباً" : "شكراً لتقييمك 🌱");
    } catch (e) {
      toast.error(errorMessage(e, "تعذّر الإرسال، حاول مرة أخرى"));
    } finally {
      setSending(false);
    }
  };

  if (saved && !saved.editing) {
    return (
      <div className="bg-white rounded-[2rem] p-5 md:p-6 border border-[#E2D8C9]" data-testid="feedback-saved">
        <div className="flex items-center gap-2 font-heading font-bold text-[#2D3748] mb-1">
          <CheckCircle2 className="w-5 h-5 text-[#729352]" /> شكراً لك
        </div>
        <p className="font-body text-sm text-[#5A677D]">
          {saved.problem ? "استلمنا بلاغك وسنراجع القصة ونتواصل معك." : "وصلنا تقييمك، وهو يساعدنا نصنع قصصاً أجمل."}
          {saved.rating ? ` (${saved.rating} من 5)` : ""}
        </p>
        <button onClick={() => setSaved({ ...saved, editing: true })} className="mt-2 text-xs font-bold text-[#729352] underline">
          تعديل
        </button>
      </div>
    );
  }

  const shown = hover || rating;
  return (
    <div className="bg-white rounded-[2rem] p-5 md:p-6 border border-[#E2D8C9]" data-testid="feedback-card">
      <h3 className="font-heading text-lg font-bold text-[#2D3748] mb-1">كيف وجدت القصة؟</h3>
      <p className="font-body text-xs text-[#5A677D] mb-3">رأيك يهمنا، ولا يراه إلا فريق غِراس.</p>
      <div className="flex items-center gap-1 mb-3" onMouseLeave={() => setHover(0)} role="radiogroup" aria-label="التقييم">
        {[1, 2, 3, 4, 5].map((n) => (
          <button key={n} type="button" role="radio" aria-checked={rating === n} aria-label={`${n} من 5`}
            onMouseEnter={() => setHover(n)} onClick={() => setRating(n)} className="p-1" data-testid={`feedback-star-${n}`}>
            <Star className={`w-8 h-8 transition ${n <= shown ? "fill-[#E9B949] text-[#E9B949]" : "text-[#D9CFC0]"}`} />
          </button>
        ))}
      </div>
      <textarea rows={2} value={comment} onChange={(e) => setComment(e.target.value)} maxLength={1000}
        placeholder="ما الذي أعجبك أو ما الذي نحسّنه؟ (اختياري)"
        className="w-full bg-[#FDFBF7] border border-[#E2D8C9] rounded-2xl px-4 py-2 font-body text-sm mb-3" />
      <label className="flex items-center gap-2 font-body text-sm text-[#B8612F] cursor-pointer mb-2">
        <input type="checkbox" checked={problem} onChange={(e) => setProblem(e.target.checked)} className="accent-[#E07A5F] w-4 h-4" data-testid="feedback-problem" />
        <Flag className="w-4 h-4" /> في القصة مشكلة أريد إصلاحها
      </label>
      {problem && (
        <textarea rows={3} value={problemNote} onChange={(e) => setProblemNote(e.target.value)} maxLength={1000}
          placeholder="صف المشكلة ومكانها، مثل: في المشهد الثاني تظهر الأم مرتين"
          className="w-full bg-[#FFF7F2] border border-[#E07A5F]/40 rounded-2xl px-4 py-2 font-body text-sm mb-3" data-testid="feedback-problem-note" />
      )}
      <button onClick={send} disabled={sending || (!rating && !problem && !comment.trim()) || (problem && problemNote.trim().length < 5)}
        className="btn-primary inline-flex items-center gap-2 disabled:opacity-50" data-testid="feedback-send">
        {sending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4 -scale-x-100" />}
        {problem ? "أرسل البلاغ" : "أرسل التقييم"}
      </button>
    </div>
  );
}
