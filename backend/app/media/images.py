"""生图：硅基流动 SiliconFlow（OpenAI 兼容 images 端点）+ mock 离线回退。

未配置 key 时自动回退 mock，保证离线演示/E2E 不因缺密钥失败。
"""
import time
from typing import Any

import httpx

from app.core.config import settings
from app.media.types import ImageRequest, ImageResult, MediaError

_MOCK_SVG = (
    "data:image/svg+xml;charset=utf-8,"
    "<svg xmlns='http://www.w3.org/2000/svg' width='512' height='512'>"
    "<rect width='512' height='512' fill='%23112036'/>"
    "<text x='50%25' y='50%25' fill='%23f472b6' font-size='40' text-anchor='middle'>YIWA mock 生图</text>"
    "</svg>"
)


def _effective() -> dict[str, Any]:
    # YIWA 生成服务网关优先：单 Token + 网关 → 走 OpenAI images 端点
    if settings.yiwa_token and settings.yiwa_gateway_url:
        return {
            "provider": "yiwa_gateway",
            "base_url": settings.yiwa_gateway_url.rstrip("/"),
            "api_key": settings.yiwa_token,
            "model": settings.image_model,
            "size": settings.image_size,
        }
    key = settings.image_api_key or settings.llm_api_key  # SiliconFlow 与文本同 key
    return {
        "provider": settings.image_provider,
        "base_url": settings.image_base_url.rstrip("/"),
        "api_key": key,
        "model": settings.image_model,
        "size": settings.image_size,
    }


async def generate_image(request: ImageRequest) -> ImageResult:
    # 画面风格：把风格 key 翻译成模型可用的 prompt 增强词/负面词，再交给下游。
    from app.media.styles import decorate
    req_prompt, req_neg = decorate(request.prompt, request.style, request.negative_prompt)
    request.negative_prompt = req_neg
    request.prompt = req_prompt
    cfg = _effective()
    if cfg["provider"] == "mock" or not cfg["api_key"] or not cfg["model"]:
        return ImageResult(provider="mock", model=cfg["model"], urls=[_MOCK_SVG], b64=[])
    if cfg["provider"] in ("siliconflow", "yiwa_gateway", "ark"):
        return await _openai_image(request, cfg)
    raise MediaError(f"未知 image_provider: {cfg['provider']}")


async def _openai_image(request: ImageRequest, cfg: dict) -> ImageResult:
    url = f"{cfg['base_url']}/images/generations"
    if cfg["provider"] == "ark":
        # 火山方舟文生图：OpenAI 风格参数（size/response_format），而非硅基的 image_size/batch_size
        payload: dict[str, Any] = {
            "model": cfg["model"],
            "prompt": request.prompt,
            "size": _ark_size(request.size or cfg["size"]),
            "response_format": "url",
            "watermark": False,
        }
    else:
        payload = {
            "model": cfg["model"],
            "prompt": request.prompt,
            "image_size": request.size or cfg["size"],
            "batch_size": max(1, request.n),
        }
    payload = _drop_none(payload)
    if request.negative_prompt and cfg["provider"] != "ark":
        payload["negative_prompt"] = request.negative_prompt
    started = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=settings.llm_timeout_seconds) as client:
            resp = await client.post(url, json=payload, headers={"Authorization": f"Bearer {cfg['api_key']}"})
    except httpx.HTTPError as exc:
        raise MediaError(f"生图请求失败：{exc}") from exc
    if resp.status_code >= 400:
        raise MediaError(f"生图上游错误（{resp.status_code}）：{resp.text[:200]}")
    try:
        data = resp.json()
    except ValueError as exc:
        raise MediaError("生图上游返回非 JSON") from exc
    items = data.get("data") or []
    return ImageResult(
        provider=cfg["provider"],
        model=cfg["model"],
        urls=[it.get("url", "") for it in items if it.get("url")],
        b64=[it.get("b64_json", "") for it in items if it.get("b64_json")],
        latency_ms=int((time.perf_counter() - started) * 1000),
    )


def _drop_none(payload: dict) -> dict:
    return {k: v for k, v in payload.items() if v is not None}


_ARK_SIZES = {
    "768x1344": "720x1280",   # 硅基 9:16 -> 火山方舟 9:16
    "1344x768": "1280x720",   # 硅基 16:9 -> 火山方舟 16:9
    "1024x1024": "1024x1024",
}


def _ark_size(size: str | None) -> str:
    key = (size or "").strip().lower()
    return _ARK_SIZES.get(key, size or "1024x1024")