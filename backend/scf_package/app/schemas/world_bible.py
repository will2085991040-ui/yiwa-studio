"""WorldBible：WorldAgent 的结构化世界观契约（Step 6）。

输出必须是结构化 Schema（列表 + 嵌套对象），而非普通文本。
"""
from pydantic import BaseModel, Field, model_validator


class Faction(BaseModel):
    """势力 / 阵营（结构化对象，而非自由文本）。"""

    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=1000)
    role: str = Field(default="", max_length=200)


class KeyLocation(BaseModel):
    """关键地点（结构化对象）。"""

    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=1000)


class WorldBible(BaseModel):
    """游戏世界观圣经。"""

    world_id: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=200)
    setting: str = Field(min_length=1, max_length=2000)
    era: str = Field(default="", max_length=120)
    location: str = Field(default="", max_length=300)
    rules: list[str] = Field(default_factory=list)
    social_structure: str = Field(default="", max_length=2000)
    factions: list[Faction] = Field(default_factory=list)
    culture: str = Field(default="", max_length=2000)
    technology: str = Field(default="", max_length=500)
    conflicts: list[str] = Field(default_factory=list)
    key_locations: list[KeyLocation] = Field(default_factory=list)
    world_constraints: list[str] = Field(default_factory=list)
    consistency_notes: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def _check_lists(self) -> "WorldBible":
        """列表不应含空字符串/重复项；factions/key_locations 按 name 去重（jsonschema 无法表达的语义）。"""
        for field, values in (
            ("rules", self.rules),
            ("conflicts", self.conflicts),
            ("world_constraints", self.world_constraints),
        ):
            if any(not v.strip() for v in values):
                raise ValueError(f"{field} 不能包含空字符串")
            if len(values) != len({v.strip() for v in values}):
                raise ValueError(f"{field} 不能存在重复项")
        faction_names = [f.name.strip() for f in self.factions]
        if len(faction_names) != len(set(faction_names)):
            raise ValueError("factions 的 name 不能重复")
        loc_names = [loc.name.strip() for loc in self.key_locations]
        if len(loc_names) != len(set(loc_names)):
            raise ValueError("key_locations 的 name 不能重复")
        return self


def world_bible_json_schema() -> dict:
    """作为 LLMProvider.generate_structured(json_schema=...) 的输入。"""
    return WorldBible.model_json_schema()