"""LLM Provider 抽象层：统一契约 + Mock 离线实现 + OpenAI 兼容实现。

契约原则：
- Agent 只依赖 LLMProvider，禁止直接调用任何厂商 SDK。
- 统一入口：generate() / generate_structured() / stream() / embed()。
- 基类确定性负责：输入预算预检、输出预算拦截、结构化 Schema 校验、
  usage/latency/request_id/cost_estimate/prompt_version 记录。
- Phase 0 的 complete() 由契约方法实现，旧接口保留不删除。
"""
import asyncio
import hashlib
import json
import re
import time
import uuid
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any

import httpx
from jsonschema import validate as jsonschema_validate
from jsonschema.exceptions import ValidationError as SchemaValidationError
from pydantic import BaseModel

from app.core.config import settings
from app.llm.pricing import estimate_cost
from app.llm.types import (
    LLMEmbeddingResult,
    LLMError,
    LLMProviderError,
    LLMRequest,
    LLMResponse,
    LLMStreamChunk,
    LLMUsage,
    estimate_tokens,
)
from app.services.credits import charge_from_context


class LLMResult(BaseModel):
    """Phase 0 兼容返回：结构化数据 + 用量。"""

    data: dict[str, Any]
    provider: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0


class LLMProvider(ABC):
    """Provider 统一契约。子类只需实现 _generate / _generate_structured / _stream / _embed。"""

    name: str = "base"
    model: str = "base-1"

    # ------------------------------------------------------------------
    # 统一入口（基类负责预算、记录、结构化校验；子类只负责与模型交互）
    # ------------------------------------------------------------------

    async def generate(self, request: LLMRequest) -> LLMResponse:
        self._check_input_budget(request)
        started = time.perf_counter()
        response = await self._generate(request)
        self._finalize_response(response, request, started)
        self._check_output_budget(request, response)
        self._charge_usage(response)
        return response

    async def generate_structured(self, request: LLMRequest) -> LLMResponse:
        if request.json_schema is None:
            message = "generate_structured() 需要 request.json_schema（JSON Schema）"
            raise self._error("schema_error", message, request=request)
        self._check_input_budget(request)
        started = time.perf_counter()
        response = await self._generate_structured(request)
        if response.data is None:
            raise self._error("schema_error", "Provider 未返回结构化数据", request=request)
        try:
            jsonschema_validate(response.data, request.json_schema)
        except SchemaValidationError as exc:
            raise self._error("schema_error", f"结构化输出不符合 Schema：{exc.message}", request=request) from exc
        self._finalize_response(response, request, started)
        self._check_output_budget(request, response)
        self._charge_usage(response)
        return response

    async def stream(self, request: LLMRequest) -> AsyncIterator[LLMStreamChunk]:
        self._check_input_budget(request)
        request_id = request.request_id or uuid.uuid4().hex
        async for chunk in self._stream(request):
            chunk.request_id = chunk.request_id or request_id
            yield chunk

    async def embed(self, texts: list[str], model: str | None = None) -> LLMEmbeddingResult:
        if not texts or not all(isinstance(text, str) for text in texts):
            raise self._error("provider_error", "embed() 需要非空字符串列表")
        started = time.perf_counter()
        result = await self._embed(texts, model)
        result.request_id = result.request_id or uuid.uuid4().hex
        result.provider = self.name
        result.model = result.model or model or self.model
        result.latency_ms = int((time.perf_counter() - started) * 1000)
        result.cost_estimate = estimate_cost(self.name, result.model, result.usage)
        return result

    # ------------------------------------------------------------------
    # 兼容入口：Phase 0 的 complete() 由契约方法实现，旧接口不删除
    # ------------------------------------------------------------------

    async def complete(self, system: str, user: str, schema: dict) -> LLMResult:
        response = await self.generate_structured(LLMRequest(system=system, user=user, json_schema=schema))
        return LLMResult(
            data=response.data or {},
            provider=response.provider,
            model=response.model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            latency_ms=response.latency_ms,
        )

    def _charge_usage(self, response: LLMResponse) -> None:
        """消费结算：当请求上下文已绑定登录用户时，为该用户记一笔点数扣减（best-effort）。"""
        if response is None or response.usage is None:
            return
        try:
            charge_from_context(
                response.model,
                response.provider,
                response.usage.input_tokens,
                response.usage.output_tokens,
            )
        except Exception:  # noqa: BLE001 - 扣费失败不影响主流程
            pass

    # ------------------------------------------------------------------
    # 子类实现点：每个 Provider 必须显式声明四项能力
    # ------------------------------------------------------------------

    @abstractmethod
    async def _generate(self, request: LLMRequest) -> LLMResponse:
        raise NotImplementedError

    @abstractmethod
    async def _generate_structured(self, request: LLMRequest) -> LLMResponse:
        raise NotImplementedError

    @abstractmethod
    async def _stream(self, request: LLMRequest) -> AsyncIterator[LLMStreamChunk]:
        raise NotImplementedError
        yield  # pragma: no cover —— 使本方法成为异步生成器

    @abstractmethod
    async def _embed(self, texts: list[str], model: str | None) -> LLMEmbeddingResult:
        raise NotImplementedError

    # ------------------------------------------------------------------
    # 确定性预算与记录（Python 强制，不依赖 LLM）
    # ------------------------------------------------------------------

    def _check_input_budget(self, request: LLMRequest) -> int:
        text = " ".join(m.content for m in request.build_messages())
        tokens = estimate_tokens(text)
        if tokens > request.budget.max_input_tokens:
            raise self._error(
                "token_limit",
                f"输入估算 {tokens} tokens 超过预算上限 {request.budget.max_input_tokens}",
                request=request,
            )
        return tokens

    def _check_output_budget(self, request: LLMRequest, response: LLMResponse) -> None:
        budget = request.budget
        if response.usage.output_tokens > budget.max_output_tokens:
            raise self._error(
                "token_limit",
                f"输出 {response.usage.output_tokens} tokens 超过预算上限 {budget.max_output_tokens}",
                request=request,
            )
        if response.usage.total_tokens > budget.max_total_tokens:
            raise self._error(
                "token_limit",
                f"总量 {response.usage.total_tokens} tokens 超过预算上限 {budget.max_total_tokens}",
                request=request,
            )

    def _finalize_response(self, response: LLMResponse, request: LLMRequest, started: float) -> None:
        response.request_id = response.request_id or request.request_id or uuid.uuid4().hex
        response.provider = response.provider or self.name
        response.model = response.model or self.model
        response.latency_ms = int((time.perf_counter() - started) * 1000)
        response.cost_estimate = estimate_cost(response.provider, response.model, response.usage)
        if response.prompt_version is None:
            response.prompt_version = request.prompt_version

    def _error(
        self,
        code: str,
        message: str,
        retryable: bool = False,
        request: LLMRequest | None = None,
        **extra: Any,
    ) -> LLMProviderError:
        return LLMProviderError(
            LLMError(
                code=code,
                message=message,
                provider=self.name,
                model=self.model,
                request_id=request.request_id if request is not None else None,
                retryable=retryable,
                **extra,
            )
        )


