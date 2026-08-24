"""Step 2 测试：OpenAICompatProvider 落到统一契约（全离线，用 httpx.MockTransport 注入）。

验证真实 HTTP 逻辑：请求映射 / 结构化解析与修复 / 流式 / 向量 / 错误分类 / 重试 / 预算前移。
不发起任何真实网络请求。
"""
import asyncio
import json

import httpx
import pytest

from app.llm.provider import LLMProviderError, OpenAICompatProvider
from app.llm.types import LLMMessage, LLMRequest


def _provider(handler, **kwargs):
    return OpenAICompatProvider(transport=httpx.MockTransport(handler), retry_backoff=0, **kwargs)


def run(coro):
    return asyncio.run(coro)


async def _collect(agen):
    return [chunk async for chunk in agen]


def _chat_json(content, usage=None, status=200, finish_reason="stop"):
    usage = usage or {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
    return httpx.Response(
        status,
        json={
            "id": "chatcmpl-1",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": finish_reason,
                }
            ],
            "usage": usage,
        },
    )


def test_generate_maps_request_to_openai_wire():
    captured = {}

    def handler(request: httpx.Request):
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return _chat_json("你好")

    provider = _provider(handler)
    req = LLMRequest(system="SYS", user="USER", temperature=0.2, max_tokens=100)
    result = run(provider.generate(req))

    body = captured["body"]
    assert "/chat/completions" in captured["url"]
    assert body["model"] == provider.model
    assert body["temperature"] == 0.2
    assert body["max_tokens"] == 100
    assert body["stream"] is False
    assert body["messages"] == [{"role": "system", "content": "SYS"}, {"role": "user", "content": "USER"}]
    assert result.provider == "openai_compat"
    assert result.content == "你好"
    assert result.usage.input_tokens == 10
    assert result.usage.output_tokens == 5
    assert result.usage.total_tokens == 15


def test_developer_role_mapped_to_system_for_compat():
    captured = {}

    def handler(request: httpx.Request):
        captured["body"] = json.loads(request.content)
        return _chat_json("x")

    provider = _provider(handler)
    req = LLMRequest(
        messages=[
            LLMMessage(role="developer", content="DEV"),
            LLMMessage(role="assistant", content="A"),
            LLMMessage(role="user", content="U"),
        ]
    )
    run(provider.generate(req))
    assert [m["role"] for m in captured["body"]["messages"]] == ["system", "assistant", "user"]


def test_generate_structured_enables_json_mode_and_repairs_fenced_output():
    schema = {"type": "object", "properties": {"agent_type": {"type": "string"}}, "required": ["agent_type"]}
    captured = {}

    def handler(request: httpx.Request):
        captured["body"] = json.loads(request.content)
        raw = '这是结果：\n```json\n{"agent_type": "growth"}\n```'
        return _chat_json(raw)

    provider = _provider(handler)
    resp = run(provider.generate_structured(LLMRequest(user="做一个课程引流", json_schema=schema)))

    assert captured["body"]["response_format"] == {"type": "json_object"}
    assert "JSON Schema" in captured["body"]["messages"][-1]["content"]
    assert resp.data == {"agent_type": "growth"}


def test_generate_structured_repairs_prose_surrounding_json():
    schema = {"type": "object", "properties": {"n": {"type": "integer"}}, "required": ["n"]}

    def handler(request: httpx.Request):
        return _chat_json('好的，规划如下：{"n": 42} 希望有帮助。')

    provider = _provider(handler)
    resp = run(provider.generate_structured(LLMRequest(user="x", json_schema=schema)))
    assert resp.data == {"n": 42}


def test_invalid_json_retries_then_raises_typed_error():
    calls = {"n": 0}

    def handler(request: httpx.Request):
        calls["n"] += 1
        return _chat_json("这根本不是 JSON")

    provider = _provider(handler, max_retries=2)
    with pytest.raises(LLMProviderError) as exc_info:
        run(provider.generate_structured(LLMRequest(user="x", json_schema={"type": "object"})))
    error = exc_info.value.error
    assert error.code == "invalid_json"
    assert error.retryable is True
    assert error.retries_attempted == 2
    assert calls["n"] == 3  # 1 次原始 + 2 次重试


def test_schema_validation_still_enforced_at_base():
    """Provider 返回合法 JSON 但违反 Schema：基类必须在 Python 侧拦截。"""
    schema = {"type": "object", "properties": {"n": {"type": "integer"}}, "required": ["n"]}

    def handler(request: httpx.Request):
        return _chat_json('{"n": "不是整数"}')

    provider = _provider(handler)
    with pytest.raises(LLMProviderError) as exc_info:
        run(provider.generate_structured(LLMRequest(user="x", json_schema=schema)))
    assert exc_info.value.error.code == "schema_error"


