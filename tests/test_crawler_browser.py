"""Hàm thuần của crawler: phát hiện bị chặn, rate limit, URL/ID. Không mở trình duyệt."""

import asyncio
import time
from pathlib import Path

import pytest

from luatgt.common.config import load_settings
from luatgt.crawler.browser import RateLimiter, detect_block
from luatgt.crawler.selectors import load_source_config

FIX = Path(__file__).parent / "fixtures" / "vbpl"


@pytest.fixture(scope="module")
def src():
    return load_source_config(Path(__file__).parents[1] / "config" / "sources" / "vbpl.yaml")


@pytest.fixture(scope="module")
def markers():
    return load_settings(env={}).crawler.challenge_markers


def test_detect_block_on_real_403_page(markers):
    page = (FIX / "blocked_403.html").read_text(encoding="utf-8")
    assert detect_block(403, page, markers) == "http_403"
    # Cùng nội dung nhưng status 200 (vd CDN trả 200 kèm trang chặn) vẫn phải nhận ra
    assert detect_block(200, page, markers).startswith("marker:")


def test_detect_block_passes_normal_page(markers):
    page = (FIX / "23289__thuoc-tinh.html").read_text(encoding="utf-8")
    assert detect_block(200, page, markers) is None


def test_detect_block_429():
    assert detect_block(429, "", []) == "http_429"


def test_rate_limiter_waits_between_calls():
    async def run():
        rl = RateLimiter(0.2, 0.3)
        t0 = time.monotonic()
        await rl.wait()  # lần đầu không chờ
        t1 = time.monotonic()
        await rl.wait()
        return t1 - t0, time.monotonic() - t1

    first, second = asyncio.run(run())
    assert first < 0.1
    assert 0.19 <= second < 0.5


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://vbpl.vn/van-ban/chi-tiet/luat-giao-thong-duong-bo-so-26-2001-qh10--23289?tabs=toan-van", "23289"),
        ("https://vbpl.vn/van-ban/chi-tiet/nghi-dinh-so-168-2024-nd-cp--173920", "173920"),
        (
            "https://vbpl.vn/van-ban/chi-tiet/nghi-dinh-so-238--f4b0c320-79e6-11f1-8c8a-3587e086d762?tabs=toan-van",
            "f4b0c320-79e6-11f1-8c8a-3587e086d762",
        ),
        ("https://vbpl.vn/van-ban/trung-uong", None),
    ],
)
def test_vbpl_id_from_url(src, url, expected):
    assert src.vbpl_id_from_url(url) == expected


def test_tab_url_replaces_tabs_param(src):
    url = "https://vbpl.vn/van-ban/chi-tiet/x--23289?tabs=toan-van"
    assert src.tab_url(url, "attributes").endswith("--23289?tabs=thuoc-tinh")
    assert src.tab_url(url, "lich-su").endswith("?tabs=lich-su")
