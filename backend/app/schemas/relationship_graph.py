"""RelationshipGraph：角色关系图（Step 9）。

结构化关系边，保留互动游戏所需的「关系状态 -> 玩家选择 -> 效果 -> 新状态 -> 分支」语义：
- affection / trust / hostility 为可被选择改变的状态维度；
- possible_changes 用 StoryEffect（复用 story_graph）表达「玩家帮助 B => affection += 10」；
- secrets / rules / triggers / relationship_arc 供未来 PlotAgent / DialogueAgent / Runtime 消费。
"""
from pydantic import BaseModel, Field, model_validator

from app.schemas.story_graph import StoryEffect


class RelationshipChange(BaseModel):
    """一次可触发的关系变化（未来 Choice/Runtime 求值）。"""

    trigger: str = Field(min_length=1, max_length=500, description="触发事件（如 玩家帮助B）")
    effects: list[StoryEffect] = Field(default_factory=list, description="状态效果（如 affection += 10）")
    resulting_branch: str = Field(default="", max_length=200, description="进入的剧情分支/场景引用（未来）")


class RelationshipEdge(BaseModel):
    """一条有向关系边：source_character -> target_character。"""

    edge_id: str = Field(min_length=1, max_length=80)
    source_character: str = Field(min_length=1, max_length=80)
    target_character: str = Field(min_length=1, max_length=80)
    relationship_type: str = Field(min_length=1, max_length=120, description="如 爱慕/怀疑/敌对/友情")
    initial_value: int = Field(default=0, ge=-100, le=100, description="综合初始关系值")
    affection: int = Field(default=0, ge=-100, le=100)
    trust: int = Field(default=0, ge=-100, le=100)
    hostility: int = Field(default=0, ge=-100, le=100)
    secrets: list[str] = Field(default_factory=list, description="这段关系承载的秘密")
    rules: list[str] = Field(default_factory=list, description="关系行为规则")
    triggers: list[str] = Field(default_factory=list, description="触发关系变化的剧情事件")
    possible_changes: list[RelationshipChange] = Field(default_factory=list)
    relationship_arc: list[str] = Field(default_factory=list, description="关系弧光阶段")


class RelationshipGraph(BaseModel):
    """角色关系图 Artifact：characters（character_id 集合）+ edges。"""

    graph_id: str = Field(min_length=1, max_length=80)
    characters: list[str] = Field(default_factory=list, description="参与关系的 character_id 集合")
    edges: list[RelationshipEdge] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_graph(self) -> "RelationshipGraph":
        chars = self.characters
        if len(chars) != len(set(chars)):
            raise ValueError("characters 不能有重复的 character_id")
        edge_ids = [e.edge_id for e in self.edges]
        if len(edge_ids) != len(set(edge_ids)):
            raise ValueError("edges 的 edge_id 不能重复")
        for e in self.edges:
            if e.source_character == e.target_character:
                raise ValueError(f"edge {e.edge_id} 不能自环")
            if e.source_character not in chars:
                raise ValueError(f"edge {e.edge_id} 的 source_character 不在 characters 内")
            if e.target_character not in chars:
                raise ValueError(f"edge {e.edge_id} 的 target_character 不在 characters 内")
            for field in ("secrets", "rules", "triggers", "relationship_arc"):
                values = [v.strip() for v in getattr(e, field)]
                if any(not v for v in values):
                    raise ValueError(f"edge {e.edge_id} 的 {field} 不能含空字符串")
        return self


def relationship_graph_json_schema() -> dict:
    return RelationshipGraph.model_json_schema()