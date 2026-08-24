// 客户端 API 封装：走同源 BFF 路由（app/api/...），由 BFF 转发 FastAPI
import type {
  AgentCreated,
  AgentDefinition,
  AgentRunOut,
  ArtifactOut,
  AssetOut,
  ChatOut,
  DirectorPlanOut,
  DirectorPlanView,
  Orchestration,
  Workflow,
} from "@/types";
import { clearAiBusy, setAiBusy } from "@/lib/aiProgress";

// 全局 AI 生成进度条：为单次 AI 内容生成请求裹一层——请求进行期间顶部显示
// 「AI 正在生成…」进度条，请求结束自动关闭（详情/百分比由后端逐步刷新）。
function aiBusy<T>(label: string, detail: string | undefined, p: Promise<T>): Promise<T> {
  setAiBusy({ label, detail });
  return p.finally(() => clearAiBusy());
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getToken();
  const res = await fetch(path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init?.headers || {}),
    },
    cache: "no-store",
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    const detail = Array.isArray(body?.detail)
      ? body.detail.map((d: { msg?: string; loc?: unknown[] }) => d?.msg).filter(Boolean).join("；")
      : "";
    throw new Error(body?.error?.message || detail || `请求失败 ${res.status}`);
  }
  return res.json() as Promise<T>;
}

/** 带鉴权的原始 fetch：自动附加 Bearer token，供需要自行解析原始响应/状态码的调用方使用。 */
export async function authenticatedFetch(path: string, init?: RequestInit): Promise<Response> {
  const token = getToken();
  return fetch(path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init?.headers || {}),
    },
    cache: "no-store",
  });
}

// ---- 受保护的剧情图 / 运行时接口（与 IDE 直接 fetch 复用同一鉴权） ----
export type StoryGraphPayload = Record<string, unknown>;

export function getStoryGraph(projectId: string) {
  return req<{ version: number; graph: StoryGraphPayload; change_reason: string | null }>(
    `/api/projects/${projectId}/storygraph`,
  );
}

export function putStoryGraph(projectId: string, graph: StoryGraphPayload, changeReason: string | null) {
  return req<{ version: number; graph: StoryGraphPayload; change_reason: string | null }>(
    `/api/projects/${projectId}/storygraph`,
    { method: "PUT", body: JSON.stringify({ graph, change_reason: changeReason }) },
  );
}

export function createPlaySession(projectId: string) {
  return req<{ session_id: string; state?: Record<string, unknown>; current_node_id?: string }>(
    `/api/projects/${projectId}/runtime/sessions`,
    { method: "POST", body: "{}" },
  );
}

// ---- 登录注册（Step 21）：用户名+密码+JWT ----
const TOKEN_KEY = "yiwa_token";

export function getToken(): string {
  if (typeof window === "undefined") return "";
  return window.localStorage.getItem(TOKEN_KEY) || "";
}
export function setToken(token: string) {
  if (typeof window === "undefined") return;
  if (token) window.localStorage.setItem(TOKEN_KEY, token);
  else window.localStorage.removeItem(TOKEN_KEY);
}
export function clearToken() {
  setToken("");
}

