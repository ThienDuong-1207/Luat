"""M4: parse chỉ dẫn sửa đổi (NĐ 238 → NĐ 168) và dựng phiên bản SCD2. Không mạng, không Spark."""

from __future__ import annotations

import collections
from dataclasses import asdict
from datetime import date

import pytest

from luatgt.common.config import load_settings
from luatgt.crawler.selectors import load_source_config
from luatgt.modeling.versions import (
    OPEN_END,
    Version,
    apply_phrase,
    build_versions,
    check_no_overlap,
    is_amending_document,
    version_at,
)
from luatgt.parsing.amendments import (
    PhraseEdit,
    Ref,
    parse_amendments,
    parse_phrase_edits,
    parse_refs,
)
from luatgt.parsing.document import DocumentInputs, parse_document
from tests.helpers import FIX, ND168, ND238, ROOT

K = "168-2024-ND-CP"
BEFORE, AFTER = date(2026, 8, 1), date(2026, 10, 20)


@pytest.fixture(scope="module")
def silver():
    src = load_source_config(ROOT / "config" / "sources" / "vbpl.yaml")
    cfg = load_settings(env={}).parsing
    tabs = {v: k for k, v in src.tabs.items()}

    def rows(vid):
        html = {tabs[t]: (FIX / f"{vid}__{t}.html").read_text("utf-8")
                for t in ("toan-van", "thuoc-tinh", "luoc-do", "lich-su")}
        return parse_document(DocumentInputs(vid, html, {}), src, cfg)

    return rows(ND168), rows(ND238)


@pytest.fixture(scope="module")
def amendments(silver):
    r168, r238 = silver
    return parse_amendments(r238.documents[0], r238.provisions, {"168/2024/NĐ-CP": r168.provisions})


@pytest.fixture(scope="module")
def versions(silver, amendments):
    r168, r238 = silver
    return build_versions(r168.documents + r238.documents, r168.provisions + r238.provisions,
                          [asdict(a) for a in amendments])


def explicit(amendments):
    return {(a.action, a.target_key) for a in amendments if a.origin == "explicit" and a.parse_status == "ok"}


# ---------------------------------------------------------------- amendments
def test_detects_amending_document(silver):
    r168, r238 = silver
    assert is_amending_document(r238.documents[0]) == "168/2024/NĐ-CP"
    assert is_amending_document(r168.documents[0]) is None


def test_supported_patterns(amendments):
    ex = explicit(amendments)
    expected = {
        ("sua_doi", f"{K}/D3/K3/Pi"),     # ngữ cảnh "một số điểm của khoản 3 Điều 3"
        ("bo_sung", f"{K}/D6/K1a"),       # "Bổ sung khoản 1a vào trước khoản 1"
        ("sua_doi", f"{K}/D6/K3/Pm"),     # "Sửa đổi, bổ sung điểm m khoản 3"
        ("sua_doi", f"{K}/D13/K8/Pb"),    # chỉ dẫn ngay ở tiêu đề Điều
        ("sua_doi", f"{K}/D18/K4/Pa"),    # "Sửa đổi bổ sung" (thiếu dấu phẩy)
        ("sua_doi", f"{K}/D20/K5/Pdd"),   # ngữ cảnh 3 tầng: Điều 20 → khoản 5 → điểm đ
        ("sua_doi", f"{K}/D20/K5/Pl"), ("sua_doi", f"{K}/D20/K5/Pm"),  # "điểm l, điểm m" → 2 bản ghi
        ("bo_sung", f"{K}/D20/K5/Pn"),    # "Bổ sung điểm n vào sau điểm m"
        ("bo_sung", f"{K}/D20/K8a"),
        ("sua_doi", f"{K}/D21/K5/Pc"),    # nội dung THIẾU ngoặc kép
        ("bo_sung", f"{K}/D26/K7/Pk"), ("bo_sung", f"{K}/D26/K7/Pl"),
        ("bo_sung", f"{K}/D29/K3a"),
        ("bo_sung", f"{K}/D41/K4/Pk1"),   # điểm có hậu tố số
        ("sua_doi", f"{K}/D42"), ("sua_doi", f"{K}/D43"), ("sua_doi", f"{K}/D44"),  # thay cả Điều
        ("sua_doi", f"{K}/D46/K2"),
        ("bo_sung", f"{K}/D53/K3"), ("bo_sung", f"{K}/D53/K4"),  # "khoản 3, khoản 4 vào sau khoản 2 Điều 53"
        ("bai_bo", f"{K}/D32/K17/Pd"), ("bai_bo", f"{K}/D32/K17/Pdd"),
        ("bai_bo", f"{K}/D32/K17/Pe"), ("bai_bo", f"{K}/D32/K17/Pg"),
    }
    assert expected <= ex
    assert collections.Counter(a for a, _ in ex) == {"sua_doi": 31, "bo_sung": 14, "bai_bo": 4}


