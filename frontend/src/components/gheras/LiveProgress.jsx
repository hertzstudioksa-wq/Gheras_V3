import React, { useEffect, useRef, useState } from "react";
import { Bell, CheckCircle2, Circle, Clock, Hourglass, Loader2 } from "lucide-react";
import { fileSrc } from "../../lib/api";

// Live progress while a story is being made: the server sends what's done
// (steps, previews), how long it has been and an estimate of what's left; the
// page ticks every second between polls so nothing ever looks frozen.

/** Seconds since `fetchedAt` (re-renders every second while `active`). */
export function useTicker(active) {
  const [, setTick] = useState(0);
  useEffect(() => {
    if (!active) return undefined;
    const iv = setInterval(() => setTick((t) => t + 1), 1000);
    return () => clearInterval(iv);
  }, [active]);
}

export function formatClock(seconds) {
  const s = Math.max(0, Math.floor(seconds || 0));
  const m = Math.floor(s / 60);
  const h = Math.floor(m / 60);
  const pad = (n) => String(n).padStart(2, "0");
  return h ? `${h}:${pad(m % 60)}:${pad(s % 60)}` : `${pad(m)}:${pad(s % 60)}`;
}

export function formatRemaining(seconds) {
  const s = Math.max(0, Math.round(seconds || 0));
  if (s < 60) return "أقل من دقيقة";
  const m = Math.round(s / 60);
  if (m === 1) return "حوالي دقيقة";
  if (m === 2) return "حوالي دقيقتين";
  if (m <= 10) return `حوالي ${m} دقايق`;
  return `حوالي ${m} دقيقة`;
}

/**
 * Smooth numbers between polls: elapsed counts up, the estimate counts down,
 * and the percent never goes backwards within one visit.
 */
export function useLiveNumbers(progress) {
  const fetchedAt = useRef(Date.now());
  const best = useRef({ stage: null, percent: 0 });
  const last = useRef(null);
  if (progress !== last.current) {
    last.current = progress;
    fetchedAt.current = Date.now();
  }
  const running = !!progress && progress.elapsed_seconds != null;
  useTicker(running);
  const since = (Date.now() - fetchedAt.current) / 1000;
  const elapsed = running ? progress.elapsed_seconds + since : null;
  const eta = progress?.eta_seconds != null ? Math.max(progress.eta_seconds - since, 0) : null;
  let percent = progress?.percent ?? 0;
  // Creep toward the next poll so the bar moves every second.
  if (running && eta != null && elapsed != null && eta > 0) {
    percent = Math.min(percent + (since / Math.max(elapsed + eta, 1)) * 72, (progress?.percent ?? 0) + 4);
  }
  if (best.current.stage === progress?.stage) percent = Math.max(percent, best.current.percent);
  best.current = { stage: progress?.stage, percent };
  return { elapsed, eta, percent: Math.round(percent) };
}

export function TimeChips({ elapsed, eta }) {
  if (elapsed == null && eta == null) return null;
  return (
    <div className="flex flex-wrap items-center gap-2 mt-3 text-xs font-body" data-testid="live-time">
      {elapsed != null && (
        <span className="inline-flex items-center gap-1.5 bg-white rounded-full px-3 py-1 border border-[#E2D8C9] text-[#5A677D]">
          <Clock className="w-3.5 h-3.5 text-[#87A96B]" /> مرّ <b className="tabular-nums text-[#2D3748]" dir="ltr">{formatClock(elapsed)}</b>
        </span>
      )}
      {eta != null && (
        <span className="inline-flex items-center gap-1.5 bg-white rounded-full px-3 py-1 border border-[#E2D8C9] text-[#5A677D]" data-testid="live-eta">
          <Hourglass className="w-3.5 h-3.5 text-[#D4A373]" /> باقي <b className="text-[#2D3748]">{formatRemaining(eta)}</b>
        </span>
      )}
    </div>
  );
}