class MockProvider(LLMProvider):
    """确定性离线实现：结构化合成 / 文本 / 流式 / 向量全部可离线运行。

    诚实声明：这是 mock，用于自动化测试与离线演示（provider 恒为 "mock"）；
    真实内容生成走 OpenAI 兼容 Provider，绝不冒充真实 LLM。
    """

    name = "mock"
    model = "mock-chat-1"
    embed_model = "mock-embed-1"

    _WORDS = ["目标", "用户", "内容", "互动", "课程", "学生", "体验", "路径", "信任", "转化"]

    def _seed(self, request: LLMRequest) -> str:
        payload = {
            "messages": [m.model_dump() for m in request.build_messages()],
            "json_schema": request.json_schema,
            "max_tokens": request.max_tokens,
        }
        return hashlib.md5(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()

    def _usage(self, request: LLMRequest, output_text: str = "") -> LLMUsage:
        input_text = " ".join(m.content for m in request.build_messages())
        return LLMUsage(input_tokens=estimate_tokens(input_text), output_tokens=estimate_tokens(output_text))

    def _build_text(self, request: LLMRequest) -> str:
        seed = self._seed(request)
        summary = " / ".join(m.content for m in request.build_messages() if m.role == "user")
        limit = min(
            request.max_tokens if request.max_tokens is not None else request.budget.max_output_tokens,
            request.budget.max_output_tokens,
        )
        text = f"[mock:{self.model}] 离线演示回复（种子 {seed[:8]}）。已理解输入：{summary[:60]}"
        return _truncate_to_tokens(text, limit)

    async def _generate(self, request: LLMRequest) -> LLMResponse:
        content = self._build_text(request)
        return LLMResponse(content=content, usage=self._usage(request, content))

    async def _generate_structured(self, request: LLMRequest) -> LLMResponse:
        if request.json_schema and request.json_schema.get("title") == "AgentPlan":
            # 离线演示：确定性生成结构合法的 AgentPlan（provider='mock'，绝不冒充真实 LLM）
            data = _synthesize_agent_plan(request)
        elif request.json_schema and request.json_schema.get("title") == "WorldBible":
            # 离线演示：确定性生成结构合法的 WorldBible
            data = _synthesize_world_bible(request)
        elif request.json_schema and request.json_schema.get("title") == "CharacterCard":
            # 离线演示：确定性生成结构合法的 CharacterCard
            data = _synthesize_character_card(request)
        elif request.json_schema and request.json_schema.get("title") == "RelationshipGraph":
            # 离线演示：确定性生成结构合法的 RelationshipGraph
            data = _synthesize_relationship_graph(request)
        elif request.json_schema and request.json_schema.get("title") == "StoryGraph":
            # 离线演示：确定性生成结构合法的 StoryGraph（长链路 >=60 节点，多分支多结局）
            data = _longchain_story_graph(request)
        elif request.json_schema and request.json_schema.get("title") == "SceneContent":
            # 离线演示：确定性生成结构合法的 SceneContent（Step11）
            data = _synthesize_scene(request)
        elif request.json_schema and request.json_schema.get("title") == "DialogueContent":
            # 离线演示：确定性生成结构合法的 DialogueContent（Step12）
            data = _synthesize_dialogue(request)
        else:
            data = self._synthesize(request.json_schema or {}, self._seed(request), depth=0)
        content = json.dumps(data, ensure_ascii=False)
        return LLMResponse(content=content, data=data, usage=self._usage(request, content))

    async def _stream(self, request: LLMRequest) -> AsyncIterator[LLMStreamChunk]:
        content = self._build_text(request)
        size = 4
        index = 0
        while index == 0 or index * size < len(content):
            delta = content[index * size : (index + 1) * size]
            finished = (index + 1) * size >= len(content)
            yield LLMStreamChunk(
                index=index,
                delta=delta,
                finish_reason="stop" if finished else None,
                usage=self._usage(request, content) if finished else None,
            )
            index += 1

    async def _embed(self, texts: list[str], model: str | None) -> LLMEmbeddingResult:
        dim = 64
        vectors: list[list[float]] = []
        for text in texts:
            vector: list[float] = []
            for i in range(dim):
                digest = hashlib.md5(f"{text}:{i}".encode()).digest()
                vector.append((digest[i % 16] / 255.0) * 2.0 - 1.0)
            vectors.append(vector)
        return LLMEmbeddingResult(
            model=model or self.embed_model,
            vectors=vectors,
            usage=LLMUsage(input_tokens=sum(estimate_tokens(t) for t in texts)),
        )

    def _synthesize(self, schema: dict, seed: str, depth: int) -> Any:
        if depth > 4:
            return None
        t = schema.get("type")
        if t == "object":
            props = schema.get("properties", {})
            return {k: self._synthesize(v, seed + k, depth + 1) for k, v in props.items()}
        if t == "array":
            item_schema = schema.get("items", {"type": "string"})
            n = min(schema.get("minItems", 1), 3)
            return [self._synthesize(item_schema, seed + str(i), depth + 1) for i in range(n)]
        if t == "string":
            if "enum" in schema:
                return schema["enum"][int(seed[:4], 16) % len(schema["enum"])]
            return self._WORDS[int(seed[:4], 16) % len(self._WORDS)]
        if t == "integer" or t == "number":
            return int(seed[:4], 16) % 100
        if t == "boolean":
            return int(seed[:2], 16) % 2 == 0
        return None


class OpenAICompatProvider(LLMProvider):
    """OpenAI 兼容实现（DeepSeek / OpenAI / Qwen / GLM / Moonshot 等）。

    厂商差异全部封装在这里：Agent 只看到 LLMProvider，换 base_url/api_key/model 即可换模型。
    错误统一转成结构化 LLMError（timeout/http_5xx/http_4xx/rate_limit/invalid_json/schema_error），
    采用 retry -> repair -> 结构化报错的固定流程，绝不无限重试。
    transport 参数用于测试注入 httpx.MockTransport，实现全离线验证。
    """

    name = "openai_compat"

    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        timeout: float | None = None,
        max_retries: int | None = None,
        retry_backoff: float | None = None,
        transport: Any = None,
    ) -> None:
        self.base_url = (base_url or settings.llm_base_url).rstrip("/")
        self.api_key = api_key or settings.llm_api_key
        self.model = model or settings.llm_model
        self.timeout = timeout if timeout is not None else settings.llm_timeout_seconds
        self.max_retries = max_retries if max_retries is not None else settings.llm_max_retries
        self.retry_backoff = retry_backoff if retry_backoff is not None else settings.llm_retry_backoff
        self._transport = transport

    # ------------------------------------------------------------------
    # 请求构造：LLMRequest -> OpenAI-compatible wire format
    # ------------------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    def _make_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=self.timeout, transport=self._transport)

    def _url(self, path: str) -> str:
        return f"{self.base_url}/{path}"

    def _usage_from(self, usage: dict) -> LLMUsage:
        return LLMUsage(
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            total_tokens=usage.get("total_tokens", 0),
        )

    def _chat_payload(self, request: LLMRequest, *, structured: bool, stream: bool) -> dict:
        # developer 角色在多数 OpenAI-compatible 端点未区分，统一映射为 system
        messages = [
            {"role": "system" if m.role == "developer" else m.role, "content": m.content}
            for m in request.build_messages()
        ]
        if structured and request.json_schema:
            messages.append(
                {
                    "role": "system",
                    "content": "只输出一个 JSON 对象，值必须严格符合以下 JSON Schema："
                    + json.dumps(request.json_schema, ensure_ascii=False)
                    + "。不要输出 markdown 代码块或任何其他文字。",
                }
            )
        payload: dict[str, Any] = {
            "model": self.model,
            "temperature": request.temperature if request.temperature is not None else settings.llm_temperature,
            "stream": stream,
            # 预算前移到请求层：硬上限 = min(显式 max_tokens, 预算 max_output_tokens)
            "max_tokens": min(
                request.max_tokens if request.max_tokens is not None else request.budget.max_output_tokens,
                request.budget.max_output_tokens,
            ),
            "messages": messages,
        }
        if structured:
            payload["response_format"] = {"type": "json_object"}
        if structured and settings.llm_disable_thinking:
            # 推理模型（DeepSeek/火山方舟 GA）产出 reasoning_content 会很慢；结构化抽取不需要思考
            payload["thinking"] = {"type": "disabled"}
        # 预留 Tool Calling：接口层透传，Step 2 不实现工具执行
        if request.tools:
            payload["tools"] = request.tools
        if request.tool_choice is not None:
            payload["tool_choice"] = request.tool_choice
        return payload

    # ------------------------------------------------------------------
    # 状态分类：HTTP 状态码 -> 结构化 LLMError
    # ------------------------------------------------------------------

    def _check_status(self, status_code: int, body: str, request: LLMRequest | None) -> None:
        preview = body[:200]
        if status_code == 429:
            message = f"上游限流（429）：{preview}"
            raise self._error("rate_limit", message, retryable=True, request=request, status_code=429)
        if status_code >= 500:
            message = f"上游服务错误（{status_code}）：{preview}"
            raise self._error("http_5xx", message, retryable=True, request=request, status_code=status_code)
        if status_code >= 400:
            message = f"请求错误（{status_code}）：{preview}"
            raise self._error("http_4xx", message, retryable=False, request=request, status_code=status_code)

    # ------------------------------------------------------------------
    # 重试：retry -> repair -> 结构化报错，绝不无限重试
    # ------------------------------------------------------------------

    async def _with_retry(self, fn: Any) -> Any:
        last_error: LLMProviderError | None = None
        for attempt in range(self.max_retries + 1):
            try:
                return await fn()
            except LLMProviderError as exc:
                exc.error.retries_attempted = attempt
                last_error = exc
            except httpx.TimeoutException as exc:
                last_error = self._error("timeout", f"请求超时：{exc}", retryable=True)
            except httpx.RequestError as exc:
                last_error = self._error("provider_error", f"网络错误：{exc}", retryable=True)
            if last_error is not None and (not last_error.error.retryable or attempt >= self.max_retries):
                raise last_error
            await self._backoff(attempt)
        raise last_error if last_error is not None else RuntimeError("LLM 重试配置错误：max_retries 必须 >= 0")

    async def _backoff(self, attempt: int) -> None:
        if self.retry_backoff > 0:
            await asyncio.sleep(self.retry_backoff * (2**attempt))

    # ------------------------------------------------------------------
    # 契约实现
    # ------------------------------------------------------------------

    async def _generate(self, request: LLMRequest) -> LLMResponse:
        payload = self._chat_payload(request, structured=False, stream=False)

        async def call() -> tuple[str, dict]:
            async with self._make_client() as client:
                resp = await client.post(self._url("chat/completions"), json=payload, headers=self._headers())
                self._check_status(resp.status_code, resp.text, request)
                try:
                    data = resp.json()
                except (json.JSONDecodeError, ValueError) as exc:
                    raise self._error(
                        "provider_error", f"上游返回非 JSON：{exc}", retryable=True, request=request
                    ) from exc
                return data["choices"][0]["message"]["content"], data.get("usage", {})

        content, usage = await self._with_retry(call)
        return LLMResponse(content=content, usage=self._usage_from(usage))

    async def _generate_structured(self, request: LLMRequest) -> LLMResponse:
        payload = self._chat_payload(request, structured=True, stream=False)

        async def call() -> tuple[dict, str, dict]:
            async with self._make_client() as client:
                resp = await client.post(self._url("chat/completions"), json=payload, headers=self._headers())
                self._check_status(resp.status_code, resp.text, request)
                try:
                    data = resp.json()
                except (json.JSONDecodeError, ValueError) as exc:
                    raise self._error(
                        "provider_error", f"上游返回非 JSON：{exc}", retryable=True, request=request
                    ) from exc
                raw = data["choices"][0]["message"]["content"]
                try:
                    parsed = _parse_json(raw)
                except ValueError as exc:
                    raise self._error(
                        "invalid_json", "模型未返回可用 JSON，将重试", retryable=True, request=request
                    ) from exc
                return parsed, raw, data.get("usage", {})

        data, raw, usage = await self._with_retry(call)
        return LLMResponse(content=raw, data=data, usage=self._usage_from(usage))

    async def _stream(self, request: LLMRequest) -> AsyncIterator[LLMStreamChunk]:
        payload = self._chat_payload(request, structured=False, stream=True)
        index = 0
        async with self._make_client() as client:
            async with client.stream(
                "POST", self._url("chat/completions"), json=payload, headers=self._headers()
            ) as resp:
                if resp.status_code != 200:
                    await resp.aread()
                    self._check_status(resp.status_code, resp.text, request)
                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    token = line[len("data:") :].strip()
                    if token == "[DONE]":
                        break
                    try:
                        obj = json.loads(token)
                    except json.JSONDecodeError:
                        continue
                    choice = obj["choices"][0]
                    delta = choice.get("delta", {}).get("content") or ""
                    finish = choice.get("finish_reason")
                    usage = self._usage_from(obj["usage"]) if obj.get("usage") else None
                    yield LLMStreamChunk(index=index, delta=delta, finish_reason=finish, usage=usage)
                    index += 1

    async def _embed(self, texts: list[str], model: str | None) -> LLMEmbeddingResult:
        emb_model = model or settings.llm_embedding_model or self.model
        payload = {"model": emb_model, "input": texts}

        async def call() -> tuple[list[list[float]], int]:
            async with self._make_client() as client:
                resp = await client.post(self._url("embeddings"), json=payload, headers=self._headers())
                self._check_status(resp.status_code, resp.text, None)
                try:
                    data = resp.json()
                except (json.JSONDecodeError, ValueError) as exc:
                    raise self._error("provider_error", f"上游返回非 JSON：{exc}", retryable=True) from exc
                ordered = sorted(data["data"], key=lambda item: item.get("index", 0))
                vectors = [item["embedding"] for item in ordered]
                return vectors, data.get("usage", {}).get("prompt_tokens", 0)

        vectors, prompt_tokens = await self._with_retry(call)
        return LLMEmbeddingResult(model=emb_model, vectors=vectors, usage=LLMUsage(input_tokens=prompt_tokens))


