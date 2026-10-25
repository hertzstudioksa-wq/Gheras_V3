import React, { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { AlertTriangle, Loader2, PlayCircle, RefreshCcw } from "lucide-react";
import { api } from "../../lib/api";

// Shown on every admin page while fal's balance is exhausted, or while orders
// it stopped are still waiting to be resumed after a top-up.
export default function EngineHealthBanner() {
  const [health, setHealth] = useState(null);
  const [busy, setBusy] = useState(null);

  const load = useCallback(async () => {
    try {
      const { data } = await api.get("/admin/engine/health");
      setHealth(data);
    } catch { /* the banner is best-effort */ }
  }, []);

  useEffect(() => {
    load();
    const iv = setInterval(load, 60000);
    return () => clearInterval(iv);
  }, [load]);

  if (!health || (!health.locked && !health.paused_orders)) return null;

  const probe = async () => {
    setBusy("probe");
    try {
      const { data } = await api.post("/admin/engine/health/probe");
      setHealth(data);
      toast[data.ok ? "success" : "error"](data.ok ? "الرصيد شغّال ✔" : data.error || "لسه مش شغّال");
    } catch (e) {
      toast.error(e?.response?.data?.detail || "تعذّر الفحص");
    } finally {
      setBusy(null);
    }
  };

  const resume = async () => {
    setBusy("resume");
    try {
      const { data } = await api.post("/admin/engine/resume-paused");
      toast.success(`اتكمّل ${data.resumed.length} طلب${data.skipped.length ? ` — ${data.skipped.length} محتاجين متابعة يدوي` : ""}`);
      await load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "تعذّر الاستكمال");
    } finally {
      setBusy(null);
    }
  };

  const locked = health.locked;
  return (
    <div
      className={`rounded-2xl border p-4 mb-5 flex flex-wrap items-center gap-3 ${locked ? "bg-[#FCE6D4] border-[#E07A5F]/50" : "bg-[#F8F1E7] border-[#D4A373]/50"}`}
      data-testid="engine-health-banner"
    >
      <AlertTriangle className={`w-5 h-5 shrink-0 ${locked ? "text-[#B8612F]" : "text-[#8B5A2B]"}`} />
      <div className="flex-1 min-w-[220px] font-body text-sm text-[#2D3748]">
        {locked ? (
          <>
            <b>رصيد fal خلص — التوليد واقف.</b> الطلبات الجديدة والدفع متوقفين لحد ما يتشحن.
            {health.locked_at && (
              <span className="text-[#5A677D]"> (من {new Date(health.locked_at).toLocaleString("ar-EG")})</span>
            )}
          </>
        ) : (
          <b>الرصيد رجع شغّال.</b>
        )}
        {health.paused_orders > 0 && <> {" "}فيه <b>{health.paused_orders}</b> طلب موقوف مستني الاستكمال.</>}
      </div>
      <div className="flex gap-2 flex-wrap">
        {locked && (
          <button type="button" onClick={probe} disabled={!!busy} data-testid="engine-probe-btn"
                  className="inline-flex items-center gap-2 rounded-full bg-white border border-[#E2D8C9] px-4 py-2 text-sm font-bold text-[#2D3748] disabled:opacity-50">
            {busy === "probe" ? <Loader2 className="w-4 h-4 animate-spin" /> : <RefreshCcw className="w-4 h-4" />}
            شحنت — افحص الرصيد
          </button>
        )}
        {health.paused_orders > 0 && (
          <button type="button" onClick={resume} disabled={!!busy} data-testid="engine-resume-btn"
                  className="inline-flex items-center gap-2 rounded-full bg-[#87A96B] text-white px-4 py-2 text-sm font-bold disabled:opacity-50">
            {busy === "resume" ? <Loader2 className="w-4 h-4 animate-spin" /> : <PlayCircle className="w-4 h-4" />}
            استكمال الطلبات الموقوفة
          </button>
        )}
      </div>
    </div>
  );
}
