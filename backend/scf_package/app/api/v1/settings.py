"""API：模型设置 —— 读写 data_dir/config.json（与桌面启动器共用同一 schema，不硬编码密钥）。

保存后关键值由启动器在下次启动时注入环境变量（重启生效）；本接口只负责安全的读写。
"""
import os

from fastapi import APIRouter
from pydantic import BaseModel

from app.core.config import settings
from app.llm.provider import _usable_key, _usable_url, provider_status
from desktop.config import DesktopConfig, load_config, save_config

router = APIRouter(prefix="/api")

_EDITABLE = (
    "llm_provider", "llm_base_url", "llm_api_key", "llm_model", "llm_disable_thinking",
    "llm_timeout_seconds",
    "image_provider", "image_base_url", "image_api_key", "image_model", "image_size",
    "video_provider", "video_base_url", "video_api_key", "video_model",
    "yiwa_token", "yiwa_gateway_url",
)
_SECRET = ("llm_api_key", "image_api_key", "video_api_key", "yiwa_token")


def _data_dir() -> str:
    if settings.yiwa_data_dir:
        return settings.yiwa_data_dir
    base = os.environ.get("APPDATA", os.path.expanduser("~"))
    return os.path.join(base, "YIWA", "data")


def _config_path() -> str:
    return os.path.join(_data_dir(), "config.json")


def _mask(key: str) -> str:
    if not key:
        return ""
    if len(key) <= 7:
        return "***"
    return f"{key[:3]}…{key[-4:]}"


def _effective() -> dict:
    cfg = load_config(_config_path())
    return cfg.to_dict()


def _ready(cfg: dict) -> dict:
    gw_url, gw_key = cfg.get("yiwa_gateway_url"), cfg.get("yiwa_token")
    gateway_ready = _usable_url(gw_url) and _usable_key(gw_key)
    direct_ready = (
        cfg.get("llm_provider") == "openai_compat"
        and _usable_url(cfg.get("llm_base_url"))
        and _usable_key(cfg.get("llm_api_key"))
    )
    return {
        "text_ready": gateway_ready or direct_ready,
        "image_ready": gateway_ready or (
            cfg.get("image_provider") in ("siliconflow", "ark")
            and _usable_key(cfg.get("image_api_key") or cfg.get("llm_api_key"))
            and _usable_url(cfg.get("image_base_url"))
        ),
        "video_ready": gateway_ready
        or (cfg.get("video_provider") == "seedance" and _usable_key(cfg.get("video_api_key"))),
        "yiwa_ready": gateway_ready,
    }


class SettingsUpdate(BaseModel):
    """可编辑项全部可选：缺省字段保留现值；显式传空字符串表示清空。"""

    llm_provider: str | None = None
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_model: str | None = None
    llm_disable_thinking: bool | None = None
    llm_timeout_seconds: int | None = None
    image_provider: str | None = None
    image_base_url: str | None = None
    image_api_key: str | None = None
    image_model: str | None = None
    image_size: str | None = None
    video_provider: str | None = None
    video_base_url: str | None = None
    video_api_key: str | None = None
    video_model: str | None = None
    yiwa_token: str | None = None
    yiwa_gateway_url: str | None = None


@router.get("/settings")
def get_settings() -> dict:
    cfg = _effective()
    view = {k: cfg.get(k, "") for k in _EDITABLE}
    for k in _SECRET:
        view[k] = _mask(view.get(k, ""))
    return {
        "config_file": _config_path(),
        "values": view,
        "ready": _ready(cfg),
        "provider": provider_status(),  # 当前运行态（保存后需重启生效）
        "note": "推荐只填「YIWA Token + 网关」即可生成；密钥打码，保存后重启生效",
    }


@router.put("/settings")
def update_settings(payload: SettingsUpdate) -> dict:
    cfg = load_config(_config_path())
    current = cfg.to_dict()
    explicit = payload.model_fields_set  # 显式传了（含空串）的字段
    for field in _EDITABLE:
        if field not in explicit:
            continue
        value = getattr(payload, field)
        if field == "llm_timeout_seconds" and isinstance(value, int):
            value = max(1, min(600, value))  # 请求超时钳位在 1s~600s，防止误设炸掉 LLM 请求
        current[field] = value
    merged = DesktopConfig.from_dict(current)
    save_config(merged, _config_path())
    return get_settings()