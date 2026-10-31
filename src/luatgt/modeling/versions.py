"""Dựng `provision_versions` (SCD Type 2) theo spec 6.3.

1. Version 1 của mọi Điều/Khoản/Điểm: text gốc, valid_from = ngày hiệu lực của văn bản gốc.
2. Amendment `ok` theo effective_date: đóng version hiện tại, mở version mới; bai_bo → text NULL.
   bo_sung tạo mục mới: version 1 bắt đầu từ ngày hiệu lực của văn bản sửa đổi.
3. Văn bản gốc het_hieu_luc có ngay_het_hieu_luc → đóng version cuối tại ngày đó.
4. Khoảng hiệu lực [valid_from, valid_to); truy vấn thời điểm X: valid_from <= X < valid_to.
5. Kết quả chỉ phụ thuộc đầu vào (không dùng ngày hôm nay) → chạy lại giống hệt.
6. Sửa cụm từ (origin = phrase) áp lên text đang có hiệu lực tại ngày đó, cho mục và các mục con (D-018).
"""

from __future__ import annotations

import itertools
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from luatgt.parsing.structure import doc_key

OPEN_END = date(9999, 12, 31)
VERSIONED_LEVELS = ("dieu", "khoan", "diem")


@dataclass(frozen=True)
class Version:
    provision_key: str
    version_no: int
    text: str | None
    source_vbpl_id: str
    valid_from: date
    valid_to: date
    is_current: bool
    level: str
    amendment_id: str | None  # None với version gốc


@dataclass(frozen=True)
class VersionIssue:
    rule: str
    severity: str  # error | warn
    provision_key: str
    detail: dict


@dataclass(frozen=True)
class _Event:
    when: date
    text: str | None
    source: str
    level: str
    amendment_id: str | None
    order: str  # sắp xếp ổn định khi cùng ngày
    phrase: bool = False  # sửa cụm từ nối tiếp bản trước, không phải thay thế nguyên văn


def build_versions(
    documents: list[dict], provisions: list[dict], amendments: list[dict]
) -> tuple[list[Version], list[VersionIssue]]:
    issues: list[VersionIssue] = []
    docs = {d["vbpl_id"]: d for d in documents}
    events: dict[str, list[_Event]] = defaultdict(list)
    end_of: dict[str, date] = {}

    for p in provisions:
        if p["level"] not in VERSIONED_LEVELS:
            continue
        doc = docs.get(p["vbpl_id"])
        start = doc.get("ngay_hieu_luc") if doc else None
        if start is None:
            issues.append(VersionIssue("missing_ngay_hieu_luc", "error", p["provision_key"],
                                       {"vbpl_id": p["vbpl_id"]}))
            continue
        events[p["provision_key"]].append(
            _Event(start, p["text"], p["vbpl_id"], p["level"], None, "0")
        )
        if doc.get("tinh_trang_norm") == "het_hieu_luc" and doc.get("ngay_het_hieu_luc"):
            end_of[p["provision_key"]] = doc["ngay_het_hieu_luc"]

    phrases = [a for a in amendments if a.get("phrase_op") and a["parse_status"] == "ok"]
    for a in amendments:
        if a["parse_status"] != "ok" or a["action"] not in ("sua_doi", "bo_sung", "bai_bo") or a.get("phrase_op"):
            continue
        if a["effective_date"] is None:
            issues.append(VersionIssue("amendment_without_date", "error", a["target_key"],
                                       {"amendment_id": a["amendment_id"]}))
            continue
        text = None if a["action"] == "bai_bo" else a["new_text"]
        level = a.get("level") or _level_of(a["target_key"])
        events[a["target_key"]].append(
            _Event(a["effective_date"], text, a["amending_vbpl_id"], level, a["amendment_id"],
                   "1" + a["amendment_id"])
        )

    issues += _apply_phrases(events, phrases)

    versions: list[Version] = []
    for key in sorted(events):
        evs = sorted(events[key], key=lambda e: (e.when, e.order))
        # Cùng ngày: bản sau cùng có hiệu lực (ghi cảnh báo để kiểm tra tay)
        merged: list[_Event] = []
        for e in evs:
            if merged and merged[-1].when == e.when:
                if not e.phrase:
                    issues.append(VersionIssue("same_day_events", "warn", key,
                                               {"date": str(e.when), "kept": e.amendment_id}))
                merged[-1] = e
            else:
                merged.append(e)
        if merged[0].amendment_id is not None and merged[0].text is None:
            issues.append(VersionIssue("repeal_without_base", "warn", key,
                                       {"amendment_id": merged[0].amendment_id}))
        end = end_of.get(key, OPEN_END)
        no = 0
        for i, e in enumerate(merged):
            valid_to = merged[i + 1].when if i + 1 < len(merged) else end
            if e.when >= valid_to:
                issues.append(VersionIssue("empty_validity", "warn", key,
                                           {"valid_from": str(e.when), "valid_to": str(valid_to)}))
                continue
            no += 1
            versions.append(Version(key, no, e.text, e.source, e.when, valid_to,
                                    valid_to == OPEN_END, e.level, e.amendment_id))
    issues += check_no_overlap(versions)
    return versions, issues


def _text_at(evs: list[_Event], when: date) -> str | None:
    """Text mới nhất có ngày <= when, gồm cả các sửa đổi cùng ngày đã áp."""
    last = None
    for e in sorted(evs, key=lambda e: (e.when, e.order)):
        if e.when <= when:
            last = e
    return last.text if last else None


