"""Đọc config/sources/vbpl.yaml và các tiện ích URL. Selector không viết cứng trong code."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import yaml
from pydantic import BaseModel, Field


class SearchConfig(BaseModel):
    url: str
    keyword_input: str
    submit_button_text: str
    result_item_title: str
    next_page: str = "TODO"


class AnnotationConfig(BaseModel):
    block: str
    label: str
    labels: list[str]


class SourceConfig(BaseModel):
    selector_version: str
    base_url: str
    detail_url_template: str
    id_regex: str
    tabs: dict[str, str]
    detail_tabs: list[str]
    download_extensions: list[str] = Field(default_factory=lambda: ["pdf"])
    tab_panel: str
    hash_unordered_list_tabs: list[str] = Field(default_factory=list)
    selectors: dict[str, str]
    fulltext_annotation: AnnotationConfig
    attribute_labels: dict[str, str]
    empty_values: list[str] = Field(default_factory=lambda: ["--", ""])
    tinh_trang_map: dict[str, str]
    relation_groups: dict[str, str | None]
    history_status: dict[str, str | None]
    so_hieu_in_text_regex: str
    so_hieu_regex: str
    search: SearchConfig
    date_format: str = "%d/%m/%Y"
    required_fields: list[str] = Field(default_factory=list)

    def sel(self, name: str) -> str:
        """Selector theo tên; báo lỗi rõ nếu thiếu hoặc còn TODO."""
        value = self.selectors.get(name)
        if not value or value == "TODO":
            raise KeyError(f"Selector {name!r} chưa cấu hình trong vbpl.yaml")
        return value

    def vbpl_id_from_url(self, url: str) -> str | None:
        """ID văn bản dạng chuỗi: số nguyên hoặc UUID (docs/DECISIONS.md D-008)."""
        m = re.search(self.id_regex, url)
        return m.group(1) if m else None

    def tab_url(self, url: str, tab_key_or_value: str) -> str:
        """Đổi tham số `tabs=` của URL chi tiết. Nhận khoá (fulltext) hoặc giá trị (toan-van)."""
        value = self.tabs.get(tab_key_or_value, tab_key_or_value)
        p = urlparse(url)
        q = parse_qs(p.query)
        q["tabs"] = [value]
        return urlunparse(p._replace(query=urlencode(q, doseq=True)))

    def todo_selectors(self) -> list[str]:
        return [k for k, v in self.selectors.items() if v == "TODO"]


def load_source_config(path: Path) -> SourceConfig:
    return SourceConfig.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
