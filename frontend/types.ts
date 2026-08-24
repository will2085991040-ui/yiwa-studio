// 类型定义：与后端 Pydantic Schema 对齐（Phase 0 子集）

export type PlanStepStatus =
  | "pending"
  | "ready"
  | "running"
  | "succeeded"
  | "failed"
  | "blocked"
  | "skipped"
  | "done";

export interface PlanStep {
  key: string;
  label: string;
  description: string;
  agent: string;
  dependencies: string[];
  status: PlanStepStatus;
  reason: string;
  /** 实时生成进度（scene/dialogue 扇出过程中由后端逐批写入） */
  progress?: { done: number; total: number; pct: number; label: string };
}

export interface AgentCreated {
  project_id: string;
  goal: string;
  template: string;
  agent_spec: {
    id: string;
    goal_summary: string;
    template: string;
    status: string;
    plan: PlanStep[];
  };
  agent_version: {
    id: string;
    version_no: number;
    label: string;
    status: string;
    created_at: string;
  };
}

export interface Workflow {
  project_id: string;
  status: string;
  steps: PlanStep[];
}

export interface ChatOut {
  reply: string;
  status: string;
  template: string;
}

export interface AgentRunOut {
  id: string;
  kind: string;
  status: string;
  started_at: string;
  steps: {
    id: string;
    seq: number;
    agent: string;
    step_key: string;
    status: string;
    latency_ms: number;
    token_usage: Record<string, unknown>;
    error: string | null;
    input_data: Record<string, unknown>;
    output_data: Record<string, unknown>;
  }[];
}

export interface AgentDefinition {
  name: string;
  layer: string;
  description: string;
  input_schema: Record<string, unknown>;
  output_schema: Record<string, unknown>;
  implemented: boolean;
}

// ---------------------------------------------------------------------------
// Director 垂直切片（Step 5）
// ---------------------------------------------------------------------------

export type Priority = "low" | "medium" | "high" | "critical";

export interface ProductionTask {
  id: string;
  agent_type: string;
  objective: string;
  input_refs: string[];
  output_schema: Record<string, unknown>;
  dependencies: string[];
  priority: Priority;
  condition: string | null;
  retry_policy: { max_retries: number; backoff_seconds: number; on_error: string };
  budget: { max_output_tokens: number; max_duration_seconds: number | null };
}

export interface AgentPlan {
  goal: string;
  goal_summary: string;
  project_type: string;
  target_audience: string;
  genre: string;
  tone: string;
  business_objective: string;
  creative_objective: string;
  required_capabilities: string[];
  characters_required: string;
  worldbuilding_required: string;
  story_required: string;
  scene_required: string;
  branch_required: string;
  dialogue_required: string;
  evaluation_required: string;
  generation_steps: ProductionTask[];
  success_metrics: string[];
  constraints: string[];
  budget: { max_total_tokens: number; max_cost_usd: number | null };
  priority: Priority;
}

export interface DirectorPlanOut {
  project_id: string;
  goal: string;
  prompt_version: string;
  provider: string;
  model: string;
  latency_ms: number;
  agent_plan: AgentPlan;
  agent_version: {
    id: string;
    version_no: number;
    label: string;
    status: string;
    created_at: string;
  };
}

export interface DirectorPlanView {
  project_id: string;
  goal: string;
  prompt_version: string;
  provider: string;
  model: string;
  agent_plan: AgentPlan;
}

// ---------------------------------------------------------------------------
// Orchestrator（Step 6）
// ---------------------------------------------------------------------------

export interface ArtifactOut {
  id: string;
  task_id: string;
  agent: string;
  kind: string;
  content: Record<string, unknown>;
  prompt_version: string;
  version: number;
  parent_version: number | null;
  source: "agent" | "user";
  change_reason: string | null;
  is_latest: boolean;
}

/** 资产（Asset）：各 Agent 生成产物汇总列表条目。 */
export interface AssetOut {
  id: string;
  project_id: string;
  project_title: string;
  agent: string;
  kind: string;
  kind_label: string;
  type: "video" | "image" | "text" | "other";
  title: string;
  version: number;
  url: string;
  is_latest: boolean;
  source: "agent" | "user";
  created_at: string;
}

