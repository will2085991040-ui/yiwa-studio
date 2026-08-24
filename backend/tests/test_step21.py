"""Step 21 测试：桌面壳（配置 / 目录解析 / server 工厂 / 环境注入 / 同源前端挂载）。"""
import os

from fastapi.testclient import TestClient

from app.db.base import get_session
from desktop.config import DesktopConfig, load_config, save_config
from desktop.launcher import DesktopLauncher
from desktop.server import build_desktop_app


def test_config_resolve_paths(tmp_path):
    cfg = DesktopConfig(data_dir=str(tmp_path))
    assert cfg.database_url.startswith("sqlite:///")
    assert "yiwa.db" in cfg.database_url
    assert cfg.project_dir.endswith("projects")
    assert cfg.config_file.endswith("config.json")


def test_config_save_load_roundtrip(tmp_path):
    cfg = DesktopConfig(data_dir=str(tmp_path), port=8877, llm_model="deepseek-chat")
    path = save_config(cfg, tmp_path / "config.json")
    loaded = load_config(str(path))
    assert loaded.port == 8877 and loaded.llm_model == "deepseek-chat"
    assert loaded.data_dir == str(tmp_path)


def test_config_from_dict_ignores_unknown(tmp_path):
    loaded = DesktopConfig.from_dict({"data_dir": str(tmp_path), "unknown_field": 123, "port": 9999})
    assert loaded.port == 9999 and not hasattr(loaded, "unknown_field")


def test_desktop_splash_and_health(tmp_path):
    app = build_desktop_app("")  # 无前端产物 → 内置启动页
    with TestClient(app) as client:
        health = client.get("/health")
        assert health.status_code == 200 and health.json()["status"] == "ok"
        page = client.get("/")
        assert page.status_code == 200 and "YIWA" in page.text


def test_desktop_serves_static_web_root(tmp_path):
    (tmp_path / "index.html").write_text("<!doctype html><html><body>FRONTEND-OK</body></html>", encoding="utf-8")
    app = build_desktop_app(str(tmp_path))
    with TestClient(app) as client:
        page = client.get("/")
        assert page.status_code == 200 and "FRONTEND-OK" in page.text
        assert client.get("/health").json()["web_root"] is True


def test_desktop_serves_api(session_factory):
    def _override():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app = build_desktop_app("")
    app.dependency_overrides[get_session] = _override
    with TestClient(app) as client:
        resp = client.get("/api/projects")
        assert resp.status_code == 200          # 桌面 app 复用主路由 + 内存 DB
        assert isinstance(resp.json(), list)


def test_launcher_apply_env(tmp_path, monkeypatch):
    cfg = DesktopConfig(data_dir=str(tmp_path), llm_provider="mock", llm_api_key="sk-test", port=8765)
    launcher = DesktopLauncher(cfg)
    launcher.apply_env()
    assert os.environ["DATABASE_URL"].startswith("sqlite:///")
    assert os.environ["LLM_PROVIDER"] == "mock"
    assert os.environ["LLM_API_KEY"] == "sk-test"
    assert os.environ["APP_ENV"] == "production"
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("APP_ENV", raising=False)