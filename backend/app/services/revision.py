"""Interactive Creation Layer（Step 8）：用户持续修改 + 局部执行。

不是「一键生成完毕」，而是让 YIWA 成为可编辑的创作引擎：
- revise_artifact：用户修改请求 -> 对应 Agent -> Artifact v2（旧版本保留）
- rerun_task：按 AgentPlan 的单个任务局部重跑（不使用 Whole Project）
"""
from app.agents.base import registry
from app.core.errors import AppError, NotFoundError
from app.models import AgentSpec, AgentVersion, Project
from app.schemas.agent_plan import AgentPlan, ProductionTask
from app.services.artifacts import latest_artifact, persist_versioned_artifact
from app.services.orchestrator import read_orchestration
from app.services.prompt_seed import (
    ensure_character_prompt,
    ensure_plot_prompt,
    ensure_relationship_prompt,
    ensure_world_prompt,
)
from app.trace.manager import trace_manager

KIND_TO_AGENT = {
    "world_bible": "world",
    "character_card": "character",
    "relationship_graph": "relationship",
    "story_graph": "plot",
}


def _agent_for_kind(kind: str) -> str | None:
    """按 kind 路由 Agent；支持 per-entity 子 kind（如 character_card:char-01）。"""
    if kind in KIND_TO_AGENT:
        return KIND_TO_AGENT[kind]
    for prefix, agent in KIND_TO_AGENT.items():
        if kind.startswith(prefix + ":"):
            return agent
    return None


def _plan_of(session, project_id: str) -> tuple[AgentSpec, AgentPlan]:
    spec = (
        session.query(AgentSpec)
        .filter(AgentSpec.project_id == project_id)
        .order_by(AgentSpec.created_at.desc())
        .first()
    )
    if spec is None:
        raise NotFoundError("项目不存在")
    if "agent_plan" not in (spec.policies or {}):
        raise AppError("该项目没有 Director 规划，无法修订/局部执行", code="no_agent_plan", status=400)
    return spec, AgentPlan.model_validate(spec.policies["agent_plan"])


def _latest_version(session, spec: AgentSpec) -> AgentVersion | None:
    return (
        session.query(AgentVersion)
        .filter(AgentVersion.agent_spec_id == spec.id)
        .order_by(AgentVersion.version_no.desc())
        .first()
    )


def _project_context(plan: AgentPlan) -> dict:
    return {"genre": plan.genre, "tone": plan.tone, "project_type": plan.project_type}


def _ensure_prompts(session) -> None:
    ensure_world_prompt(session)
    ensure_character_prompt(session)
    ensure_relationship_prompt(session)
    ensure_plot_prompt(session)


