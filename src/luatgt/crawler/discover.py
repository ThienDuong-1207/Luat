"""Tầng 1: Discover. Giai đoạn 1 chỉ có mode `seed` (spec 7.3)."""

from __future__ import annotations

from pathlib import Path

import yaml

from luatgt.common.logging import get_logger
from luatgt.crawler.context import CrawlContext

log = get_logger(__name__)


def load_seed_urls(path: Path) -> list[str]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return [d["url"] for d in data.get("documents", []) if d.get("url")]


def discover_seed(ctx: CrawlContext) -> int:
    """Đưa URL trong seed list vào crawl_queue(stage='detail'). Trả số dòng mới."""
    urls = load_seed_urls(ctx.settings.path(ctx.settings.paths.seed_documents))
    added = 0
    for url in urls:
        vbpl_id = ctx.source.vbpl_id_from_url(url)
        if vbpl_id is None:
            ctx.state.quarantine("crawl", url, "seed_url_without_id", {"url": url}, ctx.run_id)
            ctx.counters.errors += 1
            continue
        detail_url = ctx.source.tab_url(url, "fulltext")
        if ctx.state.enqueue(vbpl_id, "detail", detail_url):
            added += 1
    skipped_seeds = len(urls) - added
    log.info("discover_seed urls=%d new=%d already_queued=%d", len(urls), added, skipped_seeds)
    return added
