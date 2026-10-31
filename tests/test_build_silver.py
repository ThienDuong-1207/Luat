"""M3: Spark job Bronze → Silver trên DB/bucket test. Nghiệm thu: NĐ 168 đủ các Điều liên tục;
chạy lại cho cùng output; quarantine không nhân đôi; chỉ parse lại văn bản có needs_reparse."""

from __future__ import annotations

import hashlib

import pytest
from sqlalchemy import text

from luatgt.jobs.build_silver import TABLES, build_silver
from luatgt.jobs.spark import get_spark, read_silver
from tests.helpers import LUAT26, ND168, ND238, FakeBrowser, run

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def spark(env):
    s = get_spark(env[0])
    yield s
    s.stop()


def digest(spark, settings) -> dict[str, str]:
    out = {}
    for t in TABLES:
        rows = sorted(str(tuple(r)) for r in read_silver(spark, settings, t).collect())
        out[t] = hashlib.sha256("\n".join(rows).encode()).hexdigest()
    return out


def silver(ctx, spark, **kw):
    s, engine, storage, _, _ = ctx
    return build_silver(s, spark=spark, storage=storage, engine=engine, **kw)


def test_build_silver_end_to_end(ctx, spark):
    s, engine, storage, _, _ = ctx
    run(ctx, FakeBrowser(ctx[4]))
    stats = silver(ctx, spark)  # mặc định: văn bản needs_reparse (cả 3 vừa crawl)
    assert sorted(stats["ids"]) == sorted([LUAT26, ND168, ND238])

    prov = read_silver(spark, s, "provisions")
    dieu = [r.number for r in prov.filter("vbpl_id = '173920' AND level = 'dieu'").orderBy("ordinal").collect()]
    assert dieu == [str(i) for i in range(1, 56)]  # nghiệm thu M3
    pm = prov.filter("provision_key = '168-2024-ND-CP/D6/K3/Pm'").collect()[0]
    assert pm.provision_id == "173920:D6/K3/Pm" and pm.parent_id == "173920:D6/K3"
    assert pm.vbpl_annotations == ["Điều khoản được sửa đổi, bổ sung"]

    docs = {r.vbpl_id: r for r in read_silver(spark, s, "documents").collect()}
    assert set(docs) == {LUAT26, ND168, ND238}  # vbpl_id giữ kiểu chuỗi (không bị đoán thành số)
    assert docs[ND168].n_dieu == 55 and docs[ND168].fulltext_source == "html"
    assert docs[ND238].so_hieu == "238/2026/NĐ-CP"

    rel = read_silver(spark, s, "document_relations").filter(f"vbpl_id = '{ND168}'").collect()
    assert ("bi_sua_doi", ND238) in {(r.relation_type, r.dst_vbpl_id) for r in rel}

    keys = storage.list_keys("test-silver", "")
    assert any(k.startswith("provisions/vbpl_id=173920/") and k.endswith(".parquet") for k in keys)

    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM documents WHERE needs_reparse")).scalar_one() == 0
        q = dict(conn.execute(text(
            "SELECT rule, count(*) FROM quarantine WHERE stage = 'parse' GROUP BY rule")).all())
    assert q == {"diem_relabeled": 3, "diem_out_of_order": 2, "duplicate_key": 1}


def test_rerun_gives_identical_silver_and_no_duplicate_quarantine(ctx, spark):
    s, engine, storage, _, _ = ctx
    run(ctx, FakeBrowser(ctx[4]))
    silver(ctx, spark, all_docs=True)
    first = digest(spark, s)
    files_first = len(storage.list_keys("test-silver", ""))
    silver(ctx, spark, all_docs=True)
    assert digest(spark, s) == first
    assert len(storage.list_keys("test-silver", "")) == files_first
    with engine.connect() as conn:
        n = conn.execute(text("SELECT count(*) FROM quarantine WHERE stage = 'parse'")).scalar_one()
    assert n == 6


def test_default_mode_only_parses_flagged_documents(ctx, spark):
    _, engine, _, _, _ = ctx
    run(ctx, FakeBrowser(ctx[4]))
    silver(ctx, spark)
    assert silver(ctx, spark)["ids"] == []  # không còn văn bản cần parse
    with engine.begin() as conn:
        conn.execute(text("UPDATE documents SET needs_reparse = true WHERE vbpl_id = :v"), {"v": ND238})
    assert silver(ctx, spark)["ids"] == [ND238]


def test_unknown_id_rejected(ctx, spark):
    run(ctx, FakeBrowser(ctx[4]))
    with pytest.raises(SystemExit):
        silver(ctx, spark, ids=["999999"])
