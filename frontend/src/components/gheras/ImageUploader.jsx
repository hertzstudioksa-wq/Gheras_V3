import React, { useRef, useState } from "react";
import { uploadImage, fileSrc } from "../../lib/api";
import { UploadCloud, X, Loader2, ImagePlus } from "lucide-react";
import { toast } from "sonner";

export default function ImageUploader({
  value,
  onChange,
  scope = "child",
  label = "رفع صورة",
  required = false,
  size = "md", // 'sm' | 'md' | 'lg'
  testId = "image-uploader",
}) {
  const inputRef = useRef(null);
  const [busy, setBusy] = useState(false);

  const dims = {
    sm: "h-24 w-24",
    md: "h-36 w-36",
    lg: "h-48 w-48",
  }[size];

  const pick = () => inputRef.current?.click();

  const handleFile = async (f) => {
    if (!f) return;
    if (f.size > 6 * 1024 * 1024) {
      toast.error("حجم الصورة يجب ألا يتجاوز 6MB");
      return;
    }
    setBusy(true);
    try {
      const res = await uploadImage(f, scope);
      onChange(res.url);
      toast.success("تم رفع الصورة");
    } catch (e) {
      toast.error(e.message || "فشل الرفع");
    } finally {
      setBusy(false);
    }
  };

  const clear = (e) => {
    e?.stopPropagation();
    onChange("");
  };

  return (
    <div data-testid={testId}>
      {label && (
        <div className="text-sm font-bold text-[#2D3748] mb-2 font-body">
          {label} {required && <span className="text-[#E07A5F]">*</span>}
        </div>
      )}
      <input
        ref={inputRef}
        type="file"
        accept="image/png,image/jpeg,image/webp,image/gif"
        className="hidden"
        onChange={(e) => handleFile(e.target.files?.[0])}
      />
      <button
        type="button"
        onClick={pick}
        disabled={busy}
        className={`relative ${dims} rounded-3xl border-2 border-dashed ${
          value ? "border-[#87A96B] bg-[#E8F0E1]" : "border-[#E2D8C9] bg-[#FDFBF7] hover:border-[#87A96B]"
        } grid place-content-center transition cursor-pointer overflow-hidden shrink-0`}
        data-testid={`${testId}-btn`}
      >
        {busy ? (
          <Loader2 className="w-8 h-8 text-[#87A96B] animate-spin" />
        ) : value ? (
          <>
            <img
              src={fileSrc(value)}
              alt=""
              className="absolute inset-0 w-full h-full object-cover"
            />
            <span
              onClick={clear}
              className="absolute top-1.5 right-1.5 w-7 h-7 rounded-full bg-white/95 grid place-content-center text-[#B8612F] hover:bg-white"
              data-testid={`${testId}-clear`}
            >
              <X className="w-4 h-4" />
            </span>
          </>
        ) : (
          <div className="flex flex-col items-center gap-1 text-[#5A677D] p-2">
            <ImagePlus className="w-7 h-7" />
            <span className="font-body text-xs">اضغط للرفع</span>
          </div>
        )}
      </button>
    </div>
  );
}
