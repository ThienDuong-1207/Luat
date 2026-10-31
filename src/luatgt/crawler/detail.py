"""Tầng 2: Detail. Tải các tab, lưu Bronze, trích metadata + quan hệ, upsert Postgres (spec 7.4)."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime

from sqlalchemy import text

from luatgt.common.logging import get_logger
from luatgt.common.storage import sha256_bytes
from luatgt.crawler.context import CrawlContext, Fetcher, panel_sha, utc_stamp
from luatgt.crawler.extract import (
    DocumentMeta,
    Relation,
    extract_attributes,
    extract_downloads,
    extract_fulltext_html,
    extract_history,
    extract_related,
    merge_relations,
    relations_from_history,
)
from luatgt.crawler.schema_check import check_document
from luatgt.crawler.state import QueueItem

log = get_logger(__name__)


def _latest_sha(ctx: CrawlContext, prefix: str) -> str | None:
    """sha trong tên bản Bronze gần nhất: …/{crawled_at}__{sha}.html."""
    keys = ctx.storage.list_keys(ctx.bronze, prefix)
    if not keys:
        return None
    return keys[-1].rsplit("__", 1)[-1].removesuffix(".html")


def save_tab_html(ctx: CrawlContext, vbpl_id: str, tab: str, html: str, stamp: str) -> tuple[str, str | None]:
    """Lưu HTML gốc (cả trang) vào Bronze nếu panel khác bản gần nhất. Trả (panel_sha, key|None)."""
    sha = panel_sha(html, ctx.source, tab)
    prefix = f"html/{vbpl_id}/{tab}/"
    if _latest_sha(ctx, prefix) == sha:
        return sha, None
    key = f"{prefix}{stamp}__{sha}.html"
    ctx.storage.put_bytes(ctx.bronze, key, html.encode("utf-8"), "text/html; charset=utf-8")
    return sha, key


UPSERT_DOCUMENT = text("""
INSERT INTO documents (vbpl_id, so_hieu, ten_van_ban, loai_van_ban, co_quan_ban_hanh, nguoi_ky,
    ngay_ban_hanh, ngay_hieu_luc, ngay_het_hieu_luc, tinh_trang, tinh_trang_norm, source_url,
    needs_reparse, first_seen_at, last_crawled_at)
VALUES (:vbpl_id, :so_hieu, :ten_van_ban, :loai_van_ban, :co_quan_ban_hanh, :nguoi_ky,
    :ngay_ban_hanh, :ngay_hieu_luc, :ngay_het_hieu_luc, :tinh_trang, :tinh_trang_norm, :source_url,
    :needs_reparse, :crawled_at, :crawled_at)
ON CONFLICT (vbpl_id) DO UPDATE SET
    so_hieu = EXCLUDED.so_hieu, ten_van_ban = EXCLUDED.ten_van_ban,
    loai_van_ban = EXCLUDED.loai_van_ban, co_quan_ban_hanh = EXCLUDED.co_quan_ban_hanh,
    nguoi_ky = EXCLUDED.nguoi_ky, ngay_ban_hanh = EXCLUDED.ngay_ban_hanh,
    ngay_hieu_luc = EXCLUDED.ngay_hieu_luc, ngay_het_hieu_luc = EXCLUDED.ngay_het_hieu_luc,
    tinh_trang = EXCLUDED.tinh_trang, tinh_trang_norm = EXCLUDED.tinh_trang_norm,
    source_url = EXCLUDED.source_url,
    needs_reparse = documents.needs_reparse OR EXCLUDED.needs_reparse,
    last_crawled_at = EXCLUDED.last_crawled_at
""")

UPSERT_RELATION = text("""
INSERT INTO document_relations (src_vbpl_id, dst_vbpl_id, dst_so_hieu, relation_type, origin)
VALUES (:src_vbpl_id, :dst_vbpl_id, :dst_so_hieu, :relation_type, :origin)
ON CONFLICT (src_vbpl_id, dst_so_hieu, relation_type) DO UPDATE SET
    dst_vbpl_id = COALESCE(EXCLUDED.dst_vbpl_id, document_relations.dst_vbpl_id)
WHERE document_relations.dst_vbpl_id IS DISTINCT FROM
      COALESCE(EXCLUDED.dst_vbpl_id, document_relations.dst_vbpl_id)
