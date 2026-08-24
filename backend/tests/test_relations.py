"""测试：角色关系图 + 小游戏生成器端点。"""


def _create_project(client) -> str:
    r = client.post("/api/projects", json={"goal": "测试关系图与小游戏"})
    assert r.status_code in (200, 201), r.text
    return r.json()["project_id"]


def _add_characters(client, pid: str) -> list[dict]:
    names = ["男主A", "女主B", "反派C"]
    out = []
    for i, n in enumerate(names):
        r = client.post(
            f"/api/projects/{pid}/characters",
            json={"name": n, "role": ["青梅竹马·男主", "女主", "宿敌"][i]},
        )
        assert r.status_code == 200, r.text
        out.append(r.json()["card"])
    return out


def test_relations_generate_and_save_roundtrip(client):
    pid = _create_project(client)
    chars = _add_characters(client, pid)
    assert len(chars) == 3

    # AI 一键生成
    r = client.post(f"/api/projects/{pid}/relations/generate")
    assert r.status_code == 200, r.text
    gen = r.json()
    assert gen["graph_id"] == f"rel-{pid}"
    cids = {c["character_id"] for c in chars}
    assert set(gen["characters"]) == cids
    # 每个有序对都有一条边（3 个角色 → 6 条有向边）
    assert len(gen["edges"]) == 6
    types = {e["relationship_type"] for e in gen["edges"]}
    assert types  # 至少推断出一个类型
    for e in gen["edges"]:
        assert e["affection"] == 0 and e["trust"] == 0 and e["hostility"] == 0

    # 手工 save（去掉一条边）再读回
    trimmed = {
        "graph_id": gen["graph_id"],
        "characters": gen["characters"],
        "edges": gen["edges"][:-1],
    }
    r = client.post(f"/api/projects/{pid}/relations", json=trimmed)
    assert r.status_code == 200, r.text
    saved = r.json()
    assert len(saved["edges"]) == len(gen["edges"]) - 1

    # GET 读到相同内容
    r = client.get(f"/api/projects/{pid}/relations")
    assert r.status_code == 200, r.text
    assert set(r.json()["characters"]) == cids


def test_relations_generate_no_characters_400(client):
    pid = _create_project(client)
    r = client.post(f"/api/projects/{pid}/relations/generate")
    assert r.status_code == 400


def test_relations_new_character_from_relation(client):
    pid = _create_project(client)
    chars = _add_characters(client, pid)
    src = chars[0]["character_id"]
    r = client.post(
        f"/api/projects/{pid}/relations/new-character",
        json={
            "name": "男主师父",
            "role": "师父",
            "description": "教导男主武艺的隐世高人",
            "relations": [{"source_character": src, "relationship_type": "师徒"}],
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    nc = body["character"]
    assert nc["name"] == "男主师父"
    assert nc["character_id"] not in {c["character_id"] for c in chars}
    edge = next(
        e for e in body["graph"]["edges"]
        if e["source_character"] == src and e["target_character"] == nc["character_id"]
    )
    assert edge["relationship_type"] == "师徒"


def test_minigame_produce_list_insert(client):
    pid = _create_project(client)

    r = client.post(
        f"/api/projects/{pid}/minigames",
        json={"game_type": "click", "style": "像素", "prompt": "赛博朋克连点挑战"},
    )
    assert r.status_code == 200, r.text
    made = r.json()
    assert made["game_id"] == "click"
    cfg = made["config"]
    assert cfg["game_id"] == "click"
    assert cfg["title"] == "赛博朋克连点挑战"
    assert cfg["settings"]["style"] == "像素"
    assert cfg["settings"]["target"] == 8

    # 列表能读到最新的游戏
    lst = client.get(f"/api/projects/{pid}/minigames")
    assert lst.status_code == 200, lst.text
    games = lst.json()
    assert any(g["game_id"] == "click" for g in games)

    # 插入剧情节点
    ins = client.post(f"/api/projects/{pid}/minigames/click/insert", json={"node_id": "mg_node_1"})
    assert ins.status_code == 200, ins.text
    body = ins.json()
    assert body["ok"] is True
    assert body["node_id"] == "mg_node_1"
    assert body["kind"] == "minigame:mg_node_1"
    assert body["config"]["game_id"] == "click"

    # 列表里现在也有按节点关联的一条
    lst2 = client.get(f"/api/projects/{pid}/minigames")
    items2 = lst2.json()
    assert any(g["game_id"] == "mg_node_1" for g in items2)


def test_minigame_produce_unknown_type_400(client):
    pid = _create_project(client)
    r = client.post(f"/api/projects/{pid}/minigames", json={"game_type": "nope", "prompt": "x"})
    assert r.status_code == 400