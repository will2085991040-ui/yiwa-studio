"""Step 19 测试：Material（素材元数据 / 上传 / 关联 / 检索 / 软废弃）。"""
import pytest

from app.core.errors import AppError
from app.models import Project
from app.services.materials import MaterialStore, material_store


def _project(session) -> Project:
    project = Project(goal="制作乙女悬疑Galgame。", template="galgame")
    session.add(project)
    session.commit()
    return project


def test_upload_metadata(session_factory):
    session = session_factory()
    project = _project(session)
    m = material_store.upload(session, project.id, kind="character_image", name="女主立绘-微笑",
                              mime_type="image/png", metadata={"pose": "smile"}, tags=["女主"])
    assert m.kind == "character_image" and m.meta["pose"] == "smile"
    assert m.storage_path  # 默认生成存储路径
    assert m.status == "active"
    session.close()


def test_list_by_kind(session_factory):
    session = session_factory()
    project = _project(session)
    material_store.upload(session, project.id, kind="bgm", name="主题曲")
    material_store.upload(session, project.id, kind="sfx", name="开门声")
    assert len(material_store.list_materials(session, project.id, kind="bgm")) == 1
    assert len(material_store.list_materials(session, project.id)) == 2
    session.close()


def test_search_ranks(session_factory):
    session = session_factory()
    project = _project(session)
    material_store.upload(
        session, project.id, kind="cg", name="告白场景", description="雨夜天台告白", tags=["甜", "关键"],
    )
    material_store.upload(
        session, project.id, kind="cg", name="战斗场景", description="大楼追逐", tags=["悬疑"],
    )
    results = material_store.search(session, project.id, "告白 甜")
    assert results and results[0]["name"] == "告白场景"
    session.close()


def test_associate_reference(session_factory):
    session = session_factory()
    project = _project(session)
    m = material_store.upload(session, project.id, kind="scene_image", name="会议室")
    material_store.associate(session, m.id, ref_kind="scene:scene_01", ref_id="scene_01")
    session.expire_all()
    row = MaterialStore().get(session, m.id)
    assert row.ref_kind == "scene:scene_01" and row.ref_id == "scene_01"
    session.close()


def test_abandon_soft_delete(session_factory):
    session = session_factory()
    project = _project(session)
    m = material_store.upload(session, project.id, kind="sfx", name="脚步声")
    material_store.abandon(session, m.id)
    session.expire_all()
    row = MaterialStore().get(session, m.id)
    assert row.status == "abandoned"          # 仍在 DB（软废弃）
    assert material_store.search(session, project.id, "脚步") == []  # 废弃后不再被检索
    session.close()


def test_invalid_kind(session_factory):
    session = session_factory()
    project = _project(session)
    with pytest.raises(AppError) as e:
        material_store.upload(session, project.id, kind="video", name="x")
    assert e.value.code == "invalid_material_kind"
    session.close()


def test_material_api(client, session_factory):
    session = session_factory()
    project = _project(session)
    session.close()
    resp = client.post(f"/api/projects/{project.id}/materials",
                       json={"kind": "cg", "name": "结局CG", "tags": ["结局"]})
    assert resp.status_code == 200, resp.text
    mid = resp.json()["id"]
    resp = client.get(f"/api/projects/{project.id}/materials", params={"q": "结局"})
    assert resp.status_code == 200 and resp.json()[0]["id"] == mid