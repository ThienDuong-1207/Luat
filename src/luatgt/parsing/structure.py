"""Tách cấu trúc Phần/Chương/Mục/Điều/Khoản/Điểm từ danh sách dòng (spec 8.3).

Regex theo dòng, xét theo thứ tự ưu tiên. Mở rộng so với spec (docs/DECISIONS.md D-013):
- Khoản/Điều có hậu tố chữ ("1a.", "Điều 4a.") do văn bản sửa đổi bổ sung vào.
- Điểm được phép nằm thẳng dưới Điều khi Điều không có Khoản.
- Nội dung trong ngoặc kép của văn bản sửa đổi (kể cả nhiều dòng, hoặc thiếu dấu mở ngoặc ngay sau câu
  "... như sau:") KHÔNG được tách thành Điều/Khoản của chính văn bản: giữ nguyên khối cho amendments.py.
- Phần đuôi (Nơi nhận, chữ ký) tách riêng, không dính vào Điều cuối.
"""

from __future__ import annotations

import itertools
import re
import unicodedata
from dataclasses import dataclass, field

from luatgt.parsing.html_fulltext import SourceLine

LEVELS = ("phan", "chuong", "muc", "dieu", "khoan", "diem")
DIEM_ORDER = ["a", "b", "c", "d", "đ", "e", "g", "h", "i", "k", "l", "m", "n", "o", "p", "q", "r", "s", "t", "u", "v", "x", "y"]

# "Phần thứ nhất" / "PHẦN I". Không khớp câu thường như "Phần đường xe chạy là…"
RE_PHAN = re.compile(r"^(?:Phần|PHẦN)\s+(?:(?:thứ|THỨ)\s+([^\s.:]+)|([IVXLC]+)\b)\.?\s*(.*)$")
RE_CHUONG = re.compile(r"^Chương\s+([IVXLC]+)\b\.?\s*(.*)$", re.IGNORECASE)
RE_MUC = re.compile(r"^Mục\s+(\d+)\b\.?\s*(.*)$", re.IGNORECASE)
RE_DIEU = re.compile(r"^Điều\s+(\d+[a-z]?)\.\s*(.*)$")
RE_KHOAN = re.compile(r"^(\d+[a-z]?)\.\s+(.*)$")
# Điểm có thể có hậu tố số do văn bản sửa đổi bổ sung ("k1)" — NĐ 238 Điều 12)
RE_DIEM = re.compile(r"^([a-zđ]\d?)\)\s+(.*)$")

OPEN_QUOTES = ('"', "“", "„")
RE_CLOSES_QUOTE = re.compile(r"[\"”]\s*[.;,:]?\s*$")
# Câu chỉ dẫn sửa đổi kết thúc bằng "như sau:" → các dòng sau là nội dung mới (kể cả khi thiếu ngoặc kép)
RE_INSTRUCTION_INTRO = re.compile(
    r"^(?:(?:\d+[a-z]?\.|[a-zđ]\))\s+)?(?:Sửa đổi|Bổ sung|Thay thế|Thay)\b.*như sau:\s*$", re.IGNORECASE
)
# Dòng chỉ dẫn sửa đổi mới → kết thúc khối nội dung thiếu ngoặc
RE_NEXT_INSTRUCTION = re.compile(
    r"^(?:(?:\d+[a-z]?\.|[a-zđ]\))\s+)?(?:Sửa đổi|Bổ sung|Bãi bỏ|Thay thế|Thay|Bỏ)\b", re.IGNORECASE
)
RE_TRAILER = re.compile(
    r"^(Nơi nhận\s*:|TM\.\s|KT\.\s|Luật này đã được Quốc hội|Nghị quyết này đã được Quốc hội)", re.IGNORECASE
)


@dataclass
class Node:
    level: str
    number: str
    title: str | None = None
    lines: list[str] = field(default_factory=list)
    children: list[Node] = field(default_factory=list)
    parent: Node | None = field(default=None, repr=False)
    ordinal: int = 0
    line_no: int = 0
    annotations: list[str] = field(default_factory=list)
    has_quoted_content: bool = False
    key: str = ""
    number_raw: str | None = None  # số gốc trên trang nếu đã sửa nhầm lẫn d/đ

    @property
    def text(self) -> str:
        return "\n".join(self.lines)

    def walk(self):
        yield self
        for c in self.children:
            yield from c.walk()


@dataclass
class ParseIssue:
    rule: str
    provision_key: str
    detail: dict


@dataclass
class ParsedDocument:
    doc_key: str
    preamble: list[str]
    roots: list[Node]
    trailer: list[str]
    issues: list[ParseIssue]

    def nodes(self) -> list[Node]:
        return [n for r in self.roots for n in r.walk()]


def strip_diacritics(s: str) -> str:
    s = s.replace("đ", "d").replace("Đ", "D")
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def doc_key(so_hieu: str) -> str:
    """Khoá văn bản trong provision_key: bỏ dấu, '/' → '-' (spec 6.3). 168/2024/NĐ-CP → 168-2024-ND-CP."""
    return strip_diacritics(so_hieu).replace("/", "-").replace(" ", "")


