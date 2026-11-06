"""Gold → `chunks` (spec 8.7, 9.1). Đọc Gold đã nạp Postgres, không cần Spark (D-020).

Chunk là mục lá: Điểm; Khoản không có Điểm; Điều không có Khoản. Điểm kèm câu dẫn Khoản để tự đủ nghĩa (có mức phạt).
Câu dẫn có thể đổi độc lập với Điểm nên một version Điểm có thể tách thành nhiều chunk theo thời gian.
Chỉ embed lại chunk có `embed_text` thay đổi.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from sqlalchemy import Engine, text

from luatgt.common.config import Settings, get_settings
from luatgt.common.db import make_engine
from luatgt.common.job_runs import job_run
from luatgt.common.logging import get_logger, setup_logging
from luatgt.parsing.structure import doc_key
from luatgt.retrieval.embed import Embedder, SentenceTransformerEmbedder, to_pgvector

log = get_logger(__name__)


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    provision_key: str
    version_no: int
    vbpl_id: str
    so_hieu: str
    hierarchy_path: str
    embed_text: str
    display_text: str
    valid_from: date
    valid_to: date


def _level(key: str) -> str:
    return {"D": "dieu", "K": "khoan", "P": "diem"}[key.rsplit("/", 1)[-1][0]]


def _label(part: str) -> str:
    kind, value = part[0], part[1:]
    if kind == "D":
        return f"Điều {value}"
    if kind == "K":
        return f"Khoản {value}"
    return f"Điểm {'đ' if value == 'dd' else value}"


def _hierarchy(key: str, rows: dict[str, dict]) -> str:
    """"Chương II > Mục 1 > Điều 6. Tiêu đề > Khoản 3 > Điểm a"; mục do sửa đổi thêm dùng tiêu đề Điều gốc."""
    parts = key.split("/")
    dieu_key = "/".join(parts[:2])
    dieu = rows.get(dieu_key, {})
    ancestors = []
    parent = dieu.get("parent_id")
    by_id = {r["provision_id"]: r for r in rows.values()}
    while parent and parent in by_id:
        row = by_id[parent]
        tail = row["provision_key"].rsplit("/", 1)[-1]
        name = f"Mục {tail[1:]}" if row["level"] == "muc" else f"Chương {tail[1:]}"
        ancestors.insert(0, name)
        parent = row.get("parent_id")
    title = dieu.get("title") or ""
    head = f"{_label(parts[1])}. {title}" if title else _label(parts[1])
    return " > ".join([*ancestors, head, *(_label(p) for p in parts[2:])])


def build_chunks(
    documents: list[dict], provisions: list[dict], versions: list[dict], amending_ids: set[str]
) -> list[Chunk]:
    """Văn bản trong `amending_ids` bị loại: nội dung của chúng đã nằm trong phiên bản của văn bản đích."""
    docs = {doc_key(d["so_hieu"]): d for d in documents if d["vbpl_id"] not in amending_ids}
    rows = {p["provision_key"]: p for p in provisions}
    by_key: dict[str, list[dict]] = defaultdict(list)
    children: set[str] = set()
    for v in versions:
        by_key[v["provision_key"]].append(v)
        parts = v["provision_key"].split("/")
        children.update("/".join(parts[:i]) for i in range(2, len(parts)))

    out: list[Chunk] = []
    for key in sorted(by_key):
        doc = docs.get(key.split("/")[0])
        if doc is None or key in children:
            continue
        path = _hierarchy(key, rows)
        heads = by_key.get(key.rsplit("/", 1)[0], []) if _level(key) == "diem" else []
        for v in sorted(by_key[key], key=lambda v: v["version_no"]):
            if not v["text"]:
                continue
            spans = [(v["valid_from"], v["valid_to"], "")]
            if heads:
                spans = [(max(v["valid_from"], h["valid_from"]), min(v["valid_to"], h["valid_to"]), h["text"] or "")
                         for h in sorted(heads, key=lambda h: h["valid_from"])
                         if h["valid_from"] < v["valid_to"] and v["valid_from"] < h["valid_to"]]
            for i, (start, end, head) in enumerate(spans, 1):
                suffix = "" if i == 1 else f"#{i}"
                body = f"{head} {v['text']}".strip()
                out.append(Chunk(f"{key}@v{v['version_no']}{suffix}", key, v["version_no"], doc["vbpl_id"],
                                 doc["so_hieu"], path, f"[{doc['ten_van_ban']}] - [{path}] : {body}", v["text"],
                                 start, end))
    return out


def load_chunks(engine: Engine, chunks: list[Chunk], embedder: Embedder) -> dict:
    with engine.connect() as conn:
        existing = dict(conn.execute(text("SELECT chunk_id, embed_text FROM chunks")).all())
    changed = [c for c in chunks if existing.get(c.chunk_id) != c.embed_text]
    vectors = embedder.embed([c.embed_text for c in changed]) if changed else []
    keep = [c.chunk_id for c in chunks]
    with engine.begin() as conn:
        removed = conn.execute(text("DELETE FROM chunks WHERE NOT (chunk_id = ANY(:k))"), {"k": keep}).rowcount
        if changed:
            conn.execute(text("""
                INSERT INTO chunks (chunk_id, provision_key, version_no, vbpl_id, so_hieu, hierarchy_path,
                                    embed_text, display_text, embedding, valid_from, valid_to)
                VALUES (:chunk_id, :provision_key, :version_no, :vbpl_id, :so_hieu, :hierarchy_path,
                        :embed_text, :display_text, CAST(:embedding AS vector), :valid_from, :valid_to)
                ON CONFLICT (chunk_id) DO UPDATE SET
                    embed_text = EXCLUDED.embed_text, display_text = EXCLUDED.display_text,
                    hierarchy_path = EXCLUDED.hierarchy_path, embedding = EXCLUDED.embedding,
                    valid_from = EXCLUDED.valid_from, valid_to = EXCLUDED.valid_to"""),
                [{**vars(c), "embedding": to_pgvector(v)} for c, v in zip(changed, vectors, strict=True)])
        # Giữ embedding nhưng cập nhật thời gian nếu chỉ valid_to đổi
        unchanged = [c for c in chunks if existing.get(c.chunk_id) == c.embed_text]
        if unchanged:
            conn.execute(text("UPDATE chunks SET valid_from = :f, valid_to = :t WHERE chunk_id = :i"),
                         [{"f": c.valid_from, "t": c.valid_to, "i": c.chunk_id} for c in unchanged])
    return {"chunks": len(chunks), "embedded": len(changed), "removed": removed}


def build_index(settings: Settings, engine: Engine | None = None, embedder: Embedder | None = None) -> dict:
    """Chạy job, ghi một dòng job_runs."""
    engine = engine or make_engine(settings)
    with job_run(engine, "build_index") as run:
        run.stats = _build_index(settings, engine, embedder)
    return {**run.stats, "run_id": str(run.run_id)}


def _build_index(settings: Settings, engine: Engine, embedder: Embedder | None) -> dict:
    with engine.connect() as conn:
        documents = [dict(r) for r in conn.execute(
            text("SELECT vbpl_id, so_hieu, ten_van_ban FROM documents")).mappings()]
        provisions = [dict(r) for r in conn.execute(
            text("SELECT provision_id, provision_key, level, title, parent_id FROM provisions")).mappings()]
        versions = [dict(r) for r in conn.execute(text(
            "SELECT provision_key, version_no, text, valid_from, valid_to FROM provision_versions")).mappings()]
        amending = set(conn.execute(text(
            "SELECT DISTINCT amending_vbpl_id FROM amendments WHERE parse_status = 'ok'")).scalars())
    chunks = build_chunks(documents, provisions, versions, amending)
    stats = load_chunks(engine, chunks, embedder or SentenceTransformerEmbedder(settings))
    log.info("build_index_done %s", stats)
    return stats


def main() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)
    print(build_index(settings))


if __name__ == "__main__":
    main()
