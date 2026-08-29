"""Orchestrator：把 AgentPlan.generation_steps 作为 DAG，按依赖顺序调度已实现 Agent 执行。

状态机：pending -> ready -> running -> succeeded / failed / blocked / skipped。
未实现的（Planned）Agent 一律标记 blocked（绝不伪造成功）；上游 blocked/failed 会级联到下游。
"""
import asyncio

from sqlalchemy.orm.attributes import flag_modified

from app.agents.base import registry
from app.api.v1.storygraph import diagnose
from app.core.errors import AppError, NotFoundError
from app.models import AgentSpec, AgentVersion, Artifact, Project
from app.schemas import PlanStep
from app.schemas.agent_plan import AgentPlan, ProductionTask
from app.schemas.story_graph import StoryGraph
from app.services.artifacts import persist_versioned_artifact
from app.services.context import compile_dialogue_context
from app.services.prompt_seed import (
    ensure_character_prompt,
    ensure_dialogue_prompt,
    ensure_plot_prompt,
    ensure_relationship_prompt,
    ensure_scene_prompt,
    ensure_storyboard_prompt,
    ensure_world_prompt,
)
from app.services.upstream import first_of_kind
from app.trace.manager import trace_manager

# 全量生成时按 StoryGraph 节点「扇出」的内容 Agent（对照 Funloom 7 步闭环的 beats/扩写剧情）。
_FANOUT_AGENTS = ("scene", "dialogue")
# 扇出并发上限：长链（≥60 节点）也按并发而不是逐一串行，避免单次请求动辄数分钟导致前端超时。
_FANOUT_CONCURRENCY = 6
# 确定性收尾/评测任务：无需在 Agent 注册表中登记，由 Orchestrator 直接执行。
_NON_REGISTRY = ("finalize", "evaluation")


async def orchestrate_project(session, project_id: str) -> dict:
    project = session.get(Project, project_id)
    if project is None:
        raise NotFoundError("项目不存在")
    spec = _spec_with_plan(session, project_id)
    ensure_world_prompt(session)
    ensure_character_prompt(session)
    ensure_relationship_prompt(session)
    ensure_plot_prompt(session)
    ensure_scene_prompt(session)
    ensure_dialogue_prompt(session)
    ensure_storyboard_prompt(session)
    plan = AgentPlan.model_validate(spec.policies["agent_plan"])

    version = (
        session.query(AgentVersion)
        .filter(AgentVersion.agent_spec_id == spec.id)
        .order_by(AgentVersion.version_no.desc())
        .first()
    )
    run = trace_manager.start_run(
        session, kind="orchestrate", agent_version_id=version.id if version else None,
        meta={"project_id": project_id, "goal": project.goal[:200]},
    )

    # 重建干净的 Pipeline 状态（幂等重跑）
    session.query(Artifact).filter(Artifact.project_id == project_id).delete()
    steps = _init_steps(plan)
    spec.plan = steps
    spec.status = "building"
    session.flush()

    try:
        await _execute_dag(session, project, spec, plan, run)
    except AppError:
        trace_manager.finish_run(run, status="failed")
        spec.status = "failed"
        session.commit()
        raise
    except Exception as exc:  # 兜底：把未预期异常转成可读失败，而不是通用 500「请查看日志」
        trace_manager.finish_run(run, status="failed")
        spec.status = "failed"
        try:
            session.commit()
        except Exception:
            session.rollback()
        raise AppError(
            f"一键生成中断：{type(exc).__name__}: {exc}",
            code="orchestrate_error", status=500,
        ) from exc

    trace_manager.finish_run(run, status="ok")
    spec.status = "ok"
    session.commit()
    return read_orchestration(session, project_id)


def read_orchestration(session, project_id: str) -> dict:
    spec = (
        session.query(AgentSpec)
        .filter(AgentSpec.project_id == project_id)
        .order_by(AgentSpec.created_at.desc())
        .first()
    )
    if spec is None:
        raise NotFoundError("项目不存在")
    artifacts = (
        session.query(Artifact)
        .filter(Artifact.project_id == project_id, Artifact.is_latest.is_(True))
        .order_by(Artifact.created_at)
        .all()
    )
    return {
        "project_id": project_id,
        "status": spec.status,
        "steps": [
            {**PlanStep(**s).model_dump(), **(s.get("progress") and {"progress": s["progress"]} or {})}
            for s in (spec.plan or [])
        ],
        "artifacts": [
            {
                "id": a.id, "task_id": a.task_id, "agent": a.agent, "kind": a.kind,
                "content": a.content or {}, "prompt_version": a.prompt_version,
                "version": a.version, "parent_version": a.parent_version,
                "source": a.source, "change_reason": a.change_reason, "is_latest": a.is_latest,
            }
            for a in artifacts
        ],
    }


