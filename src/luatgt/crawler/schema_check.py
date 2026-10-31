"""Schema check sau khi trích metadata (spec mục 7.4 bước 4). Lỗi → quarantine, không ghi bản ghi."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from luatgt.crawler.extract import DocumentMeta, clean_text
from luatgt.crawler.selectors import SourceConfig


@dataclass
class CheckResult:
    errors: list[dict] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def add(self, rule: str, **detail) -> None:
        self.errors.append({"rule": rule, **detail})


def normalize_so_hieu(so_hieu: str) -> str:
    """Chuẩn hoá để so khớp: NFC, bỏ khoảng trắng, viết hoa."""
    return re.sub(r"\s+", "", clean_text(so_hieu)).upper()


def check_document(meta: DocumentMeta, fulltext_html: str | None, src: SourceConfig) -> CheckResult:
    res = CheckResult()
    values = {
        "so_hieu": meta.so_hieu,
        "ten_van_ban": meta.ten_van_ban,
        "ngay_ban_hanh": meta.ngay_ban_hanh,
        "fulltext_container": fulltext_html,
    }
    for f in src.required_fields:
        if not values.get(f):
            res.add("required_field_missing", field=f)
    for f, raw in meta.date_errors.items():
        res.add("invalid_date", field=f, value=raw)
    if meta.so_hieu and not re.match(src.so_hieu_regex, normalize_so_hieu(meta.so_hieu)):
        res.add("so_hieu_format", value=meta.so_hieu)
    if meta.ngay_ban_hanh and meta.ngay_hieu_luc and meta.ngay_hieu_luc < meta.ngay_ban_hanh:
        res.add("hieu_luc_before_ban_hanh", ban_hanh=str(meta.ngay_ban_hanh), hieu_luc=str(meta.ngay_hieu_luc))
    if meta.ngay_het_hieu_luc and meta.ngay_hieu_luc and meta.ngay_het_hieu_luc < meta.ngay_hieu_luc:
        res.add("het_hieu_luc_before_hieu_luc")
    return res