export function registerAccount(username: string, password: string) {
  return req<{ token: string; user: { id: string; username: string } }>("/api/auth/register", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
}
export function loginAccount(username: string, password: string) {
  return req<{ token: string; user: { id: string; username: string } }>("/api/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
}
export function getAuthStatus() {
  // 明文元信息：后端当前是否要求登录（决定前端是否强制跳转 /login）。
  return req<{ auth_required: boolean }>("/api/auth/status", { cache: "no-store" });
}
export async function fetchMe() {
  const token = getToken();
  if (!token) return null;
  try {
    const r = await req<{ user: { id: string; username: string } }>("/api/auth/me", {
      headers: { Authorization: `Bearer ${token}` },
    });
    return r.user;
  } catch {
    return null;
  }
}

export function createAgent(goal: string) {
  return req<AgentCreated>("/api/projects", { method: "POST", body: JSON.stringify({ goal }) });
}

// Director 垂直切片：创意 -> Director -> AgentPlan（真实业务入口，可选作品类型/标题）
// Director 垂直切片：创意 -> Director -> AgentPlan（真实业务入口，可选作品类型/标题）
export function createProjectViaDirector(goal: string, opts?: { game_type?: string; title?: string }) {
  return aiBusy(
    "AI 一键开工",
    "Director 规划世界观 / 类型 / 七步生成蓝图…",
    req<DirectorPlanOut>("/api/director/plan", {
      method: "POST",
      body: JSON.stringify({ goal, game_type: opts?.game_type ?? null, title: opts?.title ?? null }),
    }),
  );
}

// 小说导入 -> 拆剧本 -> 角色卡 -> 人物关系 -> 串联互动图
export type NovelImportResult = {
  project_id: string;
  title: string;
  game_type: string;
  game_type_label: string;
  scene_count: number;
  characters: { character_id: string; name: string; role: string; description: string }[];
  relationship_count: number;
};

export function importNovel(payload: { title: string; text: string; game_type: string }) {
  return aiBusy(
    "AI 拆解小说",
    "分析原文 → 场景 / 角色卡 → 人物关系 → 串联互动分支…",
    req<NovelImportResult>("/api/novel/import", { method: "POST", body: JSON.stringify(payload) }),
  );
}

export function getDirectorPlan(projectId: string) {
  return req<DirectorPlanView>(`/api/director/plan/${projectId}`);
}

// Orchestrator 垂直切片：执行 AgentPlan DAG -> 产出 Artifact（如 WorldBible）
export function orchestrateProject(projectId: string) {
  return req<Orchestration>(`/api/orchestrate/${projectId}`, { method: "POST" });
}

export function getOrchestration(projectId: string) {
  return req<Orchestration>(`/api/orchestrate/${projectId}`);
}

// Interactive Creation Layer（Step 8）：用户修改 / 局部执行 / 版本历史
export function reviseArtifact(projectId: string, kind: string, instruction: string) {
  return req<Orchestration>(`/api/projects/${projectId}/revise`, {
    method: "POST",
    body: JSON.stringify({ kind, instruction }),
  });
}

export function editArtifactContent(
  projectId: string,
  kind: string,
  content: Record<string, unknown>,
  changeReason?: string,
) {
  return req<Orchestration>(`/api/projects/${projectId}/artifacts/content`, {
    method: "PUT",
    body: JSON.stringify({ kind, content, change_reason: changeReason ?? null }),
  });
}

export function rerunTask(projectId: string, taskId: string) {
  return req<Orchestration>(`/api/projects/${projectId}/tasks/${taskId}/run`, { method: "POST" });
}

export function getArtifactHistory(projectId: string) {
  return req<ArtifactOut[]>(`/api/projects/${projectId}/artifacts`);
}

// Story 结构操作（Step 10）：延长剧情 / 增加分支
export function storyOperation(
  projectId: string,
  operation: "extend" | "branch",
  instruction: string,
  anchorNodeId?: string,
) {
  return aiBusy(
    operation === "branch" ? "AI 增开分支" : "AI 延长剧情",
    instruction.trim().slice(0, 40) || (operation === "branch" ? "在锚点节点新增分支选项…" : "在剧情尾部延出更多节点…"),
    req<Orchestration>(`/api/projects/${projectId}/story`, {
      method: "POST",
      body: JSON.stringify({ operation, instruction, anchor_node_id: anchorNodeId ?? null }),
    }),
  );
}

// Scene 局部操作（Step 11）：按节点生成 / 修改 / 扩写场景
export function sceneOperation(
  projectId: string,
  operation: "generate" | "revise" | "expand",
  nodeId: string,
  instruction: string,
) {
  return aiBusy(
    "AI 生成场景",
    `${nodeId} · ${operation === "revise" ? "按你的话重写" : operation === "expand" ? "扩写剧情" : "生成场景正文"}`,
    req<Orchestration>(`/api/projects/${projectId}/scene`, {
      method: "POST",
      body: JSON.stringify({ operation, node_id: nodeId, instruction }),
    }),
  );
}

// Dialogue 局部操作（Step 12）：按 (node_id, choice_id) 生成 / 修改 / 扩写对白
export function dialogueOperation(
  projectId: string,
  operation: "generate" | "revise" | "expand",
  nodeId: string,
  choiceId: string | null,
  instruction: string,
) {
  return aiBusy(
    "AI 生成对白",
    `${nodeId}${choiceId ? ` / ${choiceId}` : ""} · ${operation === "revise" ? "重写" : operation === "expand" ? "扩写" : "生成"}`,
    req<Orchestration>(`/api/projects/${projectId}/dialogue`, {
      method: "POST",
      body: JSON.stringify({ operation, node_id: nodeId, choice_id: choiceId, instruction }),
    }),
  );
}

// 开放共创分支：让 AI 为玩家编写的自由走向生图（真实媒体生成）
export function generateProjectBranchImage(projectId: string, prompt: string) {
  return aiBusy(
    "AI 绘制分支画面",
    prompt.trim().slice(0, 40) || "为共创分支生成配图…",
    req<{ image_url?: string; url?: string; provider?: string; content?: string; images?: string[] }>(
      `/api/projects/${projectId}/images`,
      { method: "POST", body: JSON.stringify({ prompt, size: "1024x1024", n: 1 }) },
    ),
  );
}

// ---- 角色关系图（关系图 + AI 一键生成 + 基于关系新增角色） ----
export type RelEdge = {
  edge_id: string; source_character: string; target_character: string; relationship_type: string;
  initial_value: number; affection: number; trust: number; hostility: number;
  secrets: string[]; rules: string[]; triggers: string[]; possible_changes: unknown[]; relationship_arc: string[];
};
export type RelGraph = { graph_id: string; characters: string[]; edges: RelEdge[] };

export function listRelations(projectId: string) {
  return req<RelGraph>(`/api/projects/${projectId}/relations`);
}
export function saveRelations(projectId: string, graph: RelGraph) {
  return req<RelGraph>(`/api/projects/${projectId}/relations`, { method: "POST", body: JSON.stringify(graph) });
}
export function genRelations(projectId: string) {
  return aiBusy("AI 生成人物关系", "按角色卡推断关系 / 亲密度 / 信任 / 冲突…",
    req<RelGraph>(`/api/projects/${projectId}/relations/generate`, { method: "POST", body: "{}" }));
}
export function newCharacterFromRelation(
  projectId: string,
  payload: { name: string; role: string; description?: string; relations?: { source_character: string; relationship_type: string }[] },
) {
  return req<{ character: { character_id: string; name: string; role: string }; graph: RelGraph }>(
    `/api/projects/${projectId}/relations/new-character`,
    { method: "POST", body: JSON.stringify(payload) },
  );
}

// ---- 小游戏生成器（10 种类型 + AI 生成 + 插入剧情节点） ----
export type GameConfig = {
  game_id: string; title: string; description: string;
  success_result: "success" | "perfect"; score_variable?: string | null;
  settings: { [k: string]: number | string };
};
export const GAME_TYPES = [
  "click", "memory", "choose", "typing", "guess", "quiz", "dialogue", "timer", "story", "score",
] as const;
export const GAME_META: Record<string, { label: string; emoji: string }> = {
  click: { label: "连点挑战", emoji: "🖱️" }, memory: { label: "记忆配对", emoji: "🧠" },
  choose: { label: "二选一抉择", emoji: "⚖️" }, typing: { label: "打字闯关", emoji: "⌨️" },
  guess: { label: "猜图/猜词", emoji: "🔍" }, quiz: { label: "知识问答", emoji: "📚" },
  dialogue: { label: "嘴上对白选择", emoji: "💬" }, timer: { label: "限时决策", emoji: "⏱️" },
  story: { label: "剧情掷骰分支", emoji: "🎲" }, score: { label: "计分挑战", emoji: "🏆" },
};
export function generateMinigame(projectId: string, body: { game_type: string; style: string; prompt: string }) {
  return aiBusy("AI 生成小游戏", `${body.game_type} · ${body.prompt.trim().slice(0, 30)}`,
    req<{ game_id: string; config: GameConfig; prompt: string; style: string }>(
      `/api/projects/${projectId}/minigames`, { method: "POST", body: JSON.stringify(body) },
    ));
}
export function listMinigames(projectId: string) {
  return req<{ game_id: string; config: GameConfig; kind: string }[]>(`/api/projects/${projectId}/minigames`);
}
export function insertMinigame(projectId: string, mid: string, nodeId: string) {
  return req<{ ok: boolean; node_id: string; kind: string }>(
    `/api/projects/${projectId}/minigames/${encodeURIComponent(mid)}/insert`,
    { method: "POST", body: JSON.stringify({ node_id: nodeId }) },
  );
}

export type BatchPortraitsResult = {
  results: { character_id: string; name: string; generated: number; version: number }[];
  total_generated: number;
};

export function batchGeneratePortraits(projectId: string, characterIds?: string[], force = false) {
  return aiBusy("AI 批量生成立绘", `${characterIds?.length ?? "全部"} 位角色 · 人物一致性锁定…`,
    req<BatchPortraitsResult>(`/api/projects/${projectId}/portraits/batch-generate`, {
      method: "POST",
      body: JSON.stringify({ character_ids: characterIds ?? null, force }),
    }));
}

// ---- 手动角色 CRUD（新增 / 编辑 / 删除一张角色卡） ----
export function listCharacters(projectId: string) {
  return req<
    { character_id: string; name: string; role: string; kind?: string }[]
  >(`/api/projects/${projectId}/characters`);
}

export function getCharacter(projectId: string, characterId: string) {
  return req<{ character_id: string; version: number; card: Record<string, unknown> | null }>(
    `/api/projects/${projectId}/characters/${characterId}`,
  );
}

export function createCharacter(
  projectId: string,
  payload: { name?: string; role?: string; appearance?: string; character_id?: string },
) {
  return req<{ character_id: string; version: number; card: Record<string, unknown> }>(
    `/api/projects/${projectId}/characters`,
    { method: "POST", body: JSON.stringify(payload) },
  );
}

export function updateCharacter(
  projectId: string,
  characterId: string,
  card: object,
  change_reason?: string,
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
): Promise<{ character_id: string; version: number; card: any }> {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  return req<any>(`/api/projects/${projectId}/characters/${characterId}`, {
    method: "PUT",
    body: JSON.stringify({ card, change_reason: change_reason ?? null }),
  });
}

export function deleteCharacter(projectId: string, characterId: string) {
  return req<{ deleted: boolean; character_id: string }>(
    `/api/projects/${projectId}/characters/${characterId}`,
    { method: "DELETE" },
  );
}

// ---- 分镜视频：横竖屏 + 整链批量拆镜 ----
export function generateStoryboardVideo(
  projectId: string,
  nodeId: string,
  opts: { duration_sec?: number; aspect_ratio?: string },
) {
  return aiBusy(
    "AI 生成分镜视频",
    `${nodeId} · 拆镜/运镜/台词合成中…`,
    req<Record<string, unknown>>(
      `/api/projects/${projectId}/storyboard/${nodeId}/video`,
      { method: "POST", body: JSON.stringify({ duration_sec: opts.duration_sec ?? null, aspect_ratio: opts.aspect_ratio ?? "16:9" }) },
    ),
  );
}

export function storyboardBreakdown(projectId: string, nodeId: string, requested_shots = 4) {
  return aiBusy(
    "AI 拆解分镜",
    `${nodeId} · 生成 ${requested_shots} 个镜头（scene 提示词 + 统一人设）…`,
    req<Record<string, unknown>>(
      `/api/projects/${projectId}/storyboard/${nodeId}/breakdown`,
      { method: "POST", body: JSON.stringify({ requested_shots }) },
    ),
  );
}

export function getStoryboardVideo(projectId: string, nodeId: string) {
  return req<Record<string, unknown>>(`/api/projects/${projectId}/storyboard/${nodeId}/video`);
}

export type StorygraphCheck = {
  version: number;
  ok: boolean;
  errors: string[];
  warnings: string[];
  counts: { nodes: number; edges: number; endings: number; variables: number };
};

export function getStorygraphCheck(projectId: string) {
  return req<StorygraphCheck>(`/api/projects/${projectId}/storygraph/check`);
}

export type Health = {
  status: string;
  version: string;
  llm_provider: string;
  agents_registered: number;
  llm_mode: string;
  llm_fallback: boolean;
  llm_note: string;
};

export function getHealth() {
  return req<Health>("/api/health");
}

export function listProjects() {
  return req<
    {
      id: string;
      goal: string;
      template: string;
      title: string;
      description: string | null;
      current_version: number;
      status: string;
      created_at: string;
    }[]
  >("/api/projects");
}

export function getWorkflow(projectId: string) {
  return req<Workflow>(`/api/projects/${projectId}/workflow`);
}

export function chat(projectId: string, message: string) {
  return req<ChatOut>(`/api/projects/${projectId}/chat`, { method: "POST", body: JSON.stringify({ message }) });
}

export function getTraces(projectId: string) {
  return req<AgentRunOut[]>(`/api/projects/${projectId}/traces`);
}

export function getAgents() {
  return req<AgentDefinition[]>("/api/agents");
}

// 模型设置（本地 config.json，密钥打码读写）
export type SettingsView = {
  config_file: string;
  values: Record<string, string | boolean>;
  ready: { text_ready: boolean; image_ready: boolean; video_ready: boolean; yiwa_ready: boolean };
  note: string;
};

export function getSettings() {
  return req<SettingsView>("/api/settings");
}

export function updateSettings(payload: Record<string, string | boolean>) {
  return req<SettingsView>("/api/settings", { method: "PUT", body: JSON.stringify(payload) });
}

// ---- 资产（Assets）----
export function listAssets() {
  return req<AssetOut[]>("/api/assets");
}

export function listProjectAssets(projectId: string) {
  return req<AssetOut[]>(`/api/projects/${projectId}/assets`);
}

// ---- 点数账户（充值 / 兑换 / 流水 / 引擎单价）----
export type CreditOverview = { balance: number; markup: number; currency: string; unit: string };
export type CreditLedgerItem = {
  id: string; delta: number; kind: string; model: string; provider: string;
  input_tokens: number; output_tokens: number; note: string; created_at: string | null;
};
export type CreditPrices = {
  markup: number;
  defaults: Record<string, [number, number]>;
  items: { model: string; input_price: number; output_price: number; markup: number }[];
};

export function getCreditOverview() {
  return req<CreditOverview>("/api/credits/overview");
}
export function getCreditLedger(limit = 50) {
  return req<{ items: CreditLedgerItem[] }>(`/api/credits/ledger?limit=${limit}`);
}
export function redeemCredit(code: string) {
  return req<{ redeemed_points: number; balance: number }>("/api/credits/redeem", {
    method: "POST", body: JSON.stringify({ code }),
  });
}
// 充值 = 购买兑换码：后台生成一个面值=金额的兑换码（线下收款后凭码入账）
export function mintCredit(yuan: number, note = "") {
  return req<{ code: string; yuan: number; points: number }>("/api/credits/mint", {
    method: "POST", body: JSON.stringify({ yuan, note }),
  });
}
export function getCreditPrices() {
  return req<CreditPrices>("/api/credits/prices");
}
export function setCreditPrice(payload: { model: string; input_price: number; output_price: number; markup?: number }) {
  return req<{ model: string; input_price: number; output_price: number; markup: number }>("/api/credits/prices", {
    method: "POST", body: JSON.stringify(payload),
  });
}
