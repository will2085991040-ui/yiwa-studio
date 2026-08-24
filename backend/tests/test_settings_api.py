"""增量：模型设置 API（读写 data_dir/config.json，密钥打码）测试。"""
from app.core.config import settings


def _use_tmp_data_dir(monkeypatch, tmp_path) -> str:
    monkeypatch.setattr(settings, "yiwa_data_dir", str(tmp_path))
    return str(tmp_path / "config.json")


def test_get_settings_defaults(client, monkeypatch, tmp_path):
    path = _use_tmp_data_dir(monkeypatch, tmp_path)
    resp = client.get("/api/settings")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["config_file"] == path
    assert body["values"]["image_provider"] == "mock"
    assert body["values"]["video_provider"] == "mock"
    assert "ready" in body


def test_put_settings_persists_and_masks(client, monkeypatch, tmp_path):
    _use_tmp_data_dir(monkeypatch, tmp_path)
    resp = client.put("/api/settings", json={
        "llm_provider": "openai_compat",
        "llm_base_url": "https://api.siliconflow.cn/v1",
        "llm_api_key": "sk-abcdefgh1234",
        "image_provider": "siliconflow",
    })
    assert resp.status_code == 200, resp.text
    assert resp.json()["values"]["llm_provider"] == "openai_compat"
    assert resp.json()["values"]["llm_api_key"] == "sk-…1234"
    assert resp.json()["ready"]["image_ready"] is True


def test_put_empty_key_clears(client, monkeypatch, tmp_path):
    _use_tmp_data_dir(monkeypatch, tmp_path)
    client.put("/api/settings", json={"llm_api_key": "sk-abcdefgh1234"})
    resp = client.put("/api/settings", json={"llm_api_key": ""})
    assert resp.status_code == 200
    assert resp.json()["values"]["llm_api_key"] == ""


def test_yiwa_token_masked_and_gateway_ready(client, monkeypatch, tmp_path):
    _use_tmp_data_dir(monkeypatch, tmp_path)
    resp = client.put("/api/settings", json={
        "yiwa_token": "yiwa_secret123456",
        "yiwa_gateway_url": "https://gateway.yiwa.example/api",
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["values"]["yiwa_token"] == "yiw…3456"  # 打码显示
    assert body["values"]["yiwa_gateway_url"] == "https://gateway.yiwa.example/api"
    assert body["ready"]["yiwa_ready"] is True
    assert body["ready"]["text_ready"] is True
    assert body["ready"]["image_ready"] is True
    assert body["ready"]["video_ready"] is True


def test_llm_timeout_seconds_persists_and_clamped(client, monkeypatch, tmp_path):
    """增量：LLM 请求超时可调（防长剧情/分镜“请求超时”），越界值被钳位。"""
    _use_tmp_data_dir(monkeypatch, tmp_path)
    # 越界(太小 + 太大)都被钳到 [1,600]
    client.put("/api/settings", json={"llm_timeout_seconds": 0})
    assert client.get("/api/settings").json()["values"]["llm_timeout_seconds"] == 1
    client.put("/api/settings", json={"llm_timeout_seconds": 99999})
    assert client.get("/api/settings").json()["values"]["llm_timeout_seconds"] == 600
    # 正常值持久化
    resp = client.put("/api/settings", json={"llm_timeout_seconds": 300})
    assert resp.status_code == 200, resp.text
    assert resp.json()["values"]["llm_timeout_seconds"] == 300
    # 落库到 config.json，重启后可用
    import json as _json
    from desktop.config import load_config
    cfg = load_config(str(tmp_path / "config.json"))
    assert cfg.llm_timeout_seconds == 300