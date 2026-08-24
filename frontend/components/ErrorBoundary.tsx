"use client";

// 面板级错误边界：任何子面板渲染抛错时，只把它所在区域降级成可见的报错卡片，
// 不拖垮整页 IDE（对应 “Application error: a client-side exception” 白屏）。
// 报错内容会以可读文本展示，方便定位真实原因。
import * as React from "react";

type Props = { children: React.ReactNode; name?: string };
type State = { error: Error | null };

export default class ErrorBoundary extends React.Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: unknown) {
    // eslint-disable-next-line no-console
    console.error("[Panel] ErrorBoundary caught:", error, info);
  }

  render() {
    if (this.state.error) {
      const msg = String(this.state.error?.message ?? this.state.error ?? "未知错误");
      return (
        <div className="flex items-start justify-center gap-2 rounded-lg border border-rose-500/40 bg-rose-950/40 p-3 text-left">
          <span className="text-lg">⚠️</span>
          <div className="min-w-0 flex-1">
            <div className="text-xs font-bold text-rose-200">{this.props.name ?? "此区域"}渲染出错，已隔离（其余编辑器仍可用）</div>
            <pre className="mt-1 max-h-28 overflow-auto whitespace-pre-wrap break-all rounded bg-black/40 p-1 text-[10px] text-rose-300">
              {msg}
            </pre>
            <button
              onClick={() => this.setState({ error: null })}
              className="mt-1 rounded bg-rose-800/60 px-2 py-0.5 text-[10px] text-rose-100 hover:bg-rose-700"
            >
              重试渲染
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}