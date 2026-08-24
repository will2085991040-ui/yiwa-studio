"""共享的结构化生成编排：内容 Agent 复用同一「generate_structured + jsonschema/Pydantic 校验 + 反馈重试 + Trace」链路。

Director 与各内容 Agent（World/Character/...）都需要：LLMRequest -> generate_structured -> 语义校验 -> 失败反馈重试。
此模块把该循环抽出，供 WorldAgent（Step 6）复用；Director（Step 5）后续可逐步迁移。
"""
import json

from pydantic import ValidationError

from app.core.errors import AppError
from app.llm.types import LLMProviderError, LLMRequest, TokenBudget
from app.trace.manager import trace_manager


def _coerce_value(value, schema):
    """Schema 感知的容错：把 LLM 返回的类型错位“软化”为字段期望类型。

    - 期望 string 却给了 list[str] -> 以换行 join（针对推理/推理模型常把一整个角色组塞进单个字符串字段的
      情况，例如 CharacterCard.background / secret 收到多行的角色清单）。
    - 期望 array 却给了 string   -> 包成 [str]。
    - 期望 object 却给了 dict     -> 递归按 properties 处理其字段。
    其余情形原样返回。在 Pydantic 强校验前先兜底，避免 "xxx is not of type 'string'" 整段生成失败。
    """
    if value is None:
        return value
    typ = schema.get("type")
    if not isinstance(typ, list):
        typ = [typ] if typ else []
    # object -> 递归 properties
    if "object" in typ and isinstance(value, dict):
        props = schema.get("properties")
        if props:
            return {k: _coerce_value(v, props[k]) for k, v in value.items() if k in props}
        return value
    # array -> 按 items 逐元素递归
    if "array" in typ and isinstance(value, list):
        items = schema.get("items") or {}
        return [_coerce_value(v, items) for v in value]
    # string 字段收到非字符串
    if "string" in typ and not isinstance(value, str):
        if isinstance(value, list):
            parts = [str(v).strip() for v in value if str(v).strip()]
            return "\n".join(parts) if parts else ""
        if isinstance(value, dict):
            return json.dumps(value, ensure_ascii=False)
        return str(value)
    # array 字段收到字符串
    if "array" in typ and isinstance(value, str):
        return [value] if value.strip() else []
    return value


def coerce_to_json_schema(data, schema):
    """顶层按 schema.properties 逐字段纠正类型；未知字段原样保留交给 pydantic extra 策略。"""
    if not isinstance(data, dict):
        return data
    props = schema.get("properties")
    if not props:
        return data
    return {k: (_coerce_value(v, props[k]) if k in props else v) for k, v in data.items()}


async def generate_structured(
    session,
    run,
    *,
    agent: str,
    provider,
    budget: TokenBudget,
    prompt_version: str,
    temperature,
    system: str,
    user: str,
    json_schema: dict,
    validate,
    max_attempts: int,
):
    """返回 (校验后的 Pydantic 对象, LLMResponse, attempts)；失败抛 AppError。"""
    last_error = "未知错误"
    for attempt in range(max_attempts):
        trace_manager.add_step(
            session, run, agent=agent, step_key="llm.request",
            input_data={"attempt": attempt + 1, "prompt_version": prompt_version, "model": provider.model},
            output_data={"provider": provider.name, "schema": json_schema.get("title", "")},
        )
        request = LLMRequest(
            system=system, user=user, json_schema=json_schema, prompt_version=prompt_version,
            temperature=temperature, budget=budget,
            request_id=f"{agent}-{run.id[:8]}-{attempt + 1}",
        )
        try:
            response = await provider.generate_structured(request)
        except LLMProviderError as exc:
            trace_manager.add_step(
                session, run, agent=agent, step_key="llm.error",
                input_data={"attempt": attempt + 1}, output_data={},
                error=exc.error.message, status="failed",
            )
            raise AppError(f"{agent} 调用 LLM 失败：{exc.error.message}",
                           code="agent_llm_error", status=502) from exc

        trace_manager.add_step(
            session, run, agent=agent, step_key="llm.response",
            input_data={"attempt": attempt + 1},
            output_data={"provider": response.provider, "model": response.model, "latency_ms": response.latency_ms},
            token_usage=response.usage.model_dump(), latency_ms=response.latency_ms,
        )
        try:
            payload = coerce_to_json_schema(response.data or {}, json_schema)
            obj = validate(payload)
        except ValidationError as exc:
            feedback = _feedback(exc)
            last_error = feedback
            trace_manager.add_step(
                session, run, agent=agent, step_key="validation",
                input_data={"attempt": attempt + 1},
                output_data={"valid": False, "errors": feedback}, status="failed",
            )
            system = system + "\n[校验失败，请修正]" + feedback
            continue

        trace_manager.add_step(
            session, run, agent=agent, step_key="validation",
            input_data={"attempt": attempt + 1}, output_data={"valid": True}, status="ok",
        )
        return obj, response, attempt + 1

    raise AppError(f"{agent} 多次尝试仍无法生成合法结构化输出：{last_error}",
                   code="schema_invalid", status=422)


def _feedback(exc: ValidationError) -> str:
    messages = [f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:5]]
    return "；".join(messages)
