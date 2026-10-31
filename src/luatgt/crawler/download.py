"""Tầng 3: Download. Tải file gốc (PDF) qua nút trên tab Tải về, kiểm tra, lưu Bronze (spec 7.5)."""

from __future__ import annotations

from datetime import UTC, datetime

import pymupdf
from sqlalchemy import text

from luatgt.common.config import CrawlerSettings
from luatgt.common.logging import get_logger
from luatgt.common.storage import sha256_bytes
from luatgt.crawler.context import CrawlContext, Fetcher
from luatgt.crawler.extract import extract_downloads
from luatgt.crawler.state import QueueItem

log = get_logger(__name__)


def validate_pdf(data: bytes, cfg: CrawlerSettings) -> tuple[list[str], bool | None]:
    """Kiểm tra file PDF. Trả (danh sách lỗi, has_text_layer)."""
    errors = []
    if not data.startswith(b"%PDF"):
        errors.append("not_pdf_magic")
    if len(data) <= cfg.min_file_bytes:
        errors.append("file_too_small")
    if errors:
        return errors, None
    try:
        with pymupdf.open(stream=data, filetype="pdf") as doc:
            if doc.page_count == 0:
                return ["pdf_no_pages"], None
            with_text = sum(
                1 for page in doc if len(page.get_text().strip()) >= cfg.text_layer_min_chars
            )
            return [], with_text / doc.page_count >= cfg.text_layer_min_ratio
    except Exception as e:  # noqa: BLE001 - mọi lỗi mở file đều là file hỏng
        return [f"pdf_unreadable:{type(e).__name__}"], None


def file_known(ctx: CrawlContext, sha: str, vbpl_id: str) -> bool:
    with ctx.state.engine.connect() as conn:
        return conn.execute(
            text("SELECT 1 FROM document_files WHERE sha256 = :s AND vbpl_id = :v"),
            {"s": sha, "v": vbpl_id},
        ).first() is not None


def record_file(
    ctx: CrawlContext, sha: str, vbpl_id: str, key: str, size: int, has_text_layer: bool | None
) -> None:
    with ctx.state.engine.begin() as conn:
        conn.execute(
            text("""INSERT INTO document_files
                      (sha256, vbpl_id, file_type, object_key, size_bytes, has_text_layer, downloaded_at)
                    VALUES (:s, :v, 'pdf', :k, :n, :t, :at)
                    ON CONFLICT (sha256, vbpl_id) DO NOTHING"""),
            {"s": sha, "v": vbpl_id, "k": key, "n": size, "t": has_text_layer,
             "at": datetime.now(UTC)},
        )


async def crawl_download(item: QueueItem, browser: Fetcher, ctx: CrawlContext) -> bool:
    """Xử lý một dòng crawl_queue(stage='download'): mọi file có đuôi cho phép của văn bản."""
    src = ctx.source
    vbpl_id = item.vbpl_id
    tab = src.tabs["download"]
    res = await browser.fetch(item.url, wait_selector=src.tab_panel.format(tab=tab))
    items = extract_downloads(res.html, src)
    wanted = [d for d in items if d.extension in src.download_extensions]
    ignored = [d.filename for d in items if d.extension not in src.download_extensions]
    if ignored:
        log.info("download_ignored vbpl_id=%s files=%s (D-010)", vbpl_id, ignored)
    if not wanted:
        ctx.state.mark(vbpl_id, "download", "skipped")
        return True

    button = f"{src.sel('download_panel')} {src.sel('download_item')} {src.sel('download_button')}"
    failed = False
    for d in wanted:
        filename, data = await browser.download(button, d.index)
        errors, has_text = validate_pdf(data, ctx.settings.crawler)
        if errors:
            for rule in errors:
                ctx.state.quarantine(
                    "crawl", vbpl_id, rule,
                    {"filename": filename, "listed_as": d.filename, "size": len(data)}, ctx.run_id,
                )
            failed = True
            continue
        sha = sha256_bytes(data)
        if file_known(ctx, sha, vbpl_id):
            ctx.counters.skipped += 1
            log.info("download_skipped_known vbpl_id=%s sha=%s", vbpl_id, sha[:12])
            continue
        key = f"pdf/{sha}.pdf"
        ctx.storage.put_bytes(ctx.bronze, key, data, "application/pdf")  # không ghi đè nếu đã có
        record_file(ctx, sha, vbpl_id, key, len(data), has_text)
        ctx.counters.pdf_downloaded += 1
        log.info(
            "download_saved vbpl_id=%s file=%s bytes=%d has_text_layer=%s",
            vbpl_id, filename, len(data), has_text,
        )

    if failed:
        ctx.state.mark(vbpl_id, "download", "failed", error="pdf_validation_failed")
        ctx.counters.errors += 1
        return False
    ctx.state.mark(vbpl_id, "download", "done")
    return True