def _spec_with_plan(session, project_id: str) -> AgentSpec:
    spec = (
        session.query(AgentSpec)
        .filter(AgentSpec.project_id == project_id)
        .order_by(AgentSpec.created_at.desc())
        .first()
    )
    if spec is None:
        raise NotFoundError("项目不存在")
    if "agent_plan" not in (spec.policies or {}):
        raise AppError("该项目没有 Director 规划，无法编排", code="no_agent_plan", status=400)
    return spec


def _init_steps(plan: AgentPlan) -> list[dict]:
    return [
        {
            "key": t.id, "label": t.agent_type, "description": t.objective,
            "agent": t.agent_type, "status": "pending",
            "dependencies": t.dependencies, "reason": "",
        }
        for t in plan.generation_steps
    ]


async def _execute_dag(session, project, spec, plan, run) -> None:
    steps = list(spec.plan)
    by_id = {t.id: t for t in plan.generation_steps}
    state = {t.id: "pending" for t in plan.generation_steps}
    reason_by: dict[str, str] = {t.id: "" for t in plan.generation_steps}
    # 依存数据流：task_id -> artifact content（下游 Agent 通过 upstream 读取，如 world -> character）
    artifact_by_task: dict[str, dict] = {}

    def set_status(tid: str, status: str, reason: str = "") -> None:
        state[tid] = status
        if reason:
            reason_by[tid] = reason
        for s in steps:
            if s["key"] == tid:
                s["status"] = status
                s["reason"] = reason_by[tid]
        spec.plan = list(steps)  # 触发 JSON 列脏标记
        flag_modified(spec, "plan")
        session.flush()
        # 每步落库提交：前端轮询进度时能读到最新步骤状态（否则跨连接看不到）。
        if status in ("succeeded", "failed", "blocked", "skipped"):
            try:
                session.commit()
            except Exception:
                session.rollback()

    def report_progress(tid: str, done: int, total: int, label: str) -> None:
        """扇出过程中逐批写进度，提交后前端进度条可见。"""
        for s in steps:
            if s["key"] == tid:
                s["progress"] = {
                    "done": done, "total": total,
                    "pct": round((100.0 * done / total), 1) if total else 100.0,
                    "label": label,
                }
        spec.plan = list(steps)
        flag_modified(spec, "plan")
        try:
            session.commit()
        except Exception:
            session.rollback()

    remaining = set(state)
    while remaining:
        progressed = False
        for tid in sorted(remaining):
            task = by_id[tid]
            deps = [state[d] for d in task.dependencies]
            if any(s in ("blocked", "failed") for s in deps):
                set_status(tid, "blocked", "上游任务 blocked/failed，无法执行")
                remaining.discard(tid)
                progressed = True
                continue
            if not all(s in ("succeeded", "skipped") for s in deps):
                continue  # 依赖尚未全部完成，等待下一轮

            set_status(tid, "ready")
            agent_type = task.agent_type
            upstream = {
                d: artifact_by_task[d]
                for d in task.dependencies if d in artifact_by_task
            }

            # 旧版 8 步计划兼容：branch 已并入 plot（互动图含分支/结局），不再单独执行。
            if agent_type == "branch":
                set_status(tid, "skipped", "分支与结局已由 plot 在 StoryGraph 中生成")
                trace_manager.add_step(
                    session, run, agent="orchestrator", step_key="task.skipped",
                    input_data={"task": tid}, output_data={"reason": "folded-into-plot"}, status="ok",
                )
                remaining.discard(tid)
                progressed = True
                continue

            # 非注册表 Agent：finalize（编译收尾）与 evaluation（兼容旧计划评测）为确定性任务。
            is_deterministic = agent_type in _NON_REGISTRY
            is_fanout = agent_type in _FANOUT_AGENTS
            if not is_deterministic and not registry.is_implemented(agent_type):
                set_status(tid, "blocked", f"Agent '{agent_type}' 尚未实现（planned）")
                trace_manager.add_step(
                    session, run, agent="orchestrator", step_key="task.blocked",
                    input_data={"task": tid, "agent": agent_type},
                    output_data={"reason": "planned"}, status="blocked",
                )
            elif not is_deterministic and not is_fanout and not registry.get(agent_type).pipeline:
                set_status(
                    tid, "blocked",
                    f"Agent '{agent_type}' 由用户按节点局部调用（on-demand），不参与流水线全量生成",
                )
                trace_manager.add_step(
                    session, run, agent="orchestrator", step_key="task.blocked",
                    input_data={"task": tid, "agent": agent_type},
                    output_data={"reason": "on-demand"}, status="blocked",
                )
            else:
                set_status(tid, "running")
                trace_manager.add_step(
                    session, run, agent="orchestrator", step_key="task.start",
                    input_data={"task": tid, "agent": agent_type}, output_data={}, status="ok",
                )
                try:
                    if agent_type == "finalize":
                        result = await _compile_project(session, run, task, project, upstream, kind="script_book")
                    elif agent_type == "evaluation":
                        result = await _compile_project(session, run, task, project, upstream, kind="evaluation")
                    elif agent_type in _FANOUT_AGENTS:
                        result = await _fanout_node_content(
                            session, run, task, project, plan, upstream,
                            progress_cb=lambda done, total, label, _t=tid: report_progress(_t, done, total, label),
                        )
                    else:
                        agent = registry.get(agent_type)
                        result = await agent.run({
                            "session": session, "run": run, "task": task, "goal": project.goal,
                            "plan": plan,
                            "project": {"genre": plan.genre, "tone": plan.tone, "project_type": plan.project_type},
                            "upstream": upstream,
                        })
                    _persist_artifact(session, project.id, task, result)
                    artifact = result.get("artifact") or {}
                    if artifact.get("content"):
                        artifact_by_task[tid] = {
                            "kind": artifact.get("kind", "unknown"),
                            "content": artifact["content"],
                        }
                    set_status(tid, "succeeded")
                    trace_manager.add_step(
                        session, run, agent="orchestrator", step_key="task.succeeded",
                        input_data={"task": tid},
                        output_data={"artifact": result.get("artifact", {}).get("kind")}, status="ok",
                    )
                except AppError as exc:
                    set_status(tid, "failed", exc.message)
                    trace_manager.add_step(
                        session, run, agent="orchestrator", step_key="task.failed",
                        input_data={"task": tid}, output_data={}, error=exc.message, status="failed",
                    )
                except Exception as exc:  # 防御：任何未预期异常都降级为单步失败，绝不 500
                    set_status(tid, "failed", f"内部错误：{type(exc).__name__}: {exc}")
                    trace_manager.add_step(
                        session, run, agent="orchestrator", step_key="task.failed",
                        input_data={"task": tid}, output_data={},
                        error=f"内部错误：{type(exc).__name__}: {exc}", status="failed",
                    )
            remaining.discard(tid)
            progressed = True

        if not progressed:
            # 防御：AgentPlan 已校验无环/依赖存在，此处理论上不可达
            for tid in list(remaining):
                set_status(tid, "blocked", "依赖未满足（无法推进）")
            remaining.clear()