def test_all_supported_amendments_ok(amendments):
    bad = [a for a in amendments if a.action != "unsupported" and a.parse_status != "ok"]
    assert bad == []
    assert {a.effective_date for a in amendments} == {date(2026, 8, 15)}
    assert {a.target_so_hieu for a in amendments} == {"168/2024/NĐ-CP"}


def test_unsupported_go_to_review(amendments):
    unsup = [a for a in amendments if a.action == "unsupported"]
    assert len(unsup) == 1 and all(a.parse_status == "needs_review" for a in unsup)  # "đoạn thứ hai"
    assert {a.target_key for a in unsup} == {f"{K}/D50/K3/Pa"}  # "đoạn thứ hai điểm a khoản 3"
    assert any(a.origin == "phrase" and a.target_key == f"{K}/D55" for a in amendments)  # "Bỏ cụm từ … tại Điều 55"
    # "tại" CUỐI câu: cụm từ trích có "quy định tại điểm b khoản 3a Điều 29" nhưng không phải mục bị sửa
    assert all(a.target_key != f"{K}/D29/K3a/Pb" for a in amendments if a.origin == "phrase")


def test_content_children_and_implied_repeal(amendments):
    by_key = {a.target_key: a for a in amendments}
    k3a = [a for a in amendments if a.target_key.startswith(f"{K}/D29/K3a/")]
    assert {a.target_key for a in k3a} == {f"{K}/D29/K3a/Pa", f"{K}/D29/K3a/Pb"}
    assert by_key[f"{K}/D42/K1/Pb"].new_text == "Phạt tiền đến 37.500.000 đồng;"
    assert by_key[f"{K}/D42/K1/Pb"].origin == "content_child"
    assert by_key[f"{K}/D42"].title.startswith("Thẩm quyền xử phạt của Chủ tịch Ủy ban nhân dân")


def test_quoted_text_stripped(amendments):
    m = next(a for a in amendments if a.target_key == f"{K}/D6/K3/Pm")
    assert m.new_text == (
        "Chở trẻ em dưới 10 tuổi và chiều cao dưới 1,35 mét trên xe ô tô ngồi cùng hàng ghế với "
        "người lái xe (trừ xe ô tô chỉ có một hàng ghế);"
    )


def test_agrees_with_vbpl_annotations_where_reliable(silver, amendments):
    """Nhãn vbpl.vn khớp từ Điều 3 đến hết Điều 20 (từ Điều 21 nhãn của trang bị lệch, xem D-015)."""
    r168, _ = silver
    order = {p["provision_key"]: p["ordinal"] for p in r168.provisions}
    stop = order[f"{K}/D21"] - 1
    ann = {p["provision_key"]: p["vbpl_annotations"][0] for p in r168.provisions
           if p["vbpl_annotations"] and p["ordinal"] <= stop}
    modified = {k for k, lab in ann.items() if lab == "Điều khoản được sửa đổi, bổ sung"}
    anchors = {k for k, lab in ann.items() if lab == "Điều khoản được bổ sung"}
    changed = {a.target_key for a in amendments if a.origin == "explicit"}
    assert modified <= changed
    # Nhãn "được bổ sung" đặt ở mục ngay trước/sau chỗ chèn (1a trước K1, 8a sau K8, n sau m)
    assert anchors == {f"{K}/D6/K1", f"{K}/D20/K8", f"{K}/D20/K5/Pm"}


@pytest.mark.parametrize("text,expected", [
    ("điểm b khoản 8 Điều 13", [Ref("13", "8", "b")]),
    ("điểm l, điểm m khoản 5", [Ref(None, "5", "l"), Ref(None, "5", "m")]),
    ("khoản 3, khoản 4", [Ref(None, "3"), Ref(None, "4")]),
    ("Điều 42", [Ref("42")]),
    ("điểm a, b, d và điểm đ khoản 2; điểm b khoản 3 Điều 12",
     [Ref("12", "2", x) for x in ("a", "b", "d", "đ")] + [Ref("12", "3", "b")]),
    ("khoản 9, 10 Điều 12", [Ref("12", "9"), Ref("12", "10")]),
    ("một số điểm của khoản 3 Điều 3", [Ref("3", "3")]),
])
def test_parse_refs(text, expected):
    assert parse_refs(text) == expected