def _truncate_to_tokens(text: str, limit: int) -> str:
    """把文本截断到 limit tokens 以内（Mock 用；按比例收敛，确定性终止）。"""
    if limit <= 0:
        return ""
    while len(text) > 1 and estimate_tokens(text) > limit:
        text = text[: int(len(text) * 0.8)]
    return text


def _synthesize_agent_plan(request: LLMRequest) -> dict:
    """离线演示（provider='mock'）：确定性生成一个结构合法的 AgentPlan，绝不冒充真实 LLM。

    Director 的业务链路（render -> generate_structured -> Pydantic 校验 -> Trace -> 持久化）
    在 mock 模式下完整跑通；真正的规划语义由 OpenAICompatProvider + 真实 LLM 在冒烟测试中验证。
    """
    goal = " ".join(m.content for m in request.build_messages() if m.role == "user").strip()
    summary = goal if len(goal) <= 80 else goal[:80] + "…"

    def task(tid: str, agent: str, objective: str, deps: list[str] | None = None) -> dict:
        return {
            "id": tid, "agent_type": agent, "objective": objective,
            "dependencies": deps or [], "output_schema": {"type": "object", "properties": {}},
        }

    return {
        "goal": goal or "制作一部互动影视",
        "goal_summary": summary,
        "project_type": "interactive_story",
        "target_audience": "喜欢互动叙事与剧情选择的用户",
        "genre": "互动影视 / Galgame",
        "tone": "沉浸、情感驱动、带悬疑张力",
        "business_objective": "让用户完整走完多结局并愿意复玩",
        "creative_objective": "通过角色与分支营造沉浸体验",
        "required_capabilities": [
            "worldbuilding", "character", "relationship", "story", "scene", "dialogue",
        ],
        "characters_required": "主角与若干配角（含隐藏身份者）",
        "worldbuilding_required": "支撑剧情的世界观与关键设定",
        "story_required": "主线剧情（多章节）",
        "scene_required": "关键互动场景",
        "branch_required": "多条分支与多结局（由 plot 在 StoryGraph 中表达）",
        "dialogue_required": "多角色对话",
        "evaluation_required": "一致性 / 沉浸度 / 选择深度评测（由 finalize 质检承担）",
        "generation_steps": [
            task("s1", "world", f"为「{summary}」构建世界观与核心设定"),
            task("s2", "character", f"为「{summary}」设计角色卡", ["s1"]),
            task("s3", "relationship", "设计角色关系图", ["s1", "s2"]),
            task("s4", "plot", "规划主线剧情（含变量/分支/结局）", ["s1", "s2", "s3"]),
            task("s5", "scene", "为每个剧情节点扩写场景正文", ["s1", "s2", "s3", "s4"]),
            task("s6", "dialogue", "为每个选项节点扩写对白", ["s1", "s2", "s3", "s4", "s5"]),
            task("s7", "finalize", "编译剧本书并质检闭环", ["s4", "s5", "s6"]),
        ],
        "success_metrics": ["选择深度", "结局达成", "复玩率"],
        "constraints": ["角色不 OOC", "分支可达"],
        "budget": {"max_total_tokens": 100000, "max_cost_usd": None},
        "priority": "high",
    }


