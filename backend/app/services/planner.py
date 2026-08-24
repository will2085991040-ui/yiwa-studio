"""规划器（Phase 0 确定性实现）：目标 → 模板 + 构建计划。

这是 Director Agent 的确定性脚手架：Phase 5 由 Director(LLM) 产出 AgentPlan 后替换此处。
当前用关键词规则识别模板（课程引流 / 客服 / 互动短剧 / 通用），并生成 14 步构建计划
（对应 Golden Path：Understanding Goal → … → Ready to Run）。
"""
from dataclasses import dataclass

TEMPLATE_KEYWORDS: dict[str, list[str]] = {
    "course_promotion": ["课程", "推广", "引流", "学习", "培训", "大学生"],
    "customer_service": ["客服", "售后", "SaaS", "支持", "工单", "咨询"],
    "interactive_drama": ["短剧", "互动剧", "剧情", "小说", "角色扮演", "故事"],
}

PLAN_STEPS = [
    ("understand_goal", "Understanding Goal", "理解用户目标", "director"),
    ("audience", "Audience Analysis", "用户画像与分层", "audience"),
    ("strategy", "Growth Strategy", "内容/引流/转化策略", "strategy"),
    ("funnel", "Funnel Design", "转化漏斗设计", "funnel"),
    ("world", "World / Context", "世界/内容背景", "world"),
    ("character", "Character Design", "角色池与角色卡", "character"),
    ("relationship", "Character Relationship", "角色关系图", "relationship"),
    ("plot", "Content Design", "内容主线", "plot"),
    ("branch", "Interaction Design", "互动分支设计", "branch"),
    ("graph", "Interaction Graph", "互动图生成", "branch"),
    ("tools", "Tool Planning", "工具与权限规划", "interaction"),
    ("memory_knowledge", "Memory & Knowledge", "记忆与知识库规划", "runtime"),
    ("evaluation", "Evaluation", "评测策略生成", "evaluation"),
    ("ready", "Ready to Run", "编译可运行 Agent", "director"),
]


@dataclass
class Plan:
    template: str
    goal_summary: str
    steps: list[dict]


def _pick_template(goal: str) -> str:
    for template, keywords in TEMPLATE_KEYWORDS.items():
        if any(k in goal for k in keywords):
            return template
    return "generic"


def _goal_summary(goal: str) -> str:
    cleaned = " ".join(goal.split())
    return cleaned[:96] + ("…" if len(cleaned) > 96 else "")


def build_plan(goal: str) -> Plan:
    """目标 → 模板 + 14 步计划（全部 pending，随 Phase 推进逐步完成）。"""
    template = _pick_template(goal)
    return Plan(
        template=template,
        goal_summary=_goal_summary(goal),
        steps=[
            {"key": key, "label": label, "description": desc, "agent": agent, "status": "pending"}
            for key, label, desc, agent in PLAN_STEPS
        ],
    )
