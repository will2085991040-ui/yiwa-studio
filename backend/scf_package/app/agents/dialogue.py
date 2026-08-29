"""DialogueAgent（Step 12）：针对 StoryGraph 指定 (node_id, choice_id) 局部生成对白。

这是「用户主动调用」的 on-demand 创作能力（pipeline=False，不进 Orchestrator DAG 全量生成）。
输入：services/context.py 编译好的 RuntimeContext + PromptDefinition + instruction。
输出：单个 (node_id, choice_id) 的结构化 DialogueContent。

Agent 不做：DB 查询 / Artifact 持久化 / 版本管理 / Trace 管理（仅记录步骤）/ Lock 判断 / State 修改。
这些由 dialogue_service / infrastructure 完成。
"""
import json

from app.agents.base import BaseAgent
from app.agents.generation import generate_structured
from app.core.errors import AppError
from app.llm.provider import get_script_provider
from app.llm.types import TokenBudget
from app.schemas.dialogue import DialogueContent, dialogue_json_schema, dialogue_kind
from app.services.prompts import get_definition, get_latest, prompt_tag, render
from app.trace.manager import trace_manager

DIALOGUE_BUDGET = TokenBudget(max_input_tokens=12288, max_output_tokens=16384, max_total_tokens=28672)


class DialogueAgent(BaseAgent):
    name = "dialogue"
    layer = "content"
    description = "对白设计师：针对 StoryGraph 指定 (node_id, choice_id) 局部生成结构化对白"
    input_schema = {
        "type": "object",
        "properties": {
            "goal": {"type": "string"},
            "node_id": {"type": "string"},
            "choice_id": {"type": ["string", "null"]},
            "instruction": {"type": ["string", "null"]},
        },
        "required": ["goal", "node_id"],
    }
    output_schema = dialogue_json_schema()
    pipeline = False  # on-demand：由用户按 (node_id, choice_id) 局部调用

    def __init__(self, max_attempts: int = 3):
        self.max_attempts = max_attempts

    async def run(self, input_data: dict) -> dict:
        session = input_data["session"]
        run = input_data["run"]
        task = input_data["task"]
        goal = input_data["goal"]
        node_id = input_data["node_id"]
        choice_id = input_data.get("choice_id")
        context = input_data.get("context") or {}
        provider = input_data.get("provider") or get_script_provider()
        budget = input_data.get("budget") or DIALOGUE_BUDGET
        revision = input_data.get("revision")

        if not node_id:
            raise AppError("缺少 node_id（对白必须按 StoryGraph 节点局部生成）", code="node_id_required", status=400)

        version = _load_dialogue_prompt(session)
        tag = prompt_tag("dialogue_generation", version.version_no)
        temperature = (version.model_preferences or {}).get("temperature")

        system = render(version, {
            "goal": goal,
            "skeleton": context.get("skeleton", ""),
            "focus": context.get("focus", ""),
            "scene": context.get("scene", ""),
            "characters": context.get("characters", ""),
            "relationships": context.get("relationships", ""),
            "protected": context.get("protected", ""),
        })
        system = _apply_revision(system, revision)

        trace_manager.add_step(
            session, run, agent="dialogue", step_key="dialogue.input",
            input_data={
                "task": task.id, "node_id": node_id, "choice_id": choice_id,
                "goal": goal, "instruction": (input_data.get("instruction") or ""),
                "context": {"missing": context.get("missing", [])},
            },
            output_data={"prompt_version": tag},
        )

        content, response, attempts = await generate_structured(
            session, run, agent="dialogue", provider=provider, budget=budget,
            prompt_version=tag, temperature=temperature, system=system, user=goal,
            json_schema=dialogue_json_schema(),
            validate=DialogueContent.model_validate,
            max_attempts=self.max_attempts,
        )
        # 稳定引用：node_id / choice_id 由服务端强制（不依赖模型输出）；这里仅作第一次对齐
        content.node_id = node_id
        content.choice_id = choice_id

        trace_manager.add_step(
            session, run, agent="dialogue", step_key="artifact",
            input_data={"task": task.id, "node_id": node_id, "choice_id": choice_id},
            output_data={"kind": dialogue_kind(node_id, choice_id), "event_count": len(content.lines)}, status="ok",
        )
        return {
            "ok": True, "agent": "dialogue", "node_id": node_id, "choice_id": choice_id,
            "artifact": {"kind": "dialogue", "content": content.model_dump()},
            "prompt_version": tag, "provider": response.provider, "model": response.model,
            "usage": response.usage.model_dump(), "latency_ms": response.latency_ms, "attempts": attempts,
        }


def _load_dialogue_prompt(session):
    definition = get_definition(session, "dialogue_generation")
    if definition is None:
        raise AppError("dialogue_generation 未初始化", code="prompt_missing", status=500)
    version = get_latest(session, definition, status="active") or get_latest(session, definition)
    if version is None:
        raise AppError("dialogue_generation 无可用版本", code="prompt_missing", status=500)
    return version


def _apply_revision(system: str, revision: dict | None) -> str:
    if not revision:
        return system
    parts = [system]
    if revision.get("instruction"):
        parts.append(f"[修改要求] {revision['instruction']}")
    previous = revision.get("previous")
    if previous:
        parts.append(f"[当前基线 JSON] {json.dumps(previous, ensure_ascii=False)[:1600]}")
    return "\n".join(parts)