def _synthesize_world_bible(request: LLMRequest) -> dict:
    """离线演示（provider='mock'）：确定性生成一个结构合法的 WorldBible，绝不冒充真实 LLM。"""
    goal = " ".join(m.content for m in request.build_messages() if m.role == "user").strip()
    summary = goal if len(goal) <= 40 else goal[:40] + "…"
    return {
        "world_id": "world-01",
        "title": f"{summary} 的世界",
        "setting": f"围绕「{summary}」展开的互动叙事世界观，拥有恋爱与悬疑双线张力",
        "era": "现代",
        "location": "都市娱乐公司",
        "rules": ["角色行为受世界观规则约束", "玩家选择会影响走向与关键关系"],
        "social_structure": "娱乐公司职场与幕后势力交织",
        "factions": [
            {"name": "娱乐公司", "description": "故事主要舞台", "role": "主线场景"},
            {"name": "调查方", "description": "隐藏的调查力量", "role": "悬疑线驱动"},
        ],
        "culture": "娱乐圈生态与粉丝文化",
        "technology": "当代都市背景",
        "conflicts": ["恋爱线与悬疑线的注意力争夺", "身份秘密与信任危机"],
        "key_locations": [
            {"name": "公司大楼", "description": "主线发生地"},
            {"name": "拍摄现场", "description": "关键事件舞台"},
        ],
        "world_constraints": ["逻辑自洽", "角色不 OOC"],
        "consistency_notes": "世界观会随角色与剧情 Agent 产出后回填校对",
    }


