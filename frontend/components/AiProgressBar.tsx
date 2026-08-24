"use client";

// 全局 AI 生成进度条：挂载在根布局，任何页面发起 AI 内容生成时，
// 顶部会实时出现一条「AI 正在生成…」的进度长条（可显示百分比 / 步骤说明）。
import { useEffect, useState } from "react";
import { getAiProgress, subscribeAiProgress, type AiProgressState } from "@/lib/aiProgress";

export default function AiProgressBar() {
  const [s, setS] = useState<AiProgressState>(() => getAiProgress());

  useEffect(() => {
    const un = subscribeAiProgress(setS);
    return un;
  }, []);

  if (!s.active) return null;

  // 有确定百分比则按百分比走；否则流动（indeterminate）到全宽。
  const definite = typeof s.pct === "number" && Number.isFinite(s.pct);
  const width = definite ? `${Math.max(0, Math.min(100, s.pct as number))}%` : "40%";

  return (
    <div
      className="fixed inset-x-0 top-0 z-[9999] border-b border-accent/30 bg-[#0b0d1f]/95 shadow-[0_2px_16px_rgba(0,0,0,0.4)] backdrop-blur"
      role="status"
      aria-live="polite"
    >
      <div className="mx-auto flex max-w-5xl items-center gap-3 px-6 py-2">
        <span className="relative flex h-2.5 w-2.5">
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-accent opacity-60" />
          <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-accent" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-baseline justify-between gap-2 text-xs">
            <span className="truncate font-bold text-glow">✦ {s.label || "AI 正在生成…"}</span>
            {definite ? (
              <span className="shrink-0 tabular-nums text-accent">{Math.round(s.pct as number)}%</span>
            ) : (
              <span className="shrink-0 text-slate-400">处理中…</span>
            )}
          </div>
          {s.detail ? <div className="mt-0.5 truncate text-[10px] text-slate-400">{s.detail}</div> : null}
          <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-panel2">
            <div
              className={
                definite
                  ? "h-full bg-gradient-to-r from-[#d90b46] to-accent transition-all duration-500"
                  : "h-full bg-gradient-to-r from-[#d90b46] via-accent to-[#ff7a59] transition-transform duration-700"
              }
              style={
                definite
                  ? { width }
                  : { width, animation: "indeterminate 1.4s ease-in-out infinite" }
              }
            />
          </div>
        </div>
      </div>
      {/* 防止遮挡页面左边距，给下方内容留出条高 */}
      <style jsx global>{`
        @keyframes indeterminate {
          0% { margin-left: -40%; }
          100% { margin-left: 100%; }
        }
      `}</style>
    </div>
  );
}