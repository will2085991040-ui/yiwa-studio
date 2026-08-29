"""Scene 局部服务（Step 11）：对 StoryGraph 单个 SceneNode 生成/修改/扩写场景内容。

这是「局部生产 + 用户决策 + 可编辑 + 可版本化」落地：绝不整体重新生成。
- generate：首次生成该节点场景（source=agent）
- revise  ：按用户要求修改该节点场景（source=user，change_reason=指令）
- expand  ：扩写该节点场景（source=user，change_reason=[expand] 指令，并追加一个事件节拍）

Artifact kind = f"scene:{node_id}"，使每个 SceneNode 拥有独立的版本链（scene:{a} 的 v2 不影响 scene:{b}）。
locked=true 的节点一律拒绝（code=locked_node），不静默覆盖。
"""
from sqlalchemy.orm import Session

from app.agents.base import registry
from app.core.errors import AppError, NotFoundError
from app.models import AgentSpec, Artifact, Project
from app.schemas.agent_plan import AgentPlan, ProductionTask
from app.services.artifacts import latest_artifact, persist_versioned_artifact
from app.services.orchestrator import read_orchestration
from app.services.prompt_seed import ensure_scene_prompt
from app.trace.manager import trace_manager


def _plan(session: Session, project_id: str) -> tuple[AgentSpec, AgentPlan]:
    spec = (
        session.query(AgentSpec)
        .filter(AgentSpec.project_id == project_id)
        .order_by(AgentSpec.created_at.desc())
        .first()
    )
    if spec is None:
        raise NotFoundError("项目不存在")
    if "agent_plan" not in (spec.policies or {}):
        raise AppError("该项目没有 Director 规划，无法生成场景", code="no_agent_plan", status=400)
    return spec, AgentPlan.model_validate(spec.policies["agent_plan"])


def _story_node(session: Session, project_id: str, node_id: str) -> dict:
    story = latest_artifact(session, project_id, kind="story_graph")
    if story is None or not story.content:
        raise AppError("该项目尚未生成剧情图（StoryGraph）", code="no_story_graph", status=400)
    node = next((n for n in story.content.get("nodes", []) if n.get("node_id") == node_id), None)
    if node is None:
        raise AppError(f"StoryGraph 中不存在节点 {node_id}", code="node_not_found", status=404)
    return node


def _build_upstream(session: Session, project_id: str) -> dict:
    """按 kind 组装完整上游：world_bible + 全部 character_card + relationship_graph + story_graph。"""
    upstream: dict = {}
    wb = latest_artifact(session, project_id, kind="world_bible")
    if wb is not None:
        upstream[f"world:{wb.task_id}"] = {"kind": "world_bible", "content": wb.content or {}}
    cards = session.query(Artifact).filter(
        Artifact.project_id == project_id, Artifact.kind.startswith("character_card"), Artifact.is_latest.is_(True)
    ).all()
    for i, c in enumerate(cards):
        cid = (c.content or {}).get("character_id") or f"char-{i}"
        upstream[f"character:{i}"] = {"kind": f"character_card:{cid}", "content": c.content or {}}
    rel = latest_artifact(session, project_id, kind="relationship_graph")
    if rel is not None:
        upstream["relationship:0"] = {"kind": "relationship_graph", "content": rel.content or {}}
    story = latest_artifact(session, project_id, kind="story_graph")
    if story is None:
        raise AppError("该项目尚未生成剧情图（StoryGraph）", code="no_story_graph", status=400)
    upstream["story:0"] = {"kind": "story_graph", "content": story.content}
    return upstream


def _persist_scene(
    session: Session, project: Project, project_id: str, node_id: str, result: dict,
    source: str, change_reason: str | None,
) -> dict:
    artifact = result.get("artifact") or {}
    content = artifact.get("content", {})
    content["scene_id"] = node_id  # 稳定引用：scene_id 恒等于 StoryGraph.node_id
    persist_versioned_artifact(
        session,
        project_id=project_id,
        task_id=result.get("node_id", node_id),
        agent="scene",
        kind=f"scene:{node_id}",
        content=content,
        prompt_version=result.get("prompt_version", ""),
        source=source,
        change_reason=change_reason,
    )
    project.current_version += 1
    session.commit()
    return read_orchestration(session, project_id)


async def run_scene_operation(
    session: Session, project_id: str, *, operation: str, node_id: str, instruction: str | None = None
) -> dict:
    project = session.get(Project, project_id)
    if project is None:
        raise NotFoundError("项目不存在")
    if operation in ("revise", "expand") and not (instruction or "").strip():
        raise AppError(f"操作 {operation} 需要 instruction", code="instruction_required", status=400)

    spec, plan = _plan(session, project_id)
    node = _story_node(session, project_id, node_id)
    if node.get("locked"):
        raise AppError("该场景节点已被用户锁定，无法生成或修改", code="locked_node", status=409)

    ensure_scene_prompt(session)
    upstream = _build_upstream(session, project_id)
    objective = instruction.strip() if instruction else "生成该场景内容"
    task = ProductionTask(
        id=f"scene-{node_id}", agent_type="scene", objective=objective,
        dependencies=[], output_schema={"type": "object"},
    )
    revision = None
    if operation == "revise":
        current = latest_artifact(session, project_id, kind=f"scene:{node_id}")
        revision = {"instruction": instruction, "previous": current.content if current else None}
    elif operation == "expand":
        current = latest_artifact(session, project_id, kind=f"scene:{node_id}")
        revision = {"instruction": f"扩写：{instruction}", "previous": current.content if current else None}

    run = trace_manager.start_run(
        session, kind=f"scene_{operation}",
        meta={"node_id": node_id, "instruction": (instruction or "")[:200]},
    )
    try:
        result = await registry.get("scene").run({
            "session": session, "run": run, "task": task, "goal": project.goal,
            "plan": plan,
            "project": {"genre": plan.genre, "tone": plan.tone, "project_type": plan.project_type},
            "upstream": upstream, "node_id": node_id, "revision": revision,
        })
    except AppError:
        trace_manager.finish_run(run, status="failed")
        session.commit()
        raise

    if operation == "expand":
        content = result.get("artifact", {}).get("content", {})
        content.setdefault("events", []).append(f"{instruction}（扩写新幕）")
        result.setdefault("artifact", {})["content"] = content

    trace_manager.finish_run(run, status="ok")
    if operation == "generate":
        change_reason = f"局部生成场景 {node_id}"
        source = "agent"
    elif operation == "expand":
        change_reason = f"[expand] {instruction}"
        source = "user"
    else:
        change_reason = instruction
        source = "user"
    return _persist_scene(session, project, project_id, node_id, result, source, change_reason)