def _synthesize_character_card(request: LLMRequest) -> dict:
    """离线演示（provider='mock'）：确定性生成一个结构合法的 CharacterCard，绝不冒充真实 LLM。"""
    goal = " ".join(m.content for m in request.build_messages() if m.role == "user").strip()
    summary = goal if len(goal) <= 30 else goal[:30] + "…"
    return {
        "character_id": "char-01",
        "name": "主角",
        "role": "女主",
        "age": "22",
        "gender": "女",
        "appearance": "干练清新的都市新人形象",
        "personality": ["坚韧", "敏锐", "外冷内热"],
        "background": f"在「{summary}」的背景下登场",
        "motivation": "在职场立足并揭开身边秘密",
        "goal": "查明真相、达成理想结局",
        "conflict": "信任与怀疑之间摇摆",
        "fear": "被重要之人背叛",
        "secret": "与关键事件有隐秘关联",
        "relationship_rules": ["对信任的人坦诚", "对可疑者保持戒备"],
        "speech_style": {
            "tone": "克制而温柔", "formality": "偏礼貌",
            "catchphrases": ["嗯……"], "quirks": ["紧张时把玩发梢"],
        },
        "likes": ["音乐", "推理小说"],
        "dislikes": ["被欺骗"],
        "hidden_information": ["其真实身份"],
        "character_arc": ["职场新人", "察觉异常", "直面真相"],
        "possible_endings": ["真相大白", "沉溺谎言"],
    }


