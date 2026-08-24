"""增量 Phase 2：角色立绘 + 8 段外貌 + 差分测试。"""
from app.models import Project
from app.schemas.portrait import (
    CharacterPortrait,
    PortraitVariant,
    compose_base_prompt,
    compose_variant_prompt,
    portrait_template,
    promote_variant,
)
from app.services.artifacts import persist_versioned_artifact


def _project(session) -> Project:
    project = Project(goal="制作乙女悬疑Galgame。", template="galgame")
    session.add(project)
    session.commit()
    return project


def _portrait() -> CharacterPortrait:
    return CharacterPortrait(
        character_id="char-01",
        name="女主",
        appearance={
            "basic": "20岁都市女性，青春剧",
            "face": "鹅蛋脸，明亮杏眼",
            "hair": "黑长直，无发饰",
            "clothing": "白衬衫+牛仔裙",
            "props": "胸口别着雏菊胸针",
            "demeanor": "温柔克制",
            "pose": "全身正视，双足完整",
            "lighting": "柔和均匀光",
        },
        base_variant_id=None,
        variants=[
            PortraitVariant(
                variant_id="v1", name="基础立绘", category=None, value="", description="全身立绘",
                image={"source": "seed", "material_id": "m-base"},
            ),
            PortraitVariant(
                variant_id="v2", name="高兴", category="expression", value="高兴",
                description="嘴角上扬，眼神明亮", image={"source": "seed", "material_id": "m-happy"},
            ),
        ],
    )


def test_template_has_8_sections():
    t = portrait_template()
    assert [s["key"] for s in t["sections"]] == [
        "basic", "face", "hair", "clothing", "props", "demeanor", "pose", "lighting",
    ]
    assert len(t["styles"]) == 4 and len(t["aspect_ratios"]) == 3
    assert "全身立绘" in t["base_rule"]


def test_compose_base_prompt_includes_sections():
    prompt = compose_base_prompt(_portrait())
    assert "【基本信息】" in prompt and "【面部特征】" in prompt
    assert "全身立绘" in prompt and "3D国风高清渲染风格" in prompt


def test_compose_variant_prompt():
    p = _portrait()
    prompt = compose_variant_prompt(p, p.variants[1])
    assert "差分类别：expression" in prompt
    assert "差分名称：高兴" in prompt
    assert "差分提示词：嘴角上扬" in prompt
    assert "只改变当前差分要求" in prompt


def test_promote_variant_backs_up_old_base():
    p = _portrait()
    p = p.model_copy(update={"base_variant_id": "v1"})
    out = promote_variant(p, "v2")
    assert out.base_variant_id == "v2"
    backups = [v for v in out.variants if v.name.startswith("原基础立绘备份")]
    assert len(backups) == 1
    assert backups[0].image == {"source": "seed", "material_id": "m-base"}


def test_get_empty_portrait(client, session_factory):
    session = session_factory()
    project = _project(session)
    session.close()

    resp = client.get(f"/api/projects/{project.id}/characters/char-01/portrait")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["version"] == 0 and body["character_id"] == "char-01"
    assert body["base_prompt"]  # 即便空外貌也有基础规则


def test_save_and_read_portrait(client, session_factory):
    session = session_factory()
    project = _project(session)
    session.close()

    payload = {"portrait": _portrait().model_dump(), "change_reason": "立绘初版"}
    resp = client.put(f"/api/projects/{project.id}/characters/char-01/portrait", json=payload)
    assert resp.status_code == 200, resp.text
    assert resp.json()["version"] == 1
    assert resp.json()["variant_prompts"]["v2"]  # 差分提示词已合成

    resp = client.get(f"/api/projects/{project.id}/characters/char-01/portrait")
    body = resp.json()
    assert body["version"] == 1
    assert body["appearance"]["hair"] == "黑长直，无发饰"
    assert len(body["variants"]) == 2


