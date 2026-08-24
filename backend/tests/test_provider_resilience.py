"""Provider 配置韧性：脏配置绝不炸流水线，优雅回退 Mock 并可见。"""
from app.core.config import settings
from app.llm.provider import (
    MockProvider,
    OpenAICompatProvider,
    _parse_json,
    get_provider,
    provider_status,
)


def _reset(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "mock")
    monkeypatch.setattr(settings, "llm_base_url", "https://api.deepseek.com")
    monkeypatch.setattr(settings, "llm_api_key", "")
    monkeypatch.setattr(settings, "yiwa_token", "")
    monkeypatch.setattr(settings, "yiwa_gateway_url", "")


def test_default_is_mock(monkeypatch):
    _reset(monkeypatch)
    assert isinstance(get_provider(), MockProvider)
    st = provider_status()
    assert st["mode"] == "mock" and st["fallback"] is False


def test_valid_openai_compat_is_used(monkeypatch):
    _reset(monkeypatch)
    monkeypatch.setattr(settings, "llm_provider", "openai_compat")
    monkeypatch.setattr(settings, "llm_base_url", "https://api.deepseek.com")
    monkeypatch.setattr(settings, "llm_api_key", "sk-abcdefgh1234")
    assert isinstance(get_provider(), OpenAICompatProvider)
    assert provider_status()["mode"] == "openai_compat"


def test_garbage_openai_compat_falls_back_to_mock(monkeypatch):
    # 复现真实事故：base_url 被填成端点 ID、api_key 被填成 `export ARK_API_KEY="..."` 命令串
    _reset(monkeypatch)
    monkeypatch.setattr(settings, "llm_provider", "openai_compat")
    monkeypatch.setattr(settings, "llm_base_url", "ep-20260812181334-qbtlq")
    monkeypatch.setattr(settings, "llm_api_key", 'export ARK_API_KEY="ark-724e6738-24b4-43fe-863c-3363ea981585"')
    assert isinstance(get_provider(), MockProvider)
    st = provider_status()
    assert st["mode"] == "mock" and st["fallback"] is True


def test_missing_key_falls_back_to_mock(monkeypatch):
    _reset(monkeypatch)
    monkeypatch.setattr(settings, "llm_provider", "openai_compat")
    monkeypatch.setattr(settings, "llm_base_url", "https://api.deepseek.com")
    monkeypatch.setattr(settings, "llm_api_key", "")
    assert isinstance(get_provider(), MockProvider)


def test_gateway_requires_both_url_and_token(monkeypatch):
    _reset(monkeypatch)
    monkeypatch.setattr(settings, "yiwa_gateway_url", "https://gateway.yiwa.example/api")
    monkeypatch.setattr(settings, "yiwa_token", "yiwa_secret123456")
    assert isinstance(get_provider(), OpenAICompatProvider)
    assert provider_status()["mode"] == "yiwa_gateway"

    monkeypatch.setattr(settings, "yiwa_token", "yiwa_")  # 过短 -> 无效
    assert isinstance(get_provider(), MockProvider)


def test_parse_json_accepts_markdown_fence():
    raw = '```json\n{"a": 1}\n```'
    assert _parse_json(raw) == {"a": 1}


def test_parse_json_takes_first_object_from_array():
    # 模型偶尔把「多个角色」输出成 JSON 数组：取首个对象兜底，避免整步失败阻塞下游
    raw = '[{"character_id": "c1", "name": "A"}, {"character_id": "c2", "name": "B"}]'
    assert _parse_json(raw) == {"character_id": "c1", "name": "A"}


def test_parse_json_raises_on_truncated_garbage():
    import pytest

    with pytest.raises(ValueError):
        _parse_json('{"a": [1, 2, 3')