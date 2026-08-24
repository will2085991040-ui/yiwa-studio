"""Dialogue 局部服务（Step 12）：对 StoryGraph 单个 (node_id, choice_id) 生成/修改/扩写对白。

这是「局部生产 + 用户决策 + 可编辑 + 可版本化」在 Dialogue 上的落地，绝不整体重新生成：
- generate：首次生成该 (node, choice) 对白（source=agent）
- revise  ：按用户要求修改（source=user，change_reason=指令）
- expand  ：扩写（source=user，change_reason=[expand] 指令，并追加一条对白）

Artifact kind = dialogue:{node_id}（default）或 dialogue:{node_id}:{choice_id}，使每个 (node, choice)
拥有独立版本链。locked=true 的节点一律拒绝（code=locked_node）。Scene 缺失时仍可生成，但 Trace
记录 context.missing=["scene:{node_id}"]，绝不伪造 Scene 已存在。
"""
from sqlalchemy.orm import Session

from app.agents.base import registry
from app.core.errors import AppError, NotFoundError
from app.models import AgentSpec, Artifact, Project
from app.schemas.agent_plan import AgentPlan, ProductionTask
from app.schemas.dialogue import dialogue_id, dialogue_kind
from app.services.artifacts import latest_artifact, persist_versioned_artifact
from app.services.context import compile_dialogue_context
from app.services.orchestrator import read_orchestration
from app.services.prompt_seed import ensure_dialogue_prompt
from app.services.upstream import artifacts_of_kind
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
        raise AppError("该项目没有 Director 规划，无法生成对白", code="no_agent_plan", status=400)
    return spec, AgentPlan.model_validate(spec.policies["agent_plan"])


def _story_graph(session: Session, project_id: str) -> dict:
    story = latest_artifact(session, project_id, kind="story_graph")
    if story is None or not story.content:
        raise AppError("该项目尚未生成剧情图（StoryGraph）", code="no_story_graph", status=400)
    return story.content or {}


def _locate_node(graph: dict, node_id: str) -> dict:
    node = next((n for n in graph.get("nodes", []) if n.get("node_id") == node_id), None)
    if node is None:
        raise AppError(f"StoryGraph 中不存在节点 {node_id}", code="node_not_found", status=404)
    return node


def _validate_choice(node: dict, choice_id: str | None) -> None:
    if choice_id is None:
        return
    if not any(c.get("choice_id") == choice_id for c in node.get("choices", [])):
        raise AppError(f"节点 {node.get('node_id')} 中不存在选择 {choice_id}", code="choice_not_found", status=404)


def _build_upstream(session: Session, project_id: str, node_id: str) -> dict:
    """按 kind 组装上游：world_bible + 全部 character_card + relationship_graph + story_graph + scene:{node_id}。"""
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
    scene = latest_artifact(session, project_id, kind=f"scene:{node_id}")
    if scene is not None:
        upstream[f"scene:{node_id}"] = {"kind": f"scene:{node_id}", "content": scene.content or {}}
    return upstream


def _validate_references(content: dict, graph: dict, character_ids: set[str]) -> None:
    """LLM 输出不能直接落盘：先做引用校验（speaker/target/next_node/变量）。"""
    node_ids = {n.get("node_id") for n in graph.get("nodes", [])}
    var_names = {v.get("name") for v in graph.get("variables", [])}
    for line in content.get("lines", []):
        speaker = line.get("speaker")
        if speaker not in character_ids:
            raise AppError(f"对白 speaker {speaker} 不是已登记角色", code="speaker_not_found", status=422)
        target = line.get("target")
        if target is not None and target not in character_ids:
            raise AppError(f"对白 target {target} 不是已登记角色", code="target_not_found", status=422)
    next_node = content.get("next_node")
    if next_node is not None and next_node not in node_ids:
        raise AppError(f"next_node {next_node} 不存在于 StoryGraph", code="next_node_not_found", status=422)
    for cond in content.get("conditions", []):
        variable = cond.get("variable")
        if variable not in var_names:
            raise AppError(f"condition 引用未声明变量 {variable}", code="variable_not_found", status=422)
    for effect in content.get("effects", []):
        variable = effect.get("variable")
        if variable not in var_names:
            raise AppError(f"effect 引用未声明变量 {variable}", code="variable_not_found", status=422)


