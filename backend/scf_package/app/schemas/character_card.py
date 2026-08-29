"""CharacterCard：结构化的互动角色卡（Step 7）。

设计目标：
- 服务未来 Galgame/互动影视，而非聊天机器人；
- DialogueAgent 直接读取 speech_style / personality / likes / dislikes / secret；
- RelationshipAgent 直接读取 relationship_rules / motivation / goal / conflict；
- 列表/对象字段结构化（非自由文本），便于后续 Interaction Graph 与 Story State 扩展。
"""
from pydantic import BaseModel, Field, field_validator, model_validator


class SpeechStyle(BaseModel):
    """对白风格：DialogueAgent 生成对白时的硬约束。"""

    tone: str = Field(default="", max_length=200, description="语气基调（如 克制温柔 / 玩世不恭）")
    formality: str = Field(default="", max_length=120, description="正式程度（如 偏礼貌 / 随意）")
    catchphrases: list[str] = Field(default_factory=list, description="口头禅")
    quirks: list[str] = Field(default_factory=list, description="语言小习惯/口癖")


class CharacterCard(BaseModel):
    # 基础信息
    character_id: str = Field(min_length=1, max_length=80, description="角色唯一标识（如 char-01）")
    name: str = Field(min_length=1, max_length=120, description="角色名")
    role: str = Field(min_length=1, max_length=200, description="剧情角色定位（如 女主 / 男主A·顶流演员）")
    age: str = Field(default="", max_length=40, description="年龄（可含 约/未知）")
    gender: str = Field(default="", max_length=40, description="性别")
    appearance: str = Field(default="", max_length=1000, description="外貌特征")

    # 人物核心
    personality: list[str] = Field(default_factory=list, description="性格标签（结构化列表）")
    background: str = Field(default="", max_length=3000, description="背景故事")
    motivation: str = Field(default="", max_length=1000, description="行为动机")
    goal: str = Field(default="", max_length=1000, description="目标")
    conflict: str = Field(default="", max_length=1000, description="内心/外部冲突")
    fear: str = Field(default="", max_length=1000, description="恐惧")
    secret: str = Field(default="", max_length=1000, description="秘密")

    # 互动游戏相关
    relationship_rules: list[str] = Field(
        default_factory=list, description="与他人的关系行为规则（供 RelationshipAgent）"
    )
    speech_style: SpeechStyle = Field(default_factory=SpeechStyle, description="对白风格")
    likes: list[str] = Field(default_factory=list, description="喜好")
    dislikes: list[str] = Field(default_factory=list, description="厌恶")
    hidden_information: list[str] = Field(default_factory=list, description="仅特定条件向玩家揭示的信息")
    character_arc: list[str] = Field(default_factory=list, description="角色弧光阶段")
    possible_endings: list[str] = Field(default_factory=list, description="该角色可达成的结局")

    @field_validator("character_id")
    @classmethod
    def _id_no_whitespace(cls, v: str) -> str:
        v = v.strip()
        if not v or any(ch.isspace() for ch in v):
            raise ValueError("character_id 不能为空且不能含空白字符")
        return v

    @model_validator(mode="after")
    def _check_lists(self):
        list_fields = [
            "personality", "relationship_rules", "likes", "dislikes",
            "hidden_information", "character_arc", "possible_endings",
        ]
        for field in list_fields:
            values = getattr(self, field)
            cleaned = [v.strip() for v in values]
            if any(not v for v in cleaned):
                raise ValueError(f"{field} 不能包含空字符串")
            if len(cleaned) != len(set(cleaned)):
                raise ValueError(f"{field} 不能包含重复项")
            setattr(self, field, cleaned)
        for field in ("catchphrases", "quirks"):
            values = getattr(self.speech_style, field)
            cleaned = [v.strip() for v in values]
            if any(not v for v in cleaned):
                raise ValueError(f"speech_style.{field} 不能包含空字符串")
            if len(cleaned) != len(set(cleaned)):
                raise ValueError(f"speech_style.{field} 不能包含重复项")
            setattr(self.speech_style, field, cleaned)
        return self


def character_card_json_schema() -> dict:
    return CharacterCard.model_json_schema()