def _prov(key, level, text, vid="1", ordinal=0, parent=None, title=None):
    return {"provision_id": f"{vid}:{key.split('/', 1)[1]}", "vbpl_id": vid, "provision_key": key,
            "level": level, "text": text, "title": title, "ordinal": ordinal,
            "parent_id": f"{vid}:{parent.split('/', 1)[1]}" if parent else None}


def test_quality_rules_mark_needs_review():
    target = [_prov("1-2024-ND-CP/D1", "dieu", "", ordinal=0),
              _prov("1-2024-ND-CP/D1/K1", "khoan", "Phạt tiền.", ordinal=1, parent="1-2024-ND-CP/D1")]
    amending = [
        _prov("2-2025-ND-CP/D1", "dieu", "", vid="2", ordinal=0, title="Sửa đổi, bổ sung Điều 1"),
        _prov("2-2025-ND-CP/D1/K1", "khoan", 'Sửa đổi, bổ sung khoản 9 như sau:\n"9. X.".', vid="2",
              ordinal=1, parent="2-2025-ND-CP/D1"),
        _prov("2-2025-ND-CP/D1/K2", "khoan", 'Bổ sung khoản 1 vào sau khoản 0 như sau:\n"1. Y.".', vid="2",
              ordinal=2, parent="2-2025-ND-CP/D1"),
        _prov("2-2025-ND-CP/D2", "dieu", "Nghị định này có hiệu lực từ ngày 01 tháng 3 năm 2025.", vid="2",
              ordinal=3, title="Hiệu lực thi hành"),
    ]
    doc = {"vbpl_id": "2", "so_hieu": "2/2025/NĐ-CP", "ngay_hieu_luc": date(2025, 3, 1),
           "ten_van_ban": "Nghị định số 2/2025/NĐ-CP sửa đổi một số điều của Nghị định số 1/2024/NĐ-CP"}
    am = {a.target_key: a for a in parse_amendments(doc, amending, {"1/2024/NĐ-CP": target})}
    assert am["1-2024-ND-CP/D1/K9"].review_reason == "mục được sửa không có trong văn bản gốc"
    assert am["1-2024-ND-CP/D1/K1"].review_reason == "mục bổ sung đã có trong văn bản gốc"
    # Hiệu lực thi hành nêu thêm ngày riêng → mọi bản ghi cần xem lại (spec 8.4)
    amending[3]["text"] += "\nRiêng khoản 2 Điều 1 có hiệu lực từ ngày 01 tháng 7 năm 2025."
    assert all(a.parse_status == "needs_review"
               for a in parse_amendments(doc, amending, {"1/2024/NĐ-CP": target}))


def _law(so_hieu, keys):
    d = so_hieu.replace("/", "-").replace("Đ", "D")
    return [_prov(f"{d}/{k}", "dieu" if "/" not in k else "khoan", "x", ordinal=i,
                  parent=f"{d}/{k.rsplit('/', 1)[0]}" if "/" in k else None) for i, k in enumerate(keys)]


def _omnibus(extra=()):
    rows = [
        _prov("9-2025-QH15/D1", "dieu", "", vid="9", ordinal=0, title="Sửa đổi một số điều của Luật Cảnh vệ"),
        _prov("9-2025-QH15/D1/K1", "khoan", 'Sửa đổi, bổ sung khoản 1 Điều 1 như sau:\n“1. Ngoài phạm vi.”.',
              vid="9", ordinal=1, parent="9-2025-QH15/D1"),
        _prov("9-2025-QH15/D2", "dieu", "", vid="9", ordinal=2,
              title="Sửa đổi, bổ sung một số điều của Luật Đường bộ"),
        _prov("9-2025-QH15/D2/K1", "khoan",
              'Sửa đổi, bổ sung khoản 1 và bổ sung khoản 1a vào sau khoản 1 Điều 1 như sau:\n“1. Mới.\n1a. Thêm.”.',
              vid="9", ordinal=3, parent="9-2025-QH15/D2"),
        _prov("9-2025-QH15/D2/K2", "khoan", "Bãi bỏ Điều 2.", vid="9", ordinal=4, parent="9-2025-QH15/D2"),
        _prov("9-2025-QH15/D2/K3", "khoan", "Sửa đổi, bổ sung tên Điều 3 như sau: “Điều 3. Tên mới”.",
              vid="9", ordinal=5, parent="9-2025-QH15/D2"),
        _prov("9-2025-QH15/D3", "dieu", "", vid="9", ordinal=6, title="Điều khoản thi hành"),
        _prov("9-2025-QH15/D3/K1", "khoan", "Luật này có hiệu lực thi hành từ ngày 01 tháng 7 năm 2026.",
              vid="9", ordinal=7, parent="9-2025-QH15/D3"),
    ]
    return rows + list(extra)


