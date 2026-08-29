"""Director 业务流程：创意 -> AgentPlan -> 持久化（Project/AgentSpec/AgentVersion）+ Trace。"""
from app.agents.director import DirectorAgent
from app.core.errors import AppError
from app.models import AgentSpec, AgentVersion, Project
from app.services.prompt_seed import ensure_director_prompt
from app.trace.manager import trace_manager


def _workflow_steps(plan) -> list[dict]:
    """把 AgentPlan 的 generation_steps 转成现有 workflow 端点可展示的 PlanStep 结构。"""
    return [
        {"key": t.id, "label": t.agent_type, "description": t.objective, "agent": t.agent_type, "status": "pending"}
        for t in plan.generation_steps
    ]


async def create_project_via_director(
    session, goal: str, *, game_type: str | None = None, title: str | None = None
) -> dict:
    ensure_director_prompt(session)
    run = trace_manager.start_run(session, kind="director_plan", meta={"goal": goal, "game_type": game_type})
    try:
        result = await DirectorAgent().run({"session": session, "run": run, "goal": goal})
    except AppError:
        trace_manager.finish_run(run, status="failed")
        session.commit()
        raise

    plan = result["agent_plan"]
    cleaned = " ".join(goal.split())
    project_title = (title or cleaned).strip()[:200]
    project = Project(
        goal=goal,
        template=(game_type or f"director:{plan.project_type}")[:40],
        title=project_title,
        status="planning",
    )
    session.add(project)
    session.flush()
    spec = AgentSpec(
        project_id=project.id,
        goal_summary=plan.goal_summary[:200],
        plan=_workflow_steps(plan),
        policies={
            "agent_plan": plan.model_dump(),
            "prompt_version": result["prompt_version"],
            "provider": result["provider"],
            "model": result["model"],
            "game_type": game_type or plan.project_type,
        },
        status="planning",
    )
    session.add(spec)
    session.flush()
    version = AgentVersion(
        agent_spec_id=spec.id,
        version_no=1,
        label="v1 · Director 规划",
        spec_snapshot={
            "goal": goal,
            "agent_plan": plan.model_dump(),
            "prompt_version": result["prompt_version"],
            "provider": result["provider"],
            "model": result["model"],
            "usage": result["usage"],
        },
        status="draft",
    )
    session.add(version)
    session.flush()
    run.agent_version_id = version.id
    trace_manager.finish_run(run, status="ok")
    session.commit()

    return {
        "project_id": project.id,
        "goal": goal,
        "prompt_version": result["prompt_version"],
        "provider": result["provider"],
        "model": result["model"],
        "latency_ms": result["latency_ms"],
        "agent_plan": plan.model_dump(),
        "agent_version": {
            "id": version.id,
            "version_no": version.version_no,
            "label": version.label,
            "status": version.status,
            "created_at": version.created_at,
        },
    }