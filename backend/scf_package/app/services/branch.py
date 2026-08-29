"""Branch Service（Step 18）：分支一等公民（创建/复制/切换/比较/废弃/恢复/版本/合并）。

与 StoryGraph 的关联：base_version/base_kind 指向分叉点的 Artifact 版本；
与 Runtime 的关联：current_node_id + state 构成 BranchState（可恢复推进位置）。
不破坏现有 StoryGraph —— 分支只引用版本，不覆盖 Artifact 链。
"""
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import Branch, BranchVersion
from app.services.artifacts import latest_artifact


def _diff(a: dict, b: dict) -> dict:
    keys = sorted(set(a) | set(b))
    added, removed, changed = {}, {}, {}
    for key in keys:
        if key not in a:
            added[key] = b[key]
        elif key not in b:
            removed[key] = a[key]
        elif a[key] != b[key]:
            changed[key] = {"from": a[key], "to": b[key]}
    return {"added": added, "removed": removed, "changed": changed}


class BranchService:
    def __init__(self, session: Session):
        self.session = session

    def _get(self, branch_id: str, project_id: str | None = None) -> Branch:
        branch = self.session.get(Branch, branch_id)
        if branch is None:
            raise AppError(f"分支 {branch_id} 不存在", code="branch_not_found", status=404)
        if project_id is not None and branch.project_id != project_id:
            raise AppError("分支不属于该项目", code="branch_not_found", status=404)
        return branch

    def _select_only(self, project_id: str, branch_id: str) -> None:
        for b in self.session.query(Branch).filter(Branch.project_id == project_id).all():
            b.is_selected = b.id == branch_id

    def create(
        self, project_id: str, *, name: str, description: str = "", plan: dict | None = None,
        base_version: int | None = None, parent_branch_id: str | None = None,
        current_node_id: str | None = None, state: dict | None = None,
    ) -> Branch:
        if base_version is None:
            latest = latest_artifact(self.session, project_id, kind="story_graph")
            base_version = latest.version if latest is not None else 1
        branch = Branch(
            project_id=project_id, name=name, description=description, plan=plan or {},
            base_version=base_version, parent_branch_id=parent_branch_id,
            current_node_id=current_node_id, state=state or {}, status="active",
        )
        self.session.add(branch)
        self.session.flush()
        self._select_only(project_id, branch.id)
        self.session.commit()
        return branch

    def list_branches(self, project_id: str) -> list[Branch]:
        return (
            self.session.query(Branch)
            .filter(Branch.project_id == project_id)
            .order_by(Branch.created_at)
            .all()
        )

    def current(self, project_id: str) -> Branch | None:
        return (
            self.session.query(Branch)
            .filter(Branch.project_id == project_id, Branch.is_selected.is_(True))
            .first()
        )

    def switch(self, project_id: str, branch_id: str) -> Branch:
        branch = self._get(branch_id, project_id)
        self._select_only(project_id, branch_id)
        self.session.commit()
        return branch

    def copy(self, branch_id: str, *, name: str | None = None) -> Branch:
        src = self._get(branch_id)
        clone = Branch(
            project_id=src.project_id, parent_branch_id=src.id,
            name=name or f"{src.name}-copy", description=src.description, plan=dict(src.plan or {}),
            base_version=src.base_version, base_kind=src.base_kind,
            current_node_id=src.current_node_id, state=dict(src.state or {}), status="active",
        )
        self.session.add(clone)
        self.session.flush()
        self._select_only(src.project_id, clone.id)
        self.session.commit()
        return clone

    def abandon(self, branch_id: str) -> Branch:
        branch = self._get(branch_id)
        branch.status = "abandoned"
        branch.is_selected = False
        self.session.commit()
        return branch

    def restore(self, branch_id: str) -> Branch:
        branch = self._get(branch_id)
        branch.status = "active"
        self.session.commit()
        return branch

    def snapshot(self, branch_id: str, content: dict, *, change_reason: str | None = None) -> BranchVersion:
        branch = self._get(branch_id)
        latest = (
            self.session.query(BranchVersion)
            .filter(BranchVersion.branch_id == branch.id)
            .order_by(BranchVersion.version_no.desc())
            .first()
        )
        version_no = (latest.version_no + 1) if latest else 1
        bv = BranchVersion(branch_id=branch.id, version_no=version_no, kind="story_graph",
                           content=content, change_reason=change_reason)
        self.session.add(bv)
        self.session.commit()
        return bv

    def versions(self, branch_id: str) -> list[BranchVersion]:
        self._get(branch_id)
        return (
            self.session.query(BranchVersion)
            .filter(BranchVersion.branch_id == branch_id)
            .order_by(BranchVersion.version_no)
            .all()
        )

    def compare(self, branch_a_id: str, branch_b_id: str) -> dict:
        a = self._get(branch_a_id)
        b = self._get(branch_b_id)
        return {
            "branch_a": a.id, "branch_b": b.id,
            "state_diff": _diff(a.state or {}, b.state or {}),
            "plan_diff": _diff(a.plan or {}, b.plan or {}),
            "base_version_a": a.base_version, "base_version_b": b.base_version,
            "current_node_diff": {"a": a.current_node_id, "b": b.current_node_id},
        }

    def merge(self, source_id: str, target_id: str) -> Branch:
        src = self._get(source_id)
        tgt = self._get(target_id)
        if src.project_id != tgt.project_id:
            raise AppError("不能跨项目合并分支", code="branch_merge_conflict", status=400)
        if src.id == tgt.id:
            raise AppError("不能合并到自身", code="branch_merge_conflict", status=400)
        self.snapshot(src.id, {"merged_into": tgt.id, "target_name": tgt.name}, change_reason=f"merge→{tgt.id}")
        src.status = "merged"
        src.is_selected = False
        self.session.query(Branch).filter(Branch.project_id == src.project_id).update({Branch.is_selected: False})
        tgt.is_selected = True
        self.session.commit()
        return src

    def resume(self, branch_id: str) -> dict:
        """返回 BranchState（供 Runtime 恢复推进位置）。"""
        branch = self._get(branch_id)
        return {"current_node_id": branch.current_node_id, "state": dict(branch.state or {})}

    def is_ending(self, branch_id: str) -> bool:
        """分支是否已停在 ending 节点（关联 StoryGraph）。"""
        branch = self._get(branch_id)
        if not branch.current_node_id:
            return False
        story = latest_artifact(self.session, branch.project_id, kind="story_graph") or {}
        node = next(
            (n for n in (story.content or {}).get("nodes", []) if n.get("node_id") == branch.current_node_id),
            None,
        )
        return node is not None and node.get("kind") == "ending"


branch_service = BranchService