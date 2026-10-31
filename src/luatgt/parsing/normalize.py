"""Chuẩn hoá text văn bản luật (spec 8.2)."""

from __future__ import annotations

import re
import unicodedata
from collections import Counter

_WS = re.compile("[ \t\u00a0\u2000-\u200b\u202f\u205f\u3000]+")
_ZERO_WIDTH = re.compile("[\u200b-\u200d\ufeff]")


def normalize_line(s: str) -> str:
    """Unicode NFC, bỏ ký tự vô hình, gộp khoảng trắng (kể cả \\u00a0, tab). Giữ nguyên chữ "đ"."""
    s = unicodedata.normalize("NFC", s)
    s = _ZERO_WIDTH.sub("", s)
    s = _WS.sub(" ", s)
    return s.strip()


def normalize_lines(lines: list[str]) -> list[str]:
    """Chuẩn hoá từng dòng, bỏ dòng rỗng."""
    out = []
    for line in lines:
        n = normalize_line(line)
        if n:
            out.append(n)
    return out


# Dòng cấu trúc không bao giờ là header/footer (dù sau khi thay số trông giống nhau giữa các trang)
_STRUCTURAL = re.compile(r"^(Phần|PHẦN|Chương|CHƯƠNG|Mục|MỤC|Điều)\s")


def _hf_key(s: str) -> str:
    return re.sub(r"\d+", "#", s)


def _edges(page: list[str], edge_lines: int) -> list[str]:
    return page[:edge_lines] + page[-edge_lines:]


def repeated_header_footer(pages: list[list[str]], min_ratio: float = 0.5, edge_lines: int = 2) -> set[str]:
    """Dòng ở đầu/cuối trang lặp lại trên ≥ min_ratio số trang PDF (header/footer, số trang).

    So khớp sau khi thay số bằng '#' để bắt cả "Trang 3/20". Chỉ xét `edge_lines` dòng đầu và cuối mỗi trang.
    """
    if len(pages) < 2:
        return set()
    counts: Counter[str] = Counter()
    for page in pages:
        counts.update({_hf_key(ln) for ln in _edges(page, edge_lines) if not _STRUCTURAL.match(ln)})
    threshold = max(2, int(len(pages) * min_ratio + 0.999))
    return {k for k, n in counts.items() if n >= threshold}


def strip_header_footer(pages: list[list[str]], min_ratio: float = 0.5, edge_lines: int = 2) -> list[list[str]]:
    repeated = repeated_header_footer(pages, min_ratio, edge_lines)
    out = []
    for page in pages:
        n = len(page)
        out.append([
            ln for i, ln in enumerate(page)
            if not ((i < edge_lines or i >= n - edge_lines) and _hf_key(ln) in repeated)
        ])
    return out