OMNIBUS_DOC = {"vbpl_id": "9", "so_hieu": "9/2025/QH15", "ngay_hieu_luc": date(2026, 7, 1),
               "ten_van_ban": "Luật sửa đổi, bổ sung một số điều của 10 luật"}
ROADS = {"3/2024/QH15": _law("3/2024/QH15", ["D1", "D1/K1", "D2", "D2/K1", "D3"])}


def test_omnibus_targets_by_article_name_and_skips_out_of_scope():
    am = parse_amendments(OMNIBUS_DOC, _omnibus(), ROADS, {"luật đường bộ": "3/2024/QH15"})
    assert {a.target_so_hieu for a in am} == {"3/2024/QH15"}  # Điều 1 sửa Luật Cảnh vệ: ngoài seed list


def test_mixed_sentence_gets_one_action_per_provision():
    am = {a.target_key: a for a in parse_amendments(OMNIBUS_DOC, _omnibus(), ROADS,
                                                    {"luật đường bộ": "3/2024/QH15"})}
    assert (am["3-2024-QH15/D1/K1"].action, am["3-2024-QH15/D1/K1"].parse_status) == ("sua_doi", "ok")
    assert (am["3-2024-QH15/D1/K1a"].action, am["3-2024-QH15/D1/K1a"].parse_status) == ("bo_sung", "ok")


def test_repealing_article_cascades_to_children():
    am = {a.target_key: a for a in parse_amendments(OMNIBUS_DOC, _omnibus(), ROADS,
                                                    {"luật đường bộ": "3/2024/QH15"})}
    assert am["3-2024-QH15/D2/K1"].action == "bai_bo"
    assert am["3-2024-QH15/D2/K1"].origin == "implied_by_replace"


def test_title_change_is_not_a_text_replacement():
    am = parse_amendments(OMNIBUS_DOC, _omnibus(), ROADS, {"luật đường bộ": "3/2024/QH15"})
    title = [a for a in am if a.target_key == "3-2024-QH15/D3"]
    assert [(a.action, a.parse_status) for a in title] == [("unsupported", "needs_review")]


@pytest.mark.parametrize("line, expected", [
    ("Quy định tại khoản 1 Điều 2 của Luật này có hiệu lực thi hành từ ngày 01 tháng 01 năm 2026.",
     {"3-2024-QH15/D1/K1": ("ok", date(2026, 1, 1)), "3-2024-QH15/D2": ("ok", date(2026, 7, 1))}),
    ("Quy định nộp hồ sơ trực tuyến tại khoản 1 Điều 2 Luật này có hiệu lực thi hành từ ngày 01 tháng 01 năm 2027.",
     {"3-2024-QH15/D1/K1": ("needs_review", date(2026, 7, 1)), "3-2024-QH15/D2": ("ok", date(2026, 7, 1))}),
    ("Điều 2 của Luật này hết hiệu lực kể từ ngày 01 tháng 3 năm 2027.",
     {"3-2024-QH15/D1/K1": ("ok", date(2026, 7, 1))}),
])
def test_separate_effective_dates_apply_per_provision(line, expected):
    extra = [_prov("9-2025-QH15/D3/K2", "khoan", line, vid="9", ordinal=8, parent="9-2025-QH15/D3")]
    am = {a.target_key: a for a in parse_amendments(OMNIBUS_DOC, _omnibus(extra), ROADS,
                                                    {"luật đường bộ": "3/2024/QH15"})}
    for key, want in expected.items():
        assert (am[key].parse_status, am[key].effective_date) == want


