"""RelationshipAgent：YIWA 第三个下游内容 Agent（Step 9）。

输入：上游 WorldBible + CharacterCard（Orchestrator 按 task_id 注入 upstream）。
输出：结构化 RelationshipGraph（relationship_generation PromptVersion -> generate_structured -> 校验 -> Artifact）。

RelationshipGraph 服务互动游戏：affection/trust/hostility 是可被玩家选择改变的状态维度，
possible_changes 用 StoryEffect 表达，供未来 Choice/Plot/Dialogue/Runtime 消费。
"""
import json

from app.agents.base import BaseAgent
from app.agents.generation import generate_structured
from app.core.errors import AppError
from app.llm.provider import get_script_provider
from app.llm.types import TokenBudget
from app.schemas.relationship_graph import RelationshipGraph, relationship_graph_json_schema
from app.services.prompts import get_definition, get_latest, prompt_tag, render
from app.services.upstream import artifacts_of_kind, first_of_kind
from app.trace.manager import trace_manager

RELATIONSHIP_BUDGET = TokenBudget(max_input_tokens=8192, max_output_tokens=16384, max_total_tokens=24576)


class RelationshipAgent(BaseAgent):
    name = "relationship"
    layer = "content"
    description = "关系设计师：把角色卡 + 世界观解构为互动关系图 RelationshipGraph"
    input_schema = {"type": "object", "properties": {"goal": {"type": "string"}}, "required": ["goal"]}
    output_schema = relationship_graph_json_schema()

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
        budget = input_data.get("budget") or RELATIONSHIP_BUDGET

        version = _load_relationship_prompt(session)
        tag = prompt_tag("relationship_generation", version.version_no)
        temperature = (version.model_preferences or {}).get("temperature")
        requirements = _build_requirements(task, plan, project, input_data.get("revision"))
        characters_summary = _build_characters_summary(upstream)
        world_summary = _build_world_summary(upstream)
        system = render(version, {
            "goal": goal, "requirements": requirements,
            "characters": characters_summary, "world": world_summary,
        })

        trace_manager.add_step(
            session, run, agent="relationship", step_key="relationship.input",
            input_data={
                "task": task.id, "goal": goal,
                "character_count": len(artifacts_of_kind(upstream, "character_card")),
            },
            output_data={"prompt_version": tag},
        )

        graph, response, attempts = await generate_structured(
            session, run, agent="relationship", provider=provider, budget=budget,
            prompt_version=tag, temperature=temperature, system=system, user=goal,
            json_schema=relationship_graph_json_schema(),
            validate=RelationshipGraph.model_validate,
            max_attempts=self.max_attempts,
        )

        trace_manager.add_step(
            session, run, agent="relationship", step_key="artifact",
            input_data={"task": task.id},
            output_data={"kind": "relationship_graph", "edge_count": len(graph.edges)}, status="ok",
        )
        return {
            "ok": True, "agent": "relationship",
            "artifact": {"kind": "relationship_graph", "content": graph.model_dump()},
            "prompt_version": tag, "provider": response.provider, "model": response.model,
            "usage": response.usage.model_dump(), "latency_ms": response.latency_ms, "attempts": attempts,
        }


def _load_relationship_prompt(session):
    definition = get_definition(session, "relationship_generation")
    if definition is None:
        raise AppError("relationship_generation 未初始化", code="prompt_missing", status=500)
    version = get_latest(session, definition, status="active") or get_latest(session, definition)
    if version is None:
        raise AppError("relationship_generation 无可用版本", code="prompt_missing", status=500)
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
            parts.append(f"当前基线（JSON）：{json.dumps(previous, ensure_ascii=False)[:1200]}")
    elif task.objective:
        parts.append(f"关系要求：{task.objective}")
    return "；".join(parts)


def _build_characters_summary(upstream: dict) -> str:
    cards = artifacts_of_kind(upstream, "character_card")
    if not cards:
        return "（无上游角色卡）"
    items = [f"{c.get('character_id', '?')} {c.get('name', '')}({c.get('role', '')})" for c in cards]
    return "；".join(items)


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