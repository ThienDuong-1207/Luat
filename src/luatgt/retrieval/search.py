"""Hybrid search có bộ lọc hiệu lực (spec 9.2).

Nhánh keyword nối từ bằng OR thay cho plainto_tsquery: câu hỏi tự nhiên hiếm khi có đủ mọi từ trong một điều
khoản, plainto (AND) gần như luôn trả rỗng (D-020). Nhánh vector quét đúng sau khi lọc, vì HNSW lọc sau khi duyệt
nên có thể thiếu kết quả; bảng chỉ vài nghìn dòng.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Literal

from sqlalchemy import Engine, text

from luatgt.common.config import RetrievalSettings
from luatgt.retrieval.embed import Embedder, to_pgvector

Mode = Literal["hybrid", "vector", "keyword"]

COLUMNS = "chunk_id, provision_key, version_no, so_hieu, hierarchy_path, display_text, valid_from, valid_to"
VALID = ":as_of >= valid_from AND :as_of < valid_to"


@dataclass
class SearchHit:
    chunk_id: str
    provision_key: str
    version_no: int
    so_hieu: str
    hierarchy_path: str
    display_text: str
    valid_from: date
    valid_to: date
    score: float
    similarity: float | None = None  # cosine của nhánh vector; None nếu chunk chỉ có ở nhánh keyword
    violations: list[dict] = field(default_factory=list)


def expand_query(question: str, expansions: dict[str, str]) -> str:
    """Thêm chữ trong văn bản luật cho từ đời thường có trong câu hỏi."""
    low = question.lower()
    extra = dict.fromkeys(v for k, v in expansions.items() if k in low)
    return " ".join([question, *extra])


def keyword_query(question: str, stopwords: list[str]) -> str:
    """Câu hỏi → biểu thức OR cho to_tsquery. Rỗng nếu chỉ còn từ dừng."""
    stop = {w.lower() for w in stopwords}
    words = [w for w in re.findall(r"\w+", question.lower()) if w not in stop]
    return " | ".join(dict.fromkeys(words))


def _keyword(conn, query: str, where: str, params: dict, n: int) -> list[dict]:
    if not query:
        return []
    return [dict(r) for r in conn.execute(text(f"""
        SELECT {COLUMNS} FROM (
            SELECT *, ts_rank(tsv, to_tsquery('simple', f_unaccent(:q))) AS rank
            FROM chunks
            WHERE tsv @@ to_tsquery('simple', f_unaccent(:q)) {where}
        ) t ORDER BY rank DESC, chunk_id LIMIT :n"""), {**params, "q": query, "n": n}).mappings()]


def _vector(conn, vector: list[float], where: str, params: dict, n: int) -> list[dict]:
    return [dict(r) for r in conn.execute(text(f"""
        WITH f AS MATERIALIZED (SELECT * FROM chunks WHERE embedding IS NOT NULL {where})
        SELECT {COLUMNS}, 1 - (embedding <=> CAST(:v AS vector)) AS similarity FROM f
        ORDER BY embedding <=> CAST(:v AS vector), chunk_id LIMIT :n"""),
        {**params, "v": to_pgvector(vector), "n": n}).mappings()]


def rrf_merge(branches: list[list[dict]], rrf_k: int) -> list[tuple[dict, float]]:
    """Reciprocal Rank Fusion: score = Σ 1/(rrf_k + rank). Hoà thì xếp theo chunk_id cho ổn định."""
    scores: dict[str, float] = {}
    rows: dict[str, dict] = {}
    for branch in branches:
        for rank, row in enumerate(branch, 1):
            scores[row["chunk_id"]] = scores.get(row["chunk_id"], 0.0) + 1 / (rrf_k + rank)
            rows[row["chunk_id"]] = {**rows.get(row["chunk_id"], {}), **row}
    return sorted(((rows[c], s) for c, s in scores.items()), key=lambda x: (-x[1], x[0]["chunk_id"]))


def _attach_violations(conn, hits: list[SearchHit], as_of: date) -> None:
    if not hits:
        return
    rows = conn.execute(text(f"""
        SELECT * FROM violations WHERE provision_key = ANY(:k) AND {VALID}"""),
        {"k": [h.provision_key for h in hits], "as_of": as_of}).mappings()
    by_key: dict[str, list[dict]] = {}
    for r in rows:
        by_key.setdefault(r["provision_key"], []).append(dict(r))
    for h in hits:
        h.violations = by_key.get(h.provision_key, [])


def hybrid_search(
    engine: Engine, embedder: Embedder, query: str, as_of: date, cfg: RetrievalSettings,
    k: int | None = None, mode: Mode = "hybrid", apply_validity: bool = True,
) -> list[SearchHit]:
    """`mode` và `apply_validity=False` chỉ dùng cho thí nghiệm spec 16.3."""
    where = f"AND {VALID}" if apply_validity else ""
    params = {"as_of": as_of} if apply_validity else {}
    n = cfg.branch_top_n
    query = expand_query(query, cfg.query_expansions)
    with engine.connect() as conn:
        branches = []
        if mode in ("hybrid", "keyword"):
            branches.append(_keyword(conn, keyword_query(query, cfg.stopwords), where, params, n))
        if mode in ("hybrid", "vector"):
            branches.append(_vector(conn, embedder.embed([query])[0], where, params, n))
        merged = rrf_merge(branches, cfg.rrf_k)[: k or cfg.k]
        hits = [SearchHit(**row, score=score) for row, score in merged]
        _attach_violations(conn, hits, as_of)
    return hits
