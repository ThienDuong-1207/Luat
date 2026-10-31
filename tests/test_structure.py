"""M3: tách cấu trúc trên fixtures + trường hợp tổng hợp. Không gọi mạng, không cần Spark."""

from __future__ import annotations

import collections

import pymupdf
import pytest

from luatgt.crawler.extract import extract_attributes
from luatgt.crawler.selectors import load_source_config
from luatgt.parsing.document import html_parse_config
from luatgt.parsing.html_fulltext import SourceLine, extract_lines
from luatgt.parsing.normalize import normalize_line, strip_header_footer
from luatgt.parsing.pdf_text import extract_pdf_text, match_dieu_pages
from luatgt.parsing.structure import doc_key, parse_structure
from tests.helpers import FIX, LUAT26, ND168, ND238, ROOT


@pytest.fixture(scope="module")
def src():
    return load_source_config(ROOT / "config" / "sources" / "vbpl.yaml")


@pytest.fixture(scope="module")
def parsed(src):
    out = {}
    for vid in (LUAT26, ND168, ND238):
        meta = extract_attributes((FIX / f"{vid}__thuoc-tinh.html").read_text("utf-8"), vid, src)
        lines = extract_lines((FIX / f"{vid}__toan-van.html").read_text("utf-8"), html_parse_config(src))
        out[vid] = parse_structure(lines, meta.so_hieu)
    return out


def by_key(doc):
    return {n.key: n for n in doc.nodes()}


def levels(doc):
    return collections.Counter(n.level for n in doc.nodes())


# ---------------------------------------------------------------- NĐ 168 (nghiệm thu M3)
def test_nd168_all_dieu_consecutive(parsed):
    doc = parsed[ND168]
    assert [n.number for n in doc.nodes() if n.level == "dieu"] == [str(i) for i in range(1, 56)]
    assert not [i for i in doc.issues if i.rule == "dieu_not_consecutive"]


def test_nd168_hierarchy_counts(parsed):
    c = levels(parsed[ND168])
    assert (c["chuong"], c["muc"], c["dieu"]) == (4, 8, 55)
    assert c["khoan"] > 300 and c["diem"] > 900


def test_nd168_keys_follow_spec(parsed):
    nodes = by_key(parsed[ND168])
    n = nodes["168-2024-ND-CP/D6/K3/Pm"]
    assert n.parent.key == "168-2024-ND-CP/D6/K3"
    assert n.text.startswith("Chở trẻ em dưới 10 tuổi")
    assert "168-2024-ND-CP/D2/K2/Pdd" in nodes  # điểm "đ" → Pdd
    assert nodes["168-2024-ND-CP/D6"].title.startswith("Xử phạt, trừ điểm giấy phép lái xe")
    assert nodes["168-2024-ND-CP/D6"].parent.key == "168-2024-ND-CP/CII/M1"  # Chương giữ số La Mã


def test_nd168_khoan_text_is_lead_sentence(parsed):
    """Câu dẫn của Khoản (mức phạt) nằm ở text của Khoản, không lẫn các Điểm."""
    k = by_key(parsed[ND168])["168-2024-ND-CP/D6/K3"]
    assert k.text.startswith("Phạt tiền từ") and "đồng" in k.text
    assert "\n" not in k.text


def test_nd168_vbpl_annotations_kept(parsed):
    ann = collections.Counter(a for n in parsed[ND168].nodes() for a in n.annotations)
    assert ann == {
        "Điều khoản được sửa đổi, bổ sung": 45,
        "Điều khoản được bổ sung": 3,
        "Điều khoản được bãi bỏ": 3,
    }
    assert by_key(parsed[ND168])["168-2024-ND-CP/D6/K3/Pm"].annotations == [
        "Điều khoản được sửa đổi, bổ sung"
    ]


def test_nd168_d_dd_typos_fixed_and_flagged(parsed):
    doc = parsed[ND168]
    relabeled = {i.provision_key for i in doc.issues if i.rule == "diem_relabeled"}
    assert relabeled == {
        "168-2024-ND-CP/D16/K2/Pd", "168-2024-ND-CP/D39/K9/Pd", "168-2024-ND-CP/D40/K3/Pd",
    }
    assert by_key(doc)["168-2024-ND-CP/D16/K2/Pd"].number_raw == "đ"
    # Lỗi nguồn không sửa được thì giữ dòng, gắn hậu tố và báo
    assert {i.rule for i in doc.issues} == {"diem_relabeled", "diem_out_of_order", "duplicate_key"}
    assert "168-2024-ND-CP/D40/K3/Pc~2" in by_key(doc)


# ---------------------------------------------------------------- văn bản khác
def test_luat26_structure(parsed):
    doc = parsed[LUAT26]
    assert levels(doc)["dieu"] == 77
    assert [i.rule for i in doc.issues] == ["diem_out_of_order"]  # Điều 20: nguyên văn nhảy đ → g
    assert doc.trailer[0].startswith("Luật này đã được Quốc hội")
    d3 = by_key(doc)["26-2001-QH10/D3"]
    assert d3.text.startswith("Trong Luật này, các từ ngữ dưới đây được hiểu như sau")
    assert len([c for c in d3.children if c.level == "khoan"]) > 10  # "như sau:" thường không nuốt Khoản


