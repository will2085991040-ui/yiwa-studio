"""Version + Content Governance（Step 14）：promote / revert / compare + 可编辑性检查。

不做复杂 Git：只提供确定性的内容 diff、latest 指针切换、以及「回滚 = 追加新版本」，
历史版本一律保留，永不物理删除。
"""
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import Artifact
from app.services.artifacts import latest_artifact, persist_versioned_artifact


def _ensure_kind_version(session: Session, project_id: str, kind: str, version: int) -> Artifact:
    artifact = (
        session.query(Artifact)
        .filter(Artifact.project_id == project_id, Artifact.kind == kind, Artifact.version == version)
        .first()
    )
    if artifact is not None:
        return artifact
    has_kind = (
        session.query(Artifact)
        .filter(Artifact.project_id == project_id, Artifact.kind == kind)
        .first()
    )
    if has_kind is None:
        raise AppError(f"artifact kind '{kind}' 不存在", code="artifact_not_found", status=404)
    raise AppError(f"版本 {kind}:v{version} 不存在", code="version_not_found", status=404)


def _diff(a: dict, b: dict) -> dict:
    """简单 deterministic diff：顶层键的 added / removed / changed（不做复杂 Git）。"""
    keys = sorted(set(a) | set(b))
    added: dict = {}
    removed: dict = {}
    changed: dict = {}
    for key in keys:
        if key not in a:
            added[key] = b[key]
        elif key not in b:
            removed[key] = a[key]
        elif a[key] != b[key]:
            changed[key] = {"from": a[key], "to": b[key]}
    return {"added": added, "removed": removed, "changed": changed}


def _metadata(a: Artifact) -> dict:
    return {
        "task_id": a.task_id,
        "agent": a.agent,
        "prompt_version": a.prompt_version,
        "source": a.source,
        "change_reason": a.change_reason,
        "parent_version": a.parent_version,
    }


def _summary(a: Artifact) -> dict:
    return {
        "kind": a.kind,
        "version": a.version,
        "is_latest": a.is_latest,
        "parent_version": a.parent_version,
        "source": a.source,
        "change_reason": a.change_reason,
    }


def _assert_no_conflict(session: Session, project_id: str, kind: str, expected_latest: int | None) -> None:
    if expected_latest is None:
        return
    current = latest_artifact(session, project_id, kind=kind)
    actual = current.version if current is not None else 0
    if actual != expected_latest:
        raise AppError(
            f"版本冲突：当前 {kind} latest=v{actual}，期望 v{expected_latest}",
            code="version_conflict", status=409,
        )


def compare_artifacts(
    session: Session, *, project_id: str, kind: str, version_a: int, version_b: int
) -> dict:
    a = _ensure_kind_version(session, project_id, kind, version_a)
    b = _ensure_kind_version(session, project_id, kind, version_b)
    return {
        "version_a": version_a,
        "version_b": version_b,
        "content_diff": _diff(a.content or {}, b.content or {}),
        "metadata_diff": _diff(_metadata(a), _metadata(b)),
    }


def promote_artifact(
    session: Session, *, project_id: str, kind: str, version: int, expected_latest: int | None = None
) -> dict:
    """指定某个历史版本成为当前 latest；历史版本一律保留，且保证唯一 latest。"""
    _ensure_kind_version(session, project_id, kind, version)
    _assert_no_conflict(session, project_id, kind, expected_latest)
    rows = (
        session.query(Artifact)
        .filter(Artifact.project_id == project_id, Artifact.kind == kind)
        .all()
    )
    for row in rows:
        row.is_latest = row.version == version
    session.flush()
    target = _ensure_kind_version(session, project_id, kind, version)
    session.commit()
    return _summary(target)


def revert_artifact(
    session: Session, *, project_id: str, kind: str, version: int, expected_latest: int | None = None
) -> dict:
    """回滚 = 追加新版本（绝不物理删除）：content 取自目标旧版本，parent 指向当前 latest。"""
    target = _ensure_kind_version(session, project_id, kind, version)
    _assert_no_conflict(session, project_id, kind, expected_latest)
    artifact = persist_versioned_artifact(
        session,
        project_id=project_id,
        task_id=target.task_id,
        agent=target.agent,
        kind=kind,
        content=dict(target.content or {}),
        prompt_version=target.prompt_version,
        source="user",
        change_reason=f"revert:v{version}",
    )
    session.commit()
    return _summary(artifact)


class ContentGovernance:
    """统一内容治理门面：assert_editable + promote / revert / compare。"""

    def __init__(self, session: Session, project_id: str):
        self.session = session
        self.project_id = project_id

    def assert_editable(self, node_id: str | None = None) -> None:
        """节点级锁检查：StoryGraph 中被 locked 的节点拒绝修改（统一 409）。"""
        if node_id is None:
            return
        story = latest_artifact(self.session, self.project_id, kind="story_graph")
        if story is None or not story.content:
            return
        node = next(
            (n for n in (story.content or {}).get("nodes", []) if n.get("node_id") == node_id), None,
        )
        if node is not None and node.get("locked"):
            raise AppError(f"节点 {node_id} 已被用户锁定，无法修改", code="locked_node", status=409)

    def compare(self, kind: str, version_a: int, version_b: int) -> dict:
        return compare_artifacts(
            self.session, project_id=self.project_id, kind=kind, version_a=version_a, version_b=version_b,
        )

    def promote(self, kind: str, version: int, expected_latest: int | None = None) -> dict:
        return promote_artifact(
            self.session, project_id=self.project_id, kind=kind, version=version, expected_latest=expected_latest,
        )

    def revert(self, kind: str, version: int, expected_latest: int | None = None) -> dict:
        return revert_artifact(
            self.session, project_id=self.project_id, kind=kind, version=version, expected_latest=expected_latest,
        )