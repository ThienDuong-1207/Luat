"""M1: trích metadata/quan hệ/lịch sử/file tải từ fixtures vbpl.vn. Không gọi mạng.

Giá trị kỳ vọng đối chiếu với trang hiển thị và kết quả tìm kiếm trên vbpl.vn ngày 23/10/2026.
"""

import socket
from datetime import date
from pathlib import Path

import pytest

from luatgt.crawler.extract import (
    extract_attributes,
    extract_downloads,
    extract_fulltext_html,
    extract_history,
    extract_related,
    merge_relations,
    relations_from_history,
)
from luatgt.crawler.schema_check import check_document
from luatgt.crawler.selectors import load_source_config

FIX = Path(__file__).parent / "fixtures" / "vbpl"
ND168 = "173920"
ND238 = "f4b0c320-79e6-11f1-8c8a-3587e086d762"
LUAT26 = "23289"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def guard(*args, **kwargs):
        raise RuntimeError("Test không được gọi mạng")

    monkeypatch.setattr(socket.socket, "connect", guard)


@pytest.fixture(scope="module")
def src():
    return load_source_config(Path(__file__).parents[1] / "config" / "sources" / "vbpl.yaml")


def html(vbpl_id: str, tab: str) -> str:
    return (FIX / f"{vbpl_id}__{tab}.html").read_text(encoding="utf-8")


EXPECTED_META = {
    LUAT26: {
        "so_hieu": "26/2001/QH10",
        "ten_van_ban": "Luật Giao thông đường bộ số 26/2001/QH10",
        "loai_van_ban": "Luật",
        "co_quan_ban_hanh": "Quốc hội",
        "nguoi_ky": "Nguyễn Văn An",
        "ngay_ban_hanh": date(2001, 6, 29),
        "ngay_hieu_luc": date(2002, 1, 1),
        "ngay_het_hieu_luc": date(2009, 7, 1),
        "tinh_trang": "Hết hiệu lực toàn bộ",
        "tinh_trang_norm": "het_hieu_luc",
    },
    ND168: {
        "so_hieu": "168/2024/NĐ-CP",
        "loai_van_ban": "Nghị định",
        "co_quan_ban_hanh": "Chính phủ",
        "nguoi_ky": "Trần Hồng Hà",
        "ngay_ban_hanh": date(2024, 12, 26),
        "ngay_hieu_luc": date(2025, 1, 1),
        "ngay_het_hieu_luc": None,
        "tinh_trang": "Hết hiệu lực một phần",
        "tinh_trang_norm": "het_hieu_luc_mot_phan",
    },
    ND238: {
        "so_hieu": "238/2026/NĐ-CP",
        "loai_van_ban": "Nghị định",
        "co_quan_ban_hanh": "Chính phủ",
        "nguoi_ky": "Phạm Gia Túc",
        "ngay_ban_hanh": date(2026, 6, 26),
        "ngay_hieu_luc": date(2026, 8, 15),
        "ngay_het_hieu_luc": None,
        "tinh_trang": "Còn hiệu lực",
        "tinh_trang_norm": "con_hieu_luc",
    },
}


@pytest.mark.parametrize("vbpl_id", list(EXPECTED_META))
def test_metadata_matches_expected(src, vbpl_id):
    meta = extract_attributes(html(vbpl_id, "thuoc-tinh"), vbpl_id, src)
    for field, expected in EXPECTED_META[vbpl_id].items():
        assert getattr(meta, field) == expected, field
    assert meta.date_errors == {}


@pytest.mark.parametrize("vbpl_id", list(EXPECTED_META))
def test_required_fields_and_schema_check_pass(src, vbpl_id):
    meta = extract_attributes(html(vbpl_id, "thuoc-tinh"), vbpl_id, src)
    fulltext = extract_fulltext_html(html(vbpl_id, "toan-van"), src)
    assert fulltext and "Điều 1" in fulltext
    assert check_document(meta, fulltext, src).ok


def test_ten_van_ban_starts_with_loai_and_so_hieu(src):
    meta = extract_attributes(html(ND168, "thuoc-tinh"), ND168, src)
    assert meta.ten_van_ban.startswith("Nghị định số 168/2024/NĐ-CP Quy định xử phạt")


def test_empty_value_dash_becomes_none(src):
    meta = extract_attributes(html(ND168, "thuoc-tinh"), ND168, src)
    assert meta.raw["nganh"] is None  # trang hiển thị "--"


