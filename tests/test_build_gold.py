"""M4: Silver → Gold → Postgres. Nghiệm thu: điều khoản bị sửa có 2 version không chồng lấn;
as_of=2026-08-01 trả bản cũ, as_of=2026-10-20 trả bản mới; mẫu không hỗ trợ nằm trong needs_review."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from luatgt.jobs import build_gold as bg
from luatgt.jobs.build_silver import build_silver
from luatgt.jobs.spark import get_spark
from luatgt.modeling.versions import VersionIssue
from tests.helpers import ND168, ND238, FakeBrowser, run

pytestmark = pytest.mark.integration

AS_OF = text("""SELECT version_no, source_vbpl_id, text FROM provision_versions
                WHERE provision_key = :k AND valid_from <= :d AND :d < valid_to""")


@pytest.fixture(scope="module")
def spark(env):
    s = get_spark(env[0])
    yield s
    s.stop()


@pytest.fixture
def gold(ctx, spark):
    s, engine, storage, _, _ = ctx
    run(ctx, FakeBrowser(ctx[4]))
    build_silver(s, spark=spark, storage=storage, engine=engine, all_docs=True)
    return lambda: bg.build_gold(s, spark=spark, storage=storage, engine=engine)


def at(conn, key, d):
    return conn.execute(AS_OF, {"k": key, "d": d}).first()


def test_as_of_queries_in_postgres(ctx, gold):
    stats = gold()
    assert stats["multi_version_keys"] == 158 and stats["documents_missing_in_postgres"] == []
    with ctx[1].connect() as conn:
        old = at(conn, "168-2024-ND-CP/D6/K3/Pm", "2026-08-01")
        new = at(conn, "168-2024-ND-CP/D6/K3/Pm", "2026-10-20")
        assert (old.version_no, old.source_vbpl_id) == (1, ND168)
        assert (new.version_no, new.source_vbpl_id) == (2, ND238)
        assert old.text != new.text
        assert at(conn, "168-2024-ND-CP/D6/K1a", "2026-08-01") is None
        assert at(conn, "168-2024-ND-CP/D32/K17/Pd", "2026-10-20").text is None
        # Luật 26/2001 hết hiệu lực 01/07/2009: không còn version tại 2026
        assert at(conn, "26-2001-QH10/D1", "2026-10-20") is None
        assert at(conn, "26-2001-QH10/D1", "2005-01-01") is not None
        review = conn.execute(text("""SELECT count(*) FROM amendments
            WHERE action = 'unsupported' AND parse_status = 'needs_review'""")).scalar_one()
        queued = conn.execute(text(
            "SELECT count(*) FROM quarantine WHERE stage = 'amend' AND rule = 'amendment_needs_review'")).scalar_one()
    assert review == 1 and queued == 1  # còn câu "đoạn thứ hai"
    assert any(k.startswith("provision_versions/") for k in ctx[2].list_keys("test-gold", ""))
    assert any(k.startswith("violations/") for k in ctx[2].list_keys("test-gold", ""))


def test_rerun_is_idempotent(ctx, gold):
    first = gold()
    second = gold()
    assert {k: first[k] for k in ("provisions", "amendments", "versions", "quarantine_amend")} == \
           {k: second[k] for k in ("provisions", "amendments", "versions", "quarantine_amend")}
    with ctx[1].connect() as conn:
        n = conn.execute(text("SELECT count(*) FROM quarantine WHERE stage = 'amend'")).scalar_one()
    assert n == first["quarantine_amend"]


def test_quality_error_stops_and_keeps_old_gold(ctx, gold, monkeypatch):
    gold()
    with ctx[1].connect() as conn:
        before = conn.execute(text("SELECT count(*) FROM provision_versions")).scalar_one()
    real = bg.build_versions

    def broken(*a, **kw):
        versions, issues = real(*a, **kw)
        return versions, [*issues, VersionIssue("overlapping_versions", "error", "x", {})]

    monkeypatch.setattr(bg, "build_versions", broken)
    with pytest.raises(bg.QualityError):
        gold()
    with ctx[1].connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM provision_versions")).scalar_one() == before
        failed = conn.execute(text("""SELECT status, error, finished_at IS NOT NULL AS done FROM job_runs
                                       WHERE job = 'build_gold' ORDER BY started_at DESC LIMIT 1""")).one()
    assert failed.status == "failed" and failed.error.startswith("QualityError") and failed.done


def test_every_quarantine_row_has_run_id(ctx, gold):
    """M11 mục 2: quarantine của parse/extract/amend gắn run của job sinh ra nó (D-027)."""
    stats = gold()
    with ctx[1].connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM quarantine")).scalar_one() > 0
        assert conn.execute(text("SELECT count(*) FROM quarantine WHERE run_id IS NULL")).scalar_one() == 0
        by_stage = dict(conn.execute(text("""
            SELECT q.stage, string_agg(DISTINCT coalesce(j.job, 'crawl:' || c.status), ',')
            FROM quarantine q LEFT JOIN job_runs j ON j.run_id = q.run_id
            LEFT JOIN crawl_runs c ON c.run_id = q.run_id GROUP BY q.stage""")).all())
        runs = conn.execute(text("""SELECT job, status, stats, data_crawled_at, finished_at >= started_at AS ok
                                    FROM job_runs ORDER BY started_at""")).mappings().all()
    assert by_stage.get("amend") == "build_gold"
    assert by_stage.get("parse", "build_silver") == "build_silver"
    assert by_stage.get("extract", "build_gold") == "build_gold"
    assert [r["job"] for r in runs] == ["build_silver", "build_gold"]
    assert all(r["status"] == "success" and r["ok"] and r["data_crawled_at"] is not None for r in runs)
    assert runs[1]["stats"]["versions"] == stats["versions"] and stats["run_id"]
