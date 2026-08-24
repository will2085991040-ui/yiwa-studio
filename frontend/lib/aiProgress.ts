"use client";

// 全局 AI 生成进度条状态机：任何页面在发起 AI 内容生成时都可发布当前进度，
// 顶部 AiProgressBar 会实时显示「正在 AI 生成…」的进度条（含百分比/说明）。
// 纯前端片段，无后端依赖。

export type AiProgressState = {
  active: boolean;
  label: string; // 短标题，如“AI 一键生成”
  detail?: string; // 具体步骤说明，如“剧情分支 12/60 节点”
  pct?: number; // 0-100；缺省表示不定长（流动条）
};

type Listener = (s: AiProgressState) => void;

let state: AiProgressState = { active: false, label: "" };
const listeners = new Set<Listener>();

function emit() {
  listeners.forEach((l) => l(state));
}

export function setAiBusy(busy: Pick<AiProgressState, "label"> & Partial<Omit<AiProgressState, "label">>) {
  state = { active: true, label: busy.label, detail: busy.detail, pct: busy.pct };
  emit();
}

export function appendAiProgress(patch: Partial<Omit<AiProgressState, "active">>) {
  if (!state.active) return;
  state = { ...state, ...patch };
  emit();
}

export function clearAiBusy() {
  state = { active: false, label: "" };
  emit();
}

// 兼容别名：setAiProgress / clearAiProgress 即 setAiBusy / clearAiBusy
export const setAiProgress = setAiBusy;
export const clearAiProgress = clearAiBusy;

export function subscribeAiProgress(l: Listener): () => void {
  listeners.add(l);
  return () => listeners.delete(l);
}

export function getAiProgress(): AiProgressState {
  return state;
}

// 便捷包装：在 promise 进行期间显示进度条，结束后关闭。
export async function withAiProgress<T>(
  busy: Pick<AiProgressState, "label"> & { detail?: string },
  fn: () => Promise<T>,
): Promise<T> {
  setAiBusy({ label: busy.label, detail: busy.detail });
  try {
    return await fn();
  } finally {
    clearAiBusy();
  }
}