def _key_part(node: Node) -> str:
    n = node.number
    if node.level == "diem":
        return "P" + ("dd" if n == "đ" else n)  # spec: điểm "đ" ghi là Pdd
    return {"phan": "PH", "chuong": "C", "muc": "M", "dieu": "D", "khoan": "K"}[node.level] + n


def fix_d_dd_confusion(roots: list[Node]) -> list[ParseIssue]:
    """Sửa nhầm lẫn "d)"/"đ)" phổ biến trên vbpl.vn (vd NĐ 168 Điều 16 khoản 2: "c) đ) đ)").

    Chỉ sửa khi vị trí mong đợi là chữ còn lại của cặp d/đ. Mọi trường hợp sửa đều ghi issue để kiểm tra tay.
    """
    issues: list[ParseIssue] = []
    for root in roots:
        for parent in root.walk():
            diem = [c for c in parent.children if c.level == "diem"]
            for pos, node in enumerate(diem):
                expected = DIEM_ORDER[pos] if pos < len(DIEM_ORDER) else None
                if {node.number, expected} == {"d", "đ"}:
                    issues.append(ParseIssue("diem_relabeled", "", {
                        "parent_line": parent.line_no, "from": node.number, "to": expected,
                        "line_no": node.line_no,
                    }))
                    node.number_raw, node.number = node.number, expected
    return issues


def finalize_keys(roots: list[Node], dkey: str) -> None:
    """Gán provision_key theo spec 6.3. Khoá trùng (lỗi nguồn) thêm hậu tố "~2", "~3"… để không mất dòng."""
    seen: dict[str, int] = {}
    for root in roots:
        for node in root.walk():
            # Điều đánh số liên tục trong toàn văn bản → khoá Điều không kèm Chương/Mục
            base = dkey if node.level == "dieu" or node.parent is None else node.parent.key
            key = f"{base}/{_key_part(node)}"
            seen[key] = seen.get(key, 0) + 1
            node.key = key if seen[key] == 1 else f"{key}~{seen[key]}"


class _Builder:
    def __init__(self, dkey: str) -> None:
        self.dkey = dkey
        self.roots: list[Node] = []
        self.preamble: list[str] = []
        self.trailer: list[str] = []
        self.current: dict[str, Node | None] = dict.fromkeys(LEVELS)
        self.ordinal = 0
        self.awaiting_title: Node | None = None

    def deepest(self) -> Node | None:
        for lv in reversed(LEVELS):
            if self.current[lv] is not None:
                return self.current[lv]
        return None

    def open(self, level: str, number: str, first_text: str, line_no: int, annotation: str | None) -> Node:
        idx = LEVELS.index(level)
        parent = None
        for lv in reversed(LEVELS[:idx]):
            if self.current[lv] is not None:
                parent = self.current[lv]
                break
        node = Node(level=level, number=number, parent=parent, ordinal=self.ordinal, line_no=line_no)
        self.ordinal += 1
        if level in ("phan", "chuong", "muc", "dieu"):
            node.title = first_text or None
        elif first_text:
            node.lines.append(first_text)
        if annotation:
            node.annotations.append(annotation)
        (parent.children if parent else self.roots).append(node)
        self.current[level] = node
        for lv in LEVELS[idx + 1 :]:
            self.current[lv] = None
        # Chương/Mục/Phần: tiêu đề thường ở dòng kế tiếp ("Chương I" / "NHỮNG QUY ĐỊNH CHUNG")
        self.awaiting_title = node if level in ("phan", "chuong", "muc") and not first_text else None
        return node

    def append(self, text: str, annotation: str | None, quoted: bool = False) -> None:
        node = self.deepest()
        if node is None:  # trước Chương/Điều đầu tiên: phần mở đầu (quốc hiệu, căn cứ…)
            self.preamble.append(text)
            return
        if self.awaiting_title is node:
            node.title = text
            self.awaiting_title = None
            return
        node.lines.append(text)
        if annotation and annotation not in node.annotations:
            node.annotations.append(annotation)
        if quoted:
            node.has_quoted_content = True