def _expand_line(lines: list[dict], instruction: str) -> dict:
    speaker = lines[-1].get("speaker", "char-01") if lines else "char-01"
    return {
        "speaker": speaker, "text": f"（扩写）{instruction}" if instruction else "（扩写）",
        "emotion": "", "delivery": "", "action": "", "target": None, "relationship_context": "",
    }


async def run_dialogue_operation(
    session: Session,
    project_id: str,
    *,
    operation: str,
    node_id: str,
    choice_id: str | None = None,
    instruction: str | None = None,
) -> dict:
    project = session.get(Project, project_id)
    if project is None:
        raise NotFoundError("项目不存在")
    if operation in ("revise", "expand") and not (instruction or "").strip():
        raise AppError(f"操作 {operation} 需要 instruction", code="instruction_required", status=400)

    spec, plan = _plan(session, project_id)
    graph = _story_graph(session, project_id)
    node = _locate_node(graph, node_id)
    if node.get("locked"):
        raise AppError("该节点已被用户锁定，无法生成或修改对白", code="locked_node", status=409)
    _validate_choice(node, choice_id)

    ensure_dialogue_prompt(session)
    upstream = _build_upstream(session, project_id, node_id)
    context = compile_dialogue_context(upstream, node_id=node_id, choice_id=choice_id, instruction=instruction or None)
    objective = instruction.strip() if instruction else "生成该对白"
    kind = dialogue_kind(node_id, choice_id)
    task = ProductionTask(
        id=f"dialogue-{dialogue_id(node_id, choice_id)}", agent_type="dialogue", objective=objective,
        dependencies=[], output_schema={"type": "object"},
    )

    revision = None
    current = latest_artifact(session, project_id, kind=kind)
    if operation == "revise":
        revision = {"instruction": instruction, "previous": current.content if current else None}
    elif operation == "expand":
        revision = {"instruction": f"扩写：{instruction}", "previous": current.content if current else None}

    run = trace_manager.start_run(
        session, kind=f"dialogue_{operation}",
        meta={"node_id": node_id, "choice_id": choice_id, "instruction": (instruction or "")[:200]},
    )
    try:
        result = await registry.get("dialogue").run({
            "session": session, "run": run, "task": task, "goal": project.goal,
            "plan": plan,
            "project": {"genre": plan.genre, "tone": plan.tone, "project_type": plan.project_type},
            "upstream": upstream, "node_id": node_id, "choice_id": choice_id,
            "context": context, "instruction": instruction or None, "revision": revision,
        })
    except AppError:
        trace_manager.finish_run(run, status="failed")
        session.commit()
        raise

    # 服务端强制稳定标识（不信任模型输出）
    content = result.get("artifact", {}).get("content", {})
    content["dialogue_id"] = dialogue_id(node_id, choice_id)
    content["node_id"] = node_id
    content["choice_id"] = choice_id

    if operation == "expand":
        content.setdefault("lines", []).append(_expand_line(content.get("lines", []), instruction or ""))

    cards = artifacts_of_kind(upstream, "character_card")
    character_ids = {c.get("character_id") for c in cards if c.get("character_id")}
    _validate_references(content, graph, character_ids)

    trace_manager.finish_run(run, status="ok")
    if operation == "generate":
        change_reason = f"局部生成对白 {kind}"
        source = "agent"
    elif operation == "expand":
        change_reason = f"[expand] {instruction}"
        source = "user"
    else:
        change_reason = instruction
        source = "user"

    persist_versioned_artifact(
        session,
        project_id=project_id,
        task_id=node_id,
        agent="dialogue",
        kind=kind,
        content=content,
        prompt_version=result.get("prompt_version", ""),
        source=source,
        change_reason=change_reason,
    )
    project.current_version += 1
    session.commit()
    return read_orchestration(session, project_id)