"use client";

// 内容工作区（角色 / 场景 / 对白 / 世界观）：左侧条目列表，右侧可视化表单编辑器。
// 所有保存都走真实 API（editArtifactContent / createCharacter）。
import { useEffect, useState } from "react";
import { createCharacter, editArtifactContent } from "@/lib/api";
import type { ArtifactOut } from "@/types";
import VisualEditor from "./VisualEditor";
import { artifactsForWorkspace, titleOf, type WorkspaceKey as WorkspaceKey } from "./workspace";

export default function ContentWorkspace({
  kind,
  artifacts,
  chars,
  projectId,
  onSaved,
  onPickChar,
  onAddNode,
  onDeleteNode,
}: {
  kind: WorkspaceKey;
  artifacts: ArtifactOut[];
  chars: { character_id: string; name: string; role: string }[];
  projectId: string;
  onSaved: () => void;
  onPickChar?: (id: string) => void;
  onAddNode?: (kind: "scene" | "choice") => void;
  onDeleteNode?: (kind: "scene" | "choice", nodeId: string) => void;
}) {
  const items = kind === "run" ? [] : artifactsForWorkspace(artifacts, kind);
  const [sel, setSel] = useState<ArtifactOut | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");

  const nodeIdOf = (a: ArtifactOut): string | null => {
    const i = a.kind.indexOf(":");
    return i >= 0 ? a.kind.slice(i + 1) : null;
  };
  const isScene = kind === "scenes";
  const isDialogue = kind === "dialogues";

  useEffect(() => {
    if (items.length && !items.find((x) => x.id === sel?.id)) setSel(null);
    else if (!sel && items.length > 0) setSel(items[0]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [kind, artifacts]);

  const save = async (content: Record<string, unknown>) => {
    if (!sel) return;
    setBusy(true);
    setMsg("");
    try {
      await editArtifactContent(projectId, sel.kind, content, "内容可视化编辑");
      setMsg("已保存并生成新版本");
      onSaved();
    } catch (e) {
      setMsg(`保存失败：${String((e as Error).message ?? e)}`);
    } finally {
      setBusy(false);
    }
  };

  const addCharacter = async () => {
    setBusy(true);
    try {
      await createCharacter(projectId, { name: "新角色" });
      onSaved();
      onPickChar?.("");
    } catch (e) {
      setMsg(`新增失败：${String((e as Error).message ?? e)}`);
    } finally {
      setBusy(false);
    }
  };

  const label =
    kind === "characters" ? "角色" :
    kind === "scenes" ? "场景" :
    kind === "dialogues" ? "对白" :
    kind === "world" ? "世界观" : "内容";

  return (
    <div className="flex h-full">
      <div className="flex w-56 shrink-0 flex-col overflow-y-auto border-r border-white/10 bg-panel/40 p-2">
        <div className="mb-1 flex items-center justify-between">
          <span className="text-xs font-bold text-slate-300">{label}（{items.length}）</span>
          {kind === "characters" ? (
            <button onClick={addCharacter} disabled={busy} className="rounded-md bg-accent/15 px-2 py-0.5 text-xs text-accent disabled:opacity-50">＋ 新增</button>
          ) : isScene || isDialogue ? (
            <button
              onClick={() => onAddNode?.(isScene ? "scene" : "choice")}
              className="rounded-md bg-accent/15 px-2 py-0.5 text-xs text-accent"
              title="在剧情图新建一个节点并生成该内容"
            >＋ 新增节点</button>
          ) : null}
        </div>
        {items.length === 0 && !(kind === "characters") && <p className="text-xs text-slate-500">暂无已生成内容。可先在「剧情」画布生成，或用顶部 Bot AI 生成。</p>}
        {(kind === "characters" ? items : items).slice(0, 60).map((a) => (
          <div key={a.id} className="group flex items-center gap-1">
            <button
              onClick={() => { setSel(a); if (kind === "characters") onPickChar?.(String(a.content?.character_id ?? "")); }}
              className={`block flex-1 truncate rounded-md px-2 py-1 text-left text-xs ${sel?.id === a.id ? "bg-accent/15 text-accent" : "text-slate-300 hover:bg-white/5"}`}
            >
              {titleOf(a)} <span className="text-[9px] text-slate-500">v{a.version}</span>
            </button>
            {(isScene || isDialogue) && onDeleteNode && nodeIdOf(a) ? (
              <button
                onClick={() => {
                  const nodeId = nodeIdOf(a);
                  if (nodeId && confirm(`删除该${label === "对白" ? "对白/节点" : "场景节点"}（同时从剧情图移除，旧版本内容保留在版本库）？`)) {
                    onDeleteNode(isScene ? "scene" : "choice", nodeId);
                  }
                }}
                className="rounded bg-rose-900/50 px-1.5 py-1 text-[10px] text-rose-200 opacity-0 hover:bg-rose-800 group-hover:opacity-100"
                title="删除此节点"
              >✕</button>
            ) : null}
          </div>
        ))}
        {kind === "characters" && chars.length > 0 && items.length === 0 ? (
          <p className="text-xs text-slate-500">已由角色卡生成；点击「＋ 新增」或先运行剧情生成。</p>
        ) : null}
      </div>

      <div className="flex-1 overflow-y-auto p-4">
        {sel ? (
          <div>
            <div className="mb-2 flex items-center justify-between">
              <div className="font-bold">{titleOf(sel)} <span className="text-xs text-slate-500">· {sel.kind} · v{sel.version}</span></div>
              <button onClick={() => save(sel.content ?? {})} disabled={busy} className="rounded-md bg-mint/20 px-3 py-1 text-xs font-bold text-mint disabled:opacity-50">
                {busy ? "保存中…" : "保存修改"}
              </button>
            </div>
            <VisualEditor key={sel.id} artifact={sel} onChange={() => {}} />
            {msg && <p className="mt-2 text-xs text-mint">{msg}</p>}
            <div className="mt-2 text-[10px] text-slate-500">上方为可视化字段编辑；保存后生成新版本并与 Artifact Version 联动。</div>
          </div>
        ) : (
          <p className="text-sm text-slate-500">从左侧选择一个条目，或回到「剧情」画布运行剧情后自动产生内容。</p>
        )}
      </div>
    </div>
  );
}