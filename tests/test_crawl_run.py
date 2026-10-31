"""M2: crawler 3 tầng chạy với trình duyệt giả (HTML từ fixtures) trên DB/bucket test riêng.

Nghiệm thu: seed → Bronze có HTML + PDF + meta; chạy lại không sinh file/bản ghi mới;
bị chặn → run dừng với status=blocked.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from tests.helpers import CRAWL_TABLES as TABLES
from tests.helpers import LUAT26, ND168, ND238, SEED_URLS, FakeBrowser, run

pytestmark = pytest.mark.integration

def counts(ctx) -> dict:
    _, engine, storage, _, _ = ctx
    with engine.connect() as conn:
        out = {t: conn.execute(text(f"SELECT count(*) FROM {t}")).scalar_one() for t in TABLES}
    keys = storage.list_keys("test-bronze", "")
    out["bronze_html"] = sum(k.startswith("html/") for k in keys)
    out["bronze_meta"] = sum(k.startswith("meta/") for k in keys)
    out["bronze_pdf"] = sum(k.startswith("pdf/") for k in keys)
    return out


def test_seed_run_fills_bronze_and_db(ctx):
    browser = FakeBrowser(ctx[4])
    _, status = run(ctx, browser)
    assert status == "success"
    c = counts(ctx)
    assert c["bronze_html"] == 3 * 5  # 3 văn bản × 5 tab detail
    assert c["bronze_meta"] == 3
    assert c["bronze_pdf"] == 1  # chỉ NĐ 238 có PDF; .doc bị bỏ qua (D-010)
    assert c["documents"] == 3
    assert c["document_files"] == 1
    assert c["quarantine"] == 0
    assert browser.downloads == [1]  # nút thứ 2 trong tab Tải về của NĐ 238

    _, engine, _, state, _ = ctx
    with engine.connect() as conn:
        doc = conn.execute(text("SELECT * FROM documents WHERE vbpl_id = :v"), {"v": ND238}).mappings().one()
        rel = conn.execute(text("""SELECT dst_vbpl_id FROM document_relations
            WHERE src_vbpl_id = :s AND dst_so_hieu = '238/2026/NĐ-CP' AND relation_type = 'bi_sua_doi'"""),
            {"s": ND168}).scalar_one()
        f = conn.execute(text("SELECT * FROM document_files")).mappings().one()
    assert doc["so_hieu"] == "238/2026/NĐ-CP" and doc["needs_reparse"] is True
    assert rel == ND238
    assert f["vbpl_id"] == ND238 and f["has_text_layer"] is True
    assert state.get(LUAT26, "download") is None  # không có file → không vào hàng đợi download
    assert state.get(ND168, "download") is None  # chỉ có .doc → không có file cần tải (D-010)


def test_second_run_creates_nothing_new(ctx):
    run(ctx, FakeBrowser(ctx[4]))
    before = counts(ctx)
    browser = FakeBrowser(ctx[4])
    _, status = run(ctx, browser)
    assert status == "success"
    assert browser.calls == []  # không còn dòng pending
    after = counts(ctx)
    assert {k: v for k, v in after.items() if k != "crawl_runs"} == {
        k: v for k, v in before.items() if k != "crawl_runs"
    }


def test_recrawl_unchanged_content_writes_no_new_bronze(ctx):
    _, _, _, state, _ = ctx
    run(ctx, FakeBrowser(ctx[4]))
    before = counts(ctx)
    for vbpl_id in SEED_URLS:
        state.requeue(vbpl_id, "detail")  # như job kiểm tra lại hằng tuần
    browser = FakeBrowser(ctx[4])
    _, status = run(ctx, browser)
    assert status == "success"
    assert len(browser.calls) == 15  # đã tải lại trang
    after = counts(ctx)
    for k in ("bronze_html", "bronze_meta", "bronze_pdf", "documents", "document_files", "document_relations"):
        assert after[k] == before[k], k
    assert browser.downloads == []  # nội dung không đổi → không tải lại file


def reverse_list_items(html: str) -> str:
    """Đảo thứ tự <li> trong mọi <ul> (như vbpl.vn trả danh sách Lược đồ theo thứ tự khác nhau)."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")
    for ul in soup.find_all("ul"):
        for li in reversed([li.extract() for li in ul.find_all("li", recursive=False)]):
            ul.append(li)
    return str(soup)


