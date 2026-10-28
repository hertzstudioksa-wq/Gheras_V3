import React, { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { AlertTriangle, CheckCircle2, Film, Loader2, Pencil, RefreshCw, ShieldCheck } from "lucide-react";
import { api, fileSrc } from "../../../lib/api";
import { ConfirmAction, PageState } from "../../../components/admin/AdminKit";

// Every shot of the order — start frame, animated clip, narration line and the
// automatic review — with a redo for one bad shot (new clip, or new start frame
// and clip) followed by a fresh video assembly.

const PROBLEM_AR = {
  duplicate: "شخصية متكررة", extra_person: "شخص زيادة", role_swap: "شخصية في مكان شخصية تانية",
  clipping: "جسم بيخترق حاجة",
  vanishing: "شخصية بتختفي", text: "كتابة", deformed: "تشوّه",
  wrong_look: "شكل مش مطابق للشخصية", outfit_change: "اللبس أو الإكسسوار اتغيّر",
  melting: "حاجة بتسيح أو بتتمدد", action_missing: "الحدث المطلوب ما حصلش", mood_mismatch: "التعبير عكس السطر",
  noise: "صورة مشوّشة (ألوان عشوائية)", object_alive: "لعبة أو حاجة بتتحرك لوحدها",
  camera_gaze: "حد باصص للكاميرا", floating: "حد بيطير أو رجله في الهوا",
};

function ReviewBadge({ label, review, redoneKey }) {
  if (!review) return null;
  if (review.skipped) {
    return <span className="text-[11px] rounded-full px-2 py-0.5 bg-[#EEE9E0] text-[#5A677D]">{label}: من غير مراجعة</span>;
  }
  const redone = review[redoneKey];
  return (
    <span className={`text-[11px] rounded-full px-2 py-0.5 inline-flex items-center gap-1 ${
      review.ok ? "bg-[#DEEBCF] text-[#3F5B2E]" : "bg-[#FCE6D4] text-[#B8612F]"}`} title={review.note || ""}>
      {review.ok ? <ShieldCheck className="w-3 h-3" /> : <AlertTriangle className="w-3 h-3" />}
      {label}: {review.ok ? "سليم" : (review.problems || []).map((p) => PROBLEM_AR[p] || p).join("، ")}
      {redone ? " (اتعادت)" : ""}
      {review.rescue ? " · اترسمت بـ GPT" : ""}
    </span>
  );
}

// The toy is checked in Wan's own clip: fine from the model (no paste), or alive in every
// take and pasted from its start picture as the last resort.
function ToyBadge({ review }) {
  const check = review?.toy_check;
  if (!check || !(check.checked || []).length) return null;
  const frozen = (review.toy_freeze?.frozen || []).length > 0;
  const alive = (check.alive || []).length > 0;
  const text = frozen ? "اللعبة اتثبتت (آخر حل)" : alive ? "اللعبة بتتحرك لوحدها" : "اللعبة سليمة من الموديل";
  return (
    <span className={`text-[11px] rounded-full px-2 py-0.5 ${frozen || alive ? "bg-[#FCE6D4] text-[#B8612F]" : "bg-[#DEEBCF] text-[#3F5B2E]"}`}
          title={Object.values(check.notes || {}).join(" · ")}>
      {text}
    </span>
  );
}

function ShotCard({ orderId, shot, busy, onDone }) {
  const [editing, setEditing] = useState(false);
  const [motion, setMotion] = useState(shot.motion_prompt || "");
  const [reassemble, setReassemble] = useState(true);
  const running = shot.redo?.state === "running";
  const keyStr = `${shot.scene_index}_${shot.shot_index}`;

  const redo = async (target) => {
    try {
      await api.post(`/admin/orders/${orderId}/shots/${shot.scene_index}/${shot.shot_index}/redo`, {
        target, reassemble, motion_prompt: editing && motion.trim() !== (shot.motion_prompt || "") ? motion.trim() : null,
      });
      toast.success(`بدأت إعادة اللقطة ${keyStr}`);
      setEditing(false);
      onDone();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "تعذّرت الإعادة");
    }
  };

  return (
    <div className="bg-[#FDFBF7] rounded-2xl border border-[#E2D8C9] p-3 flex flex-col gap-2" data-testid={`shot-${keyStr}`}>
      <div className="flex items-center justify-between text-xs font-body text-[#5A677D]">
        <b className="text-[#2D3748]">المشهد {shot.scene_index} · لقطة {shot.shot_index}</b>
        <span dir="ltr">{shot.shot_type} · {shot.clip_seconds ? `${shot.clip_seconds}s` : "—"}</span>
      </div>
      {shot.clip_url ? (
        <video src={fileSrc(shot.clip_url)} poster={shot.keyframe_url ? fileSrc(shot.keyframe_url) : undefined}
               controls preload="none" playsInline className="w-full aspect-video rounded-xl bg-black" />
      ) : shot.keyframe_url ? (
        <img src={fileSrc(shot.keyframe_url)} alt="" className="w-full aspect-video object-cover rounded-xl" />
      ) : (
        <div className="w-full aspect-video rounded-xl bg-[#F2E8DA] grid place-content-center text-xs text-[#8A9AB0]">لسه</div>
      )}
      <p className="font-body text-sm text-[#2D3748]">{shot.narration_line}</p>
      <div className="flex flex-wrap gap-1">
        <ReviewBadge label="الصورة" review={shot.keyframe_review} redoneKey="redrawn" />
        <ReviewBadge label="المقطع" review={shot.clip_review} redoneKey="redone" />
        {shot.clip_calm_redo && <span className="text-[11px] rounded-full px-2 py-0.5 bg-[#F8F1E7] text-[#8B5A2B]">حركة أهدى</span>}
        <ToyBadge review={shot.clip_review} />
        {shot.clip_rescue && (
          <span className="text-[11px] rounded-full px-2 py-0.5 bg-[#FCE6D4] text-[#B8612F]" title={shot.clip_rescue.reason || ""}>
            اتعمل بـ Kling بعد Wan
          </span>
        )}
        {running && (
          <span className="text-[11px] rounded-full px-2 py-0.5 bg-[#FCE6D4] text-[#B8612F] inline-flex items-center gap-1">
            <Loader2 className="w-3 h-3 animate-spin" /> بتتعاد...
          </span>
        )}
        {shot.redo?.state === "failed" && (
          <span className="text-[11px] rounded-full px-2 py-0.5 bg-[#FCE6D4] text-[#B8612F]" title={shot.redo.error}>الإعادة فشلت</span>
        )}
        {shot.redo?.state === "done" && <span className="text-[11px] rounded-full px-2 py-0.5 bg-[#DEEBCF] text-[#3F5B2E]">اتعادت ✔</span>}
      </div>
      {shot.clip_error && !shot.clip_url && <p className="text-[11px] text-[#B8612F] font-body break-words">{shot.clip_error}</p>}

      {editing && (
        <textarea value={motion} onChange={(e) => setMotion(e.target.value)} rows={4} dir="ltr"
                  className="w-full rounded-xl border border-[#E2D8C9] p-2 text-xs font-mono"
                  placeholder="One main action, everyone already in frame, calm camera." />
      )}
      <div className="flex flex-wrap items-center gap-2 mt-auto">
        <button type="button" onClick={() => setEditing((v) => !v)} disabled={running || busy}
                className="inline-flex items-center gap-1 rounded-full border border-[#E2D8C9] bg-white px-3 py-1.5 text-xs font-bold text-[#5A677D] disabled:opacity-50">
          <Pencil className="w-3 h-3" /> {editing ? "إلغاء التعديل" : "تعديل الحركة"}
        </button>
        <ConfirmAction tone="cost" disabled={running || busy} testId={`redo-clip-${keyStr}`}
                       title={`مقطع جديد للقطة ${keyStr}`}
                       description={`مقطع جديد بموديل الفيديو الحالي (Kling ~$0.6، وWan على Comfy أرخص بكتير)${reassemble ? "، وبعده الفيديو بيتجمّع من جديد ويوصل للعميل" : ""}.`}
                       confirmLabel="ابدأ" onConfirm={() => redo("clip")}
                       className="inline-flex items-center gap-1 rounded-full bg-[#87A96B] text-white px-3 py-1.5 text-xs font-bold disabled:opacity-50">
          <Film className="w-3 h-3" /> مقطع جديد
        </ConfirmAction>
        <ConfirmAction tone="cost" disabled={running || busy} testId={`redo-both-${keyStr}`}
                       title={`صورة بداية ومقطع جديدين للقطة ${keyStr}`}
                       description={`صورة بداية جديدة + مقطع جديد (~$0.8)${reassemble ? "، وبعدهم الفيديو بيتجمّع من جديد" : ""}.`}
                       confirmLabel="ابدأ" onConfirm={() => redo("both")}
                       className="inline-flex items-center gap-1 rounded-full bg-white border border-[#87A96B] text-[#4F6B3B] px-3 py-1.5 text-xs font-bold disabled:opacity-50">
          <RefreshCw className="w-3 h-3" /> صورة + مقطع
        </ConfirmAction>
        <label className="text-[11px] text-[#5A677D] inline-flex items-center gap-1 font-body">
          <input type="checkbox" checked={reassemble} onChange={(e) => setReassemble(e.target.checked)} />
          جمّع الفيديو بعدها
        </label>
      </div>
    </div>
  );
}

