"""Step 17 测试：Skill System（SkillRegistry / SkillResolver / use_skill / 上下文注入）。"""
from app.models import Project
from app.services.context_compiler import ContextCompiler
from app.services.skills import SkillResolver, skill_registry, use_skill


def _project(session) -> Project:
    project = Project(goal="制作乙女悬疑Galgame。", template="galgame")
    session.add(project)
    session.commit()
    return project


def test_resolve_builtin_defaults(session_factory):
    session = session_factory()
    project = _project(session)
    skills = SkillResolver(session).resolve(project.id)
    names = [s.name for s in skills]
    assert {"continuity", "voice_consistency", "declare_effect_only"} <= set(names)
    assert skills[0].name == "continuity"  # 默认按 priority 降序
    assert all(s.source == "system" for s in skills)
    session.close()


def test_use_skill_renders_instructions(session_factory):
    session = session_factory()
    project = _project(session)
    skills = SkillResolver(session).resolve(project.id)
    text = use_skill(skills)
    assert "须遵守以下技能指令" in text
    assert "continuity" in text
    assert use_skill([]) == ""
    session.close()


def test_project_skill_overrides_system(session_factory):
    session = session_factory()
    project = _project(session)
    skill_registry.create(session, project.id, name="continuity", instructions="项目专属一致性规则")
    skills = SkillResolver(session).resolve(project.id)
    continuity = next(s for s in skills if s.name == "continuity")
    assert continuity.project_id == project.id        # 项目级覆盖系统级
    assert continuity.instructions == "项目专属一致性规则"
    session.close()


def test_forced_skill_priority(session_factory):
    session = session_factory()
    project = _project(session)
    skill_registry.create(session, project.id, name="extra", instructions="强制规则", priority=-999, forced=True)
    skills = SkillResolver(session).resolve(project.id)
    assert skills[0].name == "extra"                  # 强制技能最优先，无论 priority 多低
    session.close()


def test_names_filter(session_factory):
    session = session_factory()
    project = _project(session)
    skills = SkillResolver(session).resolve(project.id, names=["voice_consistency"])
    assert [s.name for s in skills] == ["voice_consistency"]
    session.close()


def test_skill_affects_context(session_factory):
    session = session_factory()
    project = _project(session)
    skills = SkillResolver(session).resolve(project.id)
    out = ContextCompiler(session).compile(project.id, skills=skills)
    assert "continuity" in out["layers"]["L0"]        # Skill 只影响上下文
    session.close()


def test_skill_api(client, session_factory):
    session = session_factory()
    project = _project(session)
    session.close()
    resp = client.get(f"/api/projects/{project.id}/skills")
    assert resp.status_code == 200
    names = [s["name"] for s in resp.json()]
    assert "continuity" in names
    resp = client.post(f"/api/projects/{project.id}/skills",
                       json={"name": "style_guide", "instructions": "统一用轻小说文风", "priority": 5})
    assert resp.status_code == 200 and resp.json()["name"] == "style_guide"