async def _fanout_node_content(session, run, task, project, plan, upstream, progress_cb=None) -> dict:
    """scene/dialogue 全量扇出（对照 Funloom「beats 扩写剧情」）：对 StoryGraph 每个内容节点生成。

    - scene：为每个非 ending 节点生成场景正文，产出 scene:{node_id} 版本链。
    - dialogue：为每个带选项的节点生成节点对白（choice_id=None 的开场/承接对白），产出 dialogue:{node_id}。
    单个节点失败只跳过（记录 Trace），不坍缩整条流水线。
    节点间以并发（_FANOUT_CONCURRENCY 上限）跑，避免 60+ 节点串行把单次请求拖到超时。
    """
    mode = task.agent_type
    agent = registry.get(mode)
    graph = first_of_kind(upstream, "story_graph") or {}
    nodes = graph.get("nodes", [])
    if mode == "scene":
        targets = [n for n in nodes if n.get("kind") != "ending"]
    else:
        targets = [n for n in nodes if n.get("choices")]

    async def _fanout_one(node: dict) -> str | None:
        node_id = node.get("node_id")
        if not node_id:
            return None
        sub_task = ProductionTask(
            id=f"{task.id}:{node_id}", agent_type=mode, objective=task.objective,
            dependencies=[], output_schema={"type": "object"},
        )
        payload = {
            "session": session, "run": run, "task": sub_task, "goal": project.goal,
            "plan": plan,
            "project": {"genre": plan.genre, "tone": plan.tone, "project_type": plan.project_type},
            "upstream": upstream, "node_id": node_id,
        }
        if mode == "dialogue":
            payload["context"] = compile_dialogue_context(
                upstream, node_id=node_id, choice_id=None, instruction=task.objective,
            )
            payload["instruction"] = task.objective
        try:
            result = await agent.run(payload)
        except AppError as exc:
            trace_manager.add_step(
                session, run, agent="orchestrator", step_key="task.fanout_skip",
                input_data={"task": task.id, "node_id": node_id},
                output_data={}, error=exc.message, status="failed",
            )
            return None
        except Exception as exc:  # 防御：单节点崩溃只跳过该节点，绝不 500
            trace_manager.add_step(
                session, run, agent="orchestrator", step_key="task.fanout_skip",
                input_data={"task": task.id, "node_id": node_id},
                output_data={}, error=f"内部错误：{type(exc).__name__}: {exc}", status="failed",
            )
            return None
        content = result.get("artifact", {}).get("content", {})
        if mode == "scene":
            content["scene_id"] = node_id
        else:
            content["node_id"] = node_id
        persist_versioned_artifact(
            session, project_id=project.id, task_id=task.id, agent=mode,
            kind=f"{mode}:{node_id}", content=content,
            prompt_version=result.get("prompt_version", ""), source="agent",
            change_reason=f"一键生成 {mode}",
        )
        return node_id

    total = len(targets)
    done = 0
    generated: list[str] = []
    sem = asyncio.Semaphore(_FANOUT_CONCURRENCY)

    async def _guarded(node: dict) -> str | None:
        async with sem:
            return await _fanout_one(node)

    # 分批并发执行，并逐批汇报进度（前端进度条据此推进）。
    batch = 8
    for start in range(0, total, batch):
        batch_targets = targets[start:start + batch]
        results = await asyncio.gather(*(_guarded(n) for n in batch_targets))
        for rid in results:
            if rid:
                generated.append(rid)
        done = start + len(batch_targets)
        if total and progress_cb:
            progress_cb(done, total, f"{mode} {done}/{total} 节点")
    # 残余节点兜底（total 为 0 时上面不触发，但无节点可生成）
    return {
        "ok": True, "agent": mode,
        "artifact": {"kind": mode, "content": {"generated": len(generated), "node_ids": generated}},
        "prompt_version": "",
    }


