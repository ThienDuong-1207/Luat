"""Data quality rules (spec 8.6). Mọi rule trả cảnh báo/lỗi để ghi quarantine, không bỏ bản ghi âm thầm."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import replace

from luatgt.modeling.versions import VersionIssue, check_no_overlap
from luatgt.parsing.violations import Violation

__all__ = ["check_amendment_targets", "check_dieu_sequence", "check_no_overlap", "check_violations", "summarize"]


def check_violations(
    violations: list[Violation], fine_min: int, fine_max: int
) -> tuple[list[Violation], list[VersionIssue]]:
    """min > max → loại khỏi bảng và quarantine; ngoài khoảng hợp lý hoặc thiếu phương tiện → needs_review."""
    kept, issues = [], []
    for v in violations:
        if v.muc_phat_min is not None and v.muc_phat_max is not None and v.muc_phat_min > v.muc_phat_max:
            issues.append(VersionIssue("fine_min_gt_max", "error", v.violation_id,
                                       {"min": v.muc_phat_min, "max": v.muc_phat_max}))
            continue
        problems = []
        for amount in (v.muc_phat_min, v.muc_phat_max):
            if amount is not None and not fine_min <= amount <= fine_max:
                problems.append(("fine_out_of_range", {"amount": amount}))
        if not v.phuong_tien:
            problems.append(("phuong_tien_empty", {}))
        issues += [VersionIssue(rule, "warn", v.violation_id, d) for rule, d in problems]
        kept.append(replace(v, needs_review=True) if problems else v)
    return kept, issues


def check_dieu_sequence(provisions: list[dict]) -> list[VersionIssue]:
    """Số Điều liên tục, không trùng theo từng văn bản (Điều chèn như 4a không tính vào dãy)."""
    by_doc: dict[str, list[str]] = defaultdict(list)
    for p in provisions:
        if p["level"] == "dieu":
            by_doc[p["vbpl_id"]].append(p["provision_key"].rsplit("/D", 1)[-1])
    issues = []
    for vid, numbers in by_doc.items():
        plain = [int(n) for n in numbers if re.fullmatch(r"\d+", n)]
        dupes = sorted(n for n, c in Counter(plain).items() if c > 1)
        gaps = sorted(set(range(min(plain), max(plain) + 1)) - set(plain)) if plain else []
        if dupes or gaps or any("~" in n for n in numbers):
            issues.append(VersionIssue("dieu_sequence", "error", vid, {"duplicates": dupes, "missing": gaps}))
    return issues


def check_amendment_targets(amendments: list[dict], provisions: list[dict]) -> tuple[list[dict], list[VersionIssue]]:
    """Amendment `ok` phải có target_key trong provisions hoặc do một bo_sung `ok` tạo ra; sai → needs_review."""
    known = {p["provision_key"] for p in provisions}
    known |= {a["target_key"] for a in amendments if a["action"] == "bo_sung" and a["parse_status"] == "ok"}
    out, issues = [], []
    for a in amendments:
        if a["parse_status"] == "ok" and a["target_key"] not in known:
            issues.append(VersionIssue("amendment_target_missing", "error", a["target_key"],
                                       {"amendment_id": a["amendment_id"]}))
            a = {**a, "parse_status": "needs_review", "review_reason": "target_key không có trong provisions"}
        out.append(a)
    return out, issues


def summarize(total: int, issues: list[VersionIssue]) -> dict:
    """Số bản ghi pass/warn/error của một lần chạy (spec 8.6)."""
    warn = sum(i.severity == "warn" for i in issues)
    error = sum(i.severity == "error" for i in issues)
    return {"total": total, "pass": max(total - warn - error, 0), "warn": warn, "error": error}
