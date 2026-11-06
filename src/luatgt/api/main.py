"""FastAPI app (spec 12). Model embedding nạp ở lần gọi đầu."""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime
from functools import cached_property
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import Engine, text

from luatgt.common.config import Settings, get_settings
from luatgt.common.db import make_engine
from luatgt.common.storage import Storage
from luatgt.qa.answer import AskResponse
from luatgt.qa.llm_client import make_llm_client
from luatgt.qa.service import QAService, citation_label
from luatgt.retrieval.embed import Embedder, SentenceTransformerEmbedder
from luatgt.retrieval.query import today_vn


class AskRequest(BaseModel):
    session_id: str | None = None
    question: str = ""
    as_of_date: date | None = None
    selected: dict | None = None
    client_sent_at: datetime | None = None


class FeedbackRequest(BaseModel):
    session_id: str
    thumbs: str
    note: str | None = None
    client_sent_at: datetime | None = None


class App:
    def __init__(self, settings: Settings, engine: Engine, embedder: Embedder | None, llm) -> None:
        self.settings, self.engine, self._embedder, self.llm = settings, engine, embedder, llm

    @cached_property
    def service(self) -> QAService:
        return QAService(self.settings, self.engine, self._embedder or SentenceTransformerEmbedder(self.settings),
                         self.llm)

    def event(self, kind: str, session_id: str | None, topic: str, thumbs: str | None, sent: datetime | None) -> None:
        """Ghi event at-least-once cho streaming (spec 13.1). `event_time` lấy từ client nếu có.

        Mỗi event một file, đổi tên nguyên tử vào `events/`: file source của Spark đọc mỗi file đúng một lần
        nên không được nối thêm vào file cũ (D-023). Spark bỏ qua thư mục bắt đầu bằng dấu chấm.
        """
        tz = ZoneInfo(self.settings.timezone)
        now = datetime.now(tz)
        event_time = (sent.replace(tzinfo=tz) if sent and sent.tzinfo is None else sent) or now
        row = {"event_id": str(uuid.uuid4()), "event_time": event_time.isoformat(), "type": kind,
               "session_id": session_id, "topic": topic, "thumbs": thumbs,
               "client_sent_at": sent.isoformat() if sent else None, "ingest_time": now.isoformat()}
        folder = self.settings.path(self.settings.paths.events_dir)
        staging = folder / ".tmp"
        staging.mkdir(parents=True, exist_ok=True)
        name = f"evt-{now:%Y%m%dT%H%M%S}-{row['event_id']}.jsonl"
        (staging / name).write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
        (staging / name).replace(folder / name)


def _topic(response: AskResponse) -> str:
    """Q-1 (D-021): chiều đang hỏi, hoặc chiều phân biệt của fact đầu, hoặc `unknown`."""
    if response.follow_up_questions:
        return response.follow_up_questions[0].dimension
    for f in response.facts:
        for key in f.attributes:
            if key not in ("tinh_theo", "tong_muc_phat_toi_da", "che_tai_co_dieu_kien"):
                return key
    return "unknown"


