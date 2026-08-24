"""Story Graph Schema（Step 8，仅 Schema，不实现 Runtime）。

吸收 InkOS 的 Interaction Graph / Story State 思想，为后续 StoryPlot / Choice / Runtime 预留契约：
- StoryNode：剧情节点（scene/choice/ending/branch）
- StoryEdge：节点间迁移边
- StoryVariable：故事状态变量（如好感度）
- StoryEffect：状态/关系变化效果（如 relationship += 10）
- Choice：玩家选择（条件 + 效果 + 下一节点）

当前仅做结构 + Schema 级校验（无环/引用存在/变量去重），未来 Step13 Choice/Runtime Engine 再落地求值引擎。
"""
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.minigame import MinigameConfig

NodeKind = Literal["scene", "choice", "ending", "branch", "merge", "minigame"]
ValueOp = Literal["add", "sub", "set"]
ConditionOp = Literal[">=", "<=", ">", "<", "==", "!="]
VarType = Literal["number", "bool", "string", "enum"]
EndingType = Literal["good", "bad", "neutral", "secret"]
ChoiceWeight = Literal["light", "heavy", "critical"]

ENDING_TYPES: tuple[EndingType, ...] = ("good", "bad", "neutral", "secret")


class StoryVariable(BaseModel):
    """故事状态变量，如 affection / trust / has_clue。"""

    name: str = Field(min_length=1, max_length=80)
    type: VarType = "number"
    initial: Any = 0
    description: str = Field(default="", max_length=300)


class StoryEffect(BaseModel):
    """对状态变量的原子操作（未来运行时求值）。"""

    variable: str = Field(min_length=1, max_length=80)
    op: ValueOp = "add"
    value: Any = 0


class WorldAnchor(BaseModel):
    """世界观锚点（InkOS WorldAnchor）：故事核心 / 主题 / 题材 / 规则 / 时长。"""

    story_core: str = Field(default="", max_length=500)
    theme: str = Field(default="", max_length=200)
    genre: str = Field(default="", max_length=120)
    world_rules: str = Field(default="", max_length=1000)
    duration_minutes: int = Field(default=30, ge=1, le=600)


class StoryEnding(BaseModel):
    """类型化结局（InkOS Ending）：绑定节点 + good/bad/neutral/secret。"""

    ending_id: str = Field(min_length=1, max_length=80)
    node_id: str = Field(min_length=1, max_length=80)
    title: str = Field(default="", max_length=200)
    type: EndingType = "neutral"
    description: str = Field(default="", max_length=600)


class StoryCondition(BaseModel):
    """结构化状态条件（Step 12，声明式）：变量满足 `variable op value` 时成立。

    与 StoryEffect 共享同一变量域。Step 12 仅作为声明式数据存储（供 DialogueContent.conditions
    使用），真正的求值（evaluateCondition）留给 Step13 Story State / Runtime。
    """

    variable: str = Field(min_length=1, max_length=80)
    op: ConditionOp
    value: Any = Field(description="number | bool | str")

    @field_validator("value")
    @classmethod
    def _value_primitive(cls, v: Any) -> Any:
        if isinstance(v, bool | str | int | float):
            return v
        raise ValueError("StoryCondition.value 必须是 number | bool | str")


class Choice(BaseModel):
    """玩家选项：条件满足时可触发效果并迁移到下一节点。"""

    choice_id: str = Field(min_length=1, max_length=80)
    text: str = Field(min_length=1, max_length=500)
    condition: str | None = Field(default=None, max_length=500)   # 未来求值的条件表达式
    effects: list[StoryEffect] = Field(default_factory=list)
    next_node: str | None = Field(default=None, max_length=80)    # 指向 StoryNode.node_id
    weight: ChoiceWeight | None = Field(default=None, description="light/heavy/critical")
    # 互动影视：该选项在节点分镜视频的哪一秒「弹层显示」供玩家选择（None = 视频播完后再显示）。
    # 该字段仅供可视化编辑/运行时使用，缺省不影响既有图与写入（向前兼容）。
    video_at_sec: float | None = Field(default=None, ge=0, le=600, description="选项在视频中第几秒弹出（秒）")


