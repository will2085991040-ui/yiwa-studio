"use client";

// 右侧 Agent Inspector：节点可视化编辑 + AI 修改 + 版本/Agent 信息 + 动作。
import { KIND_COLOR, KIND_LABEL } from "./workspace";
import type { IdeNode } from "./workspace";

export default function Inspector({
  node,
  nodeId,
  meta,
  nodeIds,
  aiInstr,
  setAiInstr,
  aiBusy,
  aiMsg,
  onUpdate,
  onModify,
  onRerun,
  onDelete,
  onEntry,
  onAddChoice,
  onDeleteChoice,
  chars,
  onInsert,
}: {
  node?: IdeNode;
  nodeId?: string | null;
  meta?: { agent?: string; version?: number };
  nodeIds: string[];
  aiInstr: string;
  setAiInstr: (v: string) => void;
  aiBusy: boolean;
  aiMsg: string;
  onUpdate: (id: string, patch: Partial<IdeNode>) => void;
  onModify: () => void;
  onRerun: () => void;
  onDelete?: () => void;
  onEntry?: () => void;
  onAddChoice?: () => void;
  onDeleteChoice?: (choiceId: string) => void;
  chars?: { character_id: string; name: string; role: string }[];
  onInsert?: (target: "title" | "summary", text: string) => void;
}) {
  if (!node || !nodeId) {
    return (
      <div className="px-4 py-4 text-xs text-slate-500">
        选择画布上的节点进入检查器；或在左侧「内容」里打开某项，用可视化面板编辑器修改。
      </div>
    );
  }
  const inputCls = "mt-1 w-full rounded-md bg-panel border border-white/10 px-2 py-1.5 text-sm text-slate-200 outline-none focus:border-accent";
  const set = (patch: Partial<IdeNode>) => onUpdate(nodeId, patch);
  const locked = !!node.locked;

  return (
    <div className="flex flex-col overflow-y-auto p-3">
      <div className="flex items-center gap-2">
        <span style={{ width: 10, height: 10, borderRadius: 3, background: KIND_COLOR[node.kind] ?? "#64748b" }} />
        <span className="font-bold">{KIND_LABEL[node.kind] ?? node.kind}</span>
        {locked ? <span className="rounded bg-gold/20 px-1.5 py-0.5 text-[9px] text-gold">🔒 AI共创锁定</span> : null}
        {meta ? (
          <span className="ml-auto rounded-full border border-white/10 bg-panel2 px-2 py-0.5 text-[10px] text-slate-400">
            {meta.agent} · v{meta.version}
          </span>
        ) : null}
      </div>

      <div className="mt-3 space-y-3">
        {locked ? (
          <p className="rounded-md border border-gold/30 bg-gold/10 px-2 py-1.5 text-[11px] text-glow">
            🔒 这是一个玩家书写的「开放共创分支」，由 AI 全权管理（含 AIGC 生图/生文），创作者不可编辑。如需改动请让 AI 重新生成。
          </p>
        ) : null}
        <label className="block text-xs text-slate-400">
          类型
          <select value={node.kind} onChange={(e) => set({ kind: e.target.value })} disabled={locked} className={inputCls}>
            {Object.entries(KIND_LABEL).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
          </select>
        </label>
        <label className="block text-xs text-slate-400">
          标题
          <input value={node.title ?? ""} disabled={locked} onChange={(e) => set({ title: e.target.value })} className={inputCls} />
        </label>
        <label className="block text-xs text-slate-400">
          简介
          <textarea value={node.summary ?? ""} disabled={locked} onChange={(e) => set({ summary: e.target.value })} rows={4} className={inputCls} />
        </label>

        {/* 剧情编辑快捷参照：角色卡 / 人物角色 */}
        {chars && chars.length > 0 && (
          <details className="rounded-md border border-white/10 bg-panel/40 p-2">
            <summary className="cursor-pointer text-xs font-bold text-slate-400">🧑 人物卡 / 角色参照（{chars.length}）</summary>
            <div className="mt-1.5 space-y-1">
              {chars.map((c) => (
                <div key={c.character_id} className="flex items-center gap-1 text-[11px] text-slate-300">
                  <span className="truncate flex-1">{c.name} <span className="text-slate-500">· {c.role || "角色"}</span></span>
                  {onInsert ? (
                    <>
                      <button onClick={() => onInsert("title", c.name)} title="插入角色名到标题" className="rounded bg-white/5 px-1.5 py-0.5 text-[10px] hover:bg-white/10">标题</button>
                      <button onClick={() => onInsert("summary", `${c.name}（${c.role || "角色"}）`)} title="插入到简介" className="rounded bg-white/5 px-1.5 py-0.5 text-[10px] hover:bg-white/10">简介</button>
                    </>
                  ) : null}
                </div>
              ))}
            </div>
          </details>
        )}

        {(node.kind === "scene" || node.kind === "chapter" || node.kind === "choice" || node.kind === "branch") && (
          <div className="rounded-md border border-white/10 bg-panel/40 p-2">
            <div className="mb-1 flex items-center justify-between text-xs text-slate-400">
              <span>选择 / 分支（{node.choices?.length ?? 0}）</span>
              {onAddChoice && !locked ? <button onClick={onAddChoice} className="text-accent">＋ 选项</button> : locked ? <span className="text-[10px] text-slate-500">锁定</span> : null}
            </div>
            {(node.choices ?? []).map((c, i) => (
              <div key={c.choice_id} className="mb-1 rounded bg-panel/60 p-1">
                <div className="flex items-center gap-1">
                  <input
                    value={c.text}
                    onChange={(e) => {
                      const choices = (node.choices ?? []).map((x, j) => (j === i ? { ...x, text: e.target.value } : x));
                      set({ choices });
                    }}
                    className="flex-1 rounded bg-panel border border-white/10 px-2 py-1 text-xs"
                  />
                  <select
                    value={c.next_node ?? ""}
                    onChange={(e) => {
                      const choices = (node.choices ?? []).map((x, j) => (j === i ? { ...x, next_node: e.target.value || null } : x));
                      set({ choices });
                    }}
                    className="w-16 rounded bg-panel border border-white/10 px-1 py-1 text-xs"
                  >
                    <option value="">→?</option>
                    {nodeIds.filter((x) => x !== nodeId).map((x) => <option key={x} value={x}>{x}</option>)}
                  </select>
                  {onDeleteChoice ? (
                    <button onClick={() => onDeleteChoice(c.choice_id)} title="删除此选项"
                      className="rounded bg-rose-900/50 px-1.5 py-1 text-[10px] text-rose-200 hover:bg-rose-800">✕</button>
                  ) : null}
                </div>
                <label className="mt-1 flex items-center gap-1 text-[10px] text-slate-500">
                  视频中出现时机
                  <input
                    type="number" min={0} step={0.5}
                    placeholder="秒（留空=播完再选）"
                    value={c.video_at_sec ?? ""}
                    onChange={(e) => {
                      const v = e.target.value === "" ? null : Math.max(0, Number(e.target.value));
                      set({ choices: (node.choices ?? []).map((x, j) => (j === i ? { ...x, video_at_sec: v } : x)) });
                    }}
                    className="w-24 rounded bg-panel border border-white/10 px-1 py-0.5 text-[10px]"
                  />
                  秒（互动影视：第 N 秒弹层供玩家选择）
                </label>
              </div>
            ))}
          </div>
        )}

        <div className="flex gap-1.5">
          {onEntry ? <button onClick={onEntry} className="flex-1 rounded-md bg-slate-700 py-1.5 text-xs hover:bg-slate-600">设为入口</button> : null}
          <button onClick={onRerun} className="flex-1 rounded-md bg-slate-700 py-1.5 text-xs hover:bg-slate-600">重新生成</button>
          {onDelete ? <button onClick={onDelete} className="rounded-md bg-rose-800/70 px-2.5 py-1.5 text-xs text-rose-100 hover:bg-rose-700">删除</button> : null}
        </div>
      </div>

      <div className="mt-4 rounded-xl border border-accent/30 bg-accent/5 p-2.5">
        <div className="mb-1 text-xs font-bold text-accent">AI 修改这个节点</div>
        <textarea
          value={aiInstr}
          onChange={(e) => setAiInstr(e.target.value)}
          rows={2}
          placeholder="例如：让女主更加傲娇"
          className="w-full rounded-md bg-panel border border-white/10 px-2 py-1.5 text-sm outline-none focus:border-accent"
        />
        <button
          onClick={onModify}
          disabled={aiBusy}
          className="mt-1.5 w-full rounded-md bg-accent/25 py-1.5 text-sm font-bold text-accent hover:bg-accent/35 disabled:opacity-50"
        >
          {aiBusy ? "多 Agent 生产中…" : "AI 修改"}
        </button>
        {aiMsg && <p className="mt-1 text-xs text-mint">{aiMsg}</p>}
        <div className="mt-2 text-[10px] text-slate-500">修改会调用对应 Agent，旧版本保留并生成新版本。</div>
      </div>
    </div>
  );
}