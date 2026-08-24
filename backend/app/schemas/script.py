# -*- coding: utf-8 -*-
"""互动剧本 Schema（一键生成剧本 API 使用）。

产物：一部完整互动剧本（立即可用于拍摄/配音的「分场剧本+对白」）。
结构：Scene 含多条 Beat（一条 Beat = 一个镜头/对白单元），并附角色表与结构元信息。
由 app/services/script_writer.py 调和（generate_structured + 落库 Artifact kind="script"）。
"""
from typing import Any, Literal

from pydantic import BaseModel, Field


class ScriptCharacter(BaseModel):
    character_id: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=60)
    role: str = Field(default="", max_length=80)
    personality: str = Field(default="", max_length=300)


class ScriptBeat(BaseModel):
    """一条镜头/对白：时间点、说话人、台词与表演提示。"""

    beat_id: str = Field(min_length=1, max_length=40)
    speaker: str = Field(default="", max_length=60)     # 空=旁白/动作描述
    line: str = Field(default="", max_length=600)       # 台词
    direction: str = Field(default="", max_length=300)  # 表演/运镜/音效提示
    emotion: str = Field(default="", max_length=40)


class ScriptScene(BaseModel):
    scene_id: str = Field(min_length=1, max_length=40)
    title: str = Field(default="", max_length=120)
    location: str = Field(default="", max_length=120)
    time_of_day: str = Field(default="", max_length=40)
    summary: str = Field(default="", max_length=400)
    beats: list[ScriptBeat] = Field(default_factory=list)


class ScriptAct(BaseModel):
    act: int = Field(ge=1, le=20)
    title: str = Field(default="", max_length=120)
    scenes: list[ScriptScene] = Field(default_factory=list)


class Script(BaseModel):
    title: str = Field(default="", max_length=120)
    genre: str = Field(default="", max_length=60)
    logline: str = Field(default="", max_length=400)
    synopsis: str = Field(default="", max_length=1200)
    characters: list[ScriptCharacter] = Field(default_factory=list)
    acts: list[ScriptAct] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


def script_json_schema() -> dict:
    return Script.model_json_schema()
