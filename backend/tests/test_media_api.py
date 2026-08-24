"""增量：媒体生成 API（生图/生视频 + 立绘差分生图接入）测试。"""
from app.models import Artifact, Project
from app.schemas.portrait import CharacterPortrait, PortraitVariant


def _project(session) -> Project:
    project = Project(goal="媒体生成", template="galgame")
    session.add(project)
    session.commit()
    return project


def _seed_portrait(session, project_id: str) -> None:
    portrait = CharacterPortrait(
        character_id="char1", name="林烬", appearance={"face": "丹凤眼"},
        variants=[PortraitVariant(variant_id="v-happy", name="高兴", category="expression",
                                  value="高兴", description="微笑", aspect="9:16")],
    )
    session.add(Artifact(
        project_id=project_id, task_id="portrait_editor", agent="portrait_editor",
        kind="character_portrait:char1", content=portrait.model_dump(),
        prompt_version="", version=1, is_latest=True,
    ))
    session.commit()


def test_generate_image_api(client, session_factory):
    session = session_factory()
    project = _project(session)
    session.close()
    resp = client.post(f"/api/projects/{project.id}/images", json={"prompt": "雨夜霓虹少女"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["provider"] == "mock"
    assert body["urls"][0].startswith("data:image/svg+xml")


def test_generate_video_api_submit_and_poll(client, session_factory):
    session = session_factory()
    project = _project(session)
    session.close()
    sub = client.post(f"/api/projects/{project.id}/videos", json={"prompt": "海浪拍岸"})
    assert sub.status_code == 200, sub.text
    task_id = sub.json()["task_id"]
    assert sub.json()["status"] == "succeeded"

    poll = client.get(f"/api/projects/{project.id}/videos/{task_id}")
    assert poll.status_code == 200, poll.text
    assert poll.json()["video_url"] == f"mock://video/{task_id}.mp4"


def test_portrait_variant_generate_image(client, session_factory):
    session = session_factory()
    project = _project(session)
    _seed_portrait(session, project.id)
    session.close()

    resp = client.post(
        f"/api/projects/{project.id}/characters/char1/portrait/variants/v-happy/image",
        json={},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    variant = next(v for v in body["portrait"]["variants"] if v["variant_id"] == "v-happy")
    assert variant["image"]["source"] == "generated"
    assert variant["image"]["url"].startswith("data:image/svg+xml")
    assert body["prompt"]  # 已合成差分提示词


def test_storyboard_video_wired_to_media(client, session_factory):
    session = session_factory()
    project = _project(session)
    session.close()

    client.post(f"/api/projects/{project.id}/storyboard/node-9/breakdown", json={"requested_shots": 2})
    resp = client.post(f"/api/projects/{project.id}/storyboard/node-9/video", json={})
    assert resp.status_code == 200, resp.text
    job = resp.json()
    assert job["status"] == "done"
    assert job["provider"] == "mock"
    assert job["task_id"].startswith("mock-")
    assert job["video_url"].startswith("mock://video/")

    got = client.get(f"/api/projects/{project.id}/storyboard/node-9/video")
    assert got.json()["video_url"].startswith("mock://video/")


def test_portrait_variant_generate_image_missing_variant_404(client, session_factory):
    session = session_factory()
    project = _project(session)
    _seed_portrait(session, project.id)
    session.close()
    resp = client.post(
        f"/api/projects/{project.id}/characters/char1/portrait/variants/nope/image", json={}
    )
    assert resp.status_code == 404


def test_video_empty_storyboard_is_400_not_500(client, session_factory):
    """未拆镜直接生成视频 → 回可读 <400>，而非 500「内部错误」。
    这是用户报告「生成视频显示内部服务器错误」的一个来源。"""
    session = session_factory()
    project = _project(session)
    session.close()

    # 未做 breakdown：无 shots
    resp = client.post(f"/api/projects/{project.id}/storyboard/node-7/video", json={})
    assert resp.status_code == 400, resp.text
    body = resp.json()
    assert body["error"]["code"] == "storyboard_empty"
    assert "拆镜" in body["error"]["message"]


def test_video_provider_failure_is_502_not_500(client, session_factory, monkeypatch):
    """真厂商调用失败（MediaError）→ 透出可读 502，而非通用 500「请查看日志」。
    修复用户报告的视频生成内部服务器错误：MediaError 此前未被注册处理器。"""
    import app.api.v1.storyboard as sbmod

    async def _fail(request):
        from app.media.types import MediaError
        raise MediaError("生视频提交失败：上游 401 无效凭据")

    session = session_factory()
    project = _project(session)
    session.close()
    client.post(f"/api/projects/{project.id}/storyboard/node-11/breakdown", json={"requested_shots": 2})
    monkeypatch.setattr(sbmod, "submit_video", _fail)

    resp = client.post(f"/api/projects/{project.id}/storyboard/node-11/video", json={})
    assert resp.status_code == 502, resp.text
    body = resp.json()
    assert body["error"]["code"] == "media_error"
    assert "无效凭据" in body["error"]["message"]
    assert "请查看日志" not in body["error"]["message"]