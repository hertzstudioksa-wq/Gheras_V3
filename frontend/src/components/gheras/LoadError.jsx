import React from "react";
import { CloudOff, RotateCw } from "lucide-react";

/** A page section that failed to load: what happened and a retry button. */
export default function LoadError({ message, onRetry, className = "" }) {
  return (
    <div
      className={`bg-white rounded-[2rem] p-10 border border-[#E2D8C9] text-center max-w-lg mx-auto ${className}`}
      data-testid="load-error"
    >
      <div className="w-16 h-16 rounded-3xl bg-[#FCE6D4] grid place-content-center mx-auto mb-5">
        <CloudOff className="w-8 h-8 text-[#B8612F]" />
      </div>
      <p className="font-body text-[#2D3748] mb-6 leading-relaxed">{message}</p>
      {onRetry && (
        <button onClick={onRetry} className="btn-primary inline-flex items-center gap-2">
          <RotateCw className="w-4 h-4" /> حاول مرة أخرى
        </button>
      )}
    </div>
  );
}
