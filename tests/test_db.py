import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from luatgt.common.db import migrate, ping

pytestmark = pytest.mark.integration

SPEC_TABLES = {
    "crawl_runs", "crawl_queue", "documents", "document_files", "document_relations",
    "provisions", "amendments", "provision_versions", "violations", "chunks",
    "quarantine", "qa_sessions", "qa_topic_counts",
}


def test_ping(engine):
    assert ping(engine)


def test_migrate_is_idempotent(engine, settings):
    assert migrate(engine, settings.root / "db" / "migrations") == []


def test_all_spec_tables_exist(engine):
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT table_name FROM information_schema.tables WHERE table_schema='public'")
        ).scalars()
        assert SPEC_TABLES <= set(rows)


def test_every_table_has_timestamps(engine):
    with engine.connect() as conn:
        for t in SPEC_TABLES:
            cols = set(
                conn.execute(
                    text("SELECT column_name FROM information_schema.columns WHERE table_name=:t"),
                    {"t": t},
                ).scalars()
            )
            assert {"created_at", "updated_at"} <= cols, t


def test_vbpl_id_columns_are_text(engine):
    """D-008: vbpl_id nhận cả số nguyên lẫn UUID."""
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT table_name, column_name, data_type FROM information_schema.columns
            WHERE table_schema='public' AND column_name LIKE '%vbpl_id'""")).all()
    assert len(rows) == 9
    assert {r.data_type for r in rows} == {"text"}


def test_documents_accept_uuid_and_reject_garbage(engine):
    insert = text("""
        INSERT INTO documents (vbpl_id, so_hieu, ten_van_ban, source_url, first_seen_at, last_crawled_at)
        VALUES (:id, 'x', 'x', 'x', now(), now())""")
    with engine.connect() as conn:
        trans = conn.begin()
        try:
            # ID ngẫu nhiên để không trùng dữ liệu thật đã crawl (transaction rollback ở cuối)
            conn.execute(insert, {"id": str(uuid.uuid4())})
            conn.execute(insert, {"id": str(uuid.uuid4().int % 10**12)})
            with pytest.raises(IntegrityError):
                conn.execute(insert, {"id": "abc"})
        finally:
            trans.rollback()


def test_extensions_installed(engine):
    with engine.connect() as conn:
        ext = set(conn.execute(text("SELECT extname FROM pg_extension")).scalars())
    assert {"vector", "unaccent"} <= ext


def test_unaccent_vietnamese(engine):
    with engine.connect() as conn:
        out = conn.execute(text("SELECT f_unaccent('Nghị định Điều đ) xử phạt')")).scalar_one()
    assert out == "Nghi dinh Dieu d) xu phat"


def test_chunk_tsv_generated_and_searchable(engine):
    with engine.connect() as conn:
        trans = conn.begin()
        try:
            conn.execute(text("""
                INSERT INTO chunks (chunk_id, provision_key, version_no, vbpl_id, so_hieu,
                    hierarchy_path, embed_text, display_text, valid_from, valid_to)
                VALUES ('t@v1', 'T/D1', 1, 1, '1/2024/NĐ-CP', 'Điều 1',
                    'Phạt tiền người điều khiển xe mô tô', 'x', '2025-01-01', '9999-12-31')"""))
            hit = conn.execute(text(
                "SELECT count(*) FROM chunks WHERE tsv @@ plainto_tsquery('simple', f_unaccent(:q))"
            ), {"q": "xe mo to"}).scalar_one()
            assert hit == 1
        finally:
            trans.rollback()


def test_provision_versions_reject_overlap(engine):
    with engine.connect() as conn:
        trans = conn.begin()
        try:
            conn.execute(text("""
                INSERT INTO provision_versions
                  (provision_key, version_no, text, source_vbpl_id, valid_from, valid_to, is_current)
                VALUES ('T/D1', 1, 'a', 1, '2025-01-01', '2026-08-15', false),
                       ('T/D1', 2, 'b', 2, '2026-08-15', '9999-12-31', true)"""))
            with pytest.raises(IntegrityError):
                conn.execute(text("""
                    INSERT INTO provision_versions
                      (provision_key, version_no, text, source_vbpl_id, valid_from, valid_to, is_current)
                    VALUES ('T/D1', 3, 'c', 3, '2026-01-01', '2026-12-31', false)"""))
        finally:
            trans.rollback()