@pytest.mark.parametrize("header, expected", [
    ("Thay thế cụm từ “Bộ A” bằng cụm từ “Bộ B” tại khoản 3 Điều 10, điểm a khoản 3 Điều 21.",
     [PhraseEdit("replace", "Bộ A", "Bộ B", (Ref("10", "3"), Ref("21", "3", "a")))]),
    ('Bổ sung cụm từ", xe nội bộ" vào sau cụm từ "xe vận tải" tại điểm d khoản 6 Điều 20.',
     [PhraseEdit("insert_after", "xe vận tải", ", xe nội bộ", (Ref("20", "6", "d"),))]),
    ("Bổ sung cụm từ “xanh và” trước từ “đỏ” tại điểm b khoản 2 Điều 19.",
     [PhraseEdit("insert_before", "đỏ", "xanh và", (Ref("19", "2", "b"),))]),
    ('Bỏ cụm từ "A" tại điểm b khoản 7 Điều 32, cụm từ "B" tại điểm đ khoản 18 Điều 32.',
     [PhraseEdit("remove", "A", None, (Ref("32", "7", "b"),)),
      PhraseEdit("remove", "B", None, (Ref("32", "18", "đ"),))]),
    ('Bổ sung cụm từ "A" vào trước cụm từ "B", cụm từ"; C" vào sau cụm từ "D" tại điểm h khoản 3 Điều 47.',
     [PhraseEdit("insert_before", "B", "A", (Ref("47", "3", "h"),)),
      PhraseEdit("insert_after", "D", "; C", (Ref("47", "3", "h"),))]),
    ("Bãi bỏ cụm từ “sở hữu” tại tên khoản 8 Điều 11.",
     [PhraseEdit("remove", "sở hữu", None, (Ref("11", "8"),), "own")]),
    ("Thay thế Phụ lục I ban hành kèm theo Nghị định này;", None),
    ("Sửa đổi, bổ sung đoạn thứ hai điểm a khoản 3 như sau:", None),
])
def test_parse_phrase_edits(header, expected):
    assert parse_phrase_edits(header) == expected


@pytest.mark.parametrize("text, op, old, new, want", [
    ("Bộ A và Bộ A.", "replace", "Bộ A", "Bộ B", ("Bộ B và Bộ B.", 2)),
    ("theo khoản 2, khoản 20", "insert_after", "khoản 2", ", khoản 3", ("theo khoản 2, khoản 3, khoản 20", 1)),
    ("đèn đỏ sáng", "insert_before", "đỏ", "xanh và", ("đèn xanh và đỏ sáng", 1)),
    ("đi làn dừng", "insert_after", "làn dừng", "hoặc dải", ("đi làn dừng hoặc dải", 1)),
    ("a, b trực thuộc trung ương, c", "remove", "trực thuộc trung ương", None, ("a, b, c", 1)),
    ("điểm h, điểm h", "insert_after", "điểm h", ", điểm l", ("điểm h, điểm h", 2)),   # mơ hồ: không đổi
    ("khoản 20", "insert_after", "khoản 2", "x", ("khoản 20", 0)),                     # không khớp nửa từ
])
def test_apply_phrase(text, op, old, new, want):
    assert apply_phrase(text, op, old, new) == want


def _phrase(key, op, old, new, when=date(2026, 1, 1), aid="9:D1#1", scope="tree"):
    return {"amendment_id": aid, "amending_vbpl_id": "9", "target_so_hieu": "3/2024/QH15", "target_key": key,
            "action": "sua_doi", "new_text": new, "effective_date": when, "raw_instruction": "",
            "parse_status": "ok", "origin": "phrase", "phrase_op": op, "phrase_old": old, "phrase_scope": scope}


def _doc_prov(key, level, text):
    return {"vbpl_id": "3", "provision_key": key, "level": level, "text": text}


DOC3 = {"vbpl_id": "3", "ngay_hieu_luc": date(2025, 1, 1)}


def test_phrase_applies_to_children_and_longest_first():
    rows = [_doc_prov("X/D1", "dieu", "Dẫn."), _doc_prov("X/D1/K1", "khoan", "giấy chứng nhận kiểm định xe")]
    am = [_phrase("X/D1", "replace", "giấy chứng nhận", "chứng nhận", aid="9:D1#1"),
          _phrase("X/D1/K1", "remove", "giấy chứng nhận kiểm định", None, aid="9:D1#2")]
    vs, issues = build_versions([DOC3], rows, am)
    assert version_at(vs, "X/D1/K1", date(2026, 2, 1)).text == "xe"
    assert version_at(vs, "X/D1/K1", date(2025, 2, 1)).text == "giấy chứng nhận kiểm định xe"
    assert [i.rule for i in issues] == ["phrase_not_found"]    # "giấy chứng nhận" đã hết sau khi bỏ cụm dài