def _synthesize_relationship_graph(request: LLMRequest) -> dict:
    """离线演示（provider='mock'）：确定性生成结构合法的 RelationshipGraph。

    注：mock CharacterAgent 只产出单个角色卡（char-01），因此关系图仅一个节点、零条边；
    多角色关系图由 RelationshipAgent 真实消费多张 CharacterCard 时生成（见单测）。
    """
    return {
        "graph_id": "rel-01",
        "characters": ["char-01"],
        "edges": [],
    }


def _synthesize_story_graph(request: LLMRequest) -> dict:
    """离线演示（provider='mock'）：确定性生成结构合法的 StoryGraph。

    表达互动叙事：Scene（scene_01/02a/02b）、Choice（c01a/c01b/c01c）、
    Branch（choice -> next_node + edge）、Condition（var 相乘不验算，仅结构）、
    Effect（affection += 10）、Variable（affection/trust）、Ending（scene_02c kind=ending）。
    """
    return {
        "graph_id": "story-01",
        "entry_node_id": "scene_01",
        "variables": [
            {"name": "affection", "type": "number", "initial": 0, "description": "女主好感度"},
            {"name": "trust", "type": "number", "initial": 0, "description": "信任度"},
        ],
        "nodes": [
            {
                "node_id": "scene_01", "kind": "scene", "title": "入职第一天",
                "content_ref": "scene_01", "summary": "女主进入娱乐公司，暗流涌动",
                "choices": [
                    {
                        "choice_id": "c01a", "text": "帮助女主",
                        "effects": [{"variable": "affection", "op": "add", "value": 10}],
                        "next_node": "scene_02a",
                    },
                    {
                        "choice_id": "c01b", "text": "欺骗女主",
                        "effects": [{"variable": "trust", "op": "add", "value": -10}],
                        "next_node": "scene_02b",
                    },
                    {"choice_id": "c01c", "text": "离开", "next_node": "scene_02c"},
                ],
            },
            {"node_id": "scene_02a", "kind": "scene", "title": "同盟",
             "content_ref": "scene_02a", "summary": "与女主结盟"},
            {"node_id": "scene_02b", "kind": "scene", "title": "裂痕",
             "content_ref": "scene_02b", "summary": "女主起疑"},
            {"node_id": "scene_02c", "kind": "ending", "title": "退出",
             "content_ref": "scene_02c", "summary": "玩家离开"},
        ],
        "edges": [
            {"edge_id": "e1", "source": "scene_01", "target": "scene_02a", "label": "c01a"},
            {"edge_id": "e2", "source": "scene_01", "target": "scene_02b", "label": "c01b"},
            {"edge_id": "e3", "source": "scene_01", "target": "scene_02c", "label": "c01c"},
        ],
        "metadata": {"chapter": 1, "ending_count": 1, "generated_by": "mock-offline-demo"},
    }


def _synthesize_scene(request: LLMRequest) -> dict:
    """离线演示（provider='mock'）：确定性生成结构合法的 SceneContent（Step11）。

    不含对白（对白留给 Step12 DialogueAgent）；scene_id 由服务端强制校正为 node_id。
    """
    return {
        "scene_id": "scene_01",
        "title": "入职第一天",
        "summary": "女主初入娱乐公司，暗流涌动",
        "location": "娱乐公司前台大厅",
        "time": "白天 · 上午",
        "atmosphere": "光鲜外表下的紧张与试探",
        "characters_present": ["char-01"],
        "events": [
            "前台接待引导登记", "与神秘调查员正面相遇", "电梯内暗涌对话",
            "入职培训启动", "主管暗示规则", "偶遇关键线索人物",
            "旧楼层的异常声响", "发现被篡改的档案", "接到匿名警告",
            "办公室深处的监视", "与同事的试探交锋", "调取机密名单",
            "临危受命", "布置取证计划", "夜探地下资料库",
            "交易现场撞破", "被人跟踪反制", "关键证词浮出",
            "旧案卷宗重现", "目光交汇时的微妙默契",
        ],
        "visual_direction": "明亮写字楼，冷色调与暖色灯光对比",
        "camera_direction": "中景进入，跟随女主视线扫过大堂",
        "stage_direction": "女主从大门进入，停格在电梯口",
        "emotional_beats": ["忐忑", "好奇", "警觉"],
        "state_changes": [{"variable": "affection", "op": "add", "value": 0}],
        "continuity_notes": "承接世界观设定，为男主A出场铺垫",
        "asset_requirements": {"visual_assets": [], "audio_assets": []},
    }


def _synthesize_dialogue(request: LLMRequest) -> dict:
    """离线演示（provider='mock'）：确定性生成结构合法的 DialogueContent（Step12）。

    与 mock CharacterAgent 保持一致：单角色 char-01；StoryCondition/StoryEffect 只引用
    mock StoryGraph 已声明的变量（affection/trust）。dialogue_id/node_id/choice_id 由服务端强制校正。
    """
    return {
        "dialogue_id": "scene_01:default",
        "node_id": "scene_01",
        "choice_id": None,
        "lines": [
            {
                "speaker": "char-01", "text": "欢迎来到公司。", "emotion": "克制温柔",
                "delivery": "轻声", "action": "微微点头", "target": None, "relationship_context": "",
            },
            {
                "speaker": "char-01", "text": "从今天起，这里就是你的舞台。", "emotion": "平静",
                "delivery": "放慢语速", "action": "递过工牌", "target": None, "relationship_context": "",
            },
        ],
        "conditions": [{"variable": "affection", "op": ">=", "value": 0}],
        "effects": [{"variable": "trust", "op": "sub", "value": 5}],
        "next_node": None,
        "branch": None,
        "tags": ["mock-offline-demo"],
        "continuity_notes": "开场对白，铺垫职场氛围（离线演示数据）",
        "asset_requirements": {},
    }


