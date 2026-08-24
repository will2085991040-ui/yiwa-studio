"""Skill System（Step 17）：Skill / SkillRegistry / SkillResolver / use_skill。

硬约束：Skill 没有任何数据库写权限——它不持有 Session、不落 Artifact / Runtime State，
只通过 `use_skill` 把 instructions 注入 Agent 上下文来影响行为。当前不做插件市场。
"""
from sqlalchemy.orm import Session

from app.models import Skill

BUILTIN_SKILLS = [
    {
        "name": "continuity",
        "description": "剧情一致性",
        "instructions": "任何新生成内容必须与既有世界观与人物设定一致，不得无故推翻已确立事实。",
        "priority": 100, "is_default": True,
    },
    {
        "name": "voice_consistency",
        "description": "角色声线一致",
        "instructions": "对白必须保持角色已设定的性格、口癖、说话方式，不得串味。",
        "priority": 80, "is_default": True,
    },
    {
        "name": "declare_effect_only",
        "description": "状态只声明不执行",
        "instructions": "LLM 只能产出声明式 StoryEffect / StoryCondition，禁止直接修改 Runtime State。",
        "priority": 60, "is_default": True,
    },
]


class SkillRegistry:
    def ensure_defaults(self, session: Session) -> None:
        """幂等写入内置系统技能（source=system, project_id=None）。"""
        existing = {s.name for s in session.query(Skill).filter(Skill.project_id.is_(None)).all()}
        added = False
        for spec in BUILTIN_SKILLS:
            if spec["name"] in existing:
                continue
            session.add(Skill(project_id=None, source="system", **spec))
            added = True
        if added:
            session.commit()

    def create(
        self,
        session: Session,
        project_id: str,
        *,
        name: str,
        description: str = "",
        instructions: str = "",
        source: str = "project",
        enabled: bool = True,
        priority: int = 0,
        forced: bool = False,
        is_default: bool = False,
    ) -> Skill:
        skill = Skill(
            project_id=project_id, name=name, description=description, instructions=instructions,
            source=source, enabled=enabled, priority=priority, forced=forced, is_default=is_default,
        )
        session.add(skill)
        session.commit()
        return skill


class SkillResolver:
    def __init__(self, session: Session):
        self.session = session

    def resolve(self, project_id: str, *, names: list[str] | None = None) -> list[Skill]:
        """解析可用技能：系统 + 项目，enabled=True；项目同名覆盖系统；强制技能优先。"""
        SkillRegistry().ensure_defaults(self.session)
        rows = (
            self.session.query(Skill)
            .filter(Skill.enabled.is_(True), (Skill.project_id.is_(None)) | (Skill.project_id == project_id))
            .all()
        )
        dedup: dict[str, Skill] = {}
        for s in rows:
            existing = dedup.get(s.name)
            if existing is None or (s.project_id == project_id and existing.project_id is None):
                dedup[s.name] = s
        skills = list(dedup.values())
        if names:
            skills = [s for s in skills if s.name in names]
        skills.sort(key=lambda s: (0 if s.forced else 1, -s.priority, s.name))
        return skills


def use_skill(skills: list[Skill]) -> str:
    """把技能指令渲染为注入上下文的文本块（Skill 影响行为的唯一途径）。"""
    if not skills:
        return ""
    blocks = [f"## 技能：{s.name}\n{s.instructions}" for s in skills if s.instructions]
    if not blocks:
        return ""
    return "须遵守以下技能指令：\n" + "\n\n".join(blocks)


skill_registry = SkillRegistry()