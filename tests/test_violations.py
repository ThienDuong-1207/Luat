"""M5: trích xuất violations (spec 8.5) và quality rules (spec 8.6). Không mạng, không Spark."""

from __future__ import annotations

from dataclasses import asdict
from datetime import date

import pytest

from luatgt.common.config import load_settings
from luatgt.crawler.selectors import load_source_config
from luatgt.modeling.versions import OPEN_END, Version, build_versions
from luatgt.modeling.violations import (
    Violation,
    extract_violations,
    load_violation_config,
    parse_sanction,
)
from luatgt.parsing.amendments import Ref, parse_amendments
from luatgt.parsing.document import DocumentInputs, parse_document
from luatgt.quality.checks import (
    check_amendment_targets,
    check_dieu_sequence,
    check_no_overlap,
    check_violations,
    summarize,
)
from tests.helpers import FIX, ND168, ND238, ROOT

K = "168-2024-ND-CP"
BEFORE, AFTER = date(2026, 8, 1), date(2026, 10, 20)
CFG = load_violation_config(ROOT / "config" / "violation_attributes.yaml")


@pytest.fixture(scope="module")
def real():
    src = load_source_config(ROOT / "config" / "sources" / "vbpl.yaml")
    cfg = load_settings(env={}).parsing
    tabs = {v: k for k, v in src.tabs.items()}

    def rows(vid):
        html = {tabs[t]: (FIX / f"{vid}__{t}.html").read_text("utf-8")
                for t in ("toan-van", "thuoc-tinh", "luoc-do", "lich-su")}
        return parse_document(DocumentInputs(vid, html, {}), src, cfg)

    r168, r238 = rows(ND168), rows(ND238)
    am = parse_amendments(r238.documents[0], r238.provisions, {"168/2024/NĐ-CP": r168.provisions})
    versions, _ = build_versions(r168.documents + r238.documents, r168.provisions + r238.provisions,
                                 [asdict(a) for a in am])
    titles = {p["provision_key"].rsplit("/D", 1)[-1]: p["title"] or "" for p in r168.provisions if p["level"] == "dieu"}
    return extract_violations("168/2024/NĐ-CP", (6, 40), titles, versions, CFG)


def at(violations, key, when, who="ca_nhan"):
    return [v for v in violations if v.provision_key == key and v.valid_from <= when < v.valid_to
            and (who is None or v.doi_tuong == who)]


def test_fine_comes_from_khoan_head_and_act_from_diem(real):
    v = at(real[0], f"{K}/D6/K1/Pb", AFTER)[0]
    assert (v.muc_phat_min, v.muc_phat_max) == (400_000, 600_000)
    assert v.hanh_vi.startswith("Khi ra, vào vị trí dừng xe")
    assert v.violation_id == f"{K}/D6/K1/Pb@v1#1" and v.extraction_method == "regex"


def test_vehicle_from_article_title_without_mo_to_false_positive(real):
    car = at(real[0], f"{K}/D6/K6/Pc", AFTER)[0]
    bike = at(real[0], f"{K}/D7/K6/Pa", AFTER)[0]
    assert "o_to" in car.phuong_tien and "xe_may" not in car.phuong_tien
    assert "xe_may" in bike.phuong_tien and "o_to" not in bike.phuong_tien


def test_attributes_alcohol_and_speed(real):
    vs = real[0]
    assert at(vs, f"{K}/D6/K6/Pc", AFTER)[0].attributes["nong_do_con"] == "duoi_50mg"
    assert at(vs, f"{K}/D6/K9/Pa", AFTER)[0].attributes["nong_do_con"] == "50_80mg"
    assert at(vs, f"{K}/D6/K11/Pa", AFTER)[0].attributes["nong_do_con"] == "tren_80mg"
    assert at(vs, f"{K}/D6/K3/Pa", AFTER)[0].attributes["vuot_toc_do"] == "05_10kmh"
    assert at(vs, f"{K}/D6/K7/Pa", AFTER)[0].attributes["vuot_toc_do"] == "tren_35kmh"


