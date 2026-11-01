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
from luatgt.qa.service import QAService
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
        """Ghi event at-least-once cho streaming (spec 13.1). `event_time` lấy từ client nếu có."""
        tz = ZoneInfo(self.settings.timezone)
        now = datetime.now(tz)
        row = {"event_id": str(uuid.uuid4()), "event_time": (sent or now).isoformat(), "type": kind,
               "session_id": session_id, "topic": topic, "thumbs": thumbs,
               "client_sent_at": sent.isoformat() if sent else None, "ingest_time": now.isoformat()}
        folder = self.settings.path(self.settings.paths.events_dir)
        folder.mkdir(parents=True, exist_ok=True)
        with (folder / f"events-{now:%Y%m%d}.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _topic(response: AskResponse) -> str:
    """Q-1 (D-021): chiều đang hỏi, hoặc chiều phân biệt của fact đầu, hoặc `unknown`."""
    if response.follow_up_questions:
        return response.follow_up_questions[0].dimension
    for f in response.facts:
        for key in f.attributes:
            if key not in ("tinh_theo", "tong_muc_phat_toi_da"):
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
                SELECT vbpl_id, so_hieu, ten_van_ban, loai_van_ban, tinh_trang, ngay_hieu_luc, ngay_het_hieu_luc
                FROM documents
                WHERE (CAST(:t AS text) IS NULL OR tinh_trang = :t) AND (CAST(:l AS text) IS NULL OR loai_van_ban = :l)
                ORDER BY ngay_hieu_luc DESC NULLS LAST"""), {"t": tinh_trang, "l": loai}).mappings().all()
        return [dict(r) for r in rows]

    @app.get("/api/documents/{vbpl_id}")
    def document(vbpl_id: str) -> dict:
        with engine.connect() as conn:
            row = conn.execute(text("SELECT * FROM documents WHERE vbpl_id = :i"), {"i": vbpl_id}).mappings().first()
            if row is None:
                raise HTTPException(404, "Không tìm thấy văn bản")
            relations = conn.execute(text("SELECT * FROM document_relations WHERE src_vbpl_id = :i"),
                                     {"i": vbpl_id}).mappings().all()
            files = conn.execute(text("SELECT * FROM document_files WHERE vbpl_id = :i"),
                                 {"i": vbpl_id}).mappings().all()
        return {**dict(row), "relations": [dict(r) for r in relations], "files": [dict(f) for f in files]}

    @app.get("/api/provisions/{provision_key:path}")
    def provision(provision_key: str, as_of: date | None = None) -> dict:
        when = as_of or today_vn()
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT version_no, text, source_vbpl_id, valid_from, valid_to FROM provision_versions
                WHERE provision_key = :k ORDER BY version_no"""), {"k": provision_key}).mappings().all()
        if not rows:
            raise HTTPException(404, "Không tìm thấy điều khoản")
        current = next((dict(r) for r in rows if r["valid_from"] <= when < r["valid_to"]), None)
        return {"provision_key": provision_key, "as_of": when, "current": current, "versions": [dict(r) for r in rows]}

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