async def revise_artifact(session, project_id: str, *, kind: str, instruction: str) -> dict:
    """用户修改：User Request -> 对应 Agent -> Artifact v2（source=user, parent_version=v1）。"""
    project = session.get(Project, project_id)
    if project is None:
        raise NotFoundError("项目不存在")
    spec, plan = _plan_of(session, project_id)

    agent_name = _agent_for_kind(kind)
    if agent_name is None:
        raise AppError(f"不支持的 artifact kind：{kind}", code="unsupported_kind", status=400)
    if not registry.is_implemented(agent_name):
        raise AppError(f"Agent '{agent_name}' 尚未实现", code="agent_not_implemented", status=400)
    _ensure_prompts(session)

    current = latest_artifact(session, project_id, kind=kind)
    revision = {"instruction": instruction, "previous": current.content if current is not None else None}

    orig = next((t for t in plan.generation_steps if t.agent_type == agent_name), None)
    task = ProductionTask(
        id=f"rev-{kind}", agent_type=agent_name, objective=instruction,
        dependencies=[], output_schema={"type": "object"},
    )

    # 按 task_id 注入上游 Artifact（kind+content），支撑同类型多个任务
    upstream: dict = {}
    if orig is not None:
        for dep_id in orig.dependencies:
            dep = next((t for t in plan.generation_steps if t.id == dep_id), None)
            if dep is not None:
                dep_art = latest_artifact(session, project_id, task_id=dep_id)
                if dep_art is not None:
                    upstream[dep_id] = {"kind": dep_art.kind, "content": dep_art.content}

    version = _latest_version(session, spec)
    run = trace_manager.start_run(
        session, kind="revise", agent_version_id=version.id if version else None,
        meta={"kind": kind, "instruction": instruction[:200]},
    )
    try:
        result = await registry.get(agent_name).run({
            "session": session, "run": run, "task": task, "goal": project.goal,
            "plan": plan, "project": _project_context(plan), "upstream": upstream, "revision": revision,
        })
    except AppError:
        trace_manager.finish_run(run, status="failed")
        session.commit()
        raise

    artifact = result.get("artifact") or {}
    persist_versioned_artifact(
        session, project_id=project_id, task_id=task.id,
        agent=result.get("agent", agent_name),
        kind=artifact.get("kind", kind),
        content=artifact.get("content", {}),
        prompt_version=result.get("prompt_version", ""),
        source="user", change_reason=instruction,
    )
    trace_manager.finish_run(run, status="ok")
    project.current_version += 1
    session.commit()
    return read_orchestration(session, project_id)


async def rerun_task(session, project_id: str, task_id: str) -> dict:
    """局部执行：只重跑 AgentPlan 中的单个任务，产出该 kind 的下一版本。"""
    project = session.get(Project, project_id)
    if project is None:
        raise NotFoundError("项目不存在")
    spec, plan = _plan_of(session, project_id)
    task = next((t for t in plan.generation_steps if t.id == task_id), None)
    if task is None:
        raise NotFoundError(f"任务 {task_id} 不存在")
    if task.agent_type in ("finalize", "evaluation"):
        raise AppError(
            f"任务 '{task.agent_type}' 由系统确定性执行，不支持单独重跑",
            code="not_rerunnable", status=400,
        )
    if not registry.is_implemented(task.agent_type):
        raise AppError(
            f"Agent '{task.agent_type}' 尚未实现（planned），无法单独执行",
            code="agent_not_implemented", status=400,
        )
    if not registry.get(task.agent_type).pipeline:
        raise AppError(
            f"Agent '{task.agent_type}' 由用户按节点局部调用（on-demand），不属于流水线任务",
            code="on_demand_agent", status=400,
        )
    _ensure_prompts(session)

    by_id = {t.id: t for t in plan.generation_steps}
    upstream: dict = {}
    for dep_id in task.dependencies:
        dep = by_id.get(dep_id)
        if dep is not None:
            dep_art = latest_artifact(session, project_id, task_id=dep_id)
            if dep_art is not None:
                upstream[dep_id] = {"kind": dep_art.kind, "content": dep_art.content}

    version = _latest_version(session, spec)
    run = trace_manager.start_run(
        session, kind="task_run", agent_version_id=version.id if version else None,
        meta={"task_id": task_id, "agent": task.agent_type},
    )
    try:
        result = await registry.get(task.agent_type).run({
            "session": session, "run": run, "task": task, "goal": project.goal,
            "plan": plan, "project": _project_context(plan), "upstream": upstream,
        })
    except AppError:
        trace_manager.finish_run(run, status="failed")
        session.commit()
        raise

    artifact = result.get("artifact") or {}
    persist_versioned_artifact(
        session, project_id=project_id, task_id=task.id,
        agent=result.get("agent", task.agent_type),
        kind=artifact.get("kind", "unknown"),
        content=artifact.get("content", {}),
        prompt_version=result.get("prompt_version", ""),
        source="agent", change_reason=f"局部重跑任务 {task_id}",
    )
    trace_manager.finish_run(run, status="ok")
    project.current_version += 1
    session.commit()
    return read_orchestration(session, project_id)