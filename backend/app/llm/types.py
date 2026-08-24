"""Provider 统一契约类型：LLMRequest / LLMResponse / LLMUsage / LLMError 等。

设计约束：
- System Instruction 与 User Goal 严格分离：用户输入只能作为 user 数据进入模型，
  永远不能拼进 system 指令（Prompt Injection 基础防护）。
- 每次调用的 provider / model / tokens / latency / request_id / cost 都是结构化字段，
  可直接写入 Trace。
"""
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


def estimate_tokens(text: str) -> int:
    """粗略 token 估算：CJK 字符按 1 token，其余按 4 字符 1 token。

    只用于预算预检与 Mock 用量统计；真实用量一律以 Provider 返回的 usage 为准。
    """
    if not text:
        return 0
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    other = len(text) - cjk
    return cjk + max(1, other // 4)


class TokenBudget(BaseModel):
    """Token 预算：由 Python 确定性强制执行，不依赖 LLM 自觉。"""

    max_input_tokens: int = 8192
    max_output_tokens: int = 2048
    max_total_tokens: int = 10240

    @model_validator(mode="after")
    def _check_total(self) -> "TokenBudget":
        if self.max_total_tokens < self.max_input_tokens + self.max_output_tokens:
            raise ValueError("max_total_tokens 必须 >= max_input_tokens + max_output_tokens")
        return self


class LLMUsage(BaseModel):
    """Token 用量记录。total_tokens 由 input + output 自动补齐。"""

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0

    @model_validator(mode="after")
    def _fill_total(self) -> "LLMUsage":
        if self.total_tokens == 0:
            self.total_tokens = self.input_tokens + self.output_tokens
        return self


class LLMMessage(BaseModel):
    """角色受限消息。role 白名单之外的值在构造时即被拒绝。"""

    role: Literal["system", "developer", "user", "assistant"]
    content: str


class LLMRequest(BaseModel):
    """统一请求。messages 与 system/user 二选一；schema 存在时走结构化输出。"""

    system: str | None = None
    user: str | None = None
    messages: list[LLMMessage] | None = None
    json_schema: dict[str, Any] | None = None
    temperature: float | None = None
    max_tokens: int | None = Field(default=None, description="输出上限，Provider 必须截断到该值以内")
    budget: TokenBudget = Field(default_factory=TokenBudget)
    request_id: str | None = None
    prompt_version: str | None = None
    # 预留 Tool Calling：接口层透传，暂不实现工具执行
    tools: list[dict[str, Any]] | None = None
    tool_choice: Any = None

    @model_validator(mode="after")
    def _check_content(self) -> "LLMRequest":
        if self.messages is None and self.user is None:
            raise ValueError("LLMRequest 必须提供 messages 或 user")
        if self.max_tokens is not None and self.max_tokens < 1:
            raise ValueError("max_tokens 必须为正整数")
        return self

    def build_messages(self) -> list[LLMMessage]:
        """把 system/user 组装为角色受限消息列表；用户内容永远落在 user 角色。"""
        if self.messages is not None:
            return self.messages
        built: list[LLMMessage] = []
        if self.system:
            built.append(LLMMessage(role="system", content=self.system))
        if self.user:
            built.append(LLMMessage(role="user", content=self.user))
        return built


class LLMResponse(BaseModel):
    """统一响应：文本/结构化数据 + 完整用量与成本记录。"""

    request_id: str = ""
    provider: str = ""
    model: str = ""
    content: str | None = None
    data: dict[str, Any] | None = None
    usage: LLMUsage = Field(default_factory=LLMUsage)
    latency_ms: int = 0
    cost_estimate: float = 0.0
    finish_reason: str = "stop"
    prompt_version: str | None = None


class LLMStreamChunk(BaseModel):
    """流式输出分片。最后一个分片携带 finish_reason 与 usage。"""

    request_id: str = ""
    index: int = 0
    delta: str = ""
    finish_reason: str | None = None
    usage: LLMUsage | None = None


class LLMEmbeddingResult(BaseModel):
    """向量化结果：文本顺序与 vectors 一一对应。"""

    request_id: str = ""
    provider: str = ""
    model: str = ""
    vectors: list[list[float]]
    usage: LLMUsage = Field(default_factory=LLMUsage)
    latency_ms: int = 0
    cost_estimate: float = 0.0


class LLMError(BaseModel):
    """结构化错误：直接可序列化进 Trace，供重试/降级决策使用。"""

    # timeout | http_5xx | http_4xx | invalid_json | schema_error
    # rate_limit | token_limit | provider_error | not_supported
    code: str
    message: str
    provider: str
    model: str
    request_id: str | None = None
    retryable: bool = False
    retries_attempted: int = 0
    latency_ms: int = 0
    status_code: int | None = None


class LLMProviderError(Exception):
    """Provider 层抛出的异常：携带结构化 LLMError，调用方据此重试/修复/降级。"""

    def __init__(self, error: LLMError) -> None:
        super().__init__(error.message)
        self.error = error