export interface WorldBibleContent {
  world_id: string;
  title: string;
  setting: string;
  era: string;
  location: string;
  rules: string[];
  social_structure: string;
  factions: { name: string; description: string; role: string }[];
  culture: string;
  technology: string;
  conflicts: string[];
  key_locations: { name: string; description: string }[];
  world_constraints: string[];
  consistency_notes: string;
}

export interface SpeechStyle {
  tone: string;
  formality: string;
  catchphrases: string[];
  quirks: string[];
}

export interface CharacterCardContent {
  character_id: string;
  name: string;
  role: string;
  age: string;
  gender: string;
  appearance: string;
  personality: string[];
  background: string;
  motivation: string;
  goal: string;
  conflict: string;
  fear: string;
  secret: string;
  relationship_rules: string[];
  speech_style: SpeechStyle;
  likes: string[];
  dislikes: string[];
  hidden_information: string[];
  character_arc: string[];
  possible_endings: string[];
}

export interface RelationshipChange {
  trigger: string;
  effects: { variable: string; op: string; value: unknown }[];
  resulting_branch: string;
}

export interface RelationshipEdge {
  edge_id: string;
  source_character: string;
  target_character: string;
  relationship_type: string;
  affection: number;
  trust: number;
  hostility: number;
  secrets: string[];
  rules: string[];
  triggers: string[];
  possible_changes: RelationshipChange[];
  relationship_arc: string[];
}

export interface RelationshipGraphContent {
  graph_id: string;
  characters: string[];
  edges: RelationshipEdge[];
}

export interface StoryVariable {
  name: string;
  type: "number" | "bool" | "string" | "enum";
  initial: unknown;
  description: string;
}

export interface StoryEffect {
  variable: string;
  op: "add" | "sub" | "set";
  value: unknown;
}

export interface StoryCondition {
  variable: string;
  op: ">=" | "<=" | ">" | "<" | "==" | "!=";
  value: number | boolean | string;
}

export interface StoryChoice {
  choice_id: string;
  text: string;
  condition: string | null;
  effects: StoryEffect[];
  next_node: string | null;
}

export interface StoryNode {
  node_id: string;
  kind: "scene" | "choice" | "ending" | "branch" | "merge";
  title: string;
  content_ref: string | null;
  summary: string;
  entry_conditions: string[];
  on_enter: StoryEffect[];
  choices: StoryChoice[];
  locked: boolean;
}

export interface StoryEdge {
  edge_id: string;
  source: string;
  target: string;
  label: string;
  condition: string | null;
}

export interface StoryGraphContent {
  graph_id: string;
  nodes: StoryNode[];
  edges: StoryEdge[];
  variables: StoryVariable[];
  entry_node_id: string | null;
  metadata: Record<string, unknown>;
}

export interface SceneContent {
  scene_id: string;
  title: string;
  summary: string;
  location: string;
  time: string;
  atmosphere: string;
  characters_present: string[];
  events: string[];
  visual_direction: string;
  camera_direction: string;
  stage_direction: string;
  emotional_beats: string[];
  state_changes: StoryEffect[];
  continuity_notes: string;
  asset_requirements: Record<string, unknown>;
}

export interface DialogueLine {
  speaker: string;
  text: string;
  emotion: string;
  delivery: string;
  action: string;
  target: string | null;
  relationship_context: string;
}

export interface DialogueContent {
  dialogue_id: string;
  node_id: string;
  choice_id: string | null;
  lines: DialogueLine[];
  conditions: StoryCondition[];
  effects: StoryEffect[];
  next_node: string | null;
  branch: string | null;
  tags: string[];
  continuity_notes: string;
  asset_requirements: Record<string, unknown>;
}

export interface Orchestration {
  project_id: string;
  status: string;
  steps: PlanStep[];
  artifacts: ArtifactOut[];
}
