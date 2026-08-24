"""Story 局部操作（Step 10）：延长剧情 + 增加分支。

这是「用户控制权」落地的结构操作——它们是确定性的图算法，而不是 LLM 生成：
- extend_story：在每个未完结的场景叶节点之后追加 count 个新场景节点并连边（旧结构不变、新内容追加）
- add_branch：在指定锚点节点下新增一个玩家选择 + 分支场景 + 边

二者都走 Artifact 版本体系（v+1，source=user，change_reason=用户意图），旧版本保留，
locked=true 的节点绝不修改/删除（增加的锚点若被锁定则拒绝加分支）。
新节点的完整正文/对白留给未来 SceneAgent/DialogueAgent：本 Step 只扩展"结构 + 摘要"。
"""
import copy

from sqlalchemy.orm import Session

from app.core.errors import AppError, NotFoundError
from app.models import Project
from app.services.artifacts import latest_artifact, persist_versioned_artifact
from app.services.orchestrator import read_orchestration
from app.trace.manager import trace_manager


def _next_id(existing: set[str], prefix: str) -> str:
    seq = 1
    while f"{prefix}{seq:02d}" in existing:
        seq += 1
    return f"{prefix}{seq:02d}"


def _load_latest_story_graph(session: Session, project_id: str, project: Project) -> dict:
    art = latest_artifact(session, project_id, kind="story_graph")
    if art is None:
        raise AppError("该项目尚未生成剧情图（StoryGraph）", code="no_story_graph", status=400)
    graph = copy.deepcopy(art.content or {})
    if not graph.get("nodes"):
        raise AppError("剧情图为空，无法操作", code="empty_story_graph", status=400)
    return graph


def _commit_story_change(
    session: Session, project: Project, project_id: str, task_id: str, art,
    graph: dict, operation: str, instruction: str,
) -> dict:
    """按 Artifact 版本体系写入新版本并落 Trace。"""
    run = trace_manager.start_run(session, kind=operation, meta={"instruction": instruction[:200]})
    trace_manager.add_step(
        session, run, agent="plot", step_key="story_op",
        input_data={"operation": operation, "instruction": instruction[:200]},
        output_data={"node_count": len(graph.get("nodes", [])), "edge_count": len(graph.get("edges", []))},
        status="ok",
    )
    persist_versioned_artifact(
        session,
        project_id=project_id,
        task_id=task_id or "s4",
        agent="plot",
        kind="story_graph",
        content=graph,
        prompt_version=art.prompt_version or "",
        source="user",
        change_reason=f"[{operation}] {instruction}",
    )
    trace_manager.finish_run(run, status="ok")
    project.current_version += 1
    session.commit()
    return read_orchestration(session, project_id)


def extend_story(session: Session, project_id: str, *, instruction: str, count: int = 3) -> dict:
    """延长剧情：在每个未完结的 scene 叶节点后追加 count 个场景节点并连边。"""
    project = session.get(Project, project_id)
    if project is None:
        raise NotFoundError("项目不存在")
    art = latest_artifact(session, project_id, kind="story_graph")
    graph = _load_latest_story_graph(session, project_id, project)

    nodes: list[dict] = graph["nodes"]
    edges: list[dict] = graph.setdefault("edges", [])
    node_ids = {n["node_id"] for n in nodes}
    sources = {e["source"] for e in edges}
    # 未完结叶节点：scene 类型且无出边，且未被锁定（ending 不延长，锁定节点不可修改/延伸）
    leaf_scenes = [n for n in nodes if n.get("kind") == "scene" and n["node_id"] not in sources and not n.get("locked")]

    added = 0
    for leaf in leaf_scenes:
        prev = leaf["node_id"]
        for _ in range(count):
            new_id = _next_id(node_ids, "scene_ext")
            nodes.append({
                "node_id": new_id, "kind": "scene", "title": "续章",
                "content_ref": new_id, "summary": instruction, "locked": False,
            })
            node_ids.add(new_id)
            edges.append({
                "edge_id": _next_id({e["edge_id"] for e in edges}, "edge_ext"),
                "source": prev, "target": new_id, "label": "extend",
            })
            prev = new_id
            added += 1

    metadata = dict(graph.get("metadata", {}))
    metadata.update({"extended": True, "last_operation": "extend"})
    graph["metadata"] = metadata
    return _commit_story_change(session, project, project_id, art.task_id, art, graph, "extend", instruction)


def add_branch(session: Session, project_id: str, *, instruction: str, anchor_node_id: str | None = None) -> dict:
    """增加分支：在锚点节点下新增一个玩家选择 + 分支场景 + 边。"""
    project = session.get(Project, project_id)
    if project is None:
        raise NotFoundError("项目不存在")
    art = latest_artifact(session, project_id, kind="story_graph")
    graph = _load_latest_story_graph(session, project_id, project)

    nodes: list[dict] = graph["nodes"]
    edges: list[dict] = graph.setdefault("edges", [])
    anchor_id = anchor_node_id or graph.get("entry_node_id")
    anchor = next((n for n in nodes if n.get("node_id") == anchor_id), None)
    if anchor is None:
        raise AppError(f"锚点节点 {anchor_id} 不存在", code="node_not_found", status=404)
    if anchor.get("locked"):
        raise AppError("该节点已被用户锁定，无法增加分支", code="locked_node", status=409)

    node_ids = {n["node_id"] for n in nodes}
    new_id = _next_id(node_ids, "scene_br")
    nodes.append({
        "node_id": new_id, "kind": "scene", "title": instruction,
        "content_ref": new_id, "summary": instruction, "locked": False,
    })
    choice_id = _next_id(
        {c["choice_id"] for n in nodes for c in n.get("choices", []) if c.get("choice_id")},
        "choice_br",
    )
    anchor.setdefault("choices", []).append({"choice_id": choice_id, "text": instruction, "next_node": new_id})
    edges.append({
        "edge_id": _next_id({e["edge_id"] for e in edges}, "edge_br"),
        "source": anchor_id, "target": new_id, "label": choice_id,
    })

    metadata = dict(graph.get("metadata", {}))
    metadata.update({"branched": True, "last_operation": "branch"})
    graph["metadata"] = metadata
    return _commit_story_change(session, project, project_id, art.task_id, art, graph, "branch", instruction)