def test_promote_endpoint(client, session_factory):
    session = session_factory()
    project = _project(session)
    session.close()

    p = _portrait().model_copy(update={"base_variant_id": "v1"})
    client.put(f"/api/projects/{project.id}/characters/char-01/portrait", json={"portrait": p.model_dump()})
    resp = client.post(
        f"/api/projects/{project.id}/characters/char-01/portrait/promote", json={"variant_id": "v2"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["base_variant_id"] == "v2"
    assert body["version"] == 2
    assert any(v["name"].startswith("原基础立绘备份") for v in body["variants"])


def test_prompt_preview_does_not_save(client, session_factory):
    session = session_factory()
    project = _project(session)
    session.close()

    resp = client.post(
        f"/api/projects/{project.id}/characters/char-01/portrait/prompt",
        json={"portrait": _portrait().model_dump()},
    )
    assert resp.status_code == 200, resp.text
    assert "外貌/立绘描述" in resp.json()["base_prompt"]

    resp2 = client.get(f"/api/projects/{project.id}/characters/char-01/portrait")
    assert resp2.json()["version"] == 0  # 预览不落库


def test_list_characters(client, session_factory):
    session = session_factory()
    project = _project(session)
    persist_versioned_artifact(
        session, project_id=project.id, task_id="t1", agent="character", kind="character_card",
        content={"character_id": "char-01", "name": "女主", "role": "女主"}, prompt_version="pv1",
    )
    session.commit()
    session.close()

    resp = client.get(f"/api/projects/{project.id}/characters")
    assert resp.status_code == 200, resp.text
    chars = resp.json()
    assert any(c["character_id"] == "char-01" and c["name"] == "女主" for c in chars)


def test_character_id_mismatch_400(client, session_factory):
    session = session_factory()
    project = _project(session)
    session.close()

    resp = client.put(
        f"/api/projects/{project.id}/characters/char-01/portrait",
        json={"portrait": _portrait().model_copy(update={"character_id": "char-02"}).model_dump()},
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# 手动角色 CRUD（多角色增删改）
# ---------------------------------------------------------------------------


def _min_card(cid: str, name: str, role: str) -> dict:
    return {
        "character_id": cid, "name": name, "role": role,
        "age": "", "gender": "", "appearance": "",
        "personality": [], "background": "", "motivation": "", "goal": "",
        "conflict": "", "fear": "", "secret": "",
        "relationship_rules": [], "speech_style": {}, "likes": [], "dislikes": [],
        "hidden_information": [], "character_arc": [], "possible_endings": [],
    }


def test_create_character_manual(client, session_factory):
    session = session_factory()
    project = _project(session)
    session.close()

    resp = client.post(f"/api/projects/{project.id}/characters", json={"name": "林晚", "role": "女主"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["character_id"] == "char-1"
    assert body["card"]["name"] == "林晚" and body["card"]["role"] == "女主"

    # 自动递增 id：下一个是 char-2
    resp2 = client.post(f"/api/projects/{project.id}/characters", json={"name": "顾言", "role": "男主"})
    assert resp2.json()["character_id"] == "char-2"

    # 列表同时含两个角色（手动可多角色）
    chars = client.get(f"/api/projects/{project.id}/characters").json()
    ids = {c["character_id"] for c in chars}
    assert {"char-1", "char-2"} <= ids


def test_update_and_delete_character(client, session_factory):
    session = session_factory()
    project = _project(session)
    session.close()

    created = client.post(f"/api/projects/{project.id}/characters", json={"name": "林晚", "role": "女主"}).json()
    cid = created["character_id"]

    # 手改整张卡 -> v2
    card = _min_card(cid, "林晚 · 改", "女主/顶流导演")
    resp = client.put(f"/api/projects/{project.id}/characters/{cid}", json={"card": card, "change_reason": "改人设"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["version"] == 2
    assert resp.json()["card"]["name"] == "林晚 · 改"

    # 单张读取
    got = client.get(f"/api/projects/{project.id}/characters/{cid}").json()
    assert got["card"]["role"] == "女主/顶流导演"

    # 删除后列表不再返回
    d = client.delete(f"/api/projects/{project.id}/characters/{cid}")
    assert d.status_code == 200 and d.json()["deleted"] is True
    chars = client.get(f"/api/projects/{project.id}/characters").json()
    assert all(c["character_id"] != cid for c in chars)