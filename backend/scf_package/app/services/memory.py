"""Memory Store（Step 15）：基础记忆的写入与 BM25 检索。

Truth/Index 分离（硬约束）：
- 原始 Artifact / JSON / Markdown 是唯一 Truth。
- MemoryEntry 只是「引用(truth) + 摘要 + 标签」的可重建索引。
- 检索用简单确定性 BM25 打分（无外部/向量依赖），未来可接 LLM rerank。
"""
import math
import re
from collections import Counter

from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import MemoryEntry

MEMORY_KINDS = (
    "story", "character", "relationship", "plot", "scene", "dialogue", "choice",
    "world_state", "pending_hook", "foreshadow", "author_intent", "current_focus",
)

_CJK = r"\u4e00-\u9fff"


def _tokenize(text: str) -> list[str]:
    """轻量分词：ASCII 词 + CJK 单字与其相邻双字组（提升中文召回）。"""
    cleaned = re.sub(rf"[^\w{_CJK}]+", " ", (text or "").lower())
    tokens: list[str] = []
    for part in cleaned.split():
        if re.fullmatch(rf"[{_CJK}]+", part):
            chars = list(part)
            tokens.extend(chars)
            tokens.extend("".join(pair) for pair in zip(chars, chars[1:], strict=False))
        else:
            tokens.append(part)
    return tokens


def _bm25(query_tokens, doc_tokens, df, doc_count: int, avgdl: float, k1: float = 1.5, b: float = 0.75) -> float:
    score = 0.0
    tf = Counter(doc_tokens)
    dl = len(doc_tokens) or 1
    for term in query_tokens:
        dft = df.get(term, 0)
        if dft == 0:
            continue
        idf = math.log(1.0 + (doc_count - dft + 0.5) / (dft + 0.5))
        ft = tf.get(term, 0)
        score += idf * (ft * (k1 + 1.0)) / (ft + k1 * (1.0 - b + b * dl / avgdl))
    return score


def _row_dict(m: MemoryEntry, score: float) -> dict:
    return {
        "id": m.id, "kind": m.kind, "ref_kind": m.ref_kind, "ref_id": m.ref_id,
        "content": m.content, "tags": m.tags or [], "score": round(score, 6),
    }


class MemoryStore:
    def remember(
        self,
        session: Session,
        project_id: str,
        *,
        kind: str,
        content: str,
        ref_kind: str = "",
        ref_id: str | None = None,
        tags: list[str] | None = None,
    ) -> MemoryEntry:
        if kind not in MEMORY_KINDS:
            raise AppError(f"未知记忆类型：{kind}", code="invalid_memory_kind", status=400)
        entry = MemoryEntry(
            project_id=project_id, kind=kind, ref_kind=ref_kind, ref_id=ref_id,
            content=content, tags=tags or [],
        )
        session.add(entry)
        session.flush()
        return entry

    def search(self, session: Session, project_id: str, query: str, *, top_k: int = 5) -> list[dict]:
        """BM25 检索候选（可重建索引）；结果只是候选，truth 以 ref_kind/ref_id 回指为准。"""
        rows = (
            session.query(MemoryEntry)
            .filter(MemoryEntry.project_id == project_id)
            .order_by(MemoryEntry.created_at)
            .all()
        )
        if not rows or not query.strip():
            return []
        query_tokens = _tokenize(query)
        if not query_tokens:
            return []
        docs = [_tokenize(m.content + " " + " ".join(m.tags or [])) for m in rows]
        doc_count = len(docs)
        avgdl = sum(len(d) for d in docs) / doc_count if doc_count else 0.0
        df: dict[str, int] = {}
        for d in docs:
            for term in set(d):
                df[term] = df.get(term, 0) + 1
        scored = [
            (m, _bm25(query_tokens, docs[i], df, doc_count, avgdl))
            for i, m in enumerate(rows)
        ]
        scored = [(m, s) for m, s in scored if s > 0.0]
        scored.sort(key=lambda x: x[1], reverse=True)
        return [_row_dict(m, s) for m, s in scored[:top_k]]

    def forget(self, session: Session, memory_id: str) -> None:
        entry = session.get(MemoryEntry, memory_id)
        if entry is None:
            raise AppError(f"记忆 {memory_id} 不存在", code="memory_not_found", status=404)
        session.delete(entry)

    def list_kind(self, session: Session, project_id: str, kind: str) -> list[dict]:
        rows = (
            session.query(MemoryEntry)
            .filter(MemoryEntry.project_id == project_id, MemoryEntry.kind == kind)
            .order_by(MemoryEntry.created_at)
            .all()
        )
        return [_row_dict(m, 0.0) for m in rows]


memory_store = MemoryStore()