"""ORM 模型：Phase 0 闭环 + Prompt 版本基础设施。"""
import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(UTC)


class Project(Base):
    """用户输入自然语言目标后创建的项目（= 一个待构建的 Agent 实例）。"""

    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    goal: Mapped[str] = mapped_column(Text, nullable=False)          # 用户原始目标（自然语言）
    template: Mapped[str] = mapped_column(String(40), nullable=False)  # 规划器识别的模板
    title: Mapped[str] = mapped_column(String(200), default="", nullable=False)  # 用户可见的项目标题
    description: Mapped[str | None] = mapped_column(Text, nullable=True)         # 项目描述
    current_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)  # 当前整体版本（随修订递增）
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now, nullable=False)

    agent_specs: Mapped[list["AgentSpec"]] = relationship(back_populates="project", cascade="all, delete-orphan")


class AgentSpec(Base):
    """AgentSpec：一个 Agent 是什么的机器可读定义（Phase 0 为骨架版，逐阶段扩充）。"""

    __tablename__ = "agent_specs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True, nullable=False)
    goal_summary: Mapped[str] = mapped_column(String(200), default="", nullable=False)  # 一句话目标理解
    plan: Mapped[list] = mapped_column(JSON, default=list, nullable=False)  # 构建步骤（状态机）
    policies: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)  # budget/safety 等策略
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)  # draft|building|ready|archived
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now, nullable=False)

    project: Mapped["Project"] = relationship(back_populates="agent_specs")
    versions: Mapped[list["AgentVersion"]] = relationship(back_populates="agent_spec", cascade="all, delete-orphan")


class AgentVersion(Base):
    """Agent 版本：优化不改线上对象，而是创建新版本。Phase 0 只创建 v1 草稿。"""

    __tablename__ = "agent_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    agent_spec_id: Mapped[str] = mapped_column(ForeignKey("agent_specs.id"), index=True, nullable=False)
    version_no: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    label: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    spec_snapshot: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)  # 创建时快照（不可变）
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)  # draft|published|rolled_back
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)

    agent_spec: Mapped["AgentSpec"] = relationship(back_populates="versions")


class AgentRun(Base):
    """一次 Agent 运行（创建/聊天/评测），轨迹根节点。"""

    __tablename__ = "agent_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    agent_version_id: Mapped[str | None] = mapped_column(ForeignKey("agent_versions.id"), index=True, nullable=True)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)  # create_agent|chat|evaluate|optimize
    status: Mapped[str] = mapped_column(String(20), default="running", nullable=False)
    meta: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    steps: Mapped[list["AgentStep"]] = relationship(back_populates="run", cascade="all, delete-orphan")


class AgentStep(Base):
    """轨迹步骤：agent / input / output / 耗时 / token / 错误。"""

    __tablename__ = "agent_steps"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    agent_run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id"), index=True, nullable=False)
    seq: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    agent: Mapped[str] = mapped_column(String(40), nullable=False)
    step_key: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    input_data: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    output_data: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="ok", nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    token_usage: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)

    run: Mapped["AgentRun"] = relationship(back_populates="steps")


class PromptDefinition(Base):
    """Prompt 定义：一个稳定命名的 Prompt 身份（如 character_generation）。"""

    __tablename__ = "prompt_definitions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)  # 稳定引用键
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now, nullable=False)

    versions: Mapped[list["PromptVersion"]] = relationship(back_populates="definition", cascade="all, delete-orphan")


class PromptVersion(Base):
    """Prompt 版本：不可变（无 updated_at、无更新路径），v1/v2 追加式演进。"""

    __tablename__ = "prompt_versions"
    __table_args__ = (
        UniqueConstraint("prompt_definition_id", "version_no", name="uq_prompt_versions_definition_version"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    prompt_definition_id: Mapped[str] = mapped_column(ForeignKey("prompt_definitions.id"), index=True, nullable=False)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)  # 同一 prompt 下自增
    content: Mapped[str] = mapped_column(Text, nullable=False)  # 模板文本，含 {变量} 占位符
    variables: Mapped[list] = mapped_column(JSON, default=list, nullable=False)  # PromptVariable 列表
    model_preferences: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)  # 模型偏好
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)  # draft|active|deprecated
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)

    definition: Mapped["PromptDefinition"] = relationship(back_populates="versions")


