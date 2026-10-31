"""Đối tượng dùng chung trong một run crawl + giao diện trình duyệt (để test thay bằng bản giả)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol

from bs4 import BeautifulSoup

from luatgt.common.config import Settings
from luatgt.common.storage import Storage, sha256_bytes
from luatgt.crawler.browser import PageResult
from luatgt.crawler.selectors import SourceConfig
from luatgt.crawler.state import CrawlState, RunCounters


class Fetcher(Protocol):
    """Phần của BrowserSession mà các tầng crawl dùng."""

    async def fetch(self, url: str, wait_selector: str | None = None) -> PageResult: ...

    async def download(self, button_selector: str, index: int) -> tuple[str, bytes]: ...


@dataclass
class CrawlContext:
    settings: Settings
    source: SourceConfig
    storage: Storage
    state: CrawlState
    run_id: uuid.UUID
    counters: RunCounters = field(default_factory=RunCounters)

    @property
    def bronze(self) -> str:
        return self.storage.bucket("bronze")


def utc_stamp(dt: datetime | None = None) -> str:
    """Thời điểm crawl dạng sắp xếp được theo tên: 20261023T075324Z."""
    return (dt or datetime.now(UTC)).astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def panel_html(html: str, source: SourceConfig, tab: str) -> str:
    """HTML panel của tab ('' nếu không có)."""
    el = BeautifulSoup(html, "lxml").select_one(source.tab_panel.format(tab=tab))
    return str(el) if el is not None else ""


def canonical_panel(html: str, source: SourceConfig, tab: str) -> str:
    """Dạng chuẩn của panel để hash: ổn định giữa các lần tải trang.

    Với tab trong `hash_unordered_list_tabs`, sắp xếp <li> trong từng <ul> vì trang trả thứ tự ngẫu nhiên.
    """
    el = BeautifulSoup(html, "lxml").select_one(source.tab_panel.format(tab=tab))
    if el is None:
        return ""
    unordered = {source.tabs[k] for k in source.hash_unordered_list_tabs}
    if tab in unordered:
        for ul in el.find_all("ul"):
            items = sorted((li.extract() for li in ul.find_all("li", recursive=False)), key=str)
            for li in items:
                ul.append(li)
    return str(el)


def panel_sha(html: str, source: SourceConfig, tab: str) -> str:
    return sha256_bytes(canonical_panel(html, source, tab).encode("utf-8"))
