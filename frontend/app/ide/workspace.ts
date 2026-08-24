// 纯函数 + 类型：IDE 各组件共享（无 React 依赖，便于独立类型检查）
import type { ArtifactOut } from "@/types";

export type IdeEffect = { variable: string; op: "add" | "sub" | "set"; value: unknown };

export type IdeChoice = {
  choice_id: string;
  text: string;
  next_node: string | null;
  condition?: string | null;
  effects?: IdeEffect[];
  video_at_sec?: number | null;   // 互动影视：该选项在节点分镜视频第几秒弹层显示
};

export type IdeNode = {
  node_id: string;
  kind: string;
  title: string;
  summary: string;
  choices: IdeChoice[];
  isEntry?: boolean;
  position?: { x: number; y: number } | null;
  agent?: string;
  status?: string;
  generation?: string;
  version?: number | null;
  generating?: boolean;
  locked?: boolean;
};

export type IdeEdge = {
  edge_id: string;
  source: string;
  target: string;
  label: string;
};

export type WorkspaceKey = "story" | "characters" | "scenes" | "dialogues" | "world" | "run" | "assets";

export type Workspaces = { key: string; label: string; emoji: string };

export const WORKSPACES: { key: string; label: string; emoji: string }[] = [
  { key: "story", label: "剧情", emoji: "🎬" },
  { key: "characters", label: "角色", emoji: "🎭" },
  { key: "scenes", label: "场景", emoji: "🏞" },
  { key: "dialogues", label: "对白", emoji: "💬" },
  { key: "world", label: "世界观", emoji: "🌍" },
  { key: "run", label: "运行", emoji: "▶" },
  { key: "assets", label: "资产", emoji: "🗂" },
];

export const WORKSPACE_KEYS: WorkspaceKey[] = ["story", "characters", "scenes", "dialogues", "world", "run", "assets"];

export function uid(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`;
}

export function latestOf(arts: ArtifactOut[] | null | undefined): ArtifactOut[] {
  return (arts ?? []).filter((a) => a.is_latest);
}

/** 从制品派生「节点 → Agent / 版本」映射（kind 为 … : node_id 的产物）。 */
export function deriveNodeMeta(
  arts: ArtifactOut[] | null | undefined,
): Record<string, { agent?: string; version?: number }> {
  const m: Record<string, { agent?: string; version?: number }> = {};
  for (const a of latestOf(arts)) {
    const i = a.kind.indexOf(":");
    if (i < 0) continue;
    const nid = a.kind.slice(i + 1);
    if (nid) m[nid] = { agent: a.agent, version: a.version };
  }
  return m;
}

export function titleOf(a: ArtifactOut): string {
  const c = a.content as { title?: string; name?: string };
  return c?.title || c?.name || a.kind;
}

const KIND_LABEL: Record<string, string> = {
  scene: "剧情", choice: "选择", ending: "结局", branch: "分支", merge: "汇合", minigame: "小游戏",
};
const KIND_COLOR: Record<string, string> = {
  scene: "#ec4899", choice: "#a78bfa", ending: "#f472b6", branch: "#fbbf24", merge: "#34d399", minigame: "#f59e0b",
};

export { KIND_LABEL, KIND_COLOR };

/** 从 artifacts 里筛出某一内容工作区的条目（含 base kind 与 `{kind}:{node}` 每节点产物）。 */
export function artifactsForWorkspace(arts: ArtifactOut[] | null | undefined, key: WorkspaceKey): ArtifactOut[] {
  const list = latestOf(arts);
  if (key === "world") return list.filter((a) => a.kind === "world_bible");
  const base =
    key === "characters" ? "character_card" :
    key === "scenes" ? "scene" :
    key === "dialogues" ? "dialogue" :
    "scene";
  return list.filter((a) => a.kind === base || a.kind.startsWith(base + ":"));
}