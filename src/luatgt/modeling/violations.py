"""Trích xuất hành vi vi phạm từ các Điều xử phạt (spec 8.5).

Mức phạt ở câu dẫn Khoản, hành vi ở từng Điểm, phương tiện ở tiêu đề Điều hoặc câu dẫn, trừ điểm/tước GPLX
ở Khoản cuối Điều dẫn chiếu ngược lại. Câu dẫn và Điểm có thể đổi độc lập nên mỗi mốc phiên bản dựng lại cả
Điều rồi gộp các lát giống nhau (D-019).

Chế tài chỉ áp dụng khi có điều kiện ("trong trường hợp…") không gán vào cột, mà để ở
`attributes.che_tai_co_dieu_kien`, tránh báo trừ điểm cho người không thuộc trường hợp đó.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml

from luatgt.modeling.versions import OPEN_END, Version, VersionIssue
from luatgt.parsing.amendments import Ref, parse_refs
from luatgt.parsing.structure import doc_key

RE_FINE = re.compile(r"từ\s+([\d.]+)(?:\s+đồng)?\s+đến\s+([\d.]+)\s+đồng(?:\s+đối với\s+(cá nhân|tổ chức))?")
RE_FINE_HEAD = re.compile(r"^Phạt\s+(?:tiền|liền)\b")
RE_WARNING_HEAD = re.compile(r"^Phạt cảnh cáo\b")
RE_SEIZE_HEAD = re.compile(r"^Tịch thu phương tiện\b")
RE_EXTRA_HEAD = re.compile(r"^Ngoài việc\b")
RE_PER_PERSON = re.compile(r"trên mỗi người")
RE_TOTAL_CAP = re.compile(r"tối đa không vượt quá\s+([\d.]+)\s+đồng")
RE_WHO = re.compile(r"đối với\s+(?:chủ phương tiện là\s+)?(cá nhân|tổ chức)")
RE_SEIZE_INLINE = re.compile(r"^Tịch thu phương tiện\s+đối với\s+(.+)$", re.DOTALL)
RE_REF_START = re.compile(r"quy định (?:tại|lại)\s+")
RE_REF_END = re.compile(r"\s(?:(?:còn\s+)?bị|buộc|phải|trong trường hợp|mà|nếu)\s|\s*\((?:trường hợp|khi)\b")
# Động từ chế tài cụ thể: điều kiện có thể chứa "bị" thường ("bị tẩy xóa", "đã bị thay đổi")
RE_SANCTION = re.compile(r"(?:còn\s+)?bị\s+(?:áp dụng|trừ|tước|tịch thu|thu hồi|buộc|đình chỉ)\b|còn\s+bị\s|\bbuộc\s|\bphải\s")
RE_PAREN_CONDITION = re.compile(r"\(((?:trường hợp|khi)\b[^)]*)\)")
RE_POINTS = re.compile(r"trừ điểm giấy phép lái(?:\s+xe)?(?:\s*\([^)]*\))?\s+(\d+)\s+điểm")
RE_SUSPEND = re.compile(r"tước quyền sử dụng giấy phép l\w+ xe\s+từ\s+(\d+)\s+tháng\s+đến\s+(\d+)\s+tháng")
RE_EXCEPT = re.compile(r",?\s*trừ\s.*$", re.DOTALL)
SEIZE = "Tịch thu phương tiện"


@dataclass(frozen=True)
class Violation:
    violation_id: str
    provision_key: str
    version_no: int
    hanh_vi: str
    phuong_tien: tuple[str, ...]
    doi_tuong: str | None
    muc_phat_min: int | None
    muc_phat_max: int | None
    tru_diem_gplx: int | None
    tuoc_gplx_min_thang: int | None
    tuoc_gplx_max_thang: int | None
    bien_phap_bo_sung: tuple[str, ...]
    attributes: dict
    valid_from: date
    valid_to: date
    extraction_method: str
    confidence: float
    needs_review: bool


@dataclass
class ViolationConfig:
    sources: list[dict]
    phuong_tien: dict[str, re.Pattern]
    dieu_defaults: dict[str, list[str]]
    attributes: dict[str, dict[str, re.Pattern]]


def load_violation_config(path: Path) -> ViolationConfig:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return ViolationConfig(
        sources=data["sources"],
        phuong_tien={k: re.compile(v) for k, v in data["phuong_tien"].items()},
        dieu_defaults={str(k): v for k, v in data["dieu_defaults"].items()},
        attributes={d: {str(v): re.compile(rx) for v, rx in vals.items()}
                    for d, vals in data["attributes"].items()},
    )


@dataclass
class _Row:
    key: str
    version_no: int
    hanh_vi: str
    fine_min: int | None = None
    fine_max: int | None = None
    doi_tuong: str | None = None
    phuong_tien: tuple[str, ...] = ()
    attributes: dict = field(default_factory=dict)
    points: int | None = None
    suspend: tuple[int, int] | None = None
    measures: list[str] = field(default_factory=list)
    conditional: list[dict] = field(default_factory=list)
    review: bool = False


@dataclass(frozen=True)
class Sanction:
    refs: tuple[Ref, ...]
    condition: str | None
    points: int | None
    suspend: tuple[int, int] | None
    measures: tuple[str, ...]


def _money(s: str) -> int:
    return int(s.replace(".", ""))


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip(" ;.")


def _vehicles(text: str, cfg: ViolationConfig) -> tuple[str, ...]:
    return tuple(code for code, rx in cfg.phuong_tien.items() if rx.search(text))


def _attributes(text: str, cfg: ViolationConfig) -> dict:
    body = RE_EXCEPT.sub("", text)
    out = {}
    for dim, values in cfg.attributes.items():
        hit = [v for v, rx in values.items() if rx.search(body)]
        if hit:
            out[dim] = hit[-1]  # giá trị khai báo sau cụ thể hơn: "trên 35" sau "trên 20"
    return out


def parse_sanction(line: str) -> Sanction | None:
    """Câu "Thực hiện hành vi quy định tại <mục> [điều kiện] bị/buộc <chế tài>". None nếu không đúng mẫu."""
    start = RE_REF_START.search(line)
    if not start:
        return None
    rest = line[start.end():]
    end = RE_REF_END.search(rest)
    if not end:
        return None
    refs = tuple(parse_refs(rest[: end.start()]))
    tail = rest[end.start():].strip()
    verb = RE_SANCTION.search(tail)
    if not refs or not verb:
        return None
    cond = RE_PAREN_CONDITION.search(tail)
    condition = _clean(cond.group(1)) if cond else _clean(tail[: verb.start()]) or None

    points = RE_POINTS.search(tail)
    suspend = RE_SUSPEND.search(tail)
    measures: list[str] = []
    if not points and not suspend:
        measures.append(_clean(RE_PAREN_CONDITION.sub("", tail[verb.start():])))
    return Sanction(refs, condition, int(points.group(1)) if points else None,
                    (int(suspend.group(1)), int(suspend.group(2))) if suspend else None, tuple(measures))


def _children(keys: list[str], parent: str) -> list[str]:
    prefix = parent + "/P"
    return [k for k in keys if k.startswith(prefix) and "/" not in k[len(prefix):]]


def _fines(head: str) -> list[tuple[int, int, str | None, int | None]]:
    """(min, max, đối tượng, trần tổng) theo thứ tự xuất hiện trong câu dẫn."""
    found = list(RE_FINE.finditer(head))
    out = []
    for i, m in enumerate(found):
        rest = head[m.end(): found[i + 1].start() if i + 1 < len(found) else len(head)]
        cap = RE_TOTAL_CAP.search(rest)
        # "… trên mỗi người … không vượt quá 75.000.000 đồng đối với cá nhân": đối tượng đứng sau trần tổng
        who = m.group(3) or next(iter(RE_WHO.findall(rest)), None)
        out.append((_money(m.group(1)), _money(m.group(2)), who, _money(cap.group(1)) if cap else None))
    return out


CODE_WHO = {"cá nhân": "ca_nhan", "tổ chức": "to_chuc"}


class _Article:
    """Một Điều tại một thời điểm: text theo khoá của mọi mục còn hiệu lực."""

    def __init__(self, dkey: str, number: str, title: str, texts: dict[str, Version], cfg: ViolationConfig):
        self.dkey, self.number, self.title, self.cfg = dkey, number, title, cfg
        self.texts = texts
        self.keys = sorted(texts)
        self.root = f"{dkey}/D{number}"
        self.rows: list[_Row] = []
        self.issues: list[tuple[str, str, dict]] = []

    def text(self, key: str) -> str:
        return self.texts[key].text or ""

    def _vehicles_for(self, head: str, act: str) -> tuple[str, ...]:
        return (_vehicles(RE_FINE.sub("", head), self.cfg) or _vehicles(self.title, self.cfg)
                or _vehicles(act, self.cfg) or tuple(self.cfg.dieu_defaults.get(self.number, ())))

    def _add(self, key: str, act: str, head: str, **kw) -> None:
        attrs = _attributes(act, self.cfg)
        attrs.update(kw.pop("extra_attrs", {}))
        self.rows.append(_Row(key, self.texts[key].version_no, _clean(act),
                              phuong_tien=self._vehicles_for(head, act), attributes=attrs, **kw))

    def _penalty(self, key: str, head: str) -> None:
        kids = _children(self.keys, key)
        fines = _fines(head)
        if RE_WARNING_HEAD.match(head):
            for k in kids or [key]:
                self._add(k, self.text(k) if kids else head, head, measures=["Phạt cảnh cáo"],
                          doi_tuong=self._default_who(head))
            return
        if not fines:
            self.issues.append(("fine_not_parsed", key, {"text": head[:200]}))
            return
        # Khoản không có Điểm: hành vi là phần sau mức phạt cuối ("… đối với tổ chức thực hiện hành vi …")
        last = list(RE_FINE.finditer(head))[-1]
        inline = re.sub(r"^\s*(?:đối với\s+)?", "", head[last.end():])
        acts = [(k, self.text(k)) for k in kids] or [(key, inline or head)]
        ambiguous = len(fines) > 1 and any(w is None for _, _, w, _ in fines)
        for k, act in acts:
            for low, high, who, cap in fines:
                extra = {}
                if RE_PER_PERSON.search(head):
                    extra["tinh_theo"] = "moi_nguoi"
                    if cap:
                        extra["tong_muc_phat_toi_da"] = cap
                self._add(k, act, head, fine_min=low, fine_max=high, extra_attrs=extra, review=ambiguous,
                          doi_tuong=CODE_WHO.get(who) or self._default_who(head))

    def _default_who(self, head: str) -> str | None:
        return "ca_nhan" if "người" in head or "người điều khiển" in self.title or "người đi bộ" in self.title else None

    def _seizure(self, key: str, head: str) -> None:
        kids = _children(self.keys, key)
        inline = RE_SEIZE_INLINE.search(head)
        for k, act in [(k, self.text(k)) for k in kids] or [(key, inline.group(1) if inline else head)]:
            self._add(k, act, head, measures=[SEIZE], doi_tuong=self._default_who(head))

    def _extra(self, key: str, head: str) -> list[Sanction]:
        kids = _children(self.keys, key)
        out = []
        for k, line in [(k, self.text(k)) for k in kids] or [(key, head)]:
            s = parse_sanction(line)
            if s:
                out.append(s)
            else:
                self.issues.append(("sanction_not_parsed", k, {"text": line[:200]}))
        if kids and "quy định tại" in head and parse_sanction(head):
            out.append(parse_sanction(head))
        return out

    def extract(self) -> None:
        pat = re.compile(rf"^{re.escape(self.root)}/K[^/]+$")
        containers = [k for k in self.keys if pat.match(k)] or [self.root]
        sanctions: list[Sanction] = []
        for key in containers:
            head = self.text(key)
            if RE_FINE_HEAD.match(head) or RE_WARNING_HEAD.match(head):
                self._penalty(key, head)
            elif RE_SEIZE_HEAD.match(head):
                self._seizure(key, head)
            elif RE_EXTRA_HEAD.match(head):
                sanctions += self._extra(key, head)
            elif head:
                self.issues.append(("khoan_not_recognized", key, {"text": head[:200]}))
        for s in sanctions:
            self._attach(s)

    def _attach(self, s: Sanction) -> None:
        for ref in s.refs:
            full = Ref(ref.dieu or self.number, ref.khoan, ref.diem).key(self.dkey)
            rows = [r for r in self.rows if r.key == full or r.key.startswith(full + "/")]
            if not rows:
                self.issues.append(("sanction_target_missing", full,
                                    {"refs": [str(r) for r in s.refs][:6], "condition": s.condition}))
            for r in rows:
                if s.condition:
                    entry = {"dieu_kien": s.condition}
                    if s.points is not None:
                        entry["tru_diem_gplx"] = s.points
                    if s.suspend:
                        entry["tuoc_gplx_min_thang"], entry["tuoc_gplx_max_thang"] = s.suspend
                    if s.measures:
                        entry["bien_phap"] = list(s.measures)
                    r.conditional.append(entry)
                    continue
                if s.points is not None:
                    r.review = r.review or (r.points not in (None, s.points))
                    r.points = s.points
                if s.suspend:
                    r.review = r.review or (r.suspend not in (None, s.suspend))
                    r.suspend = s.suspend
                r.measures += [m for m in s.measures if m not in r.measures]


def _boundaries(versions: list[Version]) -> list[date]:
    return sorted({v.valid_from for v in versions})


def _at(versions: list[Version], when: date) -> dict[str, Version]:
    return {v.provision_key: v for v in versions
            if v.valid_from <= when < v.valid_to and v.text is not None}


def _payload(r: _Row) -> tuple:
    attrs = dict(r.attributes)
    if r.conditional:
        attrs["che_tai_co_dieu_kien"] = r.conditional
    return (r.key, r.version_no, r.hanh_vi, r.fine_min, r.fine_max, r.doi_tuong, r.phuong_tien, r.points, r.suspend,
            tuple(r.measures), repr(sorted(attrs.items(), key=str)), r.review)


def extract_violations(
    so_hieu: str, dieu_range: tuple[int, int], titles: dict[str, str], versions: list[Version], cfg: ViolationConfig,
) -> tuple[list[Violation], list[VersionIssue]]:
    """Dựng violations của một văn bản từ bảng phiên bản. `titles`: số Điều → tiêu đề."""
    dkey = doc_key(so_hieu)
    mine = [v for v in versions if v.provision_key.startswith(dkey + "/")]
    by_dieu: dict[str, list[Version]] = defaultdict(list)
    for v in mine:
        by_dieu[v.provision_key[len(dkey) + 2:].split("/")[0]].append(v)
    points = _boundaries(mine)

    spans: list[tuple[date, date, _Row]] = []
    issues: dict[tuple[str, str], dict] = {}
    for number, vs in by_dieu.items():
        digits = re.match(r"\d+", number)
        if not digits or not dieu_range[0] <= int(digits.group()) <= dieu_range[1]:
            continue
        for i, when in enumerate(points):
            art = _Article(dkey, number, titles.get(number, ""), _at(vs, when), cfg)
            if art.root not in art.texts and not art.keys:
                continue
            art.extract()
            end = points[i + 1] if i + 1 < len(points) else OPEN_END
            spans += [(when, end, r) for r in art.rows]
            issues.update({(rule, ref): detail for rule, ref, detail in art.issues})

    # Gộp lát liên tiếp giống hệt. Cá nhân/tổ chức cùng khoá là hai dòng riêng.
    merged: list[list] = []
    last: dict[tuple, list] = {}
    for start, end, row in sorted(spans, key=lambda s: (s[2].key, s[2].doi_tuong or "", s[0])):
        sig = _payload(row)
        prev = last.get(sig)
        if prev and prev[1] == start:
            prev[1] = end
        else:
            last[sig] = entry = [start, end, row]
            merged.append(entry)

    out: list[Violation] = []
    counter: dict[tuple[str, int], int] = defaultdict(int)
    for start, end, r in sorted(merged, key=lambda e: (e[2].key, e[2].version_no, e[0], e[2].doi_tuong or "")):
        counter[(r.key, r.version_no)] += 1
        attrs = dict(r.attributes)
        if r.conditional:
            attrs["che_tai_co_dieu_kien"] = r.conditional
        out.append(Violation(
            f"{r.key}@v{r.version_no}#{counter[(r.key, r.version_no)]}", r.key, r.version_no, r.hanh_vi,
            r.phuong_tien, r.doi_tuong, r.fine_min, r.fine_max, r.points,
            r.suspend[0] if r.suspend else None, r.suspend[1] if r.suspend else None,
            tuple(r.measures), attrs, start, end, "regex", 0.5 if r.review else 1.0, r.review,
        ))
    return out, [VersionIssue(rule, "warn", ref, detail) for (rule, ref), detail in sorted(issues.items())]

