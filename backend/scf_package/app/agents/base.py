"""Agent 基类与注册表：所有 Agent 的单一入口（Phase 0 注册定义，逐阶段填充实现）。"""
from abc import ABC, abstractmethod
from typing import Any


class BaseAgent(ABC):
    """Agent 契约：职责单一、输入/输出结构化、可独立测试。"""

    name: str = "base"
    layer: str = "core"
    description: str = ""
    input_schema: dict = {}
    output_schema: dict = {}
    pipeline: bool = True  # True=可被 Orchestrator DAG 全量执行；False=由用户按节点/局部主动调用（on-demand）

    @abstractmethod
    async def run(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """执行 Agent；返回 output_schema 约束的字典。"""
        raise NotImplementedError


class PlannedAgent(BaseAgent):
    """已登记、尚未实现的 Agent（Phase 0 诚实声明，后续 Phase 逐个替换为真实实现）。"""

    def __init__(self, name: str, layer: str, description: str, input_schema: dict, output_schema: dict):
        self.name = name
        self.layer = layer
        self.description = description
        self.input_schema = input_schema
        self.output_schema = output_schema

    async def run(self, input_data: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError(f"Agent '{self.name}' 尚未实现（当前 Phase 0，随 Golden Path 逐阶段接入）")


class AgentRegistry:
    """Agent 注册表：新增 Agent 不破坏现有架构。"""

    def __init__(self) -> None:
        self._agents: dict[str, BaseAgent] = {}

    def register(self, agent: BaseAgent, *, replace: bool = False) -> None:
        if agent.name in self._agents and not replace:
            raise ValueError(f"Agent '{agent.name}' 已注册")
        self._agents[agent.name] = agent

    def get(self, name: str) -> BaseAgent:
        if name not in self._agents:
            raise KeyError(f"Agent '{name}' 未注册")
        return self._agents[name]

    def is_implemented(self, name: str) -> bool:
        agent = self.get(name)
        return agent.__class__ is not PlannedAgent

    def list(self) -> list[dict]:
        return [
            {
                "name": a.name,
                "layer": a.layer,
                "description": a.description,
                "input_schema": a.input_schema,
                "output_schema": a.output_schema,
                "implemented": a.__class__ is not PlannedAgent,
            }
            for a in self._agents.values()
        ]


registry = AgentRegistry()