export default function OrderShotsTab({ orderId }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    try {
      const { data: d } = await api.get(`/admin/orders/${orderId}/shots`);
      setData(d);
      setError(null);
    } catch (e) {
      setError(e?.response?.data?.detail || "تعذّر التحميل");
    }
  }, [orderId]);

  const running = (data?.shots || []).some((s) => s.redo?.state === "running");
  const working = ["assets_generating", "assembling"].includes(data?.status);
  useEffect(() => {
    load();
  }, [load]);
  useEffect(() => {
    if (!running && !working) return undefined;
    const iv = setInterval(load, 8000);
    return () => clearInterval(iv);
  }, [running, working, load]);

  const shots = data?.shots || [];
  const flagged = shots.filter((s) => (s.clip_review && !s.clip_review.ok) || (s.keyframe_review && !s.keyframe_review.ok));
  return (
    <PageState loading={!data && !error} error={error} empty={data && !shots.length}
               emptyText="الطلب ده مفيهوش لقطات لسه" onRetry={load}>
      <div className="flex flex-wrap items-center gap-3 mb-4 font-body text-sm text-[#5A677D]">
        <span><b className="text-[#2D3748]">{shots.length}</b> لقطة</span>
        <span>· <b className="text-[#2D3748]">{shots.filter((s) => s.clip_url).length}</b> متحركة</span>
        {flagged.length > 0 ? (
          <span className="text-[#B8612F] inline-flex items-center gap-1">
            <AlertTriangle className="w-4 h-4" /> {flagged.length} اتعلّم عليها في المراجعة
          </span>
        ) : shots.some((s) => s.clip_review) ? (
          <span className="text-[#4F6B3B] inline-flex items-center gap-1"><CheckCircle2 className="w-4 h-4" /> المراجعة الآلية: كله سليم</span>
        ) : null}
        {working && <span className="inline-flex items-center gap-1"><Loader2 className="w-4 h-4 animate-spin" /> الطلب لسه بيتجهّز</span>}
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-3">
        {shots.map((s) => (
          <ShotCard key={`${s.scene_index}_${s.shot_index}`} orderId={orderId} shot={s} busy={working} onDone={load} />
        ))}
      </div>
    </PageState>
  );
}
