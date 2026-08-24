"""Prompt 版本基础设施：定义 + 不可变版本 + 变量渲染。

这是未来 Agent 执行系统稳定依赖的基础设施：
- Agent 选定某个 PromptVersion（prompt_id + version_no）
- 用 render() 把 content 渲染成最终 system prompt
- 拼进 LLMRequest（prompt_version 已由 Step 1 提供回显能力）
- 交给 LLMProvider（Step 2 已就绪）

确定性逻辑全部由 Python 负责，不依赖 LLM。
"""
from sqlalchemy.orm import Session

from app.models import PromptDefinition, PromptVersion


def get_definition(session: Session, name: str) -> PromptDefinition | None:
    return session.query(PromptDefinition).filter(PromptDefinition.name == name).first()


def get_or_create_definition(session: Session, name: str, description: str | None = None) -> PromptDefinition:
    """按 name 幂等地获取或创建 Prompt 定义（name 是稳定引用键）。"""
    definition = get_definition(session, name)
    if definition is None:
        definition = PromptDefinition(name=name, description=description)
        session.add(definition)
        session.flush()
    session.commit()
    return definition


def list_definitions(session: Session) -> list[PromptDefinition]:
    return session.query(PromptDefinition).order_by(PromptDefinition.created_at.asc()).all()


def create_version(
    session: Session,
    definition: PromptDefinition,
    *,
    content: str,
    variables: list[dict] | None = None,
    model_preferences: dict | None = None,
    status: str = "draft",
) -> PromptVersion:
    """为定义追加一个新版本（version_no 自增），绝不原地修改旧版本。"""
    version = PromptVersion(
        prompt_definition_id=definition.id,
        version_no=_next_version_no(session, definition.id),
        content=content,
        variables=variables or [],
        model_preferences=model_preferences or {},
        status=status,
    )
    session.add(version)
    session.flush()
    session.commit()
    return version


def _next_version_no(session: Session, definition_id: str) -> int:
    latest = (
        session.query(PromptVersion.version_no)
        .filter(PromptVersion.prompt_definition_id == definition_id)
        .order_by(PromptVersion.version_no.desc())
        .first()
    )
    return (latest[0] + 1) if latest is not None else 1


def get_version(session: Session, definition: PromptDefinition, version_no: int) -> PromptVersion | None:
    return (
        session.query(PromptVersion)
        .filter(
            PromptVersion.prompt_definition_id == definition.id,
            PromptVersion.version_no == version_no,
        )
        .first()
    )


def get_latest(session: Session, definition: PromptDefinition, status: str | None = None) -> PromptVersion | None:
    q = session.query(PromptVersion).filter(PromptVersion.prompt_definition_id == definition.id)
    if status is not None:
        q = q.filter(PromptVersion.status == status)
    return q.order_by(PromptVersion.version_no.desc()).first()


def list_versions(session: Session, definition: PromptDefinition) -> list[PromptVersion]:
    return (
        session.query(PromptVersion)
        .filter(PromptVersion.prompt_definition_id == definition.id)
        .order_by(PromptVersion.version_no.asc())
        .all()
    )


def render(version: PromptVersion, values: dict) -> str:
    """把模板渲染为最终文本。

    规则（确定性）：
    - 显式传入的值优先
    - 未传入但声明了 default 的变量用 default
    - 未传入、无 default、且 required 的变量 => 抛 ValueError（缺必需变量）
    - 其余未匹配占位符保留原样
    """
    params: dict = {}
    missing: list[str] = []
    for var in version.variables or []:
        name = var["name"]
        if name in values:
            params[name] = values[name]
        elif var.get("default") is not None:
            params[name] = var["default"]
        elif var.get("required", False):
            missing.append(name)
    if missing:
        raise ValueError(f"缺少必需变量：{', '.join(sorted(missing))}")
    rendered = version.content
    for name, value in params.items():
        rendered = rendered.replace("{" + name + "}", str(value))
    return rendered


def prompt_tag(definition_name: str, version_no: int) -> str:
    """生成可写入 LLMRequest.prompt_version 的稳定标签。"""
    return f"{definition_name}:v{version_no}"