class Artifact(Base):
    """生产任务的结构化产出（如 WorldBible / CharacterCard）。

    Step 8 起带版本体系：同 (project_id, kind) 的多次生成形成 v1/v2/... 链，
    parent_version 指向前一版本（Git 式追踪，旧版本不覆盖），is_latest 标记当前版本。
    """

    __tablename__ = "artifacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True, nullable=False)
    task_id: Mapped[str] = mapped_column(String(80), nullable=False)  # generation_steps 里的 task id
    agent: Mapped[str] = mapped_column(String(40), nullable=False)    # agent_type
    kind: Mapped[str] = mapped_column(String(220), nullable=False)  # 含 dialogue:{node_id}[:{choice_id}]
    content: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)           # 该 kind 下的版本号
    parent_version: Mapped[int | None] = mapped_column(Integer, nullable=True)         # 前一版本（v1 为 None）
    source: Mapped[str] = mapped_column(String(20), default="agent", nullable=False)   # agent|user
    change_reason: Mapped[str | None] = mapped_column(Text, nullable=True)             # 修订原因/修改要求
    is_latest: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)     # 是否为当前版本
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)


class PlayerSession(Base):
    """一次互动游玩会话（Step 13）：把 StoryGraph 求值为可推进的 Runtime State。"""

    __tablename__ = "player_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True, nullable=False)
    current_node_id: Mapped[str] = mapped_column(String(80), nullable=False)
    state: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)  # variable name -> current value
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now, nullable=False)


class MemoryEntry(Base):
    """基础记忆（Step 15）：Kind 维度、可重建的检索索引。

    Truth 永远在原始 Artifact；本表只是「引用 + 摘要 + 标签」的可重建索引，
    绝不允许索引成为唯一数据源（ref_kind/ref_id 指回 truth 位置）。
    kind 取值：story/character/relationship/plot/scene/dialogue/choice/
    world_state/pending_hook/foreshadow/author_intent/current_focus。
    """

    __tablename__ = "memory_entries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    ref_kind: Mapped[str] = mapped_column(String(220), default="", nullable=False)  # e.g. character_card / scene:node01
    ref_id: Mapped[str | None] = mapped_column(String(220), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    tags: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now, nullable=False)


class ActionProposal(Base):
    """创意动作提议（Step 16，HITL）：高风险动作先提议、后确认的持久化载体。

    CreativeAction 是声明式请求；ActionProposal 是进入「待确认」状态的动作，
    批准后在 ActionExecution 内校验 + 执行 + 提交 + Trace。
    """

    __tablename__ = "action_proposals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True, nullable=False)
    # chat|button|node|choice|artifact|storygraph
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    operation: Mapped[str] = mapped_column(String(40), nullable=False)
    kind: Mapped[str] = mapped_column(String(220), default="", nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    risk: Mapped[str] = mapped_column(String(10), nullable=False)  # low|medium|high|blocking
    # pending|approved|rejected|executed
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    node_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now, nullable=False)


class Skill(Base):
    """技能（Step 17）：影响 Agent 行为/上下文的声明式能力。

    Skill 没有任何数据库写权限（它不持有 Session、不落 Artifact / State），
    只能通过 SkillResolver 注入上下文来改变 Agent 的行为。
    """

    __tablename__ = "skills"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id"), index=True, nullable=True)  # None=系统级
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    instructions: Mapped[str] = mapped_column(Text, default="", nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    source: Mapped[str] = mapped_column(String(20), default="system", nullable=False)  # system|project|user
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    forced: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now, nullable=False)


class Branch(Base):
    """创作分支（Step 18）：一等公民的创作对象，与 StoryGraph / Runtime 关联。

    - base_version/base_kind 指向分叉点的 StoryGraph 版本（关联，不复制全图）
    - current_node_id + state 是 BranchState：分支对应的 Runtime 推进位置
    - is_selected 标记当前选中分支（BranchSelection），每项目唯一
    """

    __tablename__ = "branches"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True, nullable=False)
    parent_branch_id: Mapped[str | None] = mapped_column(ForeignKey("branches.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    plan: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)        # BranchPlan（意图/变更说明）
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)  # active|merged|abandoned
    base_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    base_kind: Mapped[str] = mapped_column(String(220), default="story_graph", nullable=False)
    current_node_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    state: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)       # BranchState
    is_selected: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now, nullable=False)


