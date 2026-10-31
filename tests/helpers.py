"""Dùng chung cho test crawler/parser: hằng số fixtures, PDF mẫu, trình duyệt giả, chạy crawl."""

from __future__ import annotations

import asyncio
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pymupdf

from luatgt.crawler.browser import BlockedError, FetchError, PageResult
from luatgt.crawler.run import run_crawl

ROOT = Path(__file__).parents[1]
FIX = ROOT / "tests" / "fixtures" / "vbpl"
ND168 = "173920"
ND238 = "f4b0c320-79e6-11f1-8c8a-3587e086d762"
LUAT26 = "23289"
SEED_URLS = {
    LUAT26: "https://vbpl.vn/van-ban/chi-tiet/luat-giao-thong-duong-bo-so-26-2001-qh10--23289?tabs=toan-van",
    ND168: "https://vbpl.vn/van-ban/chi-tiet/nghi-dinh-so-168-2024-nd-cp--173920?tabs=toan-van",
    ND238: f"https://vbpl.vn/van-ban/chi-tiet/nghi-dinh-so-238-2026-nd-cp--{ND238}?tabs=toan-van",
}
GOLD_TABLES = ["provisions", "amendments", "provision_versions"]
CRAWL_TABLES = ["crawl_runs", "crawl_queue", "documents", "document_files", "document_relations", "quarantine"]
TEST_DB = "luatgt_test"


def make_pdf(text_body: str = "Điều 1. Phạm vi điều chỉnh " * 10, pages: int = 2) -> bytes:
    doc = pymupdf.open()
    for _ in range(pages):
        doc.new_page().insert_text((72, 72), text_body[:200])
    return doc.tobytes()


SAMPLE_PDF = make_pdf()  # một bản duy nhất: tải lại cùng file phải ra cùng bytes


class FakeBrowser:
    """Thay BrowserSession: trả HTML fixtures theo (vbpl_id, tabs=…), tải về PDF tự sinh."""

    def __init__(self, source, *, block_on_call: int | None = None, fail_ids=(), mutate=None,
                 pdf: bytes | None = None):
        self.source = source
        self.calls: list[str] = []
        self.downloads: list[int] = []
        self.block_on_call = block_on_call
        self.fail_ids = set(fail_ids)
        self.mutate = mutate or {}
        self.pdf = pdf if pdf is not None else SAMPLE_PDF

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def fetch(self, url: str, wait_selector: str | None = None) -> PageResult:
        self.calls.append(url)
        if self.block_on_call is not None and len(self.calls) >= self.block_on_call:
            raise BlockedError(f"{url} bị chặn (http_403)")
        vbpl_id = self.source.vbpl_id_from_url(url)
        if vbpl_id in self.fail_ids:
            raise FetchError(f"{url}: net::ERR_TIMED_OUT")
        tab = parse_qs(urlparse(url).query)["tabs"][0]
        html = (FIX / f"{vbpl_id}__{tab}.html").read_text(encoding="utf-8")
        for (mid, mtab), fn in self.mutate.items():
            if (mid, mtab) == (vbpl_id, tab):
                html = fn(html)
        return PageResult(url=url, status=200, html=html, fetched_at=None)

    async def download(self, button_selector: str, index: int) -> tuple[str, bytes]:
        self.downloads.append(index)
        return "file.pdf", self.pdf


def run(ctx, browser):
    s, _, storage, state, source = ctx
    return asyncio.run(run_crawl(s, browser_factory=lambda: browser, storage=storage,
                                 state=state, source=source))

