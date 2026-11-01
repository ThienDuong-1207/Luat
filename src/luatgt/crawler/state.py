"""Thao tác bảng crawl_runs, crawl_queue, quarantine. Mọi ghi đều idempotent theo khoá."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field

from sqlalchemy import Engine, text

MAX_RETRIES = 3


@dataclass
class RunCounters:
    discovered: int = 0
    detail_ok: int = 0
    pdf_downloaded: int = 0
    errors: int = 0
    skipped: int = 0
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class QueueItem:
    vbpl_id: str
    stage: str
    url: str
    status: str
    retry_count: int
    content_hash: str | None


class CrawlState:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    # ---------- crawl_runs ----------
    def start_run(self, selector_version: str) -> uuid.UUID:
        run_id = uuid.uuid4()
        with self.engine.begin() as conn:
            conn.execute(
                text("""INSERT INTO crawl_runs (run_id, started_at, status, selector_version)
                        VALUES (:id, now(), 'running', :sv)"""),
                {"id": run_id, "sv": selector_version},
            )
        return run_id

    def finish_run(self, run_id: uuid.UUID, status: str, c: RunCounters) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                text("""UPDATE crawl_runs SET finished_at = now(), status = :st,
                          discovered = :d, detail_ok = :ok, pdf_downloaded = :pdf, errors = :err
                        WHERE run_id = :id"""),
                {"id": run_id, "st": status, "d": c.discovered, "ok": c.detail_ok,
                 "pdf": c.pdf_downloaded, "err": c.errors},
            )

    def get_run(self, run_id: uuid.UUID) -> dict:
        with self.engine.connect() as conn:
            return dict(
                conn.execute(text("SELECT * FROM crawl_runs WHERE run_id = :id"), {"id": run_id})
                .mappings().one()
            )

    # ---------- crawl_queue ----------
    def enqueue(self, vbpl_id: str, stage: str, url: str) -> bool:
        """Thêm vào hàng đợi nếu chưa có. Trả True nếu là dòng mới."""
        with self.engine.begin() as conn:
            res = conn.execute(
                text("""INSERT INTO crawl_queue (vbpl_id, stage, url, status, first_seen_at)
                        VALUES (:id, :stage, :url, 'pending', now())
                        ON CONFLICT (vbpl_id, stage) DO NOTHING"""),
                {"id": vbpl_id, "stage": stage, "url": url},
            )
            return res.rowcount == 1

    def requeue(self, vbpl_id: str, stage: str) -> None:
        """Đánh dấu lại pending (job kiểm tra lại hằng tuần, hoặc khi detail đổi nội dung)."""
        with self.engine.begin() as conn:
            conn.execute(
                text("""UPDATE crawl_queue SET status = 'pending', retry_count = 0
                        WHERE vbpl_id = :id AND stage = :stage"""),
                {"id": vbpl_id, "stage": stage},
            )

    def requeue_active(self) -> int:
        """Đánh dấu lại `pending` để crawl lại văn bản còn hiệu lực (spec 14, `dag_recheck_weekly`)."""
        with self.engine.begin() as conn:
            return conn.execute(text("""
                UPDATE crawl_queue q SET status = 'pending'
                FROM documents d
                WHERE q.vbpl_id = d.vbpl_id AND q.stage = 'detail' AND d.tinh_trang_norm = 'con_hieu_luc'
                  AND q.status <> 'pending'""")).rowcount

    def pending(self, stage: str, limit: int | None = None) -> list[QueueItem]:
        """Dòng cần xử lý: pending, hoặc failed còn lượt retry (spec 7.6)."""
        sql = """SELECT vbpl_id, stage, url, status, retry_count, content_hash FROM crawl_queue
                 WHERE stage = :stage
                   AND (status = 'pending' OR (status = 'failed' AND retry_count < :max))
                 ORDER BY first_seen_at, vbpl_id"""
        if limit:
            sql += " LIMIT :limit"
        with self.engine.connect() as conn:
            rows = conn.execute(text(sql), {"stage": stage, "max": MAX_RETRIES, "limit": limit})
            return [QueueItem(**r._mapping) for r in rows]

    def get(self, vbpl_id: str, stage: str) -> QueueItem | None:
        with self.engine.connect() as conn:
            r = conn.execute(
                text("""SELECT vbpl_id, stage, url, status, retry_count, content_hash
                        FROM crawl_queue WHERE vbpl_id = :id AND stage = :stage"""),
                {"id": vbpl_id, "stage": stage},
            ).first()
            return QueueItem(**r._mapping) if r else None

    def mark(
        self,
        vbpl_id: str,
        stage: str,
        status: str,
        content_hash: str | None = None,
        error: str | None = None,
    ) -> None:
        """done/skipped: xoá lỗi. failed: tăng retry_count, ghi lỗi."""
        with self.engine.begin() as conn:
            conn.execute(
                text("""UPDATE crawl_queue SET
                          status = :status,
                          last_crawled_at = now(),
                          content_hash = COALESCE(:hash, content_hash),
                          retry_count = CASE WHEN :status = 'failed' THEN retry_count + 1 ELSE 0 END,
                          last_error = CASE WHEN :status = 'failed' THEN :err ELSE NULL END
                        WHERE vbpl_id = :id AND stage = :stage"""),
                {"id": vbpl_id, "stage": stage, "status": status, "hash": content_hash,
                 "err": (error or "")[:2000]},
            )

    # ---------- quarantine ----------
    def quarantine(
        self, stage: str, entity_ref: str, rule: str, detail: dict, run_id: uuid.UUID | None
    ) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                text("""INSERT INTO quarantine (stage, entity_ref, rule, detail, run_id)
                        VALUES (:stage, :ref, :rule, CAST(:detail AS jsonb), :run)"""),
                {"stage": stage, "ref": entity_ref, "rule": rule,
                 "detail": json.dumps(detail, ensure_ascii=False, default=str), "run": run_id},
            )
