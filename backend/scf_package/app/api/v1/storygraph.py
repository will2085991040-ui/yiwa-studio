"""API：互动剧本节点画布（增量：Funloom 蒸馏 · Phase 1）。

提供可视化编辑器所需的读写与诊断端点。读写目标与 Runtime 一致：
把 StoryGraph（Artifact kind="story_graph"）作为唯一权威数据，新增编辑保存走
`persist_versioned_artifact` 的 Git 式版本链，不覆盖历史、不破坏 Runtime 求值。
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.db.base import get_session
from app.models import Project
from app.schemas.story_graph import StoryGraph
from app.services.artifacts import latest_artifact, persist_versioned_artifact

router = APIRouter(prefix="/api/projects")

_EDITOR_AGENT = "storygraph_editor"
_EDITOR_TASK = "storygraph_editor"


class StoryGraphSaveInput(BaseModel):
    """保存请求：完整 StoryGraph + 可选修改说明。"""

    graph: StoryGraph
    change_reason: str | None = None


def _require_project(session: Session, project_id: str) -> None:
    if session.get(Project, project_id) is None:
        raise NotFoundError("项目不存在")


def _empty_graph(project_id: str) -> dict:
    return {
        "graph_id": f"story-{project_id}",
        "nodes": [],
        "edges": [],
        "variables": [],
        "entry_node_id": None,
        "metadata": {},
    }


def _reachable(graph: StoryGraph) -> set[str]:
    """BFS：入口沿边 + 选项 next_node 可达的节点集合。"""
    entry = graph.entry_node_id
    if not entry:
        return set()
    by_id = {n.node_id: n for n in graph.nodes}
    seen: set[str] = set()
    stack = [entry]
    while stack:
        node_id = stack.pop()
        if node_id in seen or node_id not in by_id:
            continue
        seen.add(node_id)
        node = by_id[node_id]
        for c in node.choices:
            if c.next_node:
                stack.append(c.next_node)
        for e in graph.edges:
            if e.source == node_id:
                stack.append(e.target)
    return seen


def diagnose(graph: StoryGraph) -> dict:
    """Funloom 式「校验闭环」：错误（阻断试玩）＋ 警告（建议整理）。"""
    errors: list[str] = []
    warnings: list[str] = []
    node_ids = {n.node_id for n in graph.nodes}
    endings = [n for n in graph.nodes if n.kind == "ending"]
    entry = graph.entry_node_id

    if not entry:
        errors.append("未设置入口节点（entry_node_id）")
    elif entry not in node_ids:
        errors.append(f"入口节点 {entry} 不存在")
    else:
        reachable = _reachable(graph)
        unreachable = sorted(node_ids - reachable)
        if unreachable:
            warnings.append(f"存在 {len(unreachable)} 个从入口不可达的节点：{', '.join(unreachable)}")
        if endings and not (reachable & {n.node_id for n in endings}):
            warnings.append("没有任何结局节点从入口可达，可能无法正常通关")

    for n in graph.nodes:
        for c in n.choices:
            if c.next_node is not None and c.next_node not in node_ids:
                errors.append(f"节点 {n.node_id} 的选项 {c.choice_id} 指向不存在的 {c.next_node}")
            if c.next_node is None and n.kind == "scene":
                warnings.append(f"场景节点 {n.node_id} 的选项 {c.choice_id} 未设置去向")
    for e in graph.edges:
        if e.source not in node_ids or e.target not in node_ids:
            errors.append(f"边 {e.edge_id} 端点不存在")
    for n in graph.nodes:
        if n.kind == "scene" and not n.choices:
            outgoing = {e.source for e in graph.edges}
            if n.node_id not in outgoing:
                warnings.append(f"场景节点 {n.node_id} 没有选项也没有出边（死路）")

    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "counts": {
            "nodes": len(graph.nodes),
            "edges": len(graph.edges),
            "endings": len(endings),
            "variables": len(graph.variables),
        },
    }


@router.get("/{project_id}/storygraph")
def get_storygraph(project_id: str, session: Session = Depends(get_session)) -> dict:
    """返回当前 StoryGraph（无则返回空图）。"""
    _require_project(session, project_id)
    artifact = latest_artifact(session, project_id, kind="story_graph")
    if artifact is None:
        return {"version": 0, "graph": _empty_graph(project_id), "change_reason": None}
    return {
        "version": artifact.version,
        "graph": artifact.content or {},
        "change_reason": artifact.change_reason,
    }


@router.put("/{project_id}/storygraph")
def put_storygraph(
    project_id: str, payload: StoryGraphSaveInput, session: Session = Depends(get_session)
) -> dict:
    """保存（追加版本）StoryGraph。source=user，走既有 versioned artifact 链。"""
    _require_project(session, project_id)
    # 保留 condition: None 等默认字段：Runtime 的 RuntimeChoiceOut 要求 condition 字段存在。
    content = payload.graph.model_dump()
    artifact = persist_versioned_artifact(
        session,
        project_id=project_id,
        task_id=_EDITOR_TASK,
        agent=_EDITOR_AGENT,
        kind="story_graph",
        content=content,
        prompt_version="",
        source="user",
        change_reason=payload.change_reason,
    )
    session.commit()
    return {"version": artifact.version, "graph": artifact.content, "change_reason": artifact.change_reason}


@router.post("/{project_id}/storygraph/validate")
def validate_storygraph(project_id: str, payload: StoryGraphSaveInput, session: Session = Depends(get_session)) -> dict:
    """不落库的校验：返回错误/警告/计数，供画布「校验」按钮使用。"""
    _require_project(session, project_id)
    return diagnose(payload.graph)


@router.get("/{project_id}/storygraph/check")
def check_storygraph(project_id: str, session: Session = Depends(get_session)) -> dict:
    """Funloom 式「质检」：对已保存的 StoryGraph 做校验闭环（错误/警告/计数），无需落库。"""
    _require_project(session, project_id)
    artifact = latest_artifact(session, project_id, kind="story_graph")
    if artifact is None or not (artifact.content or {}).get("nodes"):
        return {
            "version": 0, "ok": False, "errors": ["尚未生成剧情图（先点「一键生成」）"],
            "warnings": [], "counts": {"nodes": 0, "edges": 0, "endings": 0, "variables": 0},
        }
    graph = StoryGraph.model_validate(artifact.content)
    result = diagnose(graph)
    result["version"] = artifact.version
    return result


@router.get("/{project_id}/storygraph/versions")
def storygraph_versions(project_id: str, session: Session = Depends(get_session)) -> list[dict]:
    """故事图历史版本（version / change_reason），供回看对比。"""
    _require_project(session, project_id)
    from app.models import Artifact

    rows = (
        session.query(Artifact)
        .filter(Artifact.project_id == project_id, Artifact.kind == "story_graph")
        .order_by(Artifact.version)
        .all()
    )
    return [
        {
            "version": a.version,
            "change_reason": a.change_reason,
            "source": a.source,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }
        for a in rows
    ]