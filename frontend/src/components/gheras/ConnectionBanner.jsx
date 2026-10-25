import React, { useEffect, useState } from "react";
import { WifiOff, RotateCw } from "lucide-react";
import { CONNECTION_EVENT } from "@/lib/api";

/**
 * One calm strip at the top when the server stops answering (network down, the
 * API restarting, the database unreachable) instead of a red error overlay on
 * every page. It goes away by itself on the next request that succeeds.
 */
export default function ConnectionBanner() {
  const [down, setDown] = useState(null);

  useEffect(() => {
    const onChange = (e) => setDown(e.detail?.ok ? null : e.detail);
    window.addEventListener(CONNECTION_EVENT, onChange);
    return () => window.removeEventListener(CONNECTION_EVENT, onChange);
  }, []);

  if (!down) return null;
  return (
    <div
      role="status"
      className="fixed top-0 inset-x-0 z-[100] bg-[#FFF4E0] border-b border-[#F2C879] text-[#7A4B00] shadow-sm"
      data-testid="connection-banner"
    >
      <div className="max-w-5xl mx-auto px-4 py-2.5 flex items-center gap-3 font-body text-sm">
        <WifiOff className="w-4 h-4 shrink-0" />
        <span className="flex-1">
          {down.message || "تعذّر الاتصال بالخادم — تأكد من الإنترنت، وسنعيد المحاولة تلقائياً."}
        </span>
        <button
          onClick={() => window.location.reload()}
          className="inline-flex items-center gap-1.5 rounded-full bg-white/80 border border-[#F2C879] px-3 py-1 font-bold hover:bg-white"
        >
          <RotateCw className="w-3.5 h-3.5" /> إعادة المحاولة
        </button>
      </div>
    </div>
  );
}
