"""StepAgent：YIWA 第四个下游内容 Agent（Step 10）。

输入：upstream 的 WorldBible + CharacterCard[] + RelationshipGraph（按 task_id 键化）。
输出：结构化 StoryGraph（plot_generation PromptVersion -> generate_structured -> 校验 -> Artifact）。

StoryGraph 表达互动叙事：scene/choice/branch/ending 节点 + 边 + 变量 + 玩家选择效果。
本 Agent 只生产"结构 + 剧情摘要"，完整场景正文/对白由未来 SceneAgent/DialogueAgent 逐层生产。
"""
import json

from app.agents.base import BaseAgent
from app.agents.generation import generate_structured
from app.core.errors import AppError
from app.llm.provider import get_script_provider
from app.llm.types import TokenBudget
from app.schemas.story_graph import StoryGraph, story_graph_json_schema
from app.services.prompts import get_definition, get_latest, prompt_tag, render
from app.services.upstream import artifacts_of_kind, first_of_kind
from app.trace.manager import trace_manager

PLOT_BUDGET = TokenBudget(max_input_tokens=12288, max_output_tokens=16384, max_total_tokens=28672)


class PlotAgent(BaseAgent):
    name = "plot"
    layer = "content"
    description = "剧情/Story 设计师：把世界观 + 角色卡 + 关系图解构为互动剧情图 StoryGraph"
    input_schema = {"type": "object", "properties": {"goal": {"type": "string"}}, "required": ["goal"]}
    output_schema = story_graph_json_schema()

    def __init__(self, max_attempts: int = 3):
        self.max_attempts = max_attempts

    async def run(self, input_data: dict) -> dict:
        session = input_data["session"]
        run = input_data["run"]
        task = input_data["task"]
        goal = input_data["goal"]
        plan = input_data["plan"]
        project = input_data.get("project", {})
        upstream = input_data.get("upstream", {})
        provider = input_data.get("provider") or get_script_provider()
        budget = input_data.get("budget") or PLOT_BUDGET

        version = _load_plot_prompt(session)
        tag = prompt_tag("plot_generation", version.version_no)
        temperature = (version.model_preferences or {}).get("temperature")
        requirements = _build_requirements(task, plan, project, input_data.get("revision"))
        system = render(version, {
            "goal": goal, "requirements": requirements,
            "characters": _build_characters_summary(upstream),
            "relationships": _build_relationships_summary(upstream),
            "world": _build_world_summary(upstream),
        })

        trace_manager.add_step(
            session, run, agent="plot", step_key="plot.input",
            input_data={"task": task.id, "goal": goal},
            output_data={"prompt_version": tag, "character_count": len(artifacts_of_kind(upstream, "character_card"))},
        )

        graph, response, attempts = await generate_structured(
            session, run, agent="plot", provider=provider, budget=budget,
            prompt_version=tag, temperature=temperature, system=system, user=goal,
            json_schema=story_graph_json_schema(),
            validate=StoryGraph.model_validate,
            max_attempts=self.max_attempts,
        )

        trace_manager.add_step(
            session, run, agent="plot", step_key="artifact",
            input_data={"task": task.id},
            output_data={"kind": "story_graph", "node_count": len(graph.nodes), "edge_count": len(graph.edges)},
            status="ok",
        )
        return {
            "ok": True, "agent": "plot",
            "artifact": {"kind": "story_graph", "content": graph.model_dump()},
            "prompt_version": tag, "provider": response.provider, "model": response.model,
            "usage": response.usage.model_dump(), "latency_ms": response.latency_ms, "attempts": attempts,
        }


def _load_plot_prompt(session):
    definition = get_definition(session, "plot_generation")
    if definition is None:
        raise AppError("plot_generation 未初始化", code="prompt_missing", status=500)
    version = get_latest(session, definition, status="active") or get_latest(session, definition)
    if version is None:
        raise AppError("plot_generation 无可用版本", code="prompt_missing", status=500)
    return version


def _build_requirements(task, plan, project, revision: dict | None = None) -> str:
    parts = []
    if project.get("genre"):
        parts.append(f"题材：{project['genre']}")
    if project.get("tone"):
        parts.append(f"基调：{project['tone']}")
    if revision:
        parts.append(f"修改要求：{revision.get('instruction') or task.objective}")
        previous = revision.get("previous")
        if previous:
            parts.append(f"当前基线（JSON）：{json.dumps(previous, ensure_ascii=False)[:1600]}")
    elif task.objective:
        parts.append(f"剧情要求：{task.objective}")
    parts.append("已锁定节点不可修改（locked=true 的节点必须原样保留）")
    return "；".join(parts)


def _build_characters_summary(upstream: dict) -> str:
    cards = artifacts_of_kind(upstream, "character_card")
    if not cards:
        return "（无上游角色卡）"
    items = [f"{c.get('character_id', '?')} {c.get('name', '')}({c.get('role', '')})" for c in cards]
    return "；".join(items)


def _build_relationships_summary(upstream: dict) -> str:
    graph = first_of_kind(upstream, "relationship_graph")
    if not graph or not graph.get("edges"):
        return "（无人物关系边）"
    lines = []
    for e in graph["edges"]:
        lines.append(f"{e.get('source_character')}—{e.get('relationship_type')}→{e.get('target_character')}")
    return "；".join(lines)


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