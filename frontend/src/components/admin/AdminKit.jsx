import React, { useState } from "react";
import { Link } from "react-router-dom";
import { ArrowRight, AlertTriangle, Inbox, Loader2, RefreshCw } from "lucide-react";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription,
  AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger,
} from "../ui/alert-dialog";

// Shared admin building blocks (M5): one page header, one loading/error/empty
// state, one KPI card and one confirmation for costly or destructive actions,
// so every admin page looks and behaves the same.

export function AdminPage({ title, description, actions, back, children, testId }) {
  return (
    <div data-testid={testId}>
      {back && (
        <Link to={back.to} className="inline-flex items-center gap-1 font-body text-sm text-[#5A677D] hover:text-[#2D3748] mb-3">
          <ArrowRight className="w-4 h-4" /> {back.label}
        </Link>
      )}
      <div className="flex items-end justify-between gap-4 flex-wrap mb-6">
        <div className="min-w-0">
          <h1 className="font-heading text-2xl md:text-3xl font-bold text-[#2D3748] mb-1">{title}</h1>
          {description && <p className="font-body text-[#5A677D] max-w-3xl">{description}</p>}
        </div>
        {actions && <div className="flex items-center gap-2 flex-wrap">{actions}</div>}
      </div>
      {children}
    </div>
  );
}

export function PageState({ loading, error, empty, emptyText = "مفيش بيانات لسه", onRetry, children }) {
  if (loading) {
    return (
      <div className="flex items-center gap-2 font-body text-[#8A9AB0] py-10 justify-center" role="status">
        <Loader2 className="w-4 h-4 animate-spin" /> جاري التحميل…
      </div>
    );
  }
  if (error) {
    return (
      <div className="bg-[#FCE6D4] text-[#B8612F] rounded-3xl p-5 font-body flex items-center justify-between gap-3 flex-wrap" role="alert">
        <span className="inline-flex items-center gap-2"><AlertTriangle className="w-4 h-4" /> {error}</span>
        {onRetry && (
          <button onClick={onRetry} className="inline-flex items-center gap-1 text-sm font-bold">
            <RefreshCw className="w-4 h-4" /> حاول تاني
          </button>
        )}
      </div>
    );
  }
  if (empty) {
    return (
      <div className="bg-white border border-dashed border-[#E2D8C9] rounded-3xl p-10 text-center font-body text-[#8A9AB0]">
        <Inbox className="w-8 h-8 mx-auto mb-2 opacity-60" />
        {emptyText}
      </div>
    );
  }
  return children;
}

export function KpiCard({ label, value, hint, tone = "neutral", to }) {
  const tones = {
    neutral: "bg-white border-[#E2D8C9]",
    good: "bg-[#E8F0E1] border-[#87A96B]/30",
    warn: "bg-[#FBEFD5] border-[#D4A373]/40",
    bad: "bg-[#FCE6D4] border-[#E07A5F]/40",
  };
  const body = (
    <div className={`rounded-3xl border p-4 h-full ${tones[tone]}`}>
      <div className="font-body text-xs text-[#5A677D] mb-1">{label}</div>
      <div className="font-heading text-2xl font-bold text-[#2D3748]">{value}</div>
      {hint && <div className="font-body text-xs text-[#8A9AB0] mt-1">{hint}</div>}
    </div>
  );
  return to ? <Link to={to} className="block hover:opacity-90">{body}</Link> : body;
}

/** Page navigator for server-side paged lists. */
export function Pager({ page, limit, total, onPage }) {
  const pages = Math.max(1, Math.ceil((total || 0) / limit));
  if (pages <= 1) return null;
  const btn = "rounded-xl border border-[#E2D8C9] bg-white px-3 py-1.5 text-sm font-body font-bold text-[#5A677D] disabled:opacity-40";
  return (
    <div className="flex items-center justify-center gap-2 mt-4 font-body text-sm text-[#5A677D]" aria-label="الصفحات">
      <button className={btn} disabled={page <= 1} onClick={() => onPage(page - 1)}>السابق</button>
      <span>صفحة {page} من {pages} • {total} نتيجة</span>
      <button className={btn} disabled={page >= pages} onClick={() => onPage(page + 1)}>التالي</button>
    </div>
  );
}

/** Debounced value (search boxes that query the server). */
export function useDebounced(value, ms = 350) {
  const [v, setV] = useState(value);
  React.useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

/**
 * A button that asks before it runs something costly or destructive.
 * tone: "danger" (deletes, overrides) or "cost" (spends provider credit).
 */
export function ConfirmAction({
  children, title, description, confirmLabel = "تأكيد", tone = "danger", requireReason = false,
  onConfirm, disabled, className, testId,
}) {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState(false);
  const confirmCls = tone === "cost" ? "bg-[#87A96B] hover:bg-[#729352]" : "bg-[#B8612F] hover:bg-[#9C4F25]";

  const run = async (e) => {
    e.preventDefault();
    setBusy(true);
    try {
      await onConfirm?.(reason.trim());
      setOpen(false);
      setReason("");
    } finally {
      setBusy(false);
    }
  };

  return (
    <AlertDialog open={open} onOpenChange={setOpen}>
      <AlertDialogTrigger asChild disabled={disabled}>
        <button type="button" className={className} disabled={disabled} data-testid={testId}>{children}</button>
      </AlertDialogTrigger>
      <AlertDialogContent dir="rtl" className="font-body">
        <AlertDialogHeader className="text-right sm:text-right">
          <AlertDialogTitle className="font-heading">{title}</AlertDialogTitle>
          {description && <AlertDialogDescription className="text-right">{description}</AlertDialogDescription>}
        </AlertDialogHeader>
        {requireReason && (
          <textarea
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            rows={2}
            placeholder="السبب (هيتسجّل في سجل التدقيق)"
            className="w-full bg-[#FDFBF7] border border-[#E2D8C9] rounded-2xl px-3 py-2 text-sm"
          />
        )}
        <AlertDialogFooter className="gap-2 sm:gap-2 sm:justify-start">
          <AlertDialogAction onClick={run} disabled={busy || (requireReason && !reason.trim())}
            className={`${confirmCls} text-white rounded-2xl`}>
            {busy ? "جاري التنفيذ…" : confirmLabel}
          </AlertDialogAction>
          <AlertDialogCancel className="rounded-2xl">إلغاء</AlertDialogCancel>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