def _phrase_pattern(phrase: str) -> re.Pattern:
    body = r"\s+".join(re.escape(w) for w in unicodedata.normalize("NFC", phrase).split())
    head = r"(?<!\w)" if phrase.strip()[0].isalnum() else ""
    tail = r"(?!\w)" if phrase.strip()[-1].isalnum() else ""
    return re.compile(head + body + tail)


def _joined(left: str, right: str) -> str:
    """Nối hai phần sau khi bỏ một cụm: một dấu cách, không có dấu cách trước dấu câu."""
    left, right = left.rstrip(" "), right.lstrip(" ")
    if not left or not right or right[0] in ",;.:)":
        return left + right
    return f"{left} {right}"


def apply_phrase(text: str, op: str, old: str, new: str | None) -> tuple[str, int]:
    """Áp một thao tác cụm từ. Trả (text mới, số lần khớp). Thao tác chèn cần đúng một lần khớp."""
    text = unicodedata.normalize("NFC", text)
    pat = _phrase_pattern(old)
    hits = list(pat.finditer(text))
    if not hits or (op.startswith("insert") and len(hits) > 1):
        return text, len(hits)
    if op == "replace":
        return pat.sub(lambda _: new or "", text), len(hits)
    if op == "remove":
        for m in reversed(hits):
            text = _joined(text[: m.start()], text[m.end():])
        return text, len(hits)
    m, added = hits[0], (new or "").strip()
    if op == "insert_after":
        sep = "" if added[0] in ",;.:" else " "
        return f"{text[: m.end()]}{sep}{added}{text[m.end():]}", 1
    return f"{text[: m.start()]}{added} {text[m.start():]}", 1


def _apply_phrases(events: dict[str, list[_Event]], phrases: list[dict]) -> list[VersionIssue]:
    """Áp sửa cụm từ theo ngày, tạo event mới. Không khớp hoặc mơ hồ → cảnh báo, giữ nguyên text.

    Cùng văn bản: chèn trước (mốc chèn là chữ cũ), rồi cụm dài trước cụm ngắn, để "Thay thế cụm A"
    không làm mất "Bỏ cụm A B" nêu ở chỗ khác trong cùng văn bản.
    """
    issues = []
    ordered = sorted(phrases, key=lambda a: (
        a["effective_date"], a["amending_vbpl_id"], not a["phrase_op"].startswith("insert"),
        -len(a["phrase_old"]), a["amendment_id"],
    ))
    for seq, a in enumerate(ordered):
        key, when = a["target_key"], a["effective_date"]
        scope = [key] if a.get("phrase_scope") == "own" else sorted(
            k for k in events if k == key or k.startswith(key + "/"))
        found = ambiguous = 0
        for k in scope:
            text = _text_at(events[k], when)
            if not text:
                continue
            new_text, hits = apply_phrase(text, a["phrase_op"], a["phrase_old"], a["new_text"])
            if hits and new_text != unicodedata.normalize("NFC", text):
                found += hits
                events[k].append(_Event(when, new_text, a["amending_vbpl_id"], events[k][0].level,
                                        a["amendment_id"], f"2{seq:06d}", phrase=True))
            elif hits:
                ambiguous += 1
        if ambiguous or not found:
            issues.append(VersionIssue(
                "phrase_ambiguous" if ambiguous else "phrase_not_found", "warn", key,
                {"amendment_id": a["amendment_id"], "phrase": a["phrase_old"], "op": a["phrase_op"]},
            ))
    return issues


def _level_of(key: str) -> str:
    last = key.rsplit("/", 1)[-1]
    return {"D": "dieu", "K": "khoan", "P": "diem"}.get(last[:1], "dieu")


def check_no_overlap(versions: list[Version]) -> list[VersionIssue]:
    """Spec 8.6: không có hai version chồng lấn thời gian cho cùng provision_key (mức error)."""
    issues = []
    by_key: dict[str, list[Version]] = defaultdict(list)
    for v in versions:
        by_key[v.provision_key].append(v)
    for key, vs in by_key.items():
        vs = sorted(vs, key=lambda v: v.valid_from)
        for a, b in itertools.pairwise(vs):
            if b.valid_from < a.valid_to:
                issues.append(VersionIssue("overlapping_versions", "error", key,
                                           {"a": a.version_no, "b": b.version_no}))
    return issues


def version_at(versions: list[Version], key: str, as_of: date) -> Version | None:
    """Version có hiệu lực tại thời điểm as_of (valid_from <= as_of < valid_to)."""
    for v in versions:
        if v.provision_key == key and v.valid_from <= as_of < v.valid_to:
            return v
    return None


def has_amending_title(doc: dict) -> bool:
    """Tên văn bản có nêu sửa đổi/bãi bỏ; gồm cả văn bản sửa nhiều văn bản (D-017)."""
    ten = (doc.get("ten_van_ban") or "").lower()
    return "sửa đổi" in ten or "bãi bỏ" in ten


def is_amending_document(doc: dict) -> str | None:
    """Số hiệu văn bản bị sửa nếu tên văn bản nêu đúng một đích, ngược lại None."""
    from luatgt.parsing.amendments import RE_TARGET_DOC

    ten = doc.get("ten_van_ban") or ""
    if not has_amending_title(doc):
        return None
    m = RE_TARGET_DOC.search(ten)
    if not m or doc_key(m.group(1)) == doc_key(doc.get("so_hieu") or ""):
        return None
    return m.group(1)