export function StepList({ steps }) {
  if (!steps?.length) return null;
  return (
    <ul className="mt-4 grid grid-cols-1 sm:grid-cols-2 gap-2" data-testid="live-steps">
      {steps.map((s) => (
        <li key={s.key}
            className={`flex items-center gap-2 rounded-xl px-3 py-2 text-sm font-body border ${
              s.state === "done" ? "bg-[#E8F0E1] border-[#87A96B]/30 text-[#3F5B2E]" :
              s.state === "active" ? "bg-white border-[#D4A373]/50 text-[#2D3748]" :
              "bg-[#FDFBF7] border-[#E2D8C9] text-[#8A9AB0]"}`}
            data-testid={`live-step-${s.key}`}>
          {s.state === "done" ? <CheckCircle2 className="w-4 h-4 shrink-0" /> :
           s.state === "active" ? <Loader2 className="w-4 h-4 shrink-0 animate-spin text-[#D4A373]" /> :
           <Circle className="w-4 h-4 shrink-0" />}
          <span className="flex-1">{s.label_ar}</span>
          {s.total > 1 && <span className="text-xs tabular-nums" dir="ltr">{s.done}/{s.total}</span>}
        </li>
      ))}
    </ul>
  );
}

/** The child's cartoon (first) and each start frame as it's drawn. */
export function PreviewStrip({ previews }) {
  const seen = useRef(new Set());
  if (!previews?.length) return null;
  const character = previews.find((p) => p.kind === "character");
  const rest = previews.filter((p) => p !== character);
  return (
    <div className="mt-5" data-testid="live-previews">
      {character && (
        <div className="flex items-center gap-4 bg-gradient-to-br from-[#F8F1E7] to-[#E8F0E1] rounded-2xl p-3 border border-[#D4A373]/30 mb-3">
          <img src={fileSrc(character.url)} alt={character.label_ar}
               className="w-20 h-28 object-contain rounded-xl bg-white border border-[#E2D8C9] animate-grow" />
          <div className="font-body">
            <div className="font-heading font-bold text-[#2D3748]">{character.label_ar} جاهزة 🎨</div>
            <div className="text-xs text-[#5A677D] mt-1">ده شكله في القصة — وبنرسم المشاهد دلوقتي.</div>
          </div>
        </div>
      )}
      {rest.length > 0 && (
        <div className="flex gap-2 overflow-x-auto pb-1 snap-x" dir="rtl">
          {rest.map((p) => {
            const fresh = !seen.current.has(p.url);
            seen.current.add(p.url);
            return (
              <figure key={p.url} className={`shrink-0 snap-start ${fresh ? "animate-grow" : ""}`}>
                <img src={fileSrc(p.url)} alt={p.label_ar} loading="lazy"
                     className={`h-20 md:h-24 rounded-xl border border-[#E2D8C9] ${p.kind === "character"
                       ? "aspect-[3/4] object-contain bg-white" : "aspect-video object-cover bg-[#F2E8DA]"}`} />
                <figcaption className="text-[10px] text-[#8A9AB0] font-body text-center mt-1">{p.label_ar}</figcaption>
              </figure>
            );
          })}
        </div>
      )}
    </div>
  );
}

/** Ask once for a browser notification when the story is ready. */
export function NotifyWhenReady() {
  const supported = typeof window !== "undefined" && "Notification" in window;
  const [perm, setPerm] = useState(supported ? Notification.permission : "unsupported");
  if (!supported || perm === "denied") return null;
  if (perm === "granted") {
    return (
      <p className="text-xs font-body text-[#4F6B3B] mt-3 inline-flex items-center gap-1.5" data-testid="notify-on">
        <Bell className="w-3.5 h-3.5" /> هنبلغك بإشعار أول ما القصة تخلص — تقدر تقفل الصفحة.
      </p>
    );
  }
  return (
    <button type="button" data-testid="notify-btn"
            onClick={async () => setPerm(await Notification.requestPermission())}
            className="mt-3 inline-flex items-center gap-2 rounded-full bg-white border border-[#E2D8C9] px-4 py-2 text-xs font-bold text-[#2D3748]">
      <Bell className="w-3.5 h-3.5 text-[#87A96B]" /> بلّغني لما تخلص
    </button>
  );
}

export function notifyReady(childName) {
  try {
    if ("Notification" in window && Notification.permission === "granted" && document.visibilityState !== "visible") {
      new Notification(`قصة ${childName || "طفلك"} جاهزة 🎉`, { body: "الفيديو والكتاب مستنيينك في غِراس.", icon: "/favicon.ico" });
    }
  } catch { /* notifications are a nicety */ }
}
