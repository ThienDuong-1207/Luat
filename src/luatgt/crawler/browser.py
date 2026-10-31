"""Quản lý Playwright: 1 context, 1 trang, rate limit, robots.txt, phát hiện bị chặn, retry.

Không có cơ chế vượt bot detection (không đổi User-Agent, không proxy, không giải CAPTCHA).
Khi bị chặn, ném `BlockedError` để run dừng hẳn (spec mục 7.2).
"""

from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Self
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright
from playwright.async_api import Error as PlaywrightError

from luatgt.common.config import CrawlerSettings
from luatgt.common.logging import get_logger

log = get_logger(__name__)

BLOCK_STATUSES = {403, 429}


class BlockedError(RuntimeError):
    """Trang trả về dấu hiệu bị chặn. Run phải dừng, không retry dồn dập."""


class RobotsDisallowedError(RuntimeError):
    """robots.txt không cho phép đường dẫn này."""


class FetchError(RuntimeError):
    """Lỗi mạng/timeout sau khi đã retry đủ số lần."""


@dataclass(frozen=True)
class PageResult:
    url: str
    status: int | None
    html: str
    fetched_at: datetime


def detect_block(status: int | None, html: str, markers: list[str]) -> str | None:
    """Trả lý do bị chặn, hoặc None nếu trang bình thường."""
    if status in BLOCK_STATUSES:
        return f"http_{status}"
    for m in markers:
        if m and m in html:
            return f"marker:{m}"
    return None


class RateLimiter:
    """Đảm bảo khoảng nghỉ ngẫu nhiên [min_s, max_s] giữa hai lần tải trang."""

    def __init__(self, min_s: float, max_s: float) -> None:
        self.min_s, self.max_s = min_s, max(min_s, max_s)
        self._last: float | None = None

    async def wait(self) -> None:
        if self._last is not None:
            target = random.uniform(self.min_s, self.max_s)
            remaining = target - (time.monotonic() - self._last)
            if remaining > 0:
                await asyncio.sleep(remaining)
        self._last = time.monotonic()


class BrowserSession:
    """Dùng: `async with BrowserSession(cfg) as b: res = await b.fetch(url)`."""

    def __init__(self, cfg: CrawlerSettings, base_url: str) -> None:
        self.cfg = cfg
        self.base_url = base_url
        self.limiter = RateLimiter(cfg.min_delay_s, cfg.max_delay_s)
        self._pw: Playwright | None = None
        self._browser: Browser | None = None
        self._ctx: BrowserContext | None = None
        self.page: Page | None = None
        self._robots: RobotFileParser | None = None

    async def __aenter__(self) -> Self:
        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(headless=self.cfg.headless)
        headers = {}
        if self.cfg.contact_header and ":" in self.cfg.contact_header:
            k, v = self.cfg.contact_header.split(":", 1)
            headers[k.strip()] = v.strip()
        self._ctx = await self._browser.new_context(locale="vi-VN", extra_http_headers=headers)
        self.page = await self._ctx.new_page()
        if self.cfg.respect_robots_txt:
            await self._load_robots()
        return self

    async def __aexit__(self, *exc) -> None:
        if self._browser:
            await self._browser.close()
        if self._pw:
            await self._pw.stop()

    async def _load_robots(self) -> None:
        url = urljoin(self.base_url, "/robots.txt")
        res = await self._goto(url)
        reason = detect_block(res.status, res.html, self.cfg.challenge_markers)
        if reason:
            raise BlockedError(f"robots.txt bị chặn ({reason})")
        body = await self.page.inner_text("body")
        rp = RobotFileParser()
        rp.parse(body.splitlines())
        self._robots = rp
        log.info("robots_loaded url=%s", url)

    def allowed(self, url: str) -> bool:
        if self._robots is None:
            return True
        return self._robots.can_fetch("*", url)

    async def _goto(self, url: str) -> PageResult:
        await self.limiter.wait()
        resp = await self.page.goto(
            url, timeout=self.cfg.page_timeout_s * 1000, wait_until="domcontentloaded"
        )
        try:
            await self.page.wait_for_load_state(
                "networkidle", timeout=self.cfg.page_timeout_s * 1000
            )
        except PlaywrightError:
            log.warning("networkidle_timeout url=%s", url)
        await self._decline_consent()
        return PageResult(
            url=self.page.url,
            status=resp.status if resp else None,
            html=await self.page.content(),
            fetched_at=datetime.now(UTC),
        )

    async def _decline_consent(self) -> None:
        """Banner cookie che thao tác bấm: chọn "Từ chối" cookie không thiết yếu (nếu có)."""
        text = self.cfg.consent_decline_text
        if not text:
            return
        btn = self.page.get_by_role("button", name=text, exact=True)
        try:
            if await btn.count() and await btn.first.is_visible():
                await btn.first.click(timeout=5000)
                log.info("consent_declined")
        except PlaywrightError as e:
            log.warning("consent_decline_failed err=%s", e)

    async def fetch(self, url: str, wait_selector: str | None = None) -> PageResult:
        """Tải trang với retry lỗi mạng. Bị chặn → BlockedError ngay, không retry."""
        if urlparse(url).netloc != urlparse(self.base_url).netloc:
            raise ValueError(f"URL ngoài nguồn cấu hình: {url}")
        if not self.allowed(url):
            raise RobotsDisallowedError(url)

        backoffs = list(self.cfg.retry_backoff_s)[: self.cfg.max_retries]
        attempt = 0
        while True:
            try:
                res = await self._goto(url)
                reason = detect_block(res.status, res.html, self.cfg.challenge_markers)
                if reason:
                    raise BlockedError(f"{url} bị chặn ({reason})")
                if wait_selector:
                    try:
                        await self.page.wait_for_selector(
                            wait_selector, timeout=self.cfg.page_timeout_s * 1000
                        )
                    except PlaywrightError as e:
                        # Không thấy selector chính: coi như bị chặn/đổi giao diện, dừng run.
                        raise BlockedError(f"{url} thiếu selector chính {wait_selector!r}") from e
                    res = PageResult(res.url, res.status, await self.page.content(), res.fetched_at)
                return res
            except BlockedError:
                raise
            except PlaywrightError as e:
                if attempt >= len(backoffs):
                    raise FetchError(f"{url}: {e}") from e
                delay = backoffs[attempt]
                attempt += 1
                log.warning("fetch_retry url=%s attempt=%d delay_s=%s err=%s", url, attempt, delay, e)
                await asyncio.sleep(delay)

    async def download(self, button_selector: str, index: int) -> tuple[str, bytes]:
        """Bấm nút tải thứ `index` trên trang hiện tại (đã fetch tab Tải về), trả (tên file, bytes).

        Tab Tải về không có link trực tiếp nên phải bấm nút (spec 7.5: page.expect_download()).
        """
        await self.limiter.wait()
        button = self.page.locator(button_selector).nth(index)
        async with self.page.expect_download(timeout=self.cfg.download_timeout_s * 1000) as info:
            await button.click()
        dl = await info.value
        failure = await dl.failure()
        if failure:
            raise FetchError(f"Tải file thất bại: {failure}")
        path = await dl.path()
        data = await asyncio.to_thread(path.read_bytes)
        return dl.suggested_filename, data

    async def screenshot(self, path: str) -> None:
        await self.page.screenshot(path=path, full_page=True)