async def _compile_project(session, run, task, project, upstream, *, kind: str) -> dict:
    """编译/质检（对照 Funloom「finalize 编译剧本书」）：确定性汇总 + StoryGraph 校验闭环。

    kind 可为 script_book（新 7 步闭环收尾）或 evaluation（兼容旧版 8 步计划的评测步骤）。
    """
    graph = first_of_kind(upstream, "story_graph") or {}
    nodes = graph.get("nodes", [])
    endings = [n for n in nodes if n.get("kind") == "ending"]
    scene_count = session.query(Artifact).filter(
        Artifact.project_id == project.id, Artifact.kind.like("scene:%"), Artifact.is_latest.is_(True),
    ).count()
    dialogue_count = session.query(Artifact).filter(
        Artifact.project_id == project.id, Artifact.kind.like("dialogue:%"), Artifact.is_latest.is_(True),
    ).count()
    quality: dict = {"errors": [], "warnings": []}
    if nodes:
        try:
            quality = diagnose(StoryGraph.model_validate(graph))
        except Exception:  # 图结构异常时降级，绝不让收尾步骤崩溃
            quality = {"ok": False, "errors": ["剧情图结构异常，无法质检"], "warnings": []}
    content = {
        "title": (project.title or project.goal or "未命名作品")[:120],
        "node_count": len(nodes),
        "scene_count": scene_count,
        "dialogue_count": dialogue_count,
        "ending_count": len(endings),
        "variable_count": len(graph.get("variables", [])),
        "quality": {"errors": quality.get("errors", []), "warnings": quality.get("warnings", [])},
    }
    trace_manager.add_step(
        session, run, agent="finalize", step_key="compile",
        input_data={"task": task.id, "kind": kind},
        output_data={
            "node_count": content["node_count"], "scene_count": content["scene_count"],
            "dialogue_count": content["dialogue_count"], "ending_count": content["ending_count"],
        },
        status="ok",
    )
    return {"ok": True, "agent": kind, "artifact": {"kind": kind, "content": content}, "prompt_version": ""}


def _persist_artifact(session, project_id: str, task, result: dict) -> None:
    artifact = result.get("artifact") or {}
    persist_versioned_artifact(
        session,
        project_id=project_id,
        task_id=task.id,
        agent=result.get("agent", task.agent_type),
        kind=artifact.get("kind", "unknown"),
        content=artifact.get("content", {}),
        prompt_version=result.get("prompt_version", ""),
        source="agent",
    )