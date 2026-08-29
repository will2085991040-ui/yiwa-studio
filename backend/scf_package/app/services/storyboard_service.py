"""Storyboard 局部服务：对 StoryGraph 指定节点做 AI 拆镜（LLM，失败回退 mock）。

Artifact kind = f"storyboard:{node_id}"，每个节点拥有独立版本链。

策略（自愈优先，绝不 500）：
1. 若项目已有 Director 规划 + StoryGraph 且命中 node → 调用 StoryboardAgent 做 LLM 拆镜；
2. 任一前置缺失或 Agent 抛错/未产出 → 回退确定性 mock `auto_breakdown`，
   并在 change_reason 标注 fallback 原因，保证离线可用。
"""
from sqlalchemy.orm import Session

from app.agents.base import registry
from app.core.errors import AppError, NotFoundError
from app.models import AgentSpec, Artifact, Project
from app.schemas.agent_plan import AgentPlan, ProductionTask
from app.schemas.storyboard import Storyboard, auto_breakdown, compose_character_identity
from app.services.artifacts import latest_artifact, persist_versioned_artifact
from app.services.prompt_seed import ensure_storyboard_prompt
from app.trace.manager import trace_manager


def _try_plan(session: Session, project_id: str) -> AgentPlan | None:
    spec = (
        session.query(AgentSpec)
        .filter(AgentSpec.project_id == project_id)
        .order_by(AgentSpec.created_at.desc())
        .first()
    )
    if spec is None or "agent_plan" not in (spec.policies or {}):
        return None
    try:
        return AgentPlan.model_validate(spec.policies["agent_plan"])
    except Exception:
        return None


def _try_story_node(session: Session, project_id: str, node_id: str) -> dict | None:
    story = latest_artifact(session, project_id, kind="story_graph")
    if story is None or not story.content:
        return None
    return next((n for n in story.content.get("nodes", []) if n.get("node_id") == node_id), None)


def _build_upstream(session: Session, project_id: str, node_id: str) -> dict:
    """按 kind 组装上游：world_bible + 全部 character_card + relationship_graph + story_graph + scene:{node_id}。"""
    upstream: dict = {}
    wb = latest_artifact(session, project_id, kind="world_bible")
    if wb is not None:
        upstream["world:0"] = {"kind": "world_bible", "content": wb.content or {}}
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
    if story is not None:
        upstream["story:0"] = {"kind": "story_graph", "content": story.content}
    scene = latest_artifact(session, project_id, kind=f"scene:{node_id}")
    if scene is not None:
        upstream[f"scene:{node_id}"] = {"kind": f"scene:{node_id}", "content": scene.content or {}}
    return upstream


def _character_identity(session: Session, project_id: str) -> str:
    """从项目角色卡组装身份一致性锁（外貌/服装/气质），供画面与视频提示复用。"""
    cards = session.query(Artifact).filter(
        Artifact.project_id == project_id, Artifact.kind.startswith("character_card"),
        Artifact.is_latest.is_(True),
    ).all()
    payload = [
        {"character_id": (c.content or {}).get("character_id") or f"char-{i}",
         "name": (c.content or {}).get("name") or "",
         "appearance": (c.content or {}).get("appearance") or ""}
        for i, c in enumerate(cards)
    ]
    return compose_character_identity(payload)


def _persist(session: Session, project: Project, project_id: str, node_id: str, sb, change_reason: str) -> None:
    persist_versioned_artifact(
        session, project_id=project_id, task_id=f"storyboard-{node_id}", agent="storyboard",
        kind=f"storyboard:{node_id}", content=sb.model_dump(), prompt_version="",
        source="agent", change_reason=change_reason,
    )
    project.current_version += 1
    session.commit()


async def run_storyboard_breakdown(
    session: Session, project_id: str, node_id: str, requested_shots: int = 4
) -> Storyboard:
    """对节点 AI 拆镜并落库；返回落库的 Storyboard（mock 或 Agent 产物）。"""
    project = session.get(Project, project_id)
    if project is None:
        raise NotFoundError("项目不存在")

    node = _try_story_node(session, project_id, node_id)
    node_summary = (node or {}).get("summary") or ""
    plan = _try_plan(session, project_id)

    # 前置不足（无 Director 规划 或 剧情图没有该节点）：直接确定性 mock，保证离线可用
    if plan is None or node is None:
        sb = auto_breakdown(node_id, node_summary, requested_shots)
        _persist(
            session, project, project_id, node_id, sb,
            "ai-breakdown-fallback:no-plan-or-node",
        )
        return sb

    # 有规划 + 有节点：走 StoryboardAgent（LLM），失败回退 mock
    ensure_storyboard_prompt(session)
    upstream = _build_upstream(session, project_id, node_id)
    task = ProductionTask(
        id=f"storyboard-{node_id}", agent_type="storyboard",
        objective=f"为节点 {node_id} 拆 {requested_shots} 个镜头",
        dependencies=[], output_schema={"type": "object"},
    )
    run = trace_manager.start_run(
        session, kind="storyboard_breakdown", meta={"node_id": node_id, "goal": project.goal[:200]},
    )
    result = None
    fallback_reason = ""
    try:
        result = await registry.get("storyboard").run({
            "session": session, "run": run, "task": task, "goal": project.goal,
            "project": {"genre": plan.genre, "tone": plan.tone, "project_type": plan.project_type},
            "upstream": upstream, "node_id": node_id,
        })
        trace_manager.finish_run(run, status="ok")
    except AppError as exc:
        trace_manager.finish_run(run, status="failed")
        session.commit()
        fallback_reason = f"{type(exc).__name__}: {exc}"
    except Exception as exc:  # 兜底：任何未预期异常都不让 500 崩溃
        trace_manager.finish_run(run, status="failed")
        session.commit()
        fallback_reason = f"{type(exc).__name__}: {exc}"

    if result is None or not getattr(result.get("storyboard"), "shots", None):
        fallback_reason = fallback_reason or "Agent 未产出镜头"
        sb = auto_breakdown(node_id, node_summary, requested_shots)
        change_reason = f"ai-breakdown-fallback:{fallback_reason}"
    else:
        sb = result["storyboard"]
        sb.metadata = {**(sb.metadata or {}), "requested_shots": requested_shots}
        change_reason = "ai-breakdown"

    sb.metadata = {**(sb.metadata or {}), "character_identity": _character_identity(session, project_id)}
    _persist(session, project, project_id, node_id, sb, change_reason)
    return sb