def test_nd238_quoted_amendments_not_split(parsed):
    doc = parsed[ND238]
    nodes = by_key(doc)
    assert levels(doc)["dieu"] == 21
    d2 = nodes["238-2026-ND-CP/D2"]
    assert d2.title == "Sửa đổi, bổ sung một số điểm, khoản của Điều 6"
    assert [c.number for c in d2.children] == ["1", "2"]  # "1a." trong ngoặc kép không thành Khoản
    assert '"1a. Phạt cảnh cáo' in d2.children[0].text
    # Điều 7 khoản 3: nội dung mới "8a." thuộc khoản 3, không thành Khoản 8a của NĐ 238
    k3 = nodes["238-2026-ND-CP/D7/K3"]
    assert k3.has_quoted_content and '"8a. Phạt tiền từ 12.000.000 đồng' in k3.text
    # Điều 8 khoản 3: dòng nội dung THIẾU ngoặc kép sau "như sau:" vẫn không thành Điểm
    k = nodes["238-2026-ND-CP/D8/K3"]
    assert not k.children and k.text.splitlines()[1].startswith("c) Điều khiển xe ô tô kinh doanh vận tải")
    assert doc.trailer[0] == "Nơi nhận:"
    assert not doc.issues


# ---------------------------------------------------------------- trường hợp tổng hợp
def lines(*texts):
    return [SourceLine(t) for t in texts]


def test_doc_key():
    assert doc_key("168/2024/NĐ-CP") == "168-2024-ND-CP"
    assert doc_key("36/2024/QH15") == "36-2024-QH15"


def test_phan_heading_vs_ordinary_sentence():
    doc = parse_structure(lines(
        "Phần thứ nhất", "QUY ĐỊNH CHUNG",
        "Điều 1. Giải thích", "1. Phần đường xe chạy là phần của đường bộ.",
    ), "1/2024/QH15")
    nodes = by_key(doc)
    assert nodes["1-2024-QH15/PHNHAT"].title == "QUY ĐỊNH CHUNG"
    assert nodes["1-2024-QH15/D1/K1"].text.startswith("Phần đường xe chạy")


def test_inserted_numbers_valid_and_gaps_flagged():
    ok = parse_structure(lines("Điều 1. A", "1. x", "1a. y", "2. z", "Điều 1a. B", "Điều 2. C"), "1/2024/QH15")
    assert not ok.issues
    bad = parse_structure(lines("Điều 1. A", "Điều 3. C", "1. x", "3. z"), "1/2024/QH15")
    assert {i.rule for i in bad.issues} == {"dieu_not_consecutive", "khoan_not_consecutive"}


def test_diem_directly_under_dieu():
    doc = parse_structure(lines("Điều 1. A", "Gồm:", "a) x;", "b) y."), "1/2024/QH15")
    assert {"1-2024-QH15/D1/Pa", "1-2024-QH15/D1/Pb"} <= set(by_key(doc))
    assert by_key(doc)["1-2024-QH15/D1"].text == "Gồm:"


def test_multiline_quote_kept_in_one_node():
    doc = parse_structure(lines(
        "Điều 1. Sửa đổi Điều 5", "1. Sửa đổi khoản 2 như sau:",
        '"2. Phạt tiền đối với:', "a) hành vi A;", 'b) hành vi B.".', "2. Bãi bỏ khoản 3.",
    ), "9/2026/ND-CP")
    d1 = by_key(doc)["9-2026-ND-CP/D1"]
    assert [c.number for c in d1.children] == ["1", "2"]
    assert d1.children[0].text.count("\n") == 3 and not d1.children[0].children


def test_normalize_line():
    assert normalize_line("  Ðiều 1.\t  Phạm   vi ") == "Ðiều 1. Phạm vi"
    assert normalize_line("Đì") == "Đì"  # NFC


def test_header_footer_removed():
    pages = [["CÔNG BÁO/Số 5", f"Điều {i}. X", f"Trang {i}"] for i in range(1, 5)]
    assert strip_header_footer(pages) == [[f"Điều {i}. X"] for i in range(1, 5)]


def test_pdf_text_and_page_matching():
    doc = pymupdf.open()
    bodies = [
        "<p>CÔNG BÁO</p><p>NGHỊ ĐỊNH quy định xử phạt vi phạm hành chính</p>",
        "<p>CÔNG BÁO</p><p>Điều 1. Phạm vi điều chỉnh</p><p>Nghị định này quy định về xử phạt.</p>",
        "<p>CÔNG BÁO</p><p>Điều 2. Đối tượng áp dụng</p><p>Cá nhân, tổ chức Việt Nam.</p>",
        "<p>CÔNG BÁO</p><p>Điều 2 của Luật này (dẫn chiếu, không phải tiêu đề)</p>",
    ]
    for html in bodies:  # insert_htmlbox dùng font có dấu tiếng Việt
        doc.new_page().insert_htmlbox(pymupdf.Rect(72, 72, 520, 760), html)
    pdf = extract_pdf_text(doc.tobytes(), min_chars=10, ocr=False)
    assert pdf.empty_pages == []
    assert all("CÔNG BÁO" not in ln for page in pdf.pages for ln in page)  # header lặp bị bỏ
    assert match_dieu_pages(pdf) == {"1": 2, "2": 3}