def parse_structure(lines: list[SourceLine], so_hieu: str) -> ParsedDocument:
    """Dòng (đã chuẩn hoá) → cây điều khoản + danh sách vấn đề cần kiểm tra."""
    b = _Builder(doc_key(so_hieu))
    in_quote = False  # đang trong khối ngoặc kép nhiều dòng
    in_unquoted_content = False  # sau "... như sau:" mà dòng nội dung thiếu ngoặc kép
    in_trailer = False

    for i, line in enumerate(lines):
        text, ann = line.text, line.annotation

        if in_trailer:
            b.trailer.append(text)
            continue

        if in_quote:
            b.append(text, ann, quoted=True)
            if RE_CLOSES_QUOTE.search(text):
                in_quote = False
            continue

        if in_unquoted_content:
            if RE_DIEU.match(text) or RE_CHUONG.match(text) or RE_NEXT_INSTRUCTION.match(text) \
                    or text.startswith(OPEN_QUOTES):
                in_unquoted_content = False  # rơi xuống xử lý bình thường bên dưới
            else:
                b.append(text, ann, quoted=True)
                continue

        if text.startswith(OPEN_QUOTES):
            b.append(text, ann, quoted=True)
            # Mở và đóng trên cùng dòng → một dòng; ngược lại khối kéo dài tới dòng có ngoặc đóng
            body = text[1:]
            in_quote = not RE_CLOSES_QUOTE.search(body)
            continue

        if b.current["dieu"] is not None and RE_TRAILER.match(text):
            in_trailer = True
            b.trailer.append(text)
            continue

        if m := RE_PHAN.match(text):
            b.open("phan", strip_diacritics(m.group(1) or m.group(2)).upper(), m.group(3).strip(), i, ann)
            continue
        if m := RE_CHUONG.match(text):
            b.open("chuong", m.group(1).upper(), m.group(2).strip(), i, ann)
            continue
        if m := RE_MUC.match(text):
            b.open("muc", m.group(1), m.group(2).strip(), i, ann)
            continue
        if m := RE_DIEU.match(text):
            b.open("dieu", m.group(1), m.group(2).strip(), i, ann)
            in_unquoted_content = bool(RE_INSTRUCTION_INTRO.match(m.group(2)))
            continue
        if b.current["dieu"] is not None and (m := RE_KHOAN.match(text)):
            b.open("khoan", m.group(1), m.group(2).strip(), i, ann)
            in_unquoted_content = bool(RE_INSTRUCTION_INTRO.match(text))
            continue
        if b.current["dieu"] is not None and (m := RE_DIEM.match(text)):
            b.open("diem", m.group(1), m.group(2).strip(), i, ann)
            in_unquoted_content = bool(RE_INSTRUCTION_INTRO.match(text))
            continue

        b.append(text, ann)
        in_unquoted_content = bool(RE_INSTRUCTION_INTRO.match(text))

    relabel = fix_d_dd_confusion(b.roots)
    finalize_keys(b.roots, b.dkey)
    doc = ParsedDocument(b.dkey, b.preamble, b.roots, b.trailer, [])
    by_line = {n.line_no: n for n in doc.nodes()}
    for iss in relabel:
        iss.provision_key = by_line[iss.detail["line_no"]].key
    doc.issues = relabel + validate(doc)
    return doc


def _num(n: str) -> tuple[int, str]:
    m = re.match(r"(\d+)([a-z]?)", n)
    return (int(m.group(1)), m.group(2)) if m else (-1, n)


def _check_sequence(nums: list[str], start: int = 1) -> list[tuple[str | None, str]]:
    """Số liên tục từ `start`; hậu tố chữ (4a) chỉ hợp lệ ngay sau số gốc. Trả các cặp (trước, sau) sai."""
    bad = []
    prev: tuple[int, str] | None = None
    for raw in nums:
        cur = _num(raw)
        if prev is None:
            ok = cur == (start, "")
        elif cur[1]:  # có hậu tố: cùng số gốc với số trước, hậu tố tăng
            ok = cur[0] == prev[0] and cur[1] > prev[1]
        else:
            ok = cur[0] == prev[0] + 1
        if not ok:
            bad.append((None if prev is None else f"{prev[0]}{prev[1]}", raw))
        prev = cur
    return bad


def validate(doc: ParsedDocument) -> list[ParseIssue]:
    """Spec 8.3: Điều liên tục; Khoản trong Điều bắt đầu từ 1; Điểm theo thứ tự a, b, c, d, đ, e…; không trùng khoá."""
    issues: list[ParseIssue] = []
    nodes = doc.nodes()

    dieu = [n for n in nodes if n.level == "dieu"]
    for prev, cur in _check_sequence([n.number for n in dieu]):
        issues.append(ParseIssue("dieu_not_consecutive", f"{doc.doc_key}/D{cur}", {"prev": prev, "cur": cur}))

    for d in dieu:
        khoan = [c for c in d.children if c.level == "khoan"]
        for prev, cur in _check_sequence([k.number for k in khoan]):
            issues.append(ParseIssue("khoan_not_consecutive", d.key, {"prev": prev, "cur": cur}))

    for parent in nodes:
        # Điểm có hậu tố số ("k1") là điểm được chèn thêm: không tính vào thứ tự a, b, c…
        diem = [c.number for c in parent.children if c.level == "diem" and c.number[-1:].isalpha()]
        if not diem:
            continue
        idx = [DIEM_ORDER.index(x) if x in DIEM_ORDER else -1 for x in diem]
        if idx[0] != 0 or any(b != a + 1 for a, b in itertools.pairwise(idx)):
            issues.append(ParseIssue("diem_out_of_order", parent.key, {"diem": diem}))

    for n in nodes:
        if "~" in n.key:
            issues.append(ParseIssue("duplicate_key", n.key, {"base": n.key.split("~")[0]}))

    for n in nodes:
        if n.level in ("khoan", "diem") and not n.text.strip():
            issues.append(ParseIssue("empty_text", n.key, {}))
    return issues