def test_phrase_not_found_keeps_text_and_warns():
    vs, issues = build_versions([DOC3], [_doc_prov("X/D1", "dieu", "Dẫn.")],
                                [_phrase("X/D1", "remove", "không có", None)])
    assert [v.version_no for v in vs] == [1]
    assert [i.rule for i in issues] == ["phrase_not_found"]


# ---------------------------------------------------------------- versions (nghiệm thu M4)
def test_amended_provisions_have_two_versions_without_overlap(versions):
    vs, issues = versions
    assert issues == []
    for key in (f"{K}/D6/K3/Pm", f"{K}/D18/K4/Pa", f"{K}/D42/K1/Pb"):
        mine = sorted((v for v in vs if v.provision_key == key), key=lambda v: v.version_no)
        assert [(v.version_no, v.valid_from, v.valid_to) for v in mine] == [
            (1, date(2025, 1, 1), date(2026, 8, 15)), (2, date(2026, 8, 15), OPEN_END)]
        assert [v.is_current for v in mine] == [False, True]


def test_as_of_returns_old_then_new(versions):
    vs, _ = versions
    old, new = version_at(vs, f"{K}/D6/K3/Pm", BEFORE), version_at(vs, f"{K}/D6/K3/Pm", AFTER)
    assert "hoặc không sử dụng thiết bị an toàn" in old.text and old.source_vbpl_id == ND168
    assert "hoặc không sử dụng" not in new.text and new.source_vbpl_id == ND238


def test_added_and_repealed_provisions(versions):
    vs, _ = versions
    assert version_at(vs, f"{K}/D6/K1a", BEFORE) is None
    assert version_at(vs, f"{K}/D6/K1a", AFTER).text.startswith("Phạt cảnh cáo")
    assert version_at(vs, f"{K}/D32/K17/Pd", BEFORE).text
    assert version_at(vs, f"{K}/D32/K17/Pd", AFTER).text is None  # bãi bỏ


def test_phrase_edits_on_real_text(versions):
    vs, _ = versions
    before = version_at(vs, f"{K}/D6/K7/Pc", BEFORE).text
    after = version_at(vs, f"{K}/D6/K7/Pc", AFTER).text
    assert "hoặc dải dừng xe khẩn cấp" not in before and "làn dừng xe khẩn cấp hoặc dải dừng xe khẩn cấp" in after
    # Bỏ cụm dài trước, Thay thế cụm ngắn sau, dù cả hai cùng áp vào điểm b khoản 7 Điều 32
    assert "giấy chứng nhận kiểm định" not in version_at(vs, f"{K}/D32/K7/Pb", AFTER).text
    assert "tại nơi phát hiện vi phạm" not in version_at(vs, f"{K}/D47/K5/Pc", AFTER).text


def test_unamended_provision_single_version(versions):
    vs, _ = versions
    mine = [v for v in vs if v.provision_key == f"{K}/D1"]
    assert len(mine) == 1 and mine[0].valid_to == OPEN_END


def test_versions_deterministic(silver, amendments, versions):
    r168, r238 = silver
    again = build_versions(r168.documents + r238.documents, r168.provisions + r238.provisions,
                           [asdict(a) for a in amendments])
    assert again == versions


def test_expired_document_closes_versions():
    docs = [{"vbpl_id": "1", "ngay_hieu_luc": date(2002, 1, 1), "ngay_het_hieu_luc": date(2009, 7, 1),
             "tinh_trang_norm": "het_hieu_luc"}]
    vs, _ = build_versions(docs, [_prov("26-2001-QH10/D1", "dieu", "x")], [])
    assert (vs[0].valid_from, vs[0].valid_to, vs[0].is_current) == (date(2002, 1, 1), date(2009, 7, 1), False)
    assert version_at(vs, "26-2001-QH10/D1", date(2026, 10, 20)) is None


def test_overlap_check_detects_error():
    a = Version("k", 1, "a", "1", date(2025, 1, 1), date(2026, 1, 1), False, "dieu", None)
    b = Version("k", 2, "b", "2", date(2025, 6, 1), OPEN_END, True, "dieu", "x")
    [issue] = check_no_overlap([a, b])
    assert (issue.rule, issue.severity) == ("overlapping_versions", "error")
