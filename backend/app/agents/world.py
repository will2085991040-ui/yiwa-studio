"""WorldAgent：YIWA 第一个下游内容 Agent。

输入：User Goal + AgentPlan + Project Context（由 Orchestrator 调度传入）。
输出：结构化 WorldBible（world_generation PromptVersion -> generate_structured -> 校验 -> Artifact）。

Step 8：支持 revision（用户修改请求），在 prompt 中注入「修改要求 + 当前基线」以产出 v2。
"""
import json

from app.agents.base import BaseAgent
from app.agents.generation import generate_structured
from app.core.errors import AppError
from app.llm.provider import get_script_provider
from app.llm.types import TokenBudget
from app.schemas.world_bible import WorldBible, world_bible_json_schema
from app.services.prompts import get_definition, get_latest, prompt_tag, render
from app.trace.manager import trace_manager

WORLD_BUDGET = TokenBudget(max_input_tokens=8192, max_output_tokens=16384, max_total_tokens=24576)


class WorldAgent(BaseAgent):
    name = "world"
    layer = "content"
    description = "世界观设计师：把目标与计划解构为结构化 WorldBible"
    input_schema = {"type": "object", "properties": {"goal": {"type": "string"}}, "required": ["goal"]}
    output_schema = world_bible_json_schema()

    def __init__(self, max_attempts: int = 3):
        self.max_attempts = max_attempts

    async def run(self, input_data: dict) -> dict:
        session = input_data["session"]
        run = input_data["run"]
        task = input_data["task"]
        goal = input_data["goal"]
        plan = input_data["plan"]
        project = input_data.get("project", {})
        provider = input_data.get("provider") or get_script_provider()
        budget = input_data.get("budget") or WORLD_BUDGET

        version = _load_world_prompt(session)
        tag = prompt_tag("world_generation", version.version_no)
        temperature = (version.model_preferences or {}).get("temperature")
        requirements = _build_requirements(task, plan, project, input_data.get("revision"))
        system = render(version, {"goal": goal, "requirements": requirements})

        trace_manager.add_step(
            session, run, agent="world", step_key="world.input",
            input_data={"task": task.id, "goal": goal}, output_data={"prompt_version": tag},
        )

        bible, response, attempts = await generate_structured(
            session, run, agent="world", provider=provider, budget=budget,
            prompt_version=tag, temperature=temperature, system=system, user=goal,
            json_schema=world_bible_json_schema(), validate=WorldBible.model_validate,
            max_attempts=self.max_attempts,
        )

        trace_manager.add_step(
            session, run, agent="world", step_key="artifact",
            input_data={"task": task.id},
            output_data={"kind": "world_bible", "world_id": bible.world_id}, status="ok",
        )
        return {
            "ok": True, "agent": "world",
            "artifact": {"kind": "world_bible", "content": bible.model_dump()},
            "prompt_version": tag, "provider": response.provider, "model": response.model,
            "usage": response.usage.model_dump(), "latency_ms": response.latency_ms, "attempts": attempts,
        }


def _load_world_prompt(session):
    definition = get_definition(session, "world_generation")
    if definition is None:
        raise AppError("world_generation 未初始化", code="prompt_missing", status=500)
    version = get_latest(session, definition, status="active") or get_latest(session, definition)
    if version is None:
        raise AppError("world_generation 无可用版本", code="prompt_missing", status=500)
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
        parts.append(f"任务目标：{task.objective}")
    if getattr(plan, "worldbuilding_required", ""):
        parts.append(f"世界观要求：{plan.worldbuilding_required}")
    return "；".join(parts)