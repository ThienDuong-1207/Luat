"""Điều phối một run crawl: discover → detail → download. Bị chặn → dừng cả run (spec 7.2)."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

from luatgt.common.config import Settings
from luatgt.common.db import make_engine
from luatgt.common.logging import get_logger
from luatgt.common.storage import Storage
from luatgt.crawler.browser import BlockedError, BrowserSession
from luatgt.crawler.context import CrawlContext, Fetcher
from luatgt.crawler.detail import crawl_detail
from luatgt.crawler.discover import discover_seed
from luatgt.crawler.download import crawl_download
from luatgt.crawler.selectors import SourceConfig, load_source_config
from luatgt.crawler.state import CrawlState

log = get_logger(__name__)

BrowserFactory = Callable[[], AbstractAsyncContextManager[Fetcher]]

STAGES = {"detail": crawl_detail, "download": crawl_download}


async def run_crawl(
    settings: Settings,
    mode: str = "seed",
    limit: int | None = None,
    browser_factory: BrowserFactory | None = None,
    storage: Storage | None = None,
    state: CrawlState | None = None,
    source: SourceConfig | None = None,
    stages: tuple[str, ...] = tuple(STAGES),
) -> tuple[uuid.UUID, str]:
    """Chạy một run. Trả (run_id, status) với status ∈ success | partial | blocked | failed.

    `stages` cho phép Airflow chạy riêng detail và download.
    """
    source = source or load_source_config(settings.path(settings.paths.vbpl_source))
    state = state or CrawlState(make_engine(settings))
    storage = storage or Storage(settings)
    browser_factory = browser_factory or (lambda: BrowserSession(settings.crawler, source.base_url))

    run_id = state.start_run(source.selector_version)
    ctx = CrawlContext(settings, source, storage, state, run_id)
    status = "failed"
    try:
        if mode != "seed":
            raise NotImplementedError(f"Mode {mode!r} chưa có ở giai đoạn 1 (spec 7.3)")
        ctx.counters.discovered = discover_seed(ctx)

        work = {stage: state.pending(stage, limit) for stage in stages}
        if any(work.values()):
            async with browser_factory() as browser:
                for stage in stages:
                    fn = STAGES[stage]
                    # Lấy lại danh sách: detail có thể vừa thêm/requeue dòng download
                    for item in state.pending(stage, limit):
                        try:
                            await fn(item, browser, ctx)
                        except BlockedError:
                            raise
                        except Exception as e:
                            log.exception("item_failed stage=%s vbpl_id=%s", stage, item.vbpl_id)
                            state.mark(item.vbpl_id, stage, "failed", error=f"{type(e).__name__}: {e}")
                            ctx.counters.errors += 1
        else:
            log.info("nothing_pending run_id=%s", run_id)
        status = "success" if ctx.counters.errors == 0 else "partial"
    except BlockedError as e:
        # Không retry dồn dập: dừng toàn bộ, lần chạy theo lịch sau thử lại (dòng đang làm vẫn pending)
        status = "blocked"
        log.error("run_blocked run_id=%s reason=%s", run_id, e)
    finally:
        state.finish_run(run_id, status, ctx.counters)
        log.info(
            "run_finished run_id=%s status=%s discovered=%d detail_ok=%d pdf=%d errors=%d",
            run_id, status, ctx.counters.discovered, ctx.counters.detail_ok,
            ctx.counters.pdf_downloaded, ctx.counters.errors,
        )
    return run_id, status