def _parse_json(raw: str) -> dict:
    """把模型输出解析成 dict：容忍 markdown 代码块与前后散文。失败抛 ValueError。"""
    text = (raw or "").strip()
    if not text:
        raise ValueError("模型返回空内容")
    candidates = [text]
    if text.startswith("```"):
        inner = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        inner = re.sub(r"\s*```$", "", inner).strip()
        candidates.append(inner)
    for candidate in candidates:
        try:
            data = json.loads(candidate)
            if isinstance(data, dict):
                return data
            # 模型偶尔把「多个角色」按客观描述输出成 JSON 数组：取首个对象兜底，避免整步失败阻塞下游
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict):
                        return item
        except json.JSONDecodeError:
            continue
    start = text.find("{")
    if start != -1:
        data = _extract_balanced_json(text, start)
        if data is not None:
            return data
    raise ValueError("模型未返回合法 JSON")


def _extract_balanced_json(text: str, start: int) -> dict | None:
    """从 start（第一个 '{'）起提取第一个平衡的大括号块并解析为 dict。"""
    depth = 0
    in_str = False
    escaped = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    data = json.loads(text[start : i + 1])
                    return data if isinstance(data, dict) else None
                except json.JSONDecodeError:
                    return None
    return None


def get_provider() -> LLMProvider:
    """按配置路由 LLM Provider；配置无效（地址/密钥缺失或脏数据）时优雅回退 Mock。

    绝不因配置问题抛异常：宁可离线演示，也不让整条流水线因上游不可用而全灭。
    """
    status = provider_status()
    if status["mode"] == "yiwa_gateway":
        return OpenAICompatProvider(
            base_url=settings.yiwa_gateway_url, api_key=settings.yiwa_token, model=settings.llm_model,
        )
    if status["mode"] == "openai_compat":
        return OpenAICompatProvider()
    return MockProvider()


def get_script_provider() -> LLMProvider:
    """剧本生成专用 Provider：优先使用 llm_script_model（缺省回退 llm_model）。

    便于把「生成剧本」的调用稳定指向某个专用模型（如火山方舟 ep-xxxx），
    同时又与主链路共用同一 base_url/api_key。配置无效时优雅回退 Mock，绝不抛异常。
    """
    status = provider_status()
    model = (settings.llm_script_model or settings.llm_model).strip() or "deepseek-chat"
    if status["mode"] == "yiwa_gateway":
        return OpenAICompatProvider(
            base_url=settings.yiwa_gateway_url, api_key=settings.yiwa_token, model=model,
        )
    if status["mode"] == "openai_compat":
        return OpenAICompatProvider(model=model)
    return MockProvider()


_URL_RE = re.compile(r"^https?://[^\s]+$")


def _usable_url(value: str | None) -> bool:
    v = (value or "").strip()
    return bool(v) and bool(_URL_RE.match(v))


def _usable_key(value: str | None) -> bool:
    v = (value or "").strip()
    if len(v) < 8:
        return False
    if any(c.isspace() for c in v):  # 密钥不含空白；避免把 shell 命令/粘贴错串当成密钥
        return False
    if v.lower().startswith(("export ", "bearer ", "key=")):
        return False
    return True


def provider_status() -> dict:
    """当前实际生效的 LLM 模式与配置健康度（供 UI 明示离线/网关/直连与回退原因）。"""
    if settings.yiwa_token or settings.yiwa_gateway_url:
        if _usable_url(settings.yiwa_gateway_url) and _usable_key(settings.yiwa_token):
            return {"mode": "yiwa_gateway", "fallback": False, "note": "YIWA 生成服务网关"}
        return {"mode": "mock", "fallback": True, "note": "YIWA 网关地址或 Token 无效，已回退离线演示"}
    if settings.llm_provider == "openai_compat":
        if _usable_url(settings.llm_base_url) and _usable_key(settings.llm_api_key):
            return {"mode": "openai_compat", "fallback": False, "note": "OpenAI 兼容直连"}
        return {"mode": "mock", "fallback": True, "note": "LLM 地址或密钥未正确配置，已回退离线演示"}
    if settings.llm_provider == "mock":
        return {"mode": "mock", "fallback": False, "note": "离线演示模式"}
    return {"mode": "mock", "fallback": True, "note": f"未知 LLM_PROVIDER（{settings.llm_provider}），已回退离线演示"}


