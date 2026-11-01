"""Thuật toán câu hỏi phụ (spec 10). Sinh từ `violations`, không dùng LLM. Hàm thuần, không truy cập DB."""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import yaml

UNKNOWN = "__khong_ro__"
ANY_VEHICLE = {"khong_ap_dung", "co_gioi"}  # áp dụng không phân biệt loại xe, không bị bộ lọc loại


@dataclass
class FollowupConfig:
    max_rounds: int
    max_questions_per_round: int
    gain_threshold: float
    dimensions: dict[str, dict]

    def label(self, dim: str, value: str) -> str:
        return self.dimensions.get(dim, {}).get("labels", {}).get(value, value)


def load_followup_config(path: Path) -> FollowupConfig:
    d = yaml.safe_load(path.read_text("utf-8"))
    return FollowupConfig(d["max_rounds"], d["max_questions_per_round"], d["gain_threshold"], d["dimensions"])


@dataclass
class Candidate:
    violation: dict
    score: float


@dataclass
class Decision:
    status: str  # answered | need_clarification | not_found
    candidates: list[Candidate] = field(default_factory=list)
    dimensions: list[str] = field(default_factory=list)
    exhausted: bool = False  # hết vòng hỏi hoặc không còn chiều đáng hỏi: trả bảng các trường hợp


def _values(v: dict, dim: str) -> list[str]:
    if dim == "phuong_tien":
        return [p for p in v["phuong_tien"] if p not in ANY_VEHICLE]
    if dim == "doi_tuong":
        return [v["doi_tuong"]] if v["doi_tuong"] else []
    value = v["attributes"].get(dim)
    return [value] if isinstance(value, str) else []


def filter_candidates(candidates: list[Candidate], slots: dict) -> list[Candidate]:
    """Lọc theo slot. "Không rõ" không lọc."""
    out = candidates
    for dim, wanted in slots.items():
        if dim == "thoi_diem" or wanted == UNKNOWN:
            continue
        wanted_set = set(wanted) if isinstance(wanted, list) else {wanted}
        if dim == "phuong_tien":
            # Mục không phân biệt loại xe chỉ dùng khi không có mục đúng loại xe
            exact = [c for c in out if wanted_set & set(c.violation["phuong_tien"])]
            out = exact or [c for c in out if set(c.violation["phuong_tien"]) <= ANY_VEHICLE]
        else:
            out = [c for c in out if wanted_set & set(_values(c.violation, dim))]
    return out


def outcome(v: dict) -> tuple:
    return (v["muc_phat_min"], v["muc_phat_max"], v["tru_diem_gplx"], v["tuoc_gplx_min_thang"], v["tuoc_gplx_max_thang"])


def gain(candidates: list[Candidate], dim: str) -> float:
    """Entropy có trọng số của chiều × chênh lệch mức phạt tối đa giữa các nhóm / mức phạt lớn nhất (spec 10.2)."""
    weights: dict[str, float] = defaultdict(float)
    tops: dict[str, int] = {}
    for c in candidates:
        fine = c.violation["muc_phat_max"] or 0
        for value in _values(c.violation, dim):
            weights[value] += c.score
            tops[value] = max(tops.get(value, 0), fine)
    if len(weights) < 2:
        return 0.0
    total = sum(weights.values())
    entropy = -sum(w / total * math.log2(w / total) for w in weights.values())
    largest = max(tops.values())
    spread = (largest - min(tops.values())) / largest if largest else 0.0
    return entropy * spread


def decide(candidates: list[Candidate], slots: dict, rounds: int, cfg: FollowupConfig) -> Decision:
    remaining = filter_candidates(candidates, slots)
    if not remaining:
        return Decision("not_found")
    if len(remaining) == 1 or len({outcome(c.violation) for c in remaining}) == 1:
        return Decision("answered", remaining)
    if rounds >= cfg.max_rounds:
        return Decision("answered", remaining, exhausted=True)
    # Thứ tự cố định theo config để hoà điểm vẫn tất định
    dims = [d for d in cfg.dimensions if d != "thoi_diem" and d not in slots]
    scored = sorted(((gain(remaining, d), d) for d in dims), key=lambda x: -x[0])
    chosen = [d for g, d in scored if g > cfg.gain_threshold][: cfg.max_questions_per_round]
    if not chosen:
        return Decision("answered", remaining, exhausted=True)
    return Decision("need_clarification", remaining, chosen)


def build_questions(decision: Decision, cfg: FollowupConfig) -> list[dict]:
    out = []
    for dim in decision.dimensions:
        seen = dict.fromkeys(v for c in decision.candidates for v in _values(c.violation, dim))
        options = [{"value": v, "label": cfg.label(dim, v)} for v in seen]
        options.append({"value": UNKNOWN, "label": "Không rõ / bỏ qua"})
        out.append({"dimension": dim, "question": cfg.dimensions[dim]["question"], "options": options})
    return out


def related_questions(siblings: list[dict], answered_keys: set[str], cfg: FollowupConfig, n: int = 2) -> list[str]:
    """Mẫu câu từ violations cùng Điều (spec 10.3). Thống kê đồng xuất hiện chờ có dữ liệu qa_sessions."""
    out: list[str] = []
    for v in siblings:
        if v["provision_key"] in answered_keys:
            continue
        act = v["hanh_vi"].split(";")[0][:90].rstrip(" ,")
        act = act[0].lower() + act[1:] if act else act
        vehicle = next((cfg.label("phuong_tien", p) for p in v["phuong_tien"] if p not in ANY_VEHICLE), None)
        text = f"Mức phạt hành vi {act}" + (f" đối với {vehicle.lower()}" if vehicle else "") + " là bao nhiêu?"
        if text not in out:
            out.append(text)
        if len(out) == n:
            break
    return out
