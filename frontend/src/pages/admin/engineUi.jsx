import React, { useEffect, useState } from "react";
import { X } from "lucide-react";
import { api } from "../../lib/api";

// Shared building blocks of the engine admin pages (layers, stages, catalog).

export const errText = (e, fallback = "فشل الحفظ") => {
  const d = e?.response?.data?.detail;
  if (Array.isArray(d)) return d.map((x) => x.msg).join(" • ");
  return d || fallback;
};

// ============================================================================ shared bits
export function Panel({ children, className = "" }) {
  return <div className={`bg-white rounded-3xl border border-[#E2D8C9] p-5 ${className}`}>{children}</div>;
}

export function Field({ label, hint, children, counter }) {
  return (
    <div className="mb-4">
      <div className="flex items-baseline justify-between gap-2 mb-1.5">
        <label className="block text-sm font-bold text-[#2D3748] font-body">{label}</label>
        {counter}
      </div>
      {children}
      {hint && <p className="font-body text-xs text-[#8A9AB0] mt-1">{hint}</p>}
    </div>
  );
}

export const inputCls = "w-full bg-[#FDFBF7] border border-[#E2D8C9] rounded-2xl px-4 py-2 font-body text-sm focus:outline-none focus:border-[#87A96B]";

export function Text({ value, onChange, rows = 4, ltr, ...rest }) {
  return (
    <textarea
      rows={rows}
      value={value ?? ""}
      onChange={(e) => onChange(e.target.value)}
      dir={ltr ? "ltr" : "auto"}
      className={`${inputCls} ${ltr ? "text-left font-mono text-xs leading-relaxed" : ""}`}
      {...rest}
    />
  );
}

export function Badge({ children, tone = "neutral" }) {
  const tones = {
    neutral: "bg-[#F8F1E7] text-[#8B5A2B]",
    green: "bg-[#DEEBCF] text-[#3F5B2E]",
    gold: "bg-[#FBEFD5] text-[#8B5A2B]",
    red: "bg-[#FCE6D4] text-[#B8612F]",
  };
  return <span className={`rounded-full px-2.5 py-0.5 text-xs font-bold font-body ${tones[tone]}`}>{children}</span>;
}

export function Drawer({ title, onClose, children, footer }) {
  return (
    <div className="fixed inset-0 bg-black/40 z-50 flex justify-end" onClick={onClose}>
      <div
        className="bg-white w-full max-w-2xl h-full flex flex-col shadow-2xl"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-label={title}
      >
        <div className="flex items-center justify-between px-6 py-4 border-b border-[#E2D8C9]">
          <h2 className="font-heading text-xl font-bold text-[#2D3748]">{title}</h2>
          <button onClick={onClose} className="text-[#8A9AB0] hover:text-[#2D3748]" aria-label="إغلاق"><X className="w-5 h-5" /></button>
        </div>
        <div className="flex-1 overflow-y-auto px-6 py-5">{children}</div>
        {footer && <div className="px-6 py-4 border-t border-[#E2D8C9] bg-[#FDFBF7]">{footer}</div>}
      </div>
    </div>
  );
}

/** Image behind an admin-only endpoint (an <img> tag can't send the bearer token). */
export function AuthImage({ path, alt, className }) {
  const [src, setSrc] = useState(null);
  useEffect(() => {
    let url = null;
    let alive = true;
    setSrc(null);
    api.get(path, { responseType: "blob" })
      .then((r) => { if (alive) { url = URL.createObjectURL(r.data); setSrc(url); } })
      .catch(() => {});
    return () => { alive = false; if (url) URL.revokeObjectURL(url); };
  }, [path]);
  if (!src) return <div className={`${className} bg-[#F8F1E7] grid place-content-center text-xs text-[#8A9AB0] font-body`}>لا توجد صورة</div>;
  return <img src={src} alt={alt} className={className} />;
}

/** Only the fields that changed (the server bumps the version per save). */
export function diff(original, edited, keys) {
  const out = {};
  keys.forEach((k) => {
    if (JSON.stringify(original?.[k] ?? null) !== JSON.stringify(edited?.[k] ?? null)) out[k] = edited[k];
  });
  return out;
}