class BranchVersion(Base):
    """分支版本（Step 18）：分支内 StoryGraph 内容快照的追加版本链。"""

    __tablename__ = "branch_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    branch_id: Mapped[str] = mapped_column(ForeignKey("branches.id"), index=True, nullable=False)
    version_no: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    kind: Mapped[str] = mapped_column(String(220), default="story_graph", nullable=False)
    content: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    change_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)


class Material(Base):
    """素材（Step 19）：角色立绘 / 场景图 / CG / BGM / SFX / 分镜 等资产的元数据与引用。

    仅存储元数据 + 引用（storage_path 指向真实文件位置），不做 AI 绘图、不接第三方服务。
    通过 ref_kind / ref_id 关联 Artifact / Scene / Character / Dialogue。
    """

    __tablename__ = "materials"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True, nullable=False)
    # character_image|scene_image|cg|bgm|sfx|storyboard|asset
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    storage_path: Mapped[str] = mapped_column(Text, default="", nullable=False)
    mime_type: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    meta: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)  # 元数据（'metadata' 为 ORM 保留名）
    ref_kind: Mapped[str] = mapped_column(String(220), default="", nullable=False)
    ref_id: Mapped[str | None] = mapped_column(String(220), nullable=True)
    tags: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)  # active|abandoned
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now, nullable=False)


class PlaySession(Base):
    """Play Session（Step 20）：与 Authoring Runtime 严格分离的游玩会话。

    world 是 Play Runtime 的权威状态（entities/edges/state/timeline/evidence），
    只能经 PlayMutation 的确定性应用来更新（LLM 永不直接改 State）。
    """

    __tablename__ = "play_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True, nullable=False)
    world: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now, nullable=False)


class PlayTurn(Base):
    """Play Turn（Step 20）：一次「Interpret→Mutation→Validate→Apply→Render」的持久记录。"""

    __tablename__ = "play_turns"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    play_session_id: Mapped[str] = mapped_column(ForeignKey("play_sessions.id"), index=True, nullable=False)
    seq: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    intent: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    mutation: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    result: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="ok", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)


class User(Base):
    """登录用户（Step 21 登录注册）：用户名 + PBKDF2 密码哈希 + JWT。

    密码永不存明文；password_hash 使用 hashlib.pbkdf2_hmac 生成（自包含、无外部依赖）。
    """

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)

    # 充值点数余额（1 点 = 1 元；允许为负，仅记流水不阻塞主流程）
    credit_balance: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    # 角色：user | admin。admin 才能 mint 兑换码 / 改引擎单价等后台操作。
    role: Mapped[str] = mapped_column(String(20), default="user", nullable=False)


class CodeOrder(Base):
    """点数购买订单 + 可插拔支付渠道。本阶段支付渠道 = manual（人工到账后管理员确认）。"""

    __tablename__ = "code_orders"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    provider: Mapped[str] = mapped_column(String(20), default="manual", nullable=False)  # wechat|alipay|stripe 后续可插拔
    status: Mapped[str] = mapped_column(String(20), default="pending_payment", nullable=False)
    # pending_payment -> paid(已确认收款) -> fulfilled(已发点数)；cancelled 可随时取消
    amount_yuan: Mapped[float] = mapped_column(Float, nullable=False)     # 用户实付（元）
    points: Mapped[float] = mapped_column(Float, nullable=False)          # 拟发放点数（1点=1元）
    payment_ref: Mapped[str] = mapped_column(String(200), default="", nullable=False)  # 用户填的转账备注/单号
    note: Mapped[str] = mapped_column(String(300), default="", nullable=False)          # 运营备注
    redeem_code: Mapped[str] = mapped_column(String(64), default="", nullable=False)    # 核销后 mint 的兑换码（留痕）
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fulfilled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)



# --- 充值点数（增量模块，仅再导出；不改动既有模型） ---
from app.models.credits import CreditLedger, CreditPrice, RedeemCode  # noqa: E402,F401
