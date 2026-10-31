"""Parse một văn bản từ Bronze (HTML các tab + meta + PDF) → các dòng cho bảng Silver.

Hàm thuần, không phụ thuộc Spark/mạng: Spark job gọi trong executor, test gọi trực tiếp.
Mọi thông tin đều trích lại từ HTML gốc trên Bronze bằng selector hiện tại (replay, spec 7.6).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

from luatgt.common.config import ParsingSettings
from luatgt.crawler.extract import (
    extract_attributes,
    extract_history,
    extract_related,
    merge_relations,
    relations_from_history,
)
from luatgt.crawler.selectors import SourceConfig
from luatgt.parsing.html_fulltext import HtmlParseConfig, SourceLine, extract_lines
from luatgt.parsing.pdf_text import extract_pdf_text, match_dieu_pages, pdf_lines
from luatgt.parsing.structure import parse_structure


@dataclass
class DocumentInputs:
    vbpl_id: str
    tab_html: dict[str, str]  # khoá tab trong config (fulltext, attributes, …) → HTML trang
    meta: dict  # JSON meta gần nhất trên Bronze
    pdf: bytes | None = None
    bronze_keys: list[str] = field(default_factory=list)


@dataclass
class SilverRows:
    documents: list[dict] = field(default_factory=list)
    document_relations: list[dict] = field(default_factory=list)
    provisions: list[dict] = field(default_factory=list)
    parse_issues: list[dict] = field(default_factory=list)


def html_parse_config(src: SourceConfig) -> HtmlParseConfig:
    a = src.fulltext_annotation
    return HtmlParseConfig(src.sel("fulltext_container"), a.block, a.label, tuple(a.labels))


def parse_document(inp: DocumentInputs, src: SourceConfig, cfg: ParsingSettings) -> SilverRows:
    out = SilverRows()
    vid = inp.vbpl_id
    issue = lambda rule, key="", **detail: out.parse_issues.append(
        {"vbpl_id": vid, "rule": rule, "provision_key": key,
         "detail": json.dumps(detail, ensure_ascii=False, default=str)}
    )

    meta = extract_attributes(inp.tab_html.get("attributes", ""), vid, src)
    if not meta.so_hieu:
        issue("missing_so_hieu")
        return out

    # Nguồn toàn văn: ưu tiên HTML, fallback PDF (spec 8.1)
    lines: list[SourceLine] = extract_lines(inp.tab_html.get("fulltext", ""), html_parse_config(src))
    source = "html"
    pdf_text = None
    if inp.pdf is not None:
        pdf_text = extract_pdf_text(
            inp.pdf, cfg.pdf_min_chars_per_page, cfg.ocr_enabled, cfg.ocr_lang, cfg.ocr_dpi,
            cfg.header_footer_ratio,
        )
        if pdf_text.empty_pages:
            issue("pdf_pages_without_text", pages=len(pdf_text.empty_pages))
    if not lines and pdf_text is not None:
        lines, source = pdf_lines(pdf_text), "pdf"
    if not lines:
        issue("no_fulltext")
        source = "none"

    parsed = parse_structure(lines, meta.so_hieu)
    pages = match_dieu_pages(pdf_text) if pdf_text is not None else {}

    for node in parsed.nodes():
        dieu = node
        while dieu is not None and dieu.level != "dieu":
            dieu = dieu.parent
        path = node.key.split("/", 1)[1]
        out.provisions.append({
            "provision_id": f"{vid}:{path}",
            "vbpl_id": vid,
            "provision_key": node.key,
            "level": node.level,
            "number": node.number,
            "number_raw": node.number_raw,
            "title": node.title,
            "text": node.text,
            "parent_id": f"{vid}:{node.parent.key.split('/', 1)[1]}" if node.parent else None,
            "ordinal": node.ordinal,
            "pdf_page": pages.get(dieu.number) if dieu is not None else None,
            "has_quoted_content": node.has_quoted_content,
            "vbpl_annotations": list(node.annotations),
            "line_no": node.line_no,
        })
    for iss in parsed.issues:
        issue(iss.rule, iss.provision_key, **iss.detail)

    related = extract_related(inp.tab_html.get("related", ""), vid, src)
    history = relations_from_history(extract_history(inp.tab_html.get("history", ""), src), vid, src)
    for r in merge_relations(related, history):
        row = asdict(r)
        out.document_relations.append(row)
    for label in related.unknown_groups + history.unknown_groups:
        issue("unknown_relation_label", label=label)

    out.documents.append({
        "vbpl_id": vid,
        "so_hieu": meta.so_hieu,
        "ten_van_ban": meta.ten_van_ban,
        "loai_van_ban": meta.loai_van_ban,
        "co_quan_ban_hanh": meta.co_quan_ban_hanh,
        "nguoi_ky": meta.nguoi_ky,
        "ngay_ban_hanh": meta.ngay_ban_hanh,
        "ngay_hieu_luc": meta.ngay_hieu_luc,
        "ngay_het_hieu_luc": meta.ngay_het_hieu_luc,
        "tinh_trang": meta.tinh_trang,
        "tinh_trang_norm": meta.tinh_trang_norm,
        "source_url": inp.meta.get("url"),
        "content_hash": inp.meta.get("content_hash"),
        "crawled_at": inp.meta.get("crawled_at"),
        "selector_version": src.selector_version,
        "parser_version": cfg.parser_version,
        "fulltext_source": source,
        "n_provisions": len(out.provisions),
        "n_dieu": sum(p["level"] == "dieu" for p in out.provisions),
        "preamble": "\n".join(parsed.preamble),
        "trailer": "\n".join(parsed.trailer),
        "bronze_keys": list(inp.bronze_keys),
    })
    return out
