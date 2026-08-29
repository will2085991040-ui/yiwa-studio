"""Dialogue Schema（Step 12）：单个 (node_id, choice_id) 的结构化对白内容。

Dialogue != Scene：Scene 表达场景结构（地点/氛围/镜头/情绪节拍，不含对白），本 Schema 只表达"台词"。
最小生产单元是 (node_id, choice_id)：choice_id=None 表示节点默认/开场对白。

- conditions 使用结构化 StoryCondition（声明式，Step13 才求值）
- effects 复用 StoryEffect（含 sub op），Step12 只声明、绝不执行
- dialogue_id / node_id / choice_id 由服务端强制覆写，不信任 LLM 输出
"""
from typing import Any

from pydantic import BaseModel, Field, model_validator

from app.schemas.story_graph import StoryCondition, StoryEffect


class DialogueLine(BaseModel):
    """一条对白台词。speaker 必须引用已有 CharacterCard（引用存在性由服务端校验）。"""

    speaker: str = Field(min_length=1, max_length=80, description="CharacterCard.character_id")
    text: str = Field(min_length=1, max_length=2000, description="台词正文")
    emotion: str = Field(default="", max_length=120, description="情绪标签")
    delivery: str = Field(default="", max_length=200, description="演绎方式/语气")
    action: str = Field(default="", max_length=300, description="动作/舞台指示")
    target: str | None = Field(default=None, max_length=80, description="说话对象 character_id")
    relationship_context: str = Field(default="", max_length=300, description="与说话对象的关系语境")

    @model_validator(mode="after")
    def _validate_line(self) -> "DialogueLine":
        for field in ("speaker", "text"):
            value = (getattr(self, field) or "").strip()
            if not value:
                raise ValueError(f"{field} 不能为空")
            setattr(self, field, value)
        for field in ("emotion", "delivery", "action", "relationship_context"):
            value = getattr(self, field)
            if isinstance(value, str):
                setattr(self, field, value.strip())
        if self.target is not None:
            self.target = self.target.strip()
        return self


class DialogueContent(BaseModel):
    """一个 (node_id, choice_id) 的对白内容 Artifact。"""

    dialogue_id: str = Field(min_length=1, max_length=220, description="服务端生成，不信任模型")
    node_id: str = Field(min_length=1, max_length=80)
    choice_id: str | None = Field(default=None, max_length=80)
    lines: list[DialogueLine] = Field(min_length=1, description="对白列表，至少一条")
    conditions: list[StoryCondition] = Field(default_factory=list, description="触发条件（声明式）")
    effects: list[StoryEffect] = Field(default_factory=list, description="状态效果（声明式，Step13 求值）")
    next_node: str | None = Field(default=None, max_length=80)
    branch: str | None = Field(default=None, max_length=200)
    tags: list[str] = Field(default_factory=list)
    continuity_notes: str = Field(default="", max_length=1000)
    asset_requirements: dict[str, Any] = Field(default_factory=dict, description="预留：未来视觉/音频资产需求")

    @model_validator(mode="after")
    def _validate_content(self) -> "DialogueContent":
        self.dialogue_id = self.dialogue_id.strip()
        self.node_id = self.node_id.strip()
        if not self.dialogue_id:
            raise ValueError("dialogue_id 不能为空")
        if not self.node_id:
            raise ValueError("node_id 不能为空")
        if self.choice_id is not None:
            self.choice_id = self.choice_id.strip()
        # tags 去空去重（对象列表 lines/conditions/effects 不做语义去重）
        cleaned = [t.strip() for t in self.tags]
        if any(not t for t in cleaned):
            raise ValueError("tags 不能含空字符串")
        self.tags = list(dict.fromkeys(cleaned))
        return self


def dialogue_json_schema() -> dict:
    return DialogueContent.model_json_schema()


def dialogue_kind(node_id: str, choice_id: str | None) -> str:
    """Artifact kind：default 对白为 dialogue:{node_id}，choice 对白为 dialogue:{node_id}:{choice_id}。"""
    return f"dialogue:{node_id}" if choice_id is None else f"dialogue:{node_id}:{choice_id}"


def dialogue_id(node_id: str, choice_id: str | None) -> str:
    """DialogueContent 内部稳定 ID：default 用 {node_id}:default，choice 用 {node_id}:{choice_id}。"""
    return f"{node_id}:default" if choice_id is None else f"{node_id}:{choice_id}"