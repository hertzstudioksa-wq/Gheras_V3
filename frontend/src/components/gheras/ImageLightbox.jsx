import React, { useEffect } from "react";
import { ChevronLeft, ChevronRight, X } from "lucide-react";

/**
 * A picture opened in front of the parent (characters, cover, scenes): its label,
 * its place in the set, the next and previous ones (arrows and keys), Esc or a tap
 * outside closes it. `items` = [{ src, label }]; `index` null = closed.
 */
export default function ImageLightbox({ items, index, onClose, onIndex }) {
  const open = index !== null && index !== undefined && items?.[index];
  const count = items?.length || 0;
  const go = (step) => onIndex?.((index + step + count) % count);

  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => {
      if (e.key === "Escape") onClose();
      // right-to-left: the right arrow goes back, the left arrow forward
      else if (e.key === "ArrowRight" && count > 1) go(-1);
      else if (e.key === "ArrowLeft" && count > 1) go(1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  if (!open) return null;
  const item = items[index];
  const stop = (e) => e.stopPropagation();
  return (
    <div className="fixed inset-0 z-[60] bg-black/85 flex flex-col items-center justify-center p-3" onClick={onClose}
         role="dialog" aria-modal="true" aria-label={item.label || "الصورة مكبّرة"} data-testid="image-lightbox">
      <img src={item.src} alt={item.label || ""} onClick={stop}
           className="max-w-[96vw] max-h-[80vh] object-contain rounded-2xl bg-white shadow-2xl" />
      {(item.label || count > 1) && (
        <div className="mt-3 font-body text-sm text-white/90 text-center" onClick={stop}>
          {item.label}{count > 1 ? `${item.label ? " · " : ""}${index + 1} من ${count}` : ""}
        </div>
      )}
      <button type="button" onClick={onClose} aria-label="إغلاق"
              className="absolute top-4 left-4 w-10 h-10 rounded-full bg-white/95 grid place-content-center">
        <X className="w-5 h-5 text-[#2D3748]" />
      </button>
      {count > 1 && (
        <>
          <button type="button" onClick={(e) => { stop(e); go(-1); }} aria-label="الصورة السابقة"
                  className="absolute right-3 top-1/2 -translate-y-1/2 w-11 h-11 rounded-full bg-white/90 grid place-content-center">
            <ChevronRight className="w-6 h-6 text-[#2D3748]" />
          </button>
          <button type="button" onClick={(e) => { stop(e); go(1); }} aria-label="الصورة التالية"
                  className="absolute left-3 top-1/2 -translate-y-1/2 w-11 h-11 rounded-full bg-white/90 grid place-content-center">
            <ChevronLeft className="w-6 h-6 text-[#2D3748]" />
          </button>
        </>
      )}
    </div>
  );
}