def test_points_and_suspension_attached_back(real):
    vs = real[0]
    assert at(vs, f"{K}/D6/K6/Pc", AFTER)[0].tru_diem_gplx == 4          # K16b nêu cả "khoản 6"
    assert at(vs, f"{K}/D6/K5/Pa", AFTER)[0].tru_diem_gplx == 2          # K16a nêu từng điểm
    v = at(vs, f"{K}/D6/K11/Pa", AFTER)[0]
    assert (v.tuoc_gplx_min_thang, v.tuoc_gplx_max_thang) == (22, 24)


def test_individual_and_organization_are_two_rows(real):
    rows = at(real[0], f"{K}/D32/K8/Ph", AFTER, None)
    assert {(r.doi_tuong, r.muc_phat_min, r.muc_phat_max) for r in rows} == {
        ("ca_nhan", 4_000_000, 6_000_000), ("to_chuc", 8_000_000, 12_000_000)}
    assert len({r.violation_id for r in rows}) == 2


def test_conditional_sanction_stays_out_of_columns(real):
    v = at(real[0], f"{K}/D32/K9/Pd", AFTER)[0]
    assert v.tru_diem_gplx is None
    assert v.attributes["che_tai_co_dieu_kien"][0]["tru_diem_gplx"] == 2


def test_per_person_fine_keeps_total_cap(real):
    v = at(real[0], f"{K}/D20/K2", AFTER)[0]
    assert v.attributes["tinh_theo"] == "moi_nguoi" and v.attributes["tong_muc_phat_toi_da"] == 75_000_000


def test_per_person_fine_splits_individual_and_organization(real):
    rows = {r.doi_tuong: r for r in at(real[0], f"{K}/D32/K5", AFTER, None)}
    assert (rows["ca_nhan"].muc_phat_min, rows["to_chuc"].muc_phat_min) == (800_000, 1_600_000)
    assert not rows["to_chuc"].needs_review


def test_warning_has_no_fine(real):
    v = at(real[0], f"{K}/D6/K1a", AFTER)[0]
    assert v.muc_phat_min is None and "Phạt cảnh cáo" in v.bien_phap_bo_sung


def test_validity_follows_amendment(real):
    vs = real[0]
    assert "dải dừng xe" not in at(vs, f"{K}/D6/K7/Pc", BEFORE)[0].hanh_vi
    new = at(vs, f"{K}/D6/K7/Pc", AFTER)[0]
    assert "dải dừng xe" in new.hanh_vi and new.valid_from == date(2026, 8, 15) and new.valid_to == OPEN_END


def test_new_khoan_from_amendment_only_after_effective_date(real):
    vs = real[0]
    assert at(vs, f"{K}/D6/K1a", BEFORE) == [] and at(vs, f"{K}/D6/K1a", AFTER)


def test_no_unrecognized_structure_except_known(real):
    assert {(i.rule, i.provision_key) for i in real[1]} == {("khoan_not_recognized", f"{K}/D39/K8")}


def test_extraction_deterministic(real):
    assert len({v.violation_id for v in real[0]}) == len(real[0])


@pytest.mark.parametrize("line, refs, cond, points, suspend", [
    ("Thực hiện hành vi quy định tại điểm a khoản 9, khoản 10 Điều này bị trừ điểm giấy phép lái xe 10 điểm.",
     (Ref(None, "9", "a"), Ref(None, "10")), None, 10, None),
    ("Thực hiện hành vi quy định tại khoản 12 Điều này bị tước quyền sử dụng giấy phép lái xe từ 10 tháng đến 12 tháng;",
     (Ref(None, "12"),), None, None, (10, 12)),
    ("Thực hiện hành vi quy định tại khoản 2 (trường hợp vượt trên 100% số người) Điều này bị trừ điểm giấy phép lái xe 10 điểm.",
     (Ref(None, "2"),), "trường hợp vượt trên 100% số người", 10, None),
    ("Thực hiện hành vi quy định tại điểm b khoản 2 Điều này bị trừ điểm giấy phép lái xe (khi điều khiển xe ô tô) 02 điểm;",
     (Ref(None, "2", "b"),), "khi điều khiển xe ô tô", 2, None),
])
def test_parse_sanction(line, refs, cond, points, suspend):
    s = parse_sanction(line)
    assert (s.refs, s.condition, s.points, s.suspend) == (refs, cond, points, suspend)