def create_app(settings: Settings | None = None, engine: Engine | None = None,
               embedder: Embedder | None = None, llm=None) -> FastAPI:
    settings = settings or get_settings()
    engine = engine or make_engine(settings)
    state = App(settings, engine, embedder, llm if llm is not None else make_llm_client(settings))
    app = FastAPI(title="LuậtGT")

    @app.post("/api/ask", response_model=AskResponse)
    def ask(body: AskRequest) -> AskResponse:
        if not body.session_id and not body.question.strip():
            raise HTTPException(422, "Thiếu câu hỏi")
        try:
            response = state.service.ask(body.question, body.session_id, body.as_of_date, body.selected)
        except KeyError as e:
            raise HTTPException(404, "Không tìm thấy phiên hỏi") from e
        state.event("select_option" if body.session_id else "ask", response.session_id, _topic(response), None,
                    body.client_sent_at)
        return response

    @app.get("/api/documents")
    def documents(tinh_trang: str | None = None, loai: str | None = None) -> list[dict]:
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT vbpl_id, so_hieu, ten_van_ban, loai_van_ban, tinh_trang, tinh_trang_norm, ngay_ban_hanh,
                       ngay_hieu_luc, ngay_het_hieu_luc
                FROM documents
                WHERE (CAST(:t AS text) IS NULL OR tinh_trang_norm = :t) AND (CAST(:l AS text) IS NULL OR loai_van_ban = :l)
                ORDER BY ngay_hieu_luc DESC NULLS LAST"""), {"t": tinh_trang, "l": loai}).mappings().all()
        return [dict(r) for r in rows]

    @app.get("/api/documents/{vbpl_id}")
    def document(vbpl_id: str) -> dict:
        with engine.connect() as conn:
            row = conn.execute(text("SELECT * FROM documents WHERE vbpl_id = :i"), {"i": vbpl_id}).mappings().first()
            if row is None:
                raise HTTPException(404, "Không tìm thấy văn bản")
            # dst_vbpl_id thường rỗng trong dữ liệu gốc: khớp lại theo số hiệu để link được văn bản trong kho
            relations = conn.execute(text("""
                SELECT r.relation_type, r.dst_so_hieu, r.origin, d.vbpl_id AS dst_vbpl_id, d.ngay_hieu_luc
                FROM document_relations r LEFT JOIN documents d ON d.so_hieu = r.dst_so_hieu
                WHERE r.src_vbpl_id = :i ORDER BY d.ngay_hieu_luc NULLS LAST, r.dst_so_hieu"""),
                {"i": vbpl_id}).mappings().all()
            incoming = conn.execute(text("""
                SELECT r.relation_type, s.so_hieu AS src_so_hieu, s.vbpl_id AS src_vbpl_id, s.ngay_hieu_luc
                FROM document_relations r JOIN documents s ON s.vbpl_id = r.src_vbpl_id
                WHERE r.dst_so_hieu = :s ORDER BY s.ngay_hieu_luc"""), {"s": row["so_hieu"]}).mappings().all()
            files = conn.execute(text("SELECT * FROM document_files WHERE vbpl_id = :i"),
                                 {"i": vbpl_id}).mappings().all()
        return {**dict(row), "relations": [dict(r) for r in relations], "incoming": [dict(r) for r in incoming],
                "files": [dict(f) for f in files]}

    @app.get("/api/documents/{vbpl_id}/provisions")
    def document_provisions(vbpl_id: str, as_of: date | None = None) -> dict:
        """Cây điều khoản tại ngày `as_of`. `text` rỗng ở điều khoản đã bãi bỏ hoặc chưa có hiệu lực."""
        when = as_of or today_vn()
        with engine.connect() as conn:
            if conn.execute(text("SELECT 1 FROM documents WHERE vbpl_id = :i"), {"i": vbpl_id}).first() is None:
                raise HTTPException(404, "Không tìm thấy văn bản")
            rows = conn.execute(text("""
                SELECT p.provision_id, p.provision_key, p.level, p.number, p.title, p.parent_id,
                       COALESCE(v.text, CASE WHEN p.level IN ('phan', 'chuong', 'muc') THEN p.text END) AS text,
                       (SELECT count(*) FROM provision_versions c WHERE c.provision_key = p.provision_key) AS n_versions
                FROM provisions p
                LEFT JOIN provision_versions v ON v.provision_key = p.provision_key
                     AND :d >= v.valid_from AND :d < v.valid_to
                WHERE p.vbpl_id = :i ORDER BY p.ordinal"""), {"i": vbpl_id, "d": when}).mappings().all()
            # Điều khoản do văn bản sửa đổi bổ sung: có version nhưng không có dòng `provisions`
            added = conn.execute(text("""
                SELECT v.provision_key, v.text, v.valid_from FROM provision_versions v
                WHERE split_part(v.provision_key, '/', 1) = :prefix AND v.text IS NOT NULL
                  AND :d >= v.valid_from AND :d < v.valid_to
                  AND NOT EXISTS (SELECT 1 FROM provisions p WHERE p.provision_key = v.provision_key)
                ORDER BY v.provision_key"""),
                {"prefix": rows[0]["provision_key"].split("/")[0] if rows else "", "d": when}).mappings().all()
        return {"as_of": when, "provisions": [dict(r) for r in rows],
                "added": [{**dict(r), "label": citation_label(r["provision_key"])} for r in added]}

    @app.get("/api/provisions/{provision_key:path}")
    def provision(provision_key: str, as_of: date | None = None) -> dict:
        when = as_of or today_vn()
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT v.version_no, v.text, v.source_vbpl_id, s.so_hieu AS source_so_hieu, v.valid_from, v.valid_to
                FROM provision_versions v LEFT JOIN documents s ON s.vbpl_id = v.source_vbpl_id
                WHERE v.provision_key = :k ORDER BY v.version_no"""), {"k": provision_key}).mappings().all()
            # Điều khoản bổ sung không có dòng `provisions`: lấy văn bản gốc qua Điều cha cùng tiền tố khoá
            origin = conn.execute(text("""
                SELECT d.vbpl_id, d.so_hieu, d.source_url, d.tinh_trang_norm, p.pdf_page
                FROM provisions p JOIN documents d USING (vbpl_id)
                WHERE p.provision_key = :k OR p.provision_key = split_part(:k, '/', 1) || '/' || split_part(:k, '/', 2)
                ORDER BY length(p.provision_key) DESC LIMIT 1"""), {"k": provision_key}).mappings().first()
        if not rows:
            raise HTTPException(404, "Không tìm thấy điều khoản")
        current = next((dict(r) for r in rows if r["valid_from"] <= when < r["valid_to"]), None)
        return {"provision_key": provision_key, "label": citation_label(provision_key), "as_of": when,
                "document": dict(origin) if origin else None, "current": current, "versions": [dict(r) for r in rows]}

    @app.post("/api/feedback")
    def feedback(body: FeedbackRequest) -> dict:
        if body.thumbs not in ("up", "down"):
            raise HTTPException(422, "thumbs phải là up hoặc down")
        with engine.connect() as conn:
            row = conn.execute(text("SELECT answer FROM qa_sessions WHERE session_id = :i"),
                               {"i": body.session_id}).first()
        if row is None:
            raise HTTPException(404, "Không tìm thấy phiên hỏi")
        topic = _topic(AskResponse.model_validate(row[0])) if row[0] else "unknown"
        state.event("feedback", body.session_id, topic, body.thumbs, body.client_sent_at)
        return {"ok": True}

    @app.get("/api/stats/topics")
    def stats(from_: Annotated[datetime, Query(alias="from")], to: datetime) -> list[dict]:
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT window_start, window_end, topic, n_questions, n_thumbs_down FROM qa_topic_counts
                WHERE window_start >= :f AND window_start < :t ORDER BY window_start, topic"""),
                {"f": from_, "t": to}).mappings().all()
        return [dict(r) for r in rows]

    @app.get("/api/stats/summary")
    def stats_summary() -> dict:
        with engine.connect() as conn:
            totals = conn.execute(text("""
                SELECT COALESCE(sum(n_questions), 0) AS n_questions, COALESCE(sum(n_thumbs_down), 0) AS n_thumbs_down,
                       max(window_end) AS last_window_end
                FROM qa_topic_counts""")).mappings().one()
            quarantine = conn.execute(text("""
                SELECT stage, count(*) AS n FROM quarantine WHERE NOT COALESCE(resolved, false)
                GROUP BY stage ORDER BY n DESC""")).mappings().all()
            # Run crawl (crawl_runs) và run build (job_runs) chung một danh sách (D-027)
            by_run = conn.execute(text("""
                WITH runs AS (
                    SELECT run_id, 'crawl' AS job, started_at, status FROM crawl_runs
                    UNION ALL SELECT run_id, job, started_at, status FROM job_runs)
                SELECT r.run_id, r.job, r.started_at, r.status, count(q.id) AS n
                FROM runs r LEFT JOIN quarantine q ON q.run_id = r.run_id AND NOT COALESCE(q.resolved, false)
                GROUP BY r.run_id, r.job, r.started_at, r.status
                ORDER BY r.started_at DESC LIMIT 10""")).mappings().all()
            unassigned = conn.execute(text("""SELECT count(*) FROM quarantine
                                              WHERE run_id IS NULL AND NOT COALESCE(resolved, false)""")).scalar_one()
            jobs = conn.execute(text("""
                SELECT DISTINCT ON (job) job, run_id, status, started_at, finished_at,
                       extract(epoch FROM finished_at - started_at)::float8 AS duration_s, data_crawled_at
                FROM job_runs ORDER BY job, started_at DESC""")).mappings().all()
            last_crawled_at = conn.execute(text("SELECT max(last_crawled_at) FROM documents")).scalar()
        return {**dict(totals), "quarantine_by_stage": [dict(r) for r in quarantine],
                "quarantine_by_run": [dict(r) for r in by_run], "quarantine_without_run": unassigned,
                "last_run": dict(by_run[0]) if by_run else None,
                "jobs": [dict(r) for r in jobs], "last_crawled_at": last_crawled_at}

    @app.get("/api/health")
    def health() -> dict:
        checks: dict[str, str] = {}
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            checks["postgres"] = "ok"
        except Exception as e:  # noqa: BLE001 - health phải báo mọi lỗi, không được ném
            checks["postgres"] = type(e).__name__
        try:
            Storage(settings).client.list_buckets()
            checks["minio"] = "ok"
        except Exception as e:  # noqa: BLE001
            checks["minio"] = type(e).__name__
        checks["model"] = "loaded" if "service" in state.__dict__ else "lazy"
        return {"status": "ok" if checks["postgres"] == checks["minio"] == "ok" else "degraded", **checks}

    return app


def app_factory() -> FastAPI:
    return create_app()
