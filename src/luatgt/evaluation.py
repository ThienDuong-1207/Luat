"""Phần thuần của eval: kiểm tra bộ câu hỏi, gán nhóm, gộp chỉ số theo nhóm, thẻ tái lập (spec 16.1, 16.4, 16.5).

`eval/run_eval.py` lo phần chạy hệ thống; module này không gọi model, chỉ đọc DB ở `data_fingerprint`.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Engine

from luatgt.retrieval.query import parse_question

SPLITS = ("dev", "test")
WORDINGS = ("doi_thuong", "thuat_ngu")
UNLABELED = "chua_gan"
MIN_GROUP_FOR_RATE = 10  # nhóm nhỏ hơn chỉ báo số đếm (spec 16.5)
LOW_GROUP_GAP = 0.10  # thấp hơn tổng quá 10 điểm % thì đánh dấu

# Cột nội dung, không gồm created_at/updated_at: dựng lại từ Bronze phải cho cùng md5 (D-024)
FINGERPRINT_SQL = {
    "provision_versions": ("provision_key, version_no, text, source_vbpl_id, valid_from, valid_to, is_current",
                           "provision_key, version_no"),
    "violations": (("violation_id, provision_key, version_no, hanh_vi, phuong_tien, doi_tuong, muc_phat_min, "
                   "muc_phat_max, tru_diem_gplx, tuoc_gplx_min_thang, tuoc_gplx_max_thang, bien_phap_bo_sung, "
                   "attributes, valid_from, valid_to, extraction_method, confidence, needs_review"),
                   "violation_id"),
}


class QuestionSetError(ValueError):
    """Bộ câu hỏi sai định dạng: thiếu split, id trùng, giá trị lạ."""


def validate_questions(questions: list[dict]) -> None:
    errors, seen = [], set()
    for q in questions:
        qid = q.get("id", "?")
        if qid in seen:
            errors.append(f"{qid}: id trùng")
        seen.add(qid)
        if q.get("split") not in SPLITS:
            errors.append(f"{qid}: split phải là một trong {SPLITS}, đang là {q.get('split')!r}")
        if "wording" in q and q["wording"] not in WORDINGS:
            errors.append(f"{qid}: wording phải là một trong {WORDINGS}, đang là {q['wording']!r}")
        if not q.get("expected_provision_keys"):
            errors.append(f"{qid}: thiếu expected_provision_keys")
    if errors:
        raise QuestionSetError("; ".join(errors))


def by_split(questions: list[dict]) -> dict[str, list[dict]]:
    return {s: [q for q in questions if q["split"] == s] for s in SPLITS}


def vehicle_group(question: str) -> str:
    vehicles = parse_question(question).slots.get("phuong_tien", [])
    if not vehicles:
        return "khong_neu"
    if len(vehicles) > 1:
        return "nhieu_loai"
    return vehicles[0] if vehicles[0] in ("xe_may", "o_to", "xe_dap") else "khac"


def source_group(q: dict) -> str:
    """Văn bản của đáp án: phần trước dấu '/' đầu tiên của provision_key, vd `168-2024-ND-CP`."""
    docs = sorted({k.split("/", 1)[0] for k in q["expected_provision_keys"]})
    return docs[0] if len(docs) == 1 else "nhieu_van_ban"


def amended_group(q: dict, amended_keys: set[str]) -> str:
    hit = "expected_version_no" in q or any(k in amended_keys for k in q["expected_provision_keys"])
    return "co_sua_doi" if hit else "khong_sua_doi"


def group_labels(q: dict, amended_keys: set[str]) -> dict[str, str]:
    return {"Phương tiện": vehicle_group(q["question"]), "Văn bản nguồn": source_group(q),
            "Sửa đổi": amended_group(q, amended_keys), "Cách viết": q.get("wording", UNLABELED)}


def amended_provision_keys(engine: Engine, keys: Iterable[str]) -> set[str]:
    """Điều khoản có hơn một version, tức từng bị sửa đổi."""
    with engine.connect() as conn:
        rows = conn.execute(text("""SELECT provision_key FROM provision_versions WHERE provision_key = ANY(:k)
                                    GROUP BY provision_key HAVING count(*) > 1"""), {"k": sorted(set(keys))})
        return {r[0] for r in rows}


@dataclass
class Rate:
    ok: int = 0
    n: int = 0

    def add(self, value: bool | None) -> None:
        """None = câu không thuộc mẫu của chỉ số này (vd câu không kiểm tra phiên bản)."""
        if value is not None:
            self.n += 1
            self.ok += bool(value)

    @property
    def value(self) -> float | None:
        return self.ok / self.n if self.n else None


@dataclass
class GroupRow:
    dimension: str
    group: str
    n_questions: int
    rates: dict[str, Rate] = field(default_factory=dict)


def group_metrics(records: list[dict], labels: dict[str, dict[str, str]], metrics: list[str]) -> list[GroupRow]:
    """records: mỗi câu một dict {id, <metric>: bool|None}. labels: id → {chiều: nhóm}."""
    rows: dict[tuple[str, str], GroupRow] = {}
    for rec in records:
        for dim, grp in labels[rec["id"]].items():
            row = rows.setdefault((dim, grp), GroupRow(dim, grp, 0, {m: Rate() for m in metrics}))
            row.n_questions += 1
            for m in metrics:
                row.rates[m].add(rec.get(m))
    return sorted(rows.values(), key=lambda r: (r.dimension, -r.n_questions, r.group))


def overall(records: list[dict], metrics: list[str]) -> dict[str, Rate]:
    out = {m: Rate() for m in metrics}
    for rec in records:
        for m in metrics:
            out[m].add(rec.get(m))
    return out


def format_rate(rate: Rate) -> str:
    if rate.n == 0:
        return "–"
    if rate.n < MIN_GROUP_FOR_RATE:
        return f"{rate.ok}/{rate.n}"
    return f"{rate.value:.1%} ({rate.ok}/{rate.n})"


def low_groups(rows: list[GroupRow], total: dict[str, Rate]) -> list[tuple[GroupRow, str]]:
    """Nhóm đủ lớn có tỉ lệ thấp hơn tổng quá LOW_GROUP_GAP (spec 16.5: ghi vào rủi ro mục 19)."""
    out = []
    for row in rows:
        for m, rate in row.rates.items():
            ref = total[m].value
            if rate.n >= MIN_GROUP_FOR_RATE and ref is not None and rate.value < ref - LOW_GROUP_GAP:
                out.append((row, m))
    return out


def group_table(rows: list[GroupRow], total: dict[str, Rate], metric_names: dict[str, str]) -> list[str]:
    head = " | ".join(metric_names.values())
    lines = [f"| Chiều | Nhóm | Số câu | {head} |", "|---|---|---|" + "---|" * len(metric_names)]
    lines.append("| **Tổng** | | " + str(max((r.n for r in total.values()), default=0)) + " | "
                 + " | ".join(format_rate(total[m]) for m in metric_names) + " |")
    flagged = {(r.dimension, r.group, m) for r, m in low_groups(rows, total)}
    for row in rows:
        cells = [format_rate(row.rates[m]) + (" ⚠" if (row.dimension, row.group, m) in flagged else "")
                 for m in metric_names]
        lines.append(f"| {row.dimension} | {row.group} | {row.n_questions} | " + " | ".join(cells) + " |")
    return lines


# ---------------------------------------------------------------- thẻ tái lập (spec 16.4)

def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


def questions_hash(questions: list[dict]) -> str:
    """Hash nội dung đã chuẩn hoá: đổi comment hay thứ tự khoá không đổi hash, đổi câu hay đáp án thì đổi."""
    canon = json.dumps(sorted(questions, key=lambda q: q["id"]), sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()[:12]


def git_state(root: Path, run: Callable[..., subprocess.CompletedProcess] = subprocess.run) -> tuple[str, bool]:
    """(commit, dirty). Bỏ qua eval/reports/ vì chính báo cáo sinh ra sẽ làm cây bị sửa ở lần chạy sau."""
    try:
        commit = run(["git", "rev-parse", "--short=12", "HEAD"], cwd=root, capture_output=True, text=True,
                     check=True).stdout.strip()
        status = run(["git", "status", "--porcelain", "--", ".", ":(exclude)eval/reports"], cwd=root,
                     capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return "không rõ", True
    return commit, bool(status.strip())


def data_fingerprint(engine: Engine) -> dict[str, tuple[int, str]]:
    """Bảng → (số dòng, md5 12 ký tự trên cột nội dung, sắp theo khoá)."""
    out = {}
    with engine.connect() as conn:
        for table, (cols, order) in FINGERPRINT_SQL.items():
            n, digest = conn.execute(text(
                f"SELECT count(*), md5(coalesce(string_agg(row({cols})::text, E'\\n' ORDER BY {order}), '')) "
                f"FROM {table}")).one()
            out[table] = (n, digest[:12])
    return out


def server_versions(engine: Engine) -> dict[str, str]:
    with engine.connect() as conn:
        pg = conn.execute(text("SHOW server_version")).scalar_one()
        vec = conn.execute(text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")).scalar()
    return {"PostgreSQL": pg.split()[0], "pgvector": vec or "không cài"}


def card_lines(card: dict) -> list[str]:
    """card: dict có thứ tự, giá trị đã là chuỗi."""
    lines = ["## Thẻ tái lập (spec 16.4)", "", "| Mục | Giá trị |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in card.items()]
    return lines + ["", "Hai lần chạy có cùng thẻ (trừ ngày chạy) phải cho cùng số liệu.", ""]
