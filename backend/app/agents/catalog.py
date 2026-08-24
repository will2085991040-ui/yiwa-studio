"""Agent 清单（V2.0 五层 14 Agent + Experiment）。
Phase 0：全部以 PlannedAgent 登记（诚实声明未实现），Director 等在后续 Phase 填充 run()。
"""
from app.agents.base import PlannedAgent, registry
from app.agents.character import CharacterAgent
from app.agents.dialogue import DialogueAgent
from app.agents.director import DirectorAgent
from app.agents.plot import PlotAgent
from app.agents.relationship import RelationshipAgent
from app.agents.scene import SceneAgent
from app.agents.storyboard import StoryboardAgent
from app.agents.world import WorldAgent

_AGENTS = [
    # Layer 1 编排
    ("director", "orchestration", "目标理解、任务分解、Agent 调度、重试与整合（Agent Architect）"),
    # Layer 2 增长智能
    ("audience", "growth", "用户画像、分层、痛点、动机、异议与转化意愿"),
    ("strategy", "growth", "内容/引流/互动/转化/渠道/CTA 策略"),
    ("funnel", "growth", "转化漏斗阶段与节点设计"),
    # Layer 3 内容智能
    ("world", "content", "IP/品牌世界观与核心设定"),
    ("character", "content", "业务化角色卡（含 conversion_role 与权限）"),
    ("relationship", "content", "角色关系图与关系迁移规则"),
    ("plot", "content", "内容主线（按漏斗阶段编排）"),
    ("branch", "content", "互动分支与行为分支 → Interaction Graph"),
    ("scene", "content", "互动场景卡"),
    ("dialogue", "content", "多角色对话生成（防 OOC）"),
    # Layer 4 互动执行
    ("interaction", "interaction", "互动决策者：聊天/提问/切角色/CTA/工具/结束"),
    ("runtime", "interaction", "实时运行循环与上下文组装"),
    # Layer 5 增长优化
    ("analytics", "optimization", "行为/漏斗/转化/成本指标与归因"),
    ("evaluation", "optimization", "质量+效果+成本评测（规则 + LLM-as-Judge）"),
    ("optimization", "optimization", "改进提案 → 审批/实验 → 版本发布"),
    ("experiment", "optimization", "A/B 流量分配、指标对比、胜出判定"),
]

for _name, _layer, _desc in _AGENTS:
    registry.register(
        PlannedAgent(
            name=_name,
            layer=_layer,
            description=_desc,
            input_schema={"type": "object", "properties": {}},
            output_schema={"type": "object", "properties": {}},
        )
    )

# Director(Step5)/World(Step6)/Character(Step7)/Relationship(Step9)/Plot(Step10)/Scene(Step11)/Dialogue(Step12) 已落地：
# 真实实现替换占位登记；SceneAgent/DialogueAgent 为 on-demand（pipeline=False，不参与 DAG 全量生成）。
registry.register(DirectorAgent(), replace=True)
registry.register(WorldAgent(), replace=True)
registry.register(CharacterAgent(), replace=True)
registry.register(RelationshipAgent(), replace=True)
registry.register(PlotAgent(), replace=True)
registry.register(SceneAgent(), replace=True)
registry.register(DialogueAgent(), replace=True)
registry.register(StoryboardAgent(), replace=True)
