"""API：角色关系图 + 小游戏生成器（增量）。

- 角色关系图：`relationship_graph` Artifact 的读写、AI 一键生成（确定性启发式）、
  基于关系的快速新增角色。
- 小游戏生成器：给定 (game_type, style, prompt) 确定性产出一份小游戏配置，
  以 `minigame:{game_id}` 落 artifact 版本链；支持按节点 `minigame:{node_id}`
  关联进剧情节点供运行时渲染。
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.errors import AppError, NotFoundError
from app.db.base import get_session
from app.models import Artifact, Project
from app.schemas.character_card import CharacterCard
from app.schemas.relationship_graph import RelationshipGraph
from app.services.artifacts import latest_artifact, persist_versioned_artifact
from app.services.manual_edit import edit_artifact_content

router = APIRouter(prefix="/api/projects")

_RELATION_KIND = "relationship_graph"

# 关系类型启发式：按角色 role/description 文本关键字映射到中文关系标签
_RELATION_HINTS: list[tuple[tuple[str, ...], str]] = [
    (("恋人", "情侣", "爱人", "夫妻", "未婚夫", "未婚妻", "老公", "老婆", "男友", "女友"), "恋人/爱人"),
    (("暗恋", "倾慕"), "爱慕"),
    (("宿敌", "敌人", "反派", "仇人", "仇敌"), "敌对"),
    (("死敌", "决裂", "仇恨", "恨之"), "仇恨"),
    (("挚友", "队友", "同伴", "搭档", "伙伴", "战友", "知己"), "友情/羁绊"),
    (("朋友", "好友", "同学", "同门"), "朋友"),
    (("师父", "师傅", "导师", "老师"), "师徒"),
    (("弟子", "学生", "徒弟", "学徒", "徒儿"), "师徒"),
    (("父亲", "母亲", "哥哥", "姐姐", "弟弟", "妹妹", "家人", "家人甲乙"), "亲情"),
    (("部下", "手下", "下属", "雇员", "人质"), "主从"),
    (("上司", "上级", "老板", "领导"), "上下级"),
    (("崇拜", "追随", "信仰", "偶像"), "崇拜"),
    (("怀疑", "猜忌"), "怀疑"),
]


def _require_project(session: Session, project_id: str) -> None:
    if session.get(Project, project_id) is None:
        raise NotFoundError("项目不存在")


def _default_graph(project_id: str) -> dict:
    return {"graph_id": f"rel-{project_id}", "characters": [], "edges": []}


def _read_graph(session: Session, project_id: str) -> dict:
    """读取最新 relationship_graph artifact；无则返回默认空图。"""
    artifact = latest_artifact(session, project_id, kind=_RELATION_KIND)
    if artifact is None or not artifact.content:
        return _default_graph(project_id)
    graph = RelationshipGraph.model_validate(artifact.content or {})
    return graph.model_dump()


def _characters(session: Session, project_id: str) -> list[dict]:
    """与 GET /api/projects/{pid}/characters 同源：读取该项目最新角色卡。"""
    rows = (
        session.query(Artifact)
        .filter(
            Artifact.project_id == project_id,
            Artifact.kind.startswith("character_card"),
            Artifact.is_latest.is_(True),
        )
        .order_by(Artifact.created_at)
        .all()
    )
    seen: dict[str, dict] = {}
    for a in rows:
        content = a.content or {}
        cid = content.get("character_id") or ""
        if not cid:
            continue
        seen[cid] = {
            "character_id": cid,
            "name": content.get("name") or "未命名角色",
            "role": content.get("role") or "",
            "description": (content.get("background") or content.get("appearance") or ""),
        }
    return list(seen.values())


def _infer_relationship(src: dict, tgt: dict) -> str:
    """按 source/target 的 role + description 文本确定性推断关系类型。"""
    text = " ".join(
        [str(src.get("role") or ""), str(src.get("description") or ""),
         str(tgt.get("role") or ""), str(tgt.get("description") or "")]
    )
    for keywords, label in _RELATION_HINTS:
        if any(k in text for k in keywords):
            return label
    return "相识"


def _next_character_id(session: Session, project_id: str) -> str:
    rows = (
        session.query(Artifact)
        .filter(Artifact.project_id == project_id, Artifact.kind.startswith("character_card"))
        .all()
    )
    used: set[str] = set()
    for a in rows:
        cid = (a.content or {}).get("character_id")
        if cid:
            used.add(cid)
    n = 1
    while f"char-{n}" in used:
        n += 1
    return f"char-{n}"


class RelationSaveInput(BaseModel):
    graph_id: str = ""
    characters: list[str] = Field(default_factory=list)
    edges: list[dict] = Field(default_factory=list)


class NewCharacterInput(BaseModel):
    name: str = ""
    role: str = ""
    description: str = ""
    appearance: str = ""
    # 从这些 source_character 指向新角色的（src + relationship_type）
    relations: list[dict] = Field(default_factory=list)


def _edge_id(src: str, tgt: str, seen: set[str]) -> str:
    base = f"rel-{src}->{tgt}"
    eid = base
    n = 1
    while eid in seen:
        n += 1
        eid = f"{base}-{n}"
    seen.add(eid)
    return eid


@router.get("/{project_id}/relations")
def get_relations(project_id: str, session: Session = Depends(get_session)) -> dict:
    _require_project(session, project_id)
    return _read_graph(session, project_id)


@router.post("/{project_id}/relations")
def save_relations(project_id: str, payload: RelationSaveInput, session: Session = Depends(get_session)) -> dict:
    _require_project(session, project_id)
    content = payload.model_dump()
    edit_artifact_content(session, project_id, kind=_RELATION_KIND, content=content, change_reason="关系编辑")
    return _read_graph(session, project_id)


@router.post("/{project_id}/relations/generate")
def generate_relations(project_id: str, session: Session = Depends(get_session)) -> dict:
    """AI 一键生成：为项目全部角色两两建边（确定性启发式关系类型）。"""
    _require_project(session, project_id)
    chars = _characters(session, project_id)
    if not chars:
        raise AppError("该项目还没有任何角色，请先创建角色卡再生成关系图", code="no_characters", status=400)

    char_ids = [c["character_id"] for c in chars]
    seen: set[str] = set()
    edges: list[dict] = []
    for i in range(len(chars)):
        for j in range(len(chars)):
            if i == j:
                continue
            src = chars[i]
            tgt = chars[j]
            etype = _infer_relationship(src, tgt)
            edges.append({
                "edge_id": _edge_id(src["character_id"], tgt["character_id"], seen),
                "source_character": src["character_id"],
                "target_character": tgt["character_id"],
                "relationship_type": etype,
                "initial_value": 0,
                "affection": 0,
                "trust": 0,
                "hostility": 0,
                "secrets": [],
                "rules": [],
                "triggers": [],
                "possible_changes": [],
                "relationship_arc": [],
            })

    graph = {
        "graph_id": f"rel-{project_id}",
        "characters": char_ids,
        "edges": edges,
    }
    # 先校验再落库
    RelationshipGraph.model_validate(graph)
    persist_versioned_artifact(
        session, project_id=project_id, task_id="relations-generate", agent="relationship_ai",
        kind=_RELATION_KIND, content=graph, prompt_version="",
        source="agent", change_reason="AI 一键生成关系图",
    )
    session.commit()
    return _read_graph(session, project_id)


@router.post("/{project_id}/relations/new-character")
def new_character_from_relation(
    project_id: str, payload: NewCharacterInput, session: Session = Depends(get_session)
) -> dict:
    """基于关系新建角色：落一张角色卡，并把传入的关系源指向新角色的边写进关系图。"""
    _require_project(session, project_id)

    cid = _next_character_id(session, project_id)
    card = CharacterCard(
        character_id=cid,
        name=(payload.name or "").strip() or "新角色",
        role=(payload.role or "").strip() or "角色",
        appearance=(payload.appearance or "").strip(),
        background=(payload.description or "").strip(),
    )
    persist_versioned_artifact(
        session, project_id=project_id, task_id=f"manual-{cid}", agent="user_editor",
        kind=f"character_card:{cid}", content=card.model_dump(), prompt_version="",
        source="user", change_reason="基于关系新增角色",
    )

    chars = _characters(session, project_id)
    char_ids = [c["character_id"] for c in chars]
    if cid not in char_ids:
        char_ids.append(cid)

    graph_dict = _read_graph(session, project_id)
    edges = graph_dict.get("edges", [])
    used_ids = {e["edge_id"] for e in edges}
    for rel in payload.relations:
        src = (rel or {}).get("source_character") or ""
        rtype = (rel or {}).get("relationship_type") or "相识"
        if not src or src not in char_ids:
            continue
        edges.append({
            "edge_id": _edge_id(src, cid, used_ids),
            "source_character": src,
            "target_character": cid,
            "relationship_type": rtype,
            "initial_value": 0, "affection": 0, "trust": 0, "hostility": 0,
            "secrets": [], "rules": [], "triggers": [],
            "possible_changes": [], "relationship_arc": [],
        })

    graph = {"graph_id": f"rel-{project_id}", "characters": char_ids, "edges": edges}
    RelationshipGraph.model_validate(graph)
    persist_versioned_artifact(
        session, project_id=project_id, task_id=f"rel-{project_id}",
        kind=_RELATION_KIND, content=graph, prompt_version="", agent="user_editor",
        source="user", change_reason="新增角色（基于关系）",
    )
    session.commit()
    return {
        "character": {"character_id": cid, "name": card.name, "role": card.role},
        "graph": _read_graph(session, project_id),
    }


# ---- 小游戏生成器 ----

class MinigameGenerateInput(BaseModel):
    game_type: str = "click"
    style: str = ""
    prompt: str = ""


class MinigameInsertInput(BaseModel):
    node_id: str = Field(min_length=1, max_length=120)


GAME_META: dict[str, dict] = {
    "click": {"label": "连点挑战", "emoji": "🖱️", "success_result": "success",
              "settings": {"target": 8, "time_limit_s": 8}},
    "memory": {"label": "记忆配对", "emoji": "🧠", "success_result": "success",
               "settings": {"grid": 8, "time_limit_s": 30}},
    "choose": {"label": "二选一抉择", "emoji": "⚖️", "success_result": "success",
               "settings": {"time_limit_s": 10}},
    "typing": {"label": "打字闯关", "emoji": "⌨️", "success_result": "success",
               "settings": {"target": 5, "time_limit_s": 30}},
    "guess": {"label": "猜图/猜词", "emoji": "🔍", "success_result": "success",
              "settings": {"rounds": 3, "time_limit_s": 15}},
    "quiz": {"label": "知识问答", "emoji": "📚", "success_result": "success",
             "settings": {"questions": 3, "time_limit_s": 15}},
    "dialogue": {"label": "嘴上对白选择", "emoji": "💬", "success_result": "success",
                 "settings": {"time_limit_s": 10}},
    "timer": {"label": "限时决策", "emoji": "⏱️", "success_result": "success",
              "settings": {"time_limit_s": 10}},
    "story": {"label": "剧情掷骰分支", "emoji": "🎲", "success_result": "success",
              "settings": {"sides": 6}},
    "score": {"label": "计分挑战", "emoji": "🏆", "success_result": "perfect",
              "settings": {"target": 100, "time_limit_s": 30}},
}

GAME_TYPES = list(GAME_META.keys())


def _build_minigame_config(game_type: str, style: str, prompt: str) -> dict:
    meta = GAME_META[game_type]
    clean_title = (prompt or "").strip()
    title = clean_title[:40] if clean_title else meta["label"]
    desc_parts = []
    if style:
        desc_parts.append(f"画风：{style}")
    if clean_title:
        desc_parts.append(clean_title)
    desc_parts.append(meta["label"])
    settings = dict(meta["settings"])
    if style:
        settings["style"] = style
    return {
        "game_id": game_type,
        "title": title,
        "description": "；".join(desc_parts),
        "success_result": meta["success_result"],
        "score_variable": "score" if game_type in ("click", "memory", "typing", "score") else None,
        "settings": settings,
    }


@router.post("/{project_id}/minigames")
def generate_minigame(project_id: str, payload: MinigameGenerateInput, session: Session = Depends(get_session)) -> dict:
    _require_project(session, project_id)
    game_type = (payload.game_type or "").strip()
    if game_type not in GAME_META:
        raise AppError(
            f"未知的小游戏类型 {game_type!r}，可选：{', '.join(GAME_TYPES)}",
            code="unknown_game_type", status=400,
        )
    config = _build_minigame_config(game_type, (payload.style or "").strip(), (payload.prompt or "").strip())
    game_id = f"minigame-{game_type}"
    persist_versioned_artifact(
        session, project_id=project_id, task_id=game_id, agent="minigame_editor",
        kind=f"minigame:{game_type}", content=config, prompt_version="",
        source="agent", change_reason="AI 小游戏生成",
    )
    session.commit()
    return {
        "game_id": game_type,
        "config": config,
        "prompt": (payload.prompt or "").strip(),
        "style": (payload.style or "").strip(),
    }


@router.get("/{project_id}/minigames")
def list_minigames(project_id: str, session: Session = Depends(get_session)) -> list[dict]:
    _require_project(session, project_id)
    rows = (
        session.query(Artifact)
        .filter(
            Artifact.project_id == project_id,
            Artifact.kind.like("minigame:%"),
            Artifact.is_latest.is_(True),
        )
        .order_by(Artifact.created_at.desc())
        .all()
    )
    latest: dict[str, dict] = {}
    for a in rows:
        gid = a.kind.split(":", 1)[1]
        if gid in latest:
            continue
        latest[gid] = {
            "game_id": gid,
            "config": a.content or {},
            "kind": a.kind,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }
    return list(latest.values())


@router.post("/{project_id}/minigames/{mid}/insert")
def insert_minigame(
    project_id: str, mid: str, payload: MinigameInsertInput, session: Session = Depends(get_session)
) -> dict:
    """把已生成的小游戏配置关联到剧情节点 node_id（落 `minigame:{node_id}` artifact）。"""
    _require_project(session, project_id)
    node_id = (payload.node_id or "").strip()
    if not node_id:
        raise AppError("缺少 node_id", code="node_id_required", status=400)

    source = latest_artifact(session, project_id, kind=f"minigame:{mid}")
    if source is None:
        raise AppError(f"小游戏 {mid} 不存在，请先生成", code="minigame_not_found", status=404)
    config = source.content or {}

    persist_versioned_artifact(
        session, project_id=project_id, task_id=f"minigame-node-{node_id}", agent="minigame_editor",
        kind=f"minigame:{node_id}", content=config, prompt_version="",
        source="agent", change_reason=f"插入剧情节点 {node_id}",
    )
    session.commit()
    return {"ok": True, "node_id": node_id, "kind": f"minigame:{node_id}", "config": config}