def _longchain_story_graph(_request: LLMRequest) -> dict:
    """mock 确定性生成：长链路（>=68 节点）+ 多分支 + 多结局的 StoryGraph。

    保留 Step13 固定入口契约不破坏：entry=scene_01、变量 affection/trust、
    选项 c01a->scene_02a（affection+=10）/ c01b->scene_02b / c01c->scene_02c。
    其余为主线 60 幕逐节推进、关键节点含可循分支/合并，节点总数 >= 60、故事更连贯。
    """
    titles = [
        "入职第一天", "同盟初结", "暗线浮现", "旧城夜探", "证据惊变", "分歧抉择",
        "深潜计划", "教团照面", "誓言与背叛", "雨夜追逃", "午夜档案室", "孤注一掷",
        "线索重校", "真假双谍", "镜中人影", "半路伏击", "内鬼浮出", "至暗时刻",
        "反戈一击", "真相揭晓", "新夜幕临", "久别重逢", "裂痕渐深", "决裂前夜",
        "转机乍现", "反攻序章", "终局摊牌", "命运岔路", "余烬未冷", "黎明之前",
        "旧城清算", "无声证词", "以命相搏", "最后通牒", "燃烧的档案", "背水一线",
        "暗号对接", "观测室之眼", "午夜列车", "教堂对峙", "旧巷追逐", "真相之门",
        "残局复燃", "重逢于星", "风起后巷", "裂隙之上", "最后底牌", "沉夜终局",
        "序章尾声", "幕间小憩", "惊蛰将起", "长夜叩问", "薄冰之上", "迂回走线",
        "升变前夕", "末路歧途", "归途灯火", "终点驿站", "新章初启", "结局分岔",
    ]  # 60 条主线标题

    # 拓扑（保证 test_extend/test_step13 固定契约）：
    #   - scene_01 为入口，三个固定选项 c01a->scene_02a / c01b->scene_02b / c01c->scene_02c，
    #     其中 scene_02a、scene_02b 是**仅有的两个可延长叶节点**（scene、无出边、未锁定）。
    #   - 长链主线 scene_03..scene_60 通过边 scene_01->scene_03 并入，逐节推进、多处分支，达结局。
    _title_for = {f"scene_{i + 1:03d}" if i + 1 >= 100 else f"scene_{i + 1:02d}": titles[i] for i in range(len(titles))}
    _title_for["scene_02a"] = titles[1]
    _title_for["scene_02b"] = "裂痕分支"

    nodes = [
        # 入口 + 两个末端叶节点 + 一个退场结局
        {"node_id": "scene_01", "kind": "scene", "title": titles[0], "content_ref": "scene_01",
         "summary": "女主进入娱乐公司，暗流涌动",
         "choices": [
             {"choice_id": "c01a", "text": "帮助女主",
              "effects": [{"variable": "affection", "op": "add", "value": 10}], "next_node": "scene_02a"},
             {"choice_id": "c01b", "text": "欺骗女主",
              "effects": [{"variable": "trust", "op": "add", "value": -10}], "next_node": "scene_02b"},
             {"choice_id": "c01c", "text": "离开", "next_node": "scene_02c"},
         ]},
        {"node_id": "scene_02a", "kind": "scene", "title": _title_for["scene_02a"],
         "content_ref": "scene_02a", "summary": "与女主结盟（黄金路径终点，可延长）", "choices": []},
        {"node_id": "scene_02b", "kind": "scene", "title": _title_for["scene_02b"],
         "content_ref": "scene_02b", "summary": "女主起疑（可延长）", "choices": []},
        {"node_id": "scene_02c", "kind": "ending", "title": "退出",
         "content_ref": "scene_02c", "summary": "退出这场纠葛", "choices": []},
    ]

    # 长链 scene_03..scene_60：每幕带「继续推进」，每 3 幕给 1 条分叉支线
    chain_ids = [f"scene_{i:02d}" for i in range(3, 61)]  # 58 个
    for pos, nid in enumerate(chain_ids):
        opts = []
        if pos + 1 < len(chain_ids):
            opts.append({"choice_id": f"c{pos:02d}a", "text": "继续推进", "next_node": chain_ids[pos + 1]})
        if pos + 2 < len(chain_ids) and pos % 3 == 1:
            opts.append({"choice_id": f"c{pos:02d}b", "text": "岔开另寻线索",
                         "effects": [{"variable": "trust", "op": "add", "value": 5}],
                         "next_node": chain_ids[pos + 2]})
        nodes.append({
            "node_id": nid, "kind": "scene", "title": _title_for[nid], "content_ref": nid,
            "summary": f"《{_title_for[nid]}》：剧情向前推进", "choices": opts,
        })

    endings = [
        {"node_id": "end_good", "kind": "ending", "title": "圆满结局",
         "content_ref": "end_good", "summary": "携手走出旧案，迎来黎明", "choices": []},
        {"node_id": "end_bitter", "kind": "ending", "title": "落尽结局",
         "content_ref": "end_bitter", "summary": "真相大白却两败俱伤", "choices": []},
    ]
    nodes.extend(endings)

    # 边：scene_01 并入长链（scene_02a/02b 保持无出边叶节点）；长链逐节推进；多结局
    edges = [{"edge_id": "e00", "source": "scene_01", "target": "scene_03", "label": "主线"}]
    edges += [
        {"edge_id": f"e{pos + 1:03d}", "source": chain_ids[pos], "target": chain_ids[pos + 1], "label": "主线"}
        for pos in range(len(chain_ids) - 1)
    ]
    edges += [
        {"edge_id": "efin1", "source": "scene_60", "target": "end_good", "label": "携手到底"},
        {"edge_id": "efin2", "source": "scene_60", "target": "end_bitter", "label": "代价惨重"},
        {"edge_id": "ealt", "source": "scene_05", "target": "end_bitter", "label": "分歧险路"},
        {"edge_id": "ebrk", "source": "scene_08", "target": "scene_02b", "label": "回溯"},
    ]
    return {
        "graph_id": "story-01",
        "entry_node_id": "scene_01",
        "variables": [
            {"name": "affection", "type": "number", "initial": 0, "description": "女主好感度"},
            {"name": "trust", "type": "number", "initial": 0, "description": "信任度"},
        ],
        "nodes": nodes,
        "edges": edges,
        "metadata": {"chapter": 1, "ending_count": len(endings), "node_count": len(nodes),
                     "generated_by": "mock-offline-demo-longchain"},
    }