def test_reordered_related_list_is_not_a_change(ctx):
    _, _, _, state, _ = ctx
    run(ctx, FakeBrowser(ctx[4]))
    before = counts(ctx)
    state.requeue(LUAT26, "detail")
    run(ctx, FakeBrowser(ctx[4], mutate={(LUAT26, "luoc-do"): reverse_list_items}))
    after = counts(ctx)
    assert (after["bronze_html"], after["bronze_meta"]) == (before["bronze_html"], before["bronze_meta"])


def test_changed_content_detected(ctx):
    _, engine, _, state, _ = ctx
    run(ctx, FakeBrowser(ctx[4]))
    with engine.begin() as conn:
        conn.execute(text("UPDATE documents SET needs_reparse = false"))
    state.requeue(ND238, "detail")
    mutate = {(ND238, "toan-van"): lambda h: h.replace("Điều 3.", "Điều 3 (đã sửa).", 1)}
    browser = FakeBrowser(ctx[4], mutate=mutate)
    run(ctx, browser)
    c = counts(ctx)
    assert c["bronze_html"] == 16 and c["bronze_meta"] == 4
    with engine.connect() as conn:
        flags = dict(conn.execute(text("SELECT vbpl_id, needs_reparse FROM documents")).all())
    assert flags == {LUAT26: False, ND168: False, ND238: True}
    assert browser.downloads == [1]  # văn bản đổi → kiểm tra lại file
    assert c["bronze_pdf"] == 1 and c["document_files"] == 1  # cùng file → không ghi thêm


def test_blocked_stops_whole_run(ctx):
    _, _, _, state, _ = ctx
    browser = FakeBrowser(ctx[4], block_on_call=3)
    run_id, status = run(ctx, browser)
    assert status == "blocked"
    assert len(browser.calls) == 3  # dừng ngay, không tải tiếp văn bản khác
    assert state.get_run(run_id)["status"] == "blocked"
    for vbpl_id in SEED_URLS:
        q = state.get(vbpl_id, "detail")
        assert (q.status, q.retry_count) == ("pending", 0)  # lần chạy sau thử lại
    assert counts(ctx)["documents"] == 0


def test_fetch_error_marks_failed_and_continues(ctx):
    _, _, _, state, _ = ctx
    _, status = run(ctx, FakeBrowser(ctx[4], fail_ids={ND168}))
    assert status == "partial"
    q = state.get(ND168, "detail")
    assert (q.status, q.retry_count) == ("failed", 1)
    assert counts(ctx)["documents"] == 2
    # failed còn lượt retry → lần sau xử lý lại và thành công
    _, status = run(ctx, FakeBrowser(ctx[4]))
    assert status == "success" and state.get(ND168, "detail").status == "done"


def test_schema_failure_goes_to_quarantine(ctx):
    _, engine, _, state, _ = ctx
    mutate = {(LUAT26, "thuoc-tinh"): lambda h: h.replace(">Số hiệu<", ">Ký hiệu<")}
    _, status = run(ctx, FakeBrowser(ctx[4], mutate=mutate))
    assert status == "partial"
    assert state.get(LUAT26, "detail").status == "failed"
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT entity_ref, rule, detail FROM quarantine")).all()
        n_docs = conn.execute(text("SELECT count(*) FROM documents WHERE vbpl_id = :v"), {"v": LUAT26}).scalar_one()
    assert [(r.entity_ref, r.rule, r.detail["field"]) for r in rows] == [
        (LUAT26, "required_field_missing", "so_hieu")
    ]
    assert n_docs == 0  # không ghi bản ghi thiếu


def test_bad_pdf_goes_to_quarantine(ctx):
    _, engine, _, state, _ = ctx
    _, status = run(ctx, FakeBrowser(ctx[4], pdf=b"<html>not a pdf</html>" * 100))
    assert status == "partial"
    assert state.get(ND238, "download").status == "failed"
    with engine.connect() as conn:
        rules = conn.execute(text("SELECT rule FROM quarantine")).scalars().all()
    assert rules == ["not_pdf_magic"]
    assert counts(ctx)["bronze_pdf"] == 0
