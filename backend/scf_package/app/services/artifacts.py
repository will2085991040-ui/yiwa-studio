"""Artifact 版本体系（Step 8）：Git 式追加版本，旧版本不覆盖。

同 (project_id, kind) 的多次生成形成 v1/v2/... 链：
- version 自增，parent_version 指向上一版本（v1 为 None）
- 新版本写入时把旧版本 is_latest 置 False
- source 区分 agent 自动生成 / user 手动修订，change_reason 记录修改原因
"""
from sqlalchemy.orm import Session

from app.models import Artifact


def latest_artifact(
    session: Session,
    project_id: str,
    *,
    kind: str | None = None,
    task_id: str | None = None,
) -> Artifact | None:
    """返回某 project 下最新（is_latest=True）的 Artifact，可按 kind / task_id 过滤。"""
    query = session.query(Artifact).filter(Artifact.project_id == project_id, Artifact.is_latest.is_(True))
    if kind is not None:
        query = query.filter(Artifact.kind == kind)
    if task_id is not None:
        query = query.filter(Artifact.task_id == task_id)
    return query.order_by(Artifact.version.desc()).first()


def persist_versioned_artifact(
    session: Session,
    *,
    project_id: str,
    task_id: str,
    agent: str,
    kind: str,
    content: dict,
    prompt_version: str,
    source: str = "agent",
    change_reason: str | None = None,
) -> Artifact:
    """写入一个新版本 Artifact，并把同 kind 的旧版本标记为非最新。"""
    existing = (
        session.query(Artifact)
        .filter(Artifact.project_id == project_id, Artifact.kind == kind)
        .order_by(Artifact.version.desc())
        .first()
    )
    parent = existing.version if existing is not None else None
    version = (existing.version + 1) if existing is not None else 1

    # 旧版本让位（Git 式：保留历史，只切换"当前"指针）
    session.query(Artifact).filter(
        Artifact.project_id == project_id, Artifact.kind == kind, Artifact.is_latest.is_(True)
    ).update({Artifact.is_latest: False})

    artifact = Artifact(
        project_id=project_id,
        task_id=task_id,
        agent=agent,
        kind=kind,
        content=content,
        prompt_version=prompt_version,
        version=version,
        parent_version=parent,
        source=source,
        change_reason=change_reason,
        is_latest=True,
    )
    session.add(artifact)
    session.flush()
    return artifact