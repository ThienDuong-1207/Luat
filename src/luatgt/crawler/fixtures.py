"""M1: lưu HTML mẫu mọi tab + ảnh chụp màn hình vào tests/fixtures/vbpl/ để viết selector.

Tên file: {vbpl_id}__{tab}.html / .png; `manifest.json` ghi url, status, thời điểm, selector_version.
"""

from __future__ import annotations

import json
from pathlib import Path

from luatgt.common.config import Settings
from luatgt.common.logging import get_logger
from luatgt.crawler.browser import BrowserSession
from luatgt.crawler.selectors import SourceConfig

log = get_logger(__name__)


async def save_fixtures(
    urls: list[str],
    out_dir: Path,
    settings: Settings,
    source: SourceConfig,
    screenshots: bool = True,
) -> list[dict]:
    """Mở từng URL chi tiết với mọi tab trong config, lưu HTML (và ảnh). Trả về manifest."""
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = out_dir / "manifest.json"
    manifest: list[dict] = (
        json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else []
    )

    async with BrowserSession(settings.crawler, source.base_url) as browser:
        for url in urls:
            vbpl_id = source.vbpl_id_from_url(url)
            if vbpl_id is None:
                raise ValueError(f"Không lấy được vbpl_id từ URL: {url}")
            for tab in source.tabs.values():
                tab_url = source.tab_url(url, tab)
                res = await browser.fetch(tab_url)
                stem = f"{vbpl_id}__{tab}"
                (out_dir / f"{stem}.html").write_text(res.html, encoding="utf-8")
                if screenshots:
                    await browser.screenshot(str(out_dir / f"{stem}.png"))
                entry = {
                    "file": f"{stem}.html",
                    "vbpl_id": vbpl_id,
                    "tab": tab,
                    "url": tab_url,
                    "final_url": res.url,
                    "status": res.status,
                    "fetched_at": res.fetched_at.isoformat(),
                    "selector_version": source.selector_version,
                }
                manifest = [m for m in manifest if m["file"] != entry["file"]] + [entry]
                log.info("fixture_saved file=%s status=%s bytes=%d", entry["file"], res.status, len(res.html))
                manifest_path.write_text(
                    json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
                )
    return manifest
