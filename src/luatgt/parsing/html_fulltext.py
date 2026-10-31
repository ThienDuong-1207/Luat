"""HTML toàn văn (tab Nội dung vbpl.vn) → danh sách dòng có chú thích sửa đổi (spec 8.1).

Toàn văn trên vbpl.vn là các <p> thường. Với văn bản đã bị sửa (vd NĐ 168), trang chèn khối chú thích
quanh đoạn GỐC bị tác động, kèm nhãn ("Điều khoản được sửa đổi, bổ sung"…). Ta giữ đoạn gốc như dòng
bình thường và ghi nhãn vào `annotation` (dùng để kiểm chứng parse sửa đổi ở M4).
"""

from __future__ import annotations

from dataclasses import dataclass

from bs4 import BeautifulSoup, NavigableString, Tag

from luatgt.parsing.normalize import normalize_line


@dataclass(frozen=True)
class SourceLine:
    text: str
    annotation: str | None = None  # nhãn chú thích của vbpl.vn nếu đoạn nằm trong khối chú thích


@dataclass(frozen=True)
class HtmlParseConfig:
    container: str  # selector vùng toàn văn
    annotation_block: str  # selector khối chú thích
    annotation_label: str  # selector nhãn trong khối
    annotation_labels: tuple[str, ...]  # các nhãn đã biết
    drop_tags: tuple[str, ...] = ("script", "style", "svg", "button", "title", "meta")


def _split_br(el: Tag) -> list[str]:
    """Text của một phần tử, tách dòng tại <br>."""
    parts: list[str] = [""]
    for node in el.descendants:
        if isinstance(node, NavigableString):
            if not any(p.name in ("script", "style") for p in node.parents if isinstance(p, Tag)):
                parts[-1] += str(node)
        elif isinstance(node, Tag) and node.name == "br":
            parts.append("")
    return parts


def _is_leaf_block(el: Tag) -> bool:
    """<p>, hoặc ô bảng không chứa <p> (tránh lấy trùng)."""
    if el.name == "p":
        return el.find("p") is None
    return el.name in ("td", "th") and el.find(["p", "td", "th"]) is None


def extract_lines(html: str, cfg: HtmlParseConfig) -> list[SourceLine]:
    """Trích dòng theo thứ tự tài liệu. Bỏ phần giao diện (nút, icon), giữ nhãn chú thích."""
    soup = BeautifulSoup(html, "lxml")
    root = soup.select_one(cfg.container) or soup

    # Gắn nhãn cho mọi <p> trong khối chú thích, rồi bỏ phần giao diện
    annotated: dict[int, str] = {}
    for block in root.select(cfg.annotation_block):
        label_el = block.select_one(cfg.annotation_label)
        label = normalize_line(label_el.get_text(" ")) if label_el else ""
        if label not in cfg.annotation_labels:
            continue
        for p in block.find_all(["p", "td", "th"]):
            annotated[id(p)] = label
    for tag in root.find_all(list(cfg.drop_tags)):
        tag.decompose()

    lines: list[SourceLine] = []
    for el in root.find_all(["p", "td", "th"]):
        if not _is_leaf_block(el):
            continue
        label = annotated.get(id(el))
        for raw in _split_br(el):
            text = normalize_line(raw)
            if text:
                lines.append(SourceLine(text, label))
    return lines
