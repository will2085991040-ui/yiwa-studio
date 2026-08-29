"""成本估算：USD / 1M tokens 参考价。仅用于记录 cost_estimate，不是计费依据。"""
from app.llm.types import LLMUsage

# (input, output) 每百万 token 参考价（USD）。随官方调价更新，此处为估算值。
_PRICE_PER_1M: dict[str, tuple[float, float]] = {
    "deepseek-chat": (0.27, 1.10),
    "deepseek-reasoner": (0.55, 2.19),
    "gpt-4o-mini": (0.15, 0.60),
    "qwen-plus": (0.40, 1.20),
    "moonshot-v1-8k": (0.24, 0.24),
    "glm-4-flash": (0.0, 0.0),
}


def estimate_cost(provider: str, model: str, usage: LLMUsage) -> float:
    """估算单次调用成本（USD）；mock 或未知模型返回 0.0。"""
    if provider == "mock":
        return 0.0
    input_price, output_price = _PRICE_PER_1M.get(model, (0.0, 0.0))
    return round(
        usage.input_tokens / 1_000_000 * input_price + usage.output_tokens / 1_000_000 * output_price,
        8,
    )