""")


def upsert_document(
    ctx: CrawlContext, meta: DocumentMeta, source_url: str, changed: bool,
    relations: list[Relation], crawled_at: datetime,
) -> None:
    params = {
        "vbpl_id": meta.vbpl_id, "so_hieu": meta.so_hieu, "ten_van_ban": meta.ten_van_ban,
        "loai_van_ban": meta.loai_van_ban, "co_quan_ban_hanh": meta.co_quan_ban_hanh,
        "nguoi_ky": meta.nguoi_ky, "ngay_ban_hanh": meta.ngay_ban_hanh,
        "ngay_hieu_luc": meta.ngay_hieu_luc, "ngay_het_hieu_luc": meta.ngay_het_hieu_luc,
        "tinh_trang": meta.tinh_trang, "tinh_trang_norm": meta.tinh_trang_norm,
        "source_url": source_url, "needs_reparse": changed, "crawled_at": crawled_at,
    }
    with ctx.state.engine.begin() as conn:
        conn.execute(UPSERT_DOCUMENT, params)
        for r in relations:
            conn.execute(UPSERT_RELATION, {
                "src_vbpl_id": r.src_vbpl_id, "dst_vbpl_id": r.dst_vbpl_id,
                "dst_so_hieu": r.dst_so_hieu, "relation_type": r.relation_type, "origin": r.origin,
            })


async def crawl_detail(item: QueueItem, browser: Fetcher, ctx: CrawlContext) -> bool:
    """Xử lý một dòng crawl_queue(stage='detail'). Trả True nếu thành công.

    BlockedError được ném tiếp để run dừng; lỗi khác do run_crawl ghi nhận cho từng văn bản.
    """
    src = ctx.source
    vbpl_id = item.vbpl_id
    stamp = utc_stamp()
    crawled_at = datetime.strptime(stamp, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
    pages: dict[str, str] = {}
    tab_hashes: dict[str, str] = {}
    bronze_keys: list[str] = []

    for key in src.detail_tabs:
        tab = src.tabs[key]
        res = await browser.fetch(src.tab_url(item.url, tab), wait_selector=src.tab_panel.format(tab=tab))
        pages[key] = res.html
        sha, written = save_tab_html(ctx, vbpl_id, tab, res.html, stamp)
        tab_hashes[tab] = sha
        if written:
            bronze_keys.append(written)

    content_hash = sha256_bytes(
        "|".join(f"{t}:{h}" for t, h in sorted(tab_hashes.items())).encode("utf-8")
    )

    meta = extract_attributes(pages["attributes"], vbpl_id, src)
    fulltext = extract_fulltext_html(pages["fulltext"], src)
    check = check_document(meta, fulltext, src)
    if not check.ok:
        for err in check.errors:
            ctx.state.quarantine("crawl", vbpl_id, err["rule"], {**err, "url": item.url}, ctx.run_id)
        ctx.state.mark(vbpl_id, "detail", "failed", error=json.dumps(check.errors, ensure_ascii=False))
        ctx.counters.errors += 1
        log.warning("detail_schema_failed vbpl_id=%s errors=%s", vbpl_id, check.errors)
        return False

    related = extract_related(pages["related"], vbpl_id, src)
    history = extract_history(pages["history"], src)
    from_history = relations_from_history(history, vbpl_id, src)
    for title in related.unknown_groups + from_history.unknown_groups:
        # Nhóm/trạng thái mới trên trang: không đoán ánh xạ, đưa vào quarantine để bổ sung config
        ctx.state.quarantine("crawl", vbpl_id, "unknown_relation_label", {"label": title}, ctx.run_id)
    relations = merge_relations(related, from_history)
    downloads = extract_downloads(pages["download"], src)

    changed = content_hash != item.content_hash
    upsert_document(ctx, meta, item.url, changed, relations, crawled_at)

    if changed:
        meta_doc = {
            "vbpl_id": vbpl_id, "url": item.url, "crawled_at": stamp,
            "selector_version": src.selector_version, "content_hash": content_hash,
            "previous_content_hash": item.content_hash, "needs_reparse": True,
            "tab_hashes": tab_hashes, "bronze_html_keys": bronze_keys,
            "attributes_raw": meta.raw, "ten_van_ban": meta.ten_van_ban,
            "tinh_trang_norm": meta.tinh_trang_norm,
            "relations": [asdict(r) for r in relations],
            "history": [asdict(e) for e in history],
            "downloads": [asdict(d) for d in downloads],
        }
        ctx.storage.put_bytes(
            # thêm hash: hai lần crawl trong cùng một giây không đè nhau (Bronze chỉ thêm)
            ctx.bronze, f"meta/{vbpl_id}/{stamp}__{content_hash[:16]}.json",
            json.dumps(meta_doc, ensure_ascii=False, indent=2, default=str).encode("utf-8"),
            "application/json",
        )

    wanted = [d for d in downloads if d.extension in src.download_extensions]
    if wanted:
        download_url = src.tab_url(item.url, "download")
        if not ctx.state.enqueue(vbpl_id, "download", download_url) and changed:
            ctx.state.requeue(vbpl_id, "download")  # nội dung đổi → kiểm tra lại file

    ctx.state.mark(vbpl_id, "detail", "done", content_hash=content_hash)
    ctx.counters.detail_ok += 1
    log.info(
        "detail_done vbpl_id=%s changed=%s new_bronze=%d relations=%d downloads=%d",
        vbpl_id, changed, len(bronze_keys), len(relations), len(wanted),
    )
    return True
