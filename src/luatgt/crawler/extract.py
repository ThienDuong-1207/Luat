"""Trích dữ liệu từ HTML từng tab trang chi tiết vbpl.vn. Hàm thuần: không gọi mạng, chỉ đọc HTML.

Mọi selector/nhãn/ánh xạ lấy từ `SourceConfig` (config/sources/vbpl.yaml).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime

from bs4 import BeautifulSoup, Tag

from luatgt.crawler.selectors import SourceConfig


def clean_text(s: str | None) -> str:
    """Unicode NFC + gộp khoảng trắng (kể cả \\u00a0)."""
    if s is None:
        return ""
    s = unicodedata.normalize("NFC", s).replace(" ", " ")
    return re.sub(r"\s+", " ", s).strip()


def parse_date(value: str | None, fmt: str) -> date | None:
    if not value:
        return None
    return datetime.strptime(value.strip(), fmt).date()


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")


def strip_count(title: str) -> str:
    """'Căn cứ ban hành (5)' → 'Căn cứ ban hành'."""
    return re.sub(r"\s*\(\d+\)\s*$", "", clean_text(title))


@dataclass
class DocumentMeta:
    """Metadata thô + đã chuẩn hoá của một văn bản (tab Thuộc tính)."""

    vbpl_id: str
    ten_van_ban: str | None
    raw: dict[str, str | None]  # theo khoá attribute_labels, giá trị nguyên văn (None nếu "--")
    so_hieu: str | None = None
    loai_van_ban: str | None = None
    co_quan_ban_hanh: str | None = None
    nguoi_ky: str | None = None
    ngay_ban_hanh: date | None = None
    ngay_hieu_luc: date | None = None
    ngay_het_hieu_luc: date | None = None
    tinh_trang: str | None = None
    tinh_trang_norm: str = "unknown"
    date_errors: dict[str, str] = field(default_factory=dict)


def extract_attributes(html: str, vbpl_id: str, src: SourceConfig) -> DocumentMeta:
    """Tab Thuộc tính → DocumentMeta. Trích theo nhãn nên không phụ thuộc thứ tự ô."""
    soup = _soup(html)
    panel = soup.select_one(src.sel("attributes_panel"))
    title_el = soup.select_one(src.sel("ten_van_ban"))
    by_label: dict[str, str] = {}
    if panel is not None:
        for item in panel.select(src.sel("attribute_item")):
            lab = item.select_one(src.sel("attribute_label"))
            val = item.select_one(src.sel("attribute_value"))
            if lab is not None and val is not None:
                by_label[clean_text(lab.get_text(" "))] = clean_text(val.get_text(" "))

    raw: dict[str, str | None] = {}
    for key, label in src.attribute_labels.items():
        v = by_label.get(label)
        raw[key] = None if v is None or v in src.empty_values else v

    meta = DocumentMeta(
        vbpl_id=vbpl_id,
        ten_van_ban=clean_text(title_el.get_text(" ")) if title_el else None,
        raw=raw,
        so_hieu=raw.get("so_hieu"),
        loai_van_ban=raw.get("loai_van_ban"),
        co_quan_ban_hanh=raw.get("co_quan_ban_hanh"),
        nguoi_ky=raw.get("nguoi_ky"),
        tinh_trang=raw.get("tinh_trang"),
    )
    meta.tinh_trang_norm = src.tinh_trang_map.get(meta.tinh_trang or "", "unknown")
    for key in ("ngay_ban_hanh", "ngay_hieu_luc", "ngay_het_hieu_luc"):
        try:
            setattr(meta, key, parse_date(raw.get(key), src.date_format))
        except ValueError:
            meta.date_errors[key] = raw.get(key) or ""
    return meta


def extract_fulltext_html(html: str, src: SourceConfig) -> str | None:
    """HTML vùng toàn văn (tab Nội dung), None nếu không có hoặc rỗng."""
    el = _soup(html).select_one(src.sel("fulltext_container"))
    if el is None or not clean_text(el.get_text(" ")):
        return None
    return str(el)


def so_hieu_from_text(text: str, src: SourceConfig) -> str | None:
    m = re.search(src.so_hieu_in_text_regex, text)
    return m.group(1) if m else None


@dataclass(frozen=True)
class Relation:
    """Một dòng document_relations (src = văn bản đang xem)."""

    src_vbpl_id: str
    dst_so_hieu: str  # số hiệu nếu tìm được, ngược lại tên văn bản (vd "Hiến pháp năm 1992")
    relation_type: str
    dst_title: str
    dst_vbpl_id: str | None = None
    effective_date: date | None = None
    origin: str = "metadata_tab"
    source_section: str = ""  # tên nhóm (Lược đồ) hoặc trạng thái (Lịch sử)


@dataclass
class RelationGroups:
    relations: list[Relation]
    unknown_groups: list[str]  # tiêu đề nhóm chưa có trong relation_groups → cần cập nhật config


def extract_related(html: str, vbpl_id: str, src: SourceConfig) -> RelationGroups:
    """Tab Lược đồ → quan hệ. Mục không có ID nên dst_vbpl_id = None (spec 6.2 cho phép)."""
    panel = _soup(html).select_one(src.sel("related_panel"))
    out: list[Relation] = []
    unknown: list[str] = []
    if panel is None:
        return RelationGroups(out, unknown)
    for group in panel.select(src.sel("related_group")):
        title_el = group.select_one(src.sel("related_group_title"))
        if title_el is None:
            continue
        title = strip_count(title_el.get_text(" "))
        if title not in src.relation_groups:
            unknown.append(title)
            continue
        rtype = src.relation_groups[title]
        if rtype is None:
            continue
        for a in group.select(src.sel("related_items")):
            text = clean_text(a.get_text(" "))
            if text in src.empty_values:
                continue
            out.append(
                Relation(
                    src_vbpl_id=vbpl_id,
                    dst_so_hieu=so_hieu_from_text(text, src) or text,
                    relation_type=rtype,
                    dst_title=text,
                    source_section=title,
                )
            )
    return RelationGroups(_dedupe(out), unknown)


@dataclass(frozen=True)
class HistoryEvent:
    event_date: date | None
    status: str
    source_title: str
    source_vbpl_id: str | None  # None khi nguồn là chính văn bản (không có link)


def extract_history(html: str, src: SourceConfig) -> list[HistoryEvent]:
    """Tab Lịch sử → danh sách sự kiện (ngày, trạng thái, văn bản nguồn)."""
    panel = _soup(html).select_one(src.sel("history_panel"))
    events: list[HistoryEvent] = []
    if panel is None:
        return events
    for row in panel.select(src.sel("history_row")):
        cells: list[Tag] = row.find_all("td", recursive=False)
        if len(cells) < 3:
            continue
        link = cells[2].select_one(src.sel("history_link"))
        events.append(
            HistoryEvent(
                event_date=parse_date(clean_text(cells[0].get_text(" ")), src.date_format),
                status=clean_text(cells[1].get_text(" ")),
                source_title=clean_text(cells[2].get_text(" ")),
                source_vbpl_id=src.vbpl_id_from_url(link["href"]) if link else None,
            )
        )
    return events


def relations_from_history(
    events: list[HistoryEvent], vbpl_id: str, src: SourceConfig
) -> RelationGroups:
    """Sự kiện Lịch sử có văn bản nguồn khác → quan hệ có dst_vbpl_id và ngày hiệu lực."""
    out: list[Relation] = []
    unknown: list[str] = []
    for ev in events:
        if ev.status not in src.history_status:
            unknown.append(ev.status)
            continue
        rtype = src.history_status[ev.status]
        if rtype is None or ev.source_vbpl_id in (None, vbpl_id):
            continue
        out.append(
            Relation(
                src_vbpl_id=vbpl_id,
                dst_so_hieu=so_hieu_from_text(ev.source_title, src) or ev.source_title,
                relation_type=rtype,
                dst_title=ev.source_title,
                dst_vbpl_id=ev.source_vbpl_id,
                effective_date=ev.event_date,
                source_section=ev.status,
            )
        )
    return RelationGroups(_dedupe(out), unknown)


def merge_relations(*groups: RelationGroups) -> list[Relation]:
    """Gộp theo khoá bảng (src, dst_so_hieu, relation_type); ưu tiên bản có dst_vbpl_id."""
    best: dict[tuple[str, str, str], Relation] = {}
    for g in groups:
        for r in g.relations:
            k = (r.src_vbpl_id, r.dst_so_hieu, r.relation_type)
            if k not in best or (best[k].dst_vbpl_id is None and r.dst_vbpl_id is not None):
                best[k] = r
    return list(best.values())


def _dedupe(rels: list[Relation]) -> list[Relation]:
    seen: set[tuple[str, str, str]] = set()
    out = []
    for r in rels:
        k = (r.src_vbpl_id, r.dst_so_hieu, r.relation_type)
        if k not in seen:
            seen.add(k)
            out.append(r)
    return out


@dataclass(frozen=True)
class DownloadItem:
    index: int  # vị trí khối trong tab (dùng để bấm nút tải ở M2)
    filename: str
    extension: str  # pdf | doc | docx | ...


def extract_downloads(html: str, src: SourceConfig) -> list[DownloadItem]:
    """Tab Tải về → danh sách file. Không có href: M2 tải bằng cách bấm nút (expect_download)."""
    panel = _soup(html).select_one(src.sel("download_panel"))
    items: list[DownloadItem] = []
    if panel is None:
        return items
    for i, block in enumerate(panel.select(src.sel("download_item"))):
        name_el = block.select_one(src.sel("download_name"))
        if name_el is None:
            continue
        name = clean_text(name_el.get_text(" "))
        ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
        items.append(DownloadItem(index=i, filename=name, extension=ext))
    return items
