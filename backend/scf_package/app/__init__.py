"""包初始化：导入模型，供 Alembic autogenerate 发现。"""
from app.agents import base, catalog  # noqa: F401
from app.agents.base import registry  # noqa: F401
from app.models import AgentRun, AgentSpec, AgentVersion, Project  # noqa: F401