class StoryNode(BaseModel):
    """剧情节点：场景 / 选择点 / 结局 / 分支。"""

    node_id: str = Field(min_length=1, max_length=80)
    kind: NodeKind = "scene"
    title: str = Field(default="", max_length=200)
    content_ref: str | None = Field(default=None, max_length=80)  # 指向 scene/dialogue artifact 引用（未来）
    summary: str = Field(default="", max_length=500)             # 剧情级摘要（结构，不含完整对白/正文）
    entry_conditions: list[str] = Field(default_factory=list)     # 进入条件表达式（未来求值）
    on_enter: list[StoryEffect] = Field(default_factory=list)     # 进入节点触发的状态效果
    choices: list[Choice] = Field(default_factory=list)
    minigame: MinigameConfig | None = Field(default=None, description="kind=minigame 时的小游戏配置")
    locked: bool = Field(default=False, description="用户锁定：后续 Agent 不得修改/删除该节点")
    position: dict[str, float] | None = Field(default=None, description="画布坐标 {x,y}（持久化）")


class StoryEdge(BaseModel):
    """节点间迁移边（显式图，供可视化工作流）。"""

    edge_id: str = Field(min_length=1, max_length=80)
    source: str = Field(min_length=1, max_length=80)
    target: str = Field(min_length=1, max_length=80)
    label: str = Field(default="", max_length=200)
    condition: str | None = Field(default=None, max_length=500)


class StoryGraph(BaseModel):
    """互动剧情图：节点 + 边 + 状态变量（Story State）。"""

    graph_id: str = Field(min_length=1, max_length=80)
    nodes: list[StoryNode] = Field(default_factory=list)
    edges: list[StoryEdge] = Field(default_factory=list)
    variables: list[StoryVariable] = Field(default_factory=list)
    endings: list[StoryEnding] = Field(default_factory=list)
    world_anchor: WorldAnchor | None = Field(default=None)
    entry_node_id: str | None = Field(default=None, max_length=80)
    metadata: dict[str, Any] = Field(default_factory=dict, description="章节数/结局数/版本元信息等")

    @model_validator(mode="after")
    def _validate_graph(self) -> "StoryGraph":
        node_ids = [n.node_id for n in self.nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("nodes 的 node_id 不能重复")
        for n in self.nodes:
            for c in n.choices:
                if c.next_node is not None and c.next_node not in node_ids:
                    raise ValueError(f"choice {c.choice_id} 的 next_node 指向不存在的节点")
        known = set(node_ids)
        for e in self.edges:
            if e.source not in known:
                raise ValueError(f"edge {e.edge_id} 的 source 不存在")
            if e.target not in known:
                raise ValueError(f"edge {e.edge_id} 的 target 不存在")
        var_names = [v.name for v in self.variables]
        if len(var_names) != len(set(var_names)):
            raise ValueError("variables 的 name 不能重复")
        for e in self.endings:
            if e.node_id not in known:
                raise ValueError(f"ending {e.ending_id} 的 node_id 不存在")
        if self.entry_node_id is not None and self.entry_node_id not in known:
            raise ValueError("entry_node_id 必须指向存在的节点")
        return self


def sync_node_positions(graph: "StoryGraph", positions: dict[str, dict[str, float]]) -> "StoryGraph":
    """把前端画布坐标写回 graph.nodes[].position（不改变其他字段）。"""
    nodes = [
        n if n.node_id not in positions else n.model_copy(update={"position": positions[n.node_id]})
        for n in graph.nodes
    ]
    return graph.model_copy(update={"nodes": nodes})


def story_graph_json_schema() -> dict:
    return StoryGraph.model_json_schema()