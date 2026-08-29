"""Director Agent：YIWA 第一个真实业务 Agent。

职责：把用户自然语言创意规划为 AgentPlan（Multi-Agent 生产计划）。
只规划、不执行内容生成；输出 AgentPlan 后由未来 Orchestrator 调度下游 Agent。

执行链路：
    PromptVersion(director_planning) -> render() -> LLMRequest(AgentPlan 的 JSON Schema)
    -> LLMProvider.generate_structured() -> AgentPlan(Pydantic 校验)
    -> 语义校验失败时反馈重试 -> 完整 Trace。
"""
from pydantic import ValidationError

from app.agents.base import BaseAgent
from app.core.errors import AppError
from app.llm.provider import get_script_provider
from app.llm.types import LLMProviderError, LLMRequest, TokenBudget
from app.schemas.agent_plan import AgentPlan, plan_json_schema
from app.services.prompts import get_definition, get_latest, prompt_tag, render
from app.trace.manager import trace_manager

# Director 自身 LLM 调用预算（确定性）
DIRECTOR_BUDGET = TokenBudget(max_input_tokens=8192, max_output_tokens=16384, max_total_tokens=24576)


class DirectorAgent(BaseAgent):
    name = "director"
    layer = "orchestration"
    description = "目标理解与任务分解：把用户创意规划为 Multi-Agent 生产计划（AgentPlan），只规划不执行"
    input_schema = {"type": "object", "properties": {"goal": {"type": "string"}}, "required": ["goal"]}
    output_schema = plan_json_schema()

    def __init__(self, max_attempts: int = 3):
        self.max_attempts = max_attempts

    async def run(self, input_data: dict) -> dict:
        session = input_data["session"]
        run = input_data["run"]
        goal = input_data["goal"]
        provider = input_data.get("provider") or get_script_provider()
        budget = input_data.get("budget") or DIRECTOR_BUDGET

        version = _load_director_prompt(session)
        tag = prompt_tag("director_planning", version.version_no)
        temperature = (version.model_preferences or {}).get("temperature")
        system = render(version, {"goal": goal})

        trace_manager.add_step(session, run, agent="director", step_key="director.input",
                               input_data={"goal": goal}, output_data={"prompt_version": tag})

        last_error = "未知错误"
        for attempt in range(self.max_attempts):
            trace_manager.add_step(session, run, agent="director", step_key="llm.request",
                                   input_data={"attempt": attempt + 1, "prompt_version": tag, "model": provider.model},
                                   output_data={"provider": provider.name, "schema": "AgentPlan"})
            request = LLMRequest(
                system=system, user=goal, json_schema=plan_json_schema(),
                prompt_version=tag, temperature=temperature, budget=budget,
                request_id=f"dir-{run.id[:8]}-{attempt + 1}",
            )
            try:
                response = await provider.generate_structured(request)
            except LLMProviderError as exc:
                trace_manager.add_step(session, run, agent="director", step_key="llm.error",
                                       input_data={"attempt": attempt + 1}, output_data={},
                                       error=exc.error.message, status="failed")
                raise AppError(f"Director 调用 LLM 失败：{exc.error.message}",
                               code="director_llm_error", status=502) from exc

            trace_manager.add_step(session, run, agent="director", step_key="llm.response",
                                   input_data={"attempt": attempt + 1},
                                   output_data={"provider": response.provider, "model": response.model,
                                                "latency_ms": response.latency_ms},
                                   token_usage=response.usage.model_dump(), latency_ms=response.latency_ms)
            try:
                plan = AgentPlan.model_validate(response.data or {})
            except ValidationError as exc:
                feedback = _validation_feedback(exc)
                last_error = feedback
                trace_manager.add_step(session, run, agent="director", step_key="validation",
                                       input_data={"attempt": attempt + 1},
                                       output_data={"valid": False, "errors": feedback}, status="failed")
                system = system + "\n[校验失败，请修正]" + feedback
                continue

            trace_manager.add_step(session, run, agent="director", step_key="validation",
                                   input_data={"attempt": attempt + 1}, output_data={"valid": True}, status="ok")
            trace_manager.add_step(session, run, agent="director", step_key="final_plan",
                                   input_data={}, output_data={"agent_plan": plan.model_dump()}, status="ok")
            return {
                "agent_plan": plan,
                "prompt_version": tag,
                "provider": response.provider,
                "model": response.model,
                "usage": response.usage.model_dump(),
                "latency_ms": response.latency_ms,
                "attempts": attempt + 1,
            }

        raise AppError(f"Director 多次尝试仍无法生成合法 AgentPlan：{last_error}",
                       code="plan_invalid", status=422)


def _load_director_prompt(session):
    definition = get_definition(session, "director_planning")
    if definition is None:
        raise AppError("director_planning 未初始化", code="prompt_missing", status=500)
    version = get_latest(session, definition, status="active") or get_latest(session, definition)
    if version is None:
        raise AppError("director_planning 无可用版本", code="prompt_missing", status=500)
    return version


def _validation_feedback(exc: ValidationError) -> str:
    messages = [f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:5]]
    return "；".join(messages)