"""PDF → text theo trang (spec 8.1–8.2): lớp chữ của PyMuPDF, OCR Tesseract (`vie`) cho trang scan.

Dùng cho (1) fallback khi không có HTML toàn văn, (2) khớp Điều với số trang PDF để trích dẫn.
OCR là tuỳ chọn: máy không có `tesseract` thì trang scan để trống và ghi cảnh báo.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass

import pymupdf

from luatgt.common.logging import get_logger
from luatgt.parsing.html_fulltext import SourceLine
from luatgt.parsing.normalize import normalize_lines, strip_header_footer

log = get_logger(__name__)

RE_DIEU_HEAD = re.compile(r"^Điều\s+(\d+[a-z]?)\.")


@dataclass
class PdfText:
    pages: list[list[str]]  # dòng đã chuẩn hoá theo trang (đã bỏ header/footer lặp)
    ocr_pages: list[int]  # trang (1-based) lấy bằng OCR
    empty_pages: list[int]  # trang không có chữ (scan mà không OCR được)


def tesseract_available() -> bool:
    return shutil.which("tesseract") is not None


def _ocr_page(page: pymupdf.Page, lang: str, dpi: int) -> str:
    import io

    import pytesseract
    from PIL import Image

    pix = page.get_pixmap(dpi=dpi)
    return pytesseract.image_to_string(Image.open(io.BytesIO(pix.tobytes("png"))), lang=lang)


def extract_pdf_text(
    data: bytes,
    min_chars: int = 50,
    ocr: bool = True,
    ocr_lang: str = "vie",
    ocr_dpi: int = 300,
    header_footer_ratio: float = 0.5,
) -> PdfText:
    can_ocr = ocr and tesseract_available()
    raw_pages: list[list[str]] = []
    ocr_pages: list[int] = []
    empty: list[int] = []
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        for i, page in enumerate(doc, start=1):
            text = page.get_text()
            if len(text.strip()) < min_chars:
                if can_ocr:
                    text = _ocr_page(page, ocr_lang, ocr_dpi)
                    ocr_pages.append(i)
                else:
                    empty.append(i)
            raw_pages.append(normalize_lines(text.splitlines()))
    if empty:
        log.warning("pdf_pages_without_text pages=%d ocr_available=%s", len(empty), can_ocr)
    return PdfText(strip_header_footer(raw_pages, header_footer_ratio), ocr_pages, empty)


def pdf_lines(pdf: PdfText) -> list[SourceLine]:
    """Dòng của cả văn bản (fallback khi không có HTML toàn văn)."""
    return [SourceLine(line) for page in pdf.pages for line in page]


def match_dieu_pages(pdf: PdfText) -> dict[str, int]:
    """Số Điều → trang PDF (1-based) đầu tiên có dòng bắt đầu bằng "Điều {n}." (spec 8.1 bước 3)."""
    found: dict[str, int] = {}
    for page_no, lines in enumerate(pdf.pages, start=1):
        for line in lines:
            if (m := RE_DIEU_HEAD.match(line)) and m.group(1) not in found:
                found[m.group(1)] = page_no
    return found