def test_retry_on_5xx_then_success():
    calls = {"n": 0}

    def handler(request: httpx.Request):
        calls["n"] += 1
        if calls["n"] < 2:
            return httpx.Response(500, text="boom")
        return _chat_json("ok")

    provider = _provider(handler, max_retries=1)
    resp = run(provider.generate(LLMRequest(user="hi")))
    assert resp.content == "ok"
    assert calls["n"] == 2


def test_rate_limit_classified_retryable():
    def handler(request: httpx.Request):
        return httpx.Response(429, text="slow down")

    provider = _provider(handler, max_retries=1)
    with pytest.raises(LLMProviderError) as exc_info:
        run(provider.generate(LLMRequest(user="hi")))
    error = exc_info.value.error
    assert error.code == "rate_limit"
    assert error.status_code == 429
    assert error.retryable is True
    assert error.retries_attempted == 1


def test_4xx_not_retried():
    calls = {"n": 0}

    def handler(request: httpx.Request):
        calls["n"] += 1
        return httpx.Response(400, text="bad request")

    provider = _provider(handler, max_retries=3)
    with pytest.raises(LLMProviderError) as exc_info:
        run(provider.generate(LLMRequest(user="hi")))
    error = exc_info.value.error
    assert error.code == "http_4xx"
    assert error.status_code == 400
    assert error.retryable is False
    assert calls["n"] == 1


def test_timeout_classified_retryable():
    def handler(request: httpx.Request):
        raise httpx.TimeoutException("请求超时")

    provider = _provider(handler, max_retries=0)
    with pytest.raises(LLMProviderError) as exc_info:
        run(provider.generate(LLMRequest(user="hi")))
    error = exc_info.value.error
    assert error.code == "timeout"
    assert error.retryable is True


def test_stream_yields_chunks_and_usage():
    sse = (
        'data: {"choices":[{"delta":{"content":"你"}}]}\n\n'
        'data: {"choices":[{"delta":{"content":"好"}}]}\n\n'
        'data: {"choices":[{"delta":{},"finish_reason":"stop"}],'
        '"usage":{"prompt_tokens":3,"completion_tokens":2,"total_tokens":5}}\n\n'
        "data: [DONE]\n\n"
    )
    captured = {}

    def handler(request: httpx.Request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, content=sse.encode(), headers={"content-type": "text/event-stream"})

    provider = _provider(handler)
    chunks = run(_collect(provider.stream(LLMRequest(user="你好"))))
    assert captured["body"]["stream"] is True
    assert "".join(c.delta for c in chunks) == "你好"
    assert chunks[-1].finish_reason == "stop"
    assert chunks[-1].usage is not None and chunks[-1].usage.total_tokens == 5


def test_embed_calls_embeddings_endpoint():
    def handler(request: httpx.Request):
        assert "/embeddings" in str(request.url)
        body = json.loads(request.content)
        assert body["input"] == ["a", "b"]
        return httpx.Response(
            200,
            json={
                "data": [{"index": 0, "embedding": [0.1, 0.2]}, {"index": 1, "embedding": [0.3, 0.4]}],
                "usage": {"prompt_tokens": 2, "total_tokens": 2},
            },
        )

    provider = _provider(handler)
    result = run(provider.embed(["a", "b"], model="deepseek-embed"))
    assert result.model == "deepseek-embed"
    assert result.vectors == [[0.1, 0.2], [0.3, 0.4]]
    assert result.usage.input_tokens == 2


def test_cost_estimate_computed():
    def handler(request: httpx.Request):
        return _chat_json("hi", usage={"prompt_tokens": 10000, "completion_tokens": 0, "total_tokens": 10000})

    provider = _provider(handler, model="deepseek-chat")
    resp = run(provider.generate(LLMRequest(user="hi")))
    assert resp.cost_estimate > 0
    assert resp.latency_ms >= 0


def test_tools_reserved_passthrough():
    captured = {}

    def handler(request: httpx.Request):
        captured["body"] = json.loads(request.content)
        return _chat_json("x")

    provider = _provider(handler)
    tools = [{"type": "function", "function": {"name": "search", "parameters": {"type": "object", "properties": {}}}}]
    run(provider.generate(LLMRequest(user="hi", tools=tools, tool_choice="auto")))
    assert captured["body"]["tools"] == tools
    assert captured["body"]["tool_choice"] == "auto"


def test_max_tokens_budget_moved_into_request():
    captured = {}

    def handler(request: httpx.Request):
        captured["body"] = json.loads(request.content)
        return _chat_json("x")

    provider = _provider(handler)
    run(provider.generate(LLMRequest(user="hi")))  # 未显式指定 max_tokens
    # 输出上限前移到请求层 = 默认预算 max_output_tokens
    assert captured["body"]["max_tokens"] == 2048