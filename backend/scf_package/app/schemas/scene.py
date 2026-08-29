"""Scene Schema（Step 11）：单个 StoryNode 的可编辑场景内容。

Scene ≠ Dialogue：本 Schema 只表达"场景"（地点/时间/氛围/在场角色/事件/镜头/舞台/情绪拍/状态变化），
对白留给 Step 12 DialogueAgent。scene_id 即 StoryGraph 中的 node_id，保持稳定引用，
未来 Runtime 可直接消费（Scene -> Choice -> Condition -> Effect -> Next Node）。
asset_requirements 预留给未来多模态 API（visual_assets/audio_assets/video_assets）。
"""
from typing import Any

from pydantic import BaseModel, Field, model_validator

from app.schemas.story_graph import StoryEffect


class SceneContent(BaseModel):
    """场景卡 Artifact：结构与方向，不含对白。"""

    scene_id: str = Field(min_length=1, max_length=80, description="即 StoryGraph.node_id（稳定引用）")
    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(default="", max_length=1000)
    location: str = Field(default="", max_length=200)
    time: str = Field(default="", max_length=200)
    atmosphere: str = Field(default="", max_length=500)
    characters_present: list[str] = Field(default_factory=list, description="在场角色 character_id 列表")
    events: list[str] = Field(default_factory=list, description="场景事件序列（每幕一段）")
    visual_direction: str = Field(default="", max_length=1000, description="视觉/美术方向")
    camera_direction: str = Field(default="", max_length=500, description="镜头方向")
    stage_direction: str = Field(default="", max_length=1000, description="舞台调度")
    emotional_beats: list[str] = Field(default_factory=list, description="情绪节拍")
    state_changes: list[StoryEffect] = Field(default_factory=list, description="进入/离开场景的状态效果")
    continuity_notes: str = Field(default="", max_length=1000, description="与前后场景的衔接说明")
    asset_requirements: dict[str, Any] = Field(default_factory=dict, description="预留：未来视觉/音频/视频资产需求")

    @model_validator(mode="after")
    def _validate_scene(self) -> "SceneContent":
        if " " in self.scene_id:
            raise ValueError("scene_id 不能包含空格")
        for field in ("characters_present", "events", "emotional_beats"):
            values = [v.strip() for v in getattr(self, field)]
            if any(not v for v in values):
                raise ValueError(f"{field} 不能含空字符串")
            if len(values) != len(set(values)):
                raise ValueError(f"{field} 不能含重复项")
        return self


def scene_json_schema() -> dict:
    return SceneContent.model_json_schema()