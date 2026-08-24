"""增量：桌面静态服务 —— 无扩展名路由映射 .html（/settings → settings.html）。"""
from fastapi.testclient import TestClient

from desktop.server import build_desktop_app


def test_static_extensionless_routes(tmp_path):
    (tmp_path / "index.html").write_text("YIWA home", encoding="utf-8")
    (tmp_path / "settings.html").write_text("<h1>模型设置</h1>", encoding="utf-8")
    app = build_desktop_app(str(tmp_path))
    client = TestClient(app)

    assert client.get("/").status_code == 200
    assert client.get("/settings").status_code == 200
    assert client.get("/settings").text == "<h1>模型设置</h1>"
    assert client.get("/settings.html").status_code == 200
    assert client.get("/health").status_code == 200
    assert client.get("/nope").status_code == 404