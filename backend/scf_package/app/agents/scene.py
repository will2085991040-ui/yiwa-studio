"""SceneAgent：按节点局部生产场景内容（Step 11）。

这是「用户主动调用」的创作工具能力，不参与流水线全量生成（pipeline=False）。
输入：WorldBible + CharacterCard[] + RelationshipGraph + StoryGraph + 指定 node_id（含前后节点/选择/变量）+ 用户意图。
输出：单个场景的结构化 SceneContent（不含对白，对白留给 Step12 DialogueAgent）。
"""
import json

from app.agents.base import BaseAgent
from app.agents.generation import generate_structured
from app.core.errors import AppError
from app.llm.provider import get_script_provider
from app.llm.types import TokenBudget
from app.schemas.scene import SceneContent, scene_json_schema
from app.services.prompts import get_definition, get_latest, prompt_tag, render
from app.services.upstream import artifacts_of_kind, first_of_kind
from app.trace.manager import trace_manager

SCENE_BUDGET = TokenBudget(max_input_tokens=12288, max_output_tokens=16384, max_total_tokens=28672)


class SceneAgent(BaseAgent):
    name = "scene"
    layer = "content"
    description = "场景设计师：针对 StoryGraph 中指定 SceneNode 局部生成可编辑的场景内容（不含对白）"
    input_schema = {
        "type": "object",
        "properties": {"goal": {"type": "string"}, "node_id": {"type": "string"}},
        "required": ["goal", "node_id"],
    }
    output_schema = scene_json_schema()
    pipeline = False  # on-demand：由用户按节点主动调用

    def __init__(self, max_attempts: int = 3):
        self.max_attempts = max_attempts

    async def run(self, input_data: dict) -> dict:
        session = input_data["session"]
        run = input_data["run"]
        task = input_data["task"]
        goal = input_data["goal"]
        node_id = input_data.get("node_id")
        upstream = input_data.get("upstream", {})
        provider = input_data.get("provider") or get_script_provider()
        budget = input_data.get("budget") or SCENE_BUDGET
        revision = input_data.get("revision")

        if not node_id:
            raise AppError("缺少 node_id（场景必须按 StoryGraph 节点局部生成）", code="node_id_required", status=400)

        version = _load_scene_prompt(session)
        tag = prompt_tag("scene_generation", version.version_no)
        temperature = (version.model_preferences or {}).get("temperature")

        node, ctx = _locate_node(upstream, node_id)
        if node.get("locked"):
            raise AppError("该场景节点已被用户锁定，无法生成或修改", code="locked_node", status=409)

        system = render(version, {
            "goal": goal,
            "requirements": _build_requirements(node_id, node, ctx, task, revision),
            "characters": _build_characters_summary(upstream),
            "relationships": _build_relationships_summary(upstream),
            "world": _build_world_summary(upstream),
        })

        trace_manager.add_step(
            session, run, agent="scene", step_key="scene.input",
            input_data={"task": task.id, "node_id": node_id, "goal": goal},
            output_data={"prompt_version": tag},
        )

        content, response, attempts = await generate_structured(
            session, run, agent="scene", provider=provider, budget=budget,
            prompt_version=tag, temperature=temperature, system=system, user=goal,
            json_schema=scene_json_schema(),
            validate=SceneContent.model_validate,
            max_attempts=self.max_attempts,
        )
        # 稳定引用：scene_id 强制等于 StoryGraph.node_id（不依赖模型输出）
        content.scene_id = node_id

        trace_manager.add_step(
            session, run, agent="scene", step_key="artifact",
            input_data={"task": task.id, "node_id": node_id},
            output_data={"kind": f"scene:{node_id}", "event_count": len(content.events)}, status="ok",
        )
        return {
            "ok": True, "agent": "scene", "node_id": node_id,
            "artifact": {"kind": "scene", "content": content.model_dump()},
            "prompt_version": tag, "provider": response.provider, "model": response.model,
            "usage": response.usage.model_dump(), "latency_ms": response.latency_ms, "attempts": attempts,
        }


def _load_scene_prompt(session):
    definition = get_definition(session, "scene_generation")
    if definition is None:
        raise AppError("scene_generation 未初始化", code="prompt_missing", status=500)
    version = get_latest(session, definition, status="active") or get_latest(session, definition)
    if version is None:
        raise AppError("scene_generation 无可用版本", code="prompt_missing", status=500)
    return version


def _locate_node(upstream: dict, node_id: str) -> tuple[dict, dict]:
    """在 StoryGraph 中定位 node 并计算其前后关系/选择/变量上下文。"""
    graph = first_of_kind(upstream, "story_graph")
    if not graph:
        raise AppError("上游缺少 StoryGraph，无法定位场景节点", code="no_story_graph", status=400)
    node = next((n for n in graph.get("nodes", []) if n.get("node_id") == node_id), None)
    if node is None:
        raise AppError(f"StoryGraph 中不存在节点 {node_id}", code="node_not_found", status=404)

    edges = graph.get("edges", [])
    predecessors = [e["source"] for e in edges if e.get("target") == node_id]
    successors = [e["target"] for e in edges if e.get("source") == node_id]
    ctx = {
        "predecessors": predecessors,
        "successors": successors,
        "choices": node.get("choices", []),
        "variables": graph.get("variables", []),
        "kind": node.get("kind"),
        "entry_conditions": node.get("entry_conditions", []),
    }
    return node, ctx


def _build_requirements(node_id: str, node: dict, ctx: dict, task, revision: dict | None = None) -> str:
    parts = [f"节点 node_id={node_id}", f"节点类型={ctx['kind']}", f"标题={node.get('title', '')}"]
    if node.get("summary"):
        parts.append(f"摘要={node['summary']}")
    if ctx["predecessors"]:
        parts.append(f"前置节点={','.join(ctx['predecessors'])}")
    if ctx["successors"]:
        parts.append(f"后续节点={','.join(ctx['successors'])}")
    if ctx["choices"]:
        parts.append("选择=" + "；".join(f"{c['text']} -> {c.get('next_node') or '（无）'}" for c in ctx["choices"]))
    if ctx["variables"]:
        parts.append("状态变量=" + ",".join(f"{v['name']}={v['initial']}" for v in ctx["variables"]))
    if revision:
        parts.append(f"修改要求：{revision.get('instruction') or task.objective}")
        previous = revision.get("previous")
        if previous:
            parts.append(f"当前基线（JSON）：{json.dumps(previous, ensure_ascii=False)[:1600]}")
    elif task.objective:
        parts.append(f"场景要求：{task.objective}")
    return "；".join(parts)


def _build_characters_summary(upstream: dict) -> str:
    cards = artifacts_of_kind(upstream, "character_card")
    if not cards:
        return "（无上游角色卡）"
    return "；".join(f"{c.get('character_id', '?')} {c.get('name', '')}({c.get('role', '')})" for c in cards)


def _build_relationships_summary(upstream: dict) -> str:
    graph = first_of_kind(upstream, "relationship_graph")
    if not graph or not graph.get("edges"):
        return "（无人物关系边）"
    return "；".join(
        f"{e.get('source_character')}—{e.get('relationship_type')}→{e.get('target_character')}"
        for e in graph["edges"]
    )


def _build_world_summary(upstream: dict) -> str:
    world = first_of_kind(upstream, "world_bible")
    if not world:
        return "（无上游世界观）"
    parts = []
    if world.get("title"):
        parts.append(f"世界观《{world['title']}》")
    if world.get("setting"):
        parts.append(world["setting"])
    return "；".join(parts)