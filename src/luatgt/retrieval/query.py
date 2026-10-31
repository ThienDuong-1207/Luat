"""Trích slot dễ nhận diện từ câu hỏi bằng từ điển (spec 9.3)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from zoneinfo import ZoneInfo

VEHICLES = {
    "xe_may": r"xe máy|xe gắn máy|xe mô tô|mô tô|xe sh\b",
    "o_to": r"\bô tô|ôtô|xe hơi|xe con|xe tải|xe khách",
    "xe_dap": r"xe đạp",
    "xe_may_chuyen_dung": r"xe máy chuyên dùng",
    "nguoi_di_bo": r"người đi bộ|đi bộ",
}
RE_DATE = re.compile(r"(?<![\d/])(\d{1,2})[/-](\d{1,2})(?:[/-](\d{4}))?(?![\d/])")
RE_MG = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:mg|miligam)")
RE_KMH = re.compile(r"(\d+)\s*(?:km/?h|cây số)")


@dataclass
class ParsedQuestion:
    as_of: date
    slots: dict = field(default_factory=dict)


def today_vn() -> date:
    return datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).date()


def _alcohol(mg: float) -> str:
    return "duoi_50mg" if mg <= 50 else "50_80mg" if mg <= 80 else "tren_80mg"


def _speed(kmh: int) -> str | None:
    if kmh < 5:
        return None
    return "05_10kmh" if kmh < 10 else "10_20kmh" if kmh <= 20 else "20_35kmh" if kmh <= 35 else "tren_35kmh"


def parse_question(question: str, today: date | None = None) -> ParsedQuestion:
    """as_of = ngày nêu trong câu (thiếu năm thì lấy năm của `today`), mặc định hôm nay theo giờ Việt Nam."""
    today = today or today_vn()
    low = question.lower()
    slots: dict = {}
    # "xe máy chuyên dùng" chứa "xe máy": khớp cụm dài trước
    rest = low
    vehicles = []
    for code in ("xe_may_chuyen_dung", *[c for c in VEHICLES if c != "xe_may_chuyen_dung"]):
        if re.search(VEHICLES[code], rest):
            vehicles.append(code)
            rest = re.sub(VEHICLES[code], " ", rest)
    if vehicles:
        slots["phuong_tien"] = vehicles
    if mg := RE_MG.search(low):
        slots["nong_do_con"] = _alcohol(float(mg.group(1).replace(",", ".")))
    if (kmh := RE_KMH.search(low)) and (value := _speed(int(kmh.group(1)))):
        slots["vuot_toc_do"] = value
    as_of = today
    if m := RE_DATE.search(question):
        day, month = int(m.group(1)), int(m.group(2))
        try:
            as_of = date(int(m.group(3) or today.year), month, day)
        except ValueError:
            pass
    return ParsedQuestion(as_of, slots)