def test_schema_check_flags_missing_fields(src):
    meta = extract_attributes(html(LUAT26, "thuoc-tinh"), LUAT26, src)
    meta.so_hieu = None
    res = check_document(meta, None, src)
    rules = {(e["rule"], e.get("field")) for e in res.errors}
    assert ("required_field_missing", "so_hieu") in rules
    assert ("required_field_missing", "fulltext_container") in rules


def test_schema_check_flags_bad_so_hieu(src):
    meta = extract_attributes(html(LUAT26, "thuoc-tinh"), LUAT26, src)
    meta.so_hieu = "Hiến pháp năm 1992"
    assert {e["rule"] for e in check_document(meta, "<p>x</p>", src).errors} == {"so_hieu_format"}


def test_all_related_group_titles_are_mapped(src):
    for vbpl_id in EXPECTED_META:
        assert extract_related(html(vbpl_id, "luoc-do"), vbpl_id, src).unknown_groups == []


def test_relations_are_symmetric_between_168_and_238(src):
    r168 = extract_related(html(ND168, "luoc-do"), ND168, src).relations
    r238 = extract_related(html(ND238, "luoc-do"), ND238, src).relations
    assert ("bi_sua_doi", "238/2026/NĐ-CP") in {(r.relation_type, r.dst_so_hieu) for r in r168}
    assert ("sua_doi", "168/2024/NĐ-CP") in {(r.relation_type, r.dst_so_hieu) for r in r238}


def test_related_counts_23289(src):
    rels = extract_related(html(LUAT26, "luoc-do"), LUAT26, src).relations
    by_type = {}
    for r in rels:
        by_type[r.relation_type] = by_type.get(r.relation_type, 0) + 1
    # Trang hiển thị: hướng dẫn thi hành (47) ở cột phải, (1) ở cột trái; hết hiệu lực toàn bộ (1)
    assert by_type == {"huong_dan": 1, "duoc_huong_dan": 47, "bi_thay_the": 1, "can_cu": 1}


def test_related_without_so_hieu_keeps_title(src):
    rels = extract_related(html(LUAT26, "luoc-do"), LUAT26, src).relations
    assert any(r.dst_so_hieu == "Hiến pháp năm 1992" and r.dst_vbpl_id is None for r in rels)


def test_history_gives_amendment_with_id_and_date(src):
    events = extract_history(html(ND168, "lich-su"), src)
    assert [e.status for e in events] == [
        "Văn bản bị sửa đổi, bổ sung",
        "Văn bản có hiệu lực",
        "Văn bản được ban hành",
    ]
    rels = relations_from_history(events, ND168, src)
    assert rels.unknown_groups == []
    [r] = rels.relations
    assert (r.relation_type, r.dst_so_hieu, r.dst_vbpl_id, r.effective_date) == (
        "bi_sua_doi", "238/2026/NĐ-CP", ND238, date(2026, 8, 15),
    )


def test_history_replacement_23289(src):
    rels = relations_from_history(extract_history(html(LUAT26, "lich-su"), src), LUAT26, src)
    [r] = rels.relations
    assert (r.relation_type, r.dst_so_hieu, r.dst_vbpl_id) == ("bi_thay_the", "23/2008/QH12", "12333")


def test_merge_prefers_relation_with_id(src):
    rg = extract_related(html(ND168, "luoc-do"), ND168, src)
    hr = relations_from_history(extract_history(html(ND168, "lich-su"), src), ND168, src)
    all_rels = merge_relations(rg, hr)
    merged = {r.dst_so_hieu: r for r in all_rels if r.relation_type != "can_cu"}
    assert merged["238/2026/NĐ-CP"].dst_vbpl_id == ND238
    assert merged["336/2025/NĐ-CP"].dst_vbpl_id is None
    assert len(merged) == 3
    # D-009: "Căn cứ ban hành (5)" → 5 quan hệ can_cu, trong đó có Luật 36/2024
    can_cu = {r.dst_so_hieu for r in all_rels if r.relation_type == "can_cu"}
    assert len(can_cu) == 5 and "36/2024/QH15" in can_cu


def test_downloads(src):
    assert extract_downloads(html(LUAT26, "tai-ve"), src) == []
    assert [d.filename for d in extract_downloads(html(ND168, "tai-ve"), src)] == ["168.2024.NĐ.CP.doc"]
    assert [d.extension for d in extract_downloads(html(ND238, "tai-ve"), src)] == ["doc", "pdf"]