def test_sanction_condition_may_contain_plain_bi():
    s = parse_sanction("Thực hiện hành vi quy định tại khoản 3 Điều này nếu số khung bị tẩy xóa còn bị tịch thu phương tiện;")
    assert s.condition == "nếu số khung bị tẩy xóa" and s.measures == ("còn bị tịch thu phương tiện",)
    assert parse_sanction("Không có dẫn chiếu nào.") is None


def _v(**kw):
    base = {"violation_id": "x@v1#1", "provision_key": "x", "version_no": 1, "hanh_vi": "h", "phuong_tien": ("o_to",),
                "doi_tuong": "ca_nhan", "muc_phat_min": 100_000, "muc_phat_max": 200_000, "tru_diem_gplx": None,
                "tuoc_gplx_min_thang": None, "tuoc_gplx_max_thang": None, "bien_phap_bo_sung": (), "attributes": {},
                "valid_from": date(2025, 1, 1), "valid_to": OPEN_END, "extraction_method": "regex", "confidence": 1.0,
                "needs_review": False}
    return Violation(**{**base, **kw})


def test_rule_min_le_max_quarantines():
    kept, issues = check_violations([_v(muc_phat_min=9, muc_phat_max=1)], 0, 10**9)
    assert kept == [] and [(i.rule, i.severity) for i in issues] == [("fine_min_gt_max", "error")]


def test_rule_fine_range_marks_review():
    kept, issues = check_violations([_v(muc_phat_max=200_000_000)], 50_000, 150_000_000)
    assert kept[0].needs_review and [(i.rule, i.severity) for i in issues] == [("fine_out_of_range", "warn")]


def test_rule_empty_vehicle_marks_review():
    kept, issues = check_violations([_v(phuong_tien=())], 50_000, 150_000_000)
    assert kept[0].needs_review and [i.rule for i in issues] == ["phuong_tien_empty"]


def test_rule_clean_row_passes():
    kept, issues = check_violations([_v()], 50_000, 150_000_000)
    assert issues == [] and not kept[0].needs_review


def _article(key, vid="1"):
    return {"provision_key": key, "level": "dieu", "vbpl_id": vid}


def test_rule_dieu_sequence():
    assert check_dieu_sequence([_article("A/D1"), _article("A/D2"), _article("A/D2a")]) == []
    gap = check_dieu_sequence([_article("A/D1"), _article("A/D3")])
    assert gap[0].severity == "error" and gap[0].detail["missing"] == [2]
    assert check_dieu_sequence([_article("A/D1"), _article("A/D1")])[0].detail["duplicates"] == [1]


def test_rule_amendment_target_exists():
    prov = [{"provision_key": "A/D1"}]
    am = [{"amendment_id": "1", "target_key": "A/D9", "parse_status": "ok", "action": "sua_doi"},
          {"amendment_id": "2", "target_key": "A/D1", "parse_status": "ok", "action": "sua_doi"},
          {"amendment_id": "3", "target_key": "A/D2", "parse_status": "ok", "action": "bo_sung"}]
    out, issues = check_amendment_targets(am, prov)
    assert [a["parse_status"] for a in out] == ["needs_review", "ok", "ok"]
    assert [(i.rule, i.severity) for i in issues] == [("amendment_target_missing", "error")]


def test_rule_overlap_is_error():
    a = Version("k", 1, "a", "1", date(2025, 1, 1), date(2026, 1, 1), False, "dieu", None)
    b = Version("k", 2, "b", "1", date(2025, 6, 1), OPEN_END, True, "dieu", None)
    assert [i.severity for i in check_no_overlap([a, b])] == ["error"]


def test_summarize_counts():
    _, issues = check_violations([_v(phuong_tien=()), _v(), _v(muc_phat_min=9, muc_phat_max=1)], 50_000, 150_000_000)
    assert summarize(3, issues) == {"total": 3, "pass": 1, "warn": 1, "error": 1}
