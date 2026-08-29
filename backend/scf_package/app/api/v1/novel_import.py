"""API：小说导入 → 拆解剧本 → 角色卡 → 人物关系 → 串联互动图（增量创作闭环入口）。

干净移植 Funloom「导入小说开始创作」的结构：输入原文，产出可立刻在剧情画布/试玩/导出里使用的
StoryGraph，并落库角色卡与人物关系，角色卡可继续进角色立绘生成差分。
"""
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.base import get_session
from app.models import Artifact
from app.schemas.character_card import CharacterCard
from app.schemas.relationship_graph import RelationshipEdge, RelationshipGraph
from app.services.artifacts import persist_versioned_artifact
from app.services.director_service import create_project_via_director
from app.services.novel_import import GAME_TYPE_LABELS, breakdown_novel

router = APIRouter(prefix="/api/novel")

GameType = Literal["galgame", "avg", "interactive_film"]


class NovelImportInput(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=50, max_length=200000, description="小说/剧本原文（txt 或纯文本）")
    game_type: GameType = "avg"


class CharacterOut(BaseModel):
    character_id: str
    name: str
    role: str
    description: str


class NovelImportOut(BaseModel):
    project_id: str
    title: str
    game_type: GameType
    game_type_label: str
    scene_count: int
    characters: list[CharacterOut]
    relationship_count: int


@router.post("/import", response_model=NovelImportOut, status_code=201)
async def import_novel(payload: NovelImportInput, session: Session = Depends(get_session)) -> dict:
    """导入原文并一次完成：建项目（保留多 Agent 流水线）+ 拆剧本 + 角色卡 + 关系 + 串联互动图。"""
    goal = (
        f"创作一部{GAME_TYPE_LABELS[payload.game_type]}《{payload.title}》，"
        "拆解导入文本并生成角色与人物关系，串联成可试玩的互动作品"
    )
    created = await create_project_via_director(
        session, goal, game_type=payload.game_type, title=payload.title,
    )
    project_id = created["project_id"]

    breakdown = breakdown_novel(payload.text, payload.game_type, payload.title)

    # 1) 原文 + 拆解场景（可回溯的版本化 Artifact）
    persist_versioned_artifact(
        session, project_id=project_id, task_id="novel_import", agent="novel_import",
        kind="novel:source", content={"title": payload.title, "text": payload.text, "game_type": payload.game_type},
        prompt_version="",
    )
    persist_versioned_artifact(
        session, project_id=project_id, task_id="novel_import", agent="novel_import",
        kind="novel:scenes", content={"scenes": breakdown["scenes"]}, prompt_version="",
    )

    # 2) 角色卡（每个角色一张，供角色选择器/立绘生成复用）
    cards = [
        CharacterCard(
            character_id=f"char-{index:02d}",
            name=c["name"],
            role=c["role"],
            appearance=c.get("description", ""),
            background=c.get("description", ""),
            likes=[],
            dislikes=[],
        )
        for index, c in enumerate(breakdown["characters"])
    ]
    for index, card in enumerate(cards):
        session.add(Artifact(
            project_id=project_id, task_id=f"character:{index}", agent="novel_import",
            kind=f"character_card:{card.character_id}", content=card.model_dump(), prompt_version="",
            version=1, parent_version=None, source="agent", is_latest=True,
        ))
    persist_versioned_artifact(
        session, project_id=project_id, task_id="novel_import", agent="novel_import",
        kind="character_roster",
        content={"characters": [c.model_dump() for c in cards]},
        prompt_version="",
    )

    # 3) 人物关系图（复用 RelationshipGraph Schema，供后续 Plot/Dialogue/Runtime 消费）
    id_by_name = {c["name"]: f"char-{i:02d}" for i, c in enumerate(breakdown["characters"])}
    edges = [
        RelationshipEdge(
            edge_id=f"rel-{i:02d}",
            source_character=id_by_name[r["source"]],
            target_character=id_by_name[r["target"]],
            relationship_type=r["kind"],
            affection=+10,
            triggers=[r["description"]],
        )
        for i, r in enumerate(breakdown["relationships"])
        if r["source"] in id_by_name and r["target"] in id_by_name
    ]
    rel_graph = RelationshipGraph(
        graph_id="novel",
        characters=[id_by_name[c["name"]] for c in breakdown["characters"]],
        edges=edges,
    )
    persist_versioned_artifact(
        session, project_id=project_id, task_id="relationship", agent="novel_import",
        kind="relationship_graph", content=rel_graph.model_dump(), prompt_version="",
    )

    # 4) 串联互动图：让剧情画布 / 试玩 / 导出立即可用
    persist_versioned_artifact(
        session, project_id=project_id, task_id="compiler", agent="novel_import",
        kind="story_graph", content=breakdown["story_graph"], prompt_version="",
        change_reason="由小说导入自动串联",
    )

    session.commit()
    return {
        "project_id": project_id,
        "title": payload.title,
        "game_type": payload.game_type,
        "game_type_label": breakdown["game_type_label"],
        "scene_count": breakdown["scene_count"],
        "characters": [
            {"character_id": c.character_id, "name": c.name, "role": c.role, "description": c.appearance}
            for c in cards
        ],
        "relationship_count": len(edges),
    }