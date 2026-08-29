"""CharacterAgent：YIWA 第二个下游内容 Agent（Step 7）。

输入：User Goal + AgentPlan + Project Context + 上游 WorldBible（Orchestrator 按任务依赖注入）。
输出：结构化 CharacterCard（character_generation PromptVersion -> generate_structured -> 校验 -> Artifact）。

Step 8：支持 revision（用户修改请求），在 prompt 中注入「修改要求 + 当前基线」以产出 v2。
"""
import json

from app.agents.base import BaseAgent
from app.agents.generation import generate_structured
from app.core.errors import AppError
from app.llm.provider import get_script_provider
from app.llm.types import TokenBudget
from app.schemas.character_card import CharacterCard, character_card_json_schema
from app.services.prompts import get_definition, get_latest, prompt_tag, render
from app.services.upstream import first_of_kind
from app.trace.manager import trace_manager

CHARACTER_BUDGET = TokenBudget(max_input_tokens=8192, max_output_tokens=16384, max_total_tokens=24576)


class CharacterAgent(BaseAgent):
    name = "character"
    layer = "content"
    description = "角色设计师：把创意 + 世界观解构为结构化 CharacterCard"
    input_schema = {"type": "object", "properties": {"goal": {"type": "string"}}, "required": ["goal"]}
    output_schema = character_card_json_schema()

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
        budget = input_data.get("budget") or CHARACTER_BUDGET

        version = _load_character_prompt(session)
        tag = prompt_tag("character_generation", version.version_no)
        temperature = (version.model_preferences or {}).get("temperature")
        requirements = _build_requirements(task, plan, project, input_data.get("revision"))
        world_summary = _build_world_summary(upstream)
        system = render(version, {"goal": goal, "requirements": requirements, "world": world_summary})

        trace_manager.add_step(
            session, run, agent="character", step_key="character.input",
            input_data={"task": task.id, "goal": goal, "has_world_bible": bool(world_summary)},
            output_data={"prompt_version": tag},
        )

        card, response, attempts = await generate_structured(
            session, run, agent="character", provider=provider, budget=budget,
            prompt_version=tag, temperature=temperature, system=system, user=goal,
            json_schema=character_card_json_schema(), validate=CharacterCard.model_validate,
            max_attempts=self.max_attempts,
        )

        trace_manager.add_step(
            session, run, agent="character", step_key="artifact",
            input_data={"task": task.id},
            output_data={"kind": "character_card", "character_id": card.character_id}, status="ok",
        )
        return {
            "ok": True, "agent": "character",
            "artifact": {"kind": f"character_card:{card.character_id}", "content": card.model_dump()},
            "prompt_version": tag, "provider": response.provider, "model": response.model,
            "usage": response.usage.model_dump(), "latency_ms": response.latency_ms, "attempts": attempts,
        }


def _load_character_prompt(session):
    definition = get_definition(session, "character_generation")
    if definition is None:
        raise AppError("character_generation 未初始化", code="prompt_missing", status=500)
    version = get_latest(session, definition, status="active") or get_latest(session, definition)
    if version is None:
        raise AppError("character_generation 无可用版本", code="prompt_missing", status=500)
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
        parts.append(f"角色要求：{task.objective}")
    if getattr(plan, "characters_required", ""):
        parts.append(f"角色补充：{plan.characters_required}")
    return "；".join(parts)


def _build_world_summary(upstream: dict) -> str:
    """把上游 WorldBible 压成一行上下文注入 prompt（按 task_id 键化的 upstream 读取）。"""
    world = first_of_kind(upstream, "world_bible") or {}
    parts = []
    if world.get("title"):
        parts.append(f"世界观《{world['title']}》")
    if world.get("setting"):
        parts.append(world["setting"])
    if world.get("era"):
        parts.append(f"时代：{world['era']}")
    if world.get("location"):
        parts.append(f"地点：{world['location']}")
    return "；".join(parts) if parts else "（无上游世界观上下文）"