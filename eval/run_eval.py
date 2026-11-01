"""Đo các chỉ số spec 16.2 và thí nghiệm 16.3 trên eval/questions.yaml. Xuất eval/reports/report.md.

Phần Q&A chạy luồng thật bằng câu trả lời template (không gọi LLM). Câu hỏi phụ được trả lời theo đáp án chuẩn,
mô phỏng người dùng biết rõ tình huống của mình. Phiên hỏi sinh ra bị xoá sau khi đo.

Chạy: .venv/bin/python eval/run_eval.py
"""

from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path

import yaml
from sqlalchemy import text

from luatgt.common.config import get_settings
from luatgt.common.db import make_engine
from luatgt.qa.followup import UNKNOWN
from luatgt.qa.service import QAService
from luatgt.retrieval.embed import SentenceTransformerEmbedder
from luatgt.retrieval.search import hybrid_search

ROOT = Path(__file__).parent
MAX_ROUNDS = 4
SPEC_MIN_QUESTIONS, SPEC_MIN_VERSIONED = 100, 20
CONFIGS = [("Vector, có lọc", "vector", True), ("Keyword, có lọc", "keyword", True),
           ("Hybrid, không lọc hiệu lực", "hybrid", False), ("Hybrid + lọc hiệu lực", "hybrid", True)]


def is_hit(hit, q) -> bool:
    if hit.provision_key not in q["expected_provision_keys"]:
        return False
    return "expected_version_no" not in q or hit.version_no == q["expected_version_no"]


def evaluate(engine, embedder, cfg, questions, mode, validity) -> dict:
    found, found20, reciprocal, versioned, versioned_ok, wrong_version, misses = 0, 0, 0.0, 0, 0, 0, []
    for q in questions:
        all_hits = hybrid_search(engine, embedder, q["question"], date.fromisoformat(q["as_of_date"]), cfg,
                                 k=20, mode=mode, apply_validity=validity)
        found20 += any(is_hit(h, q) for h in all_hits)
        hits = all_hits[:5]
        rank = next((i for i, h in enumerate(hits, 1) if is_hit(h, q)), None)
        found += rank is not None
        reciprocal += 1 / rank if rank else 0
        if "expected_version_no" in q:
            versioned += 1
            versioned_ok += rank is not None
            top = next((h for h in hits if h.provision_key in q["expected_provision_keys"]), None)
            wrong_version += top is not None and top.version_no != q["expected_version_no"]
        if rank is None:
            misses.append(q)
    n = len(questions)
    return {"recall": found / n, "recall20": found20 / n, "mrr": reciprocal / n, "version": versioned_ok / max(versioned, 1),
            "wrong_version": wrong_version, "misses": misses}


def truth_for(engine, q) -> list[dict]:
    """Violation của điều khoản đáp án tại ngày hỏi. Rỗng nếu câu không hỏi về mức phạt."""
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT phuong_tien, muc_phat_min, muc_phat_max, attributes FROM violations
            WHERE provision_key = ANY(:k) AND :d >= valid_from AND :d < valid_to AND NOT needs_review"""),
            {"k": q["expected_provision_keys"], "d": date.fromisoformat(q["as_of_date"])}).mappings().all()
    return [dict(r) for r in rows]


def oracle_choice(question, truth: list[dict]) -> str:
    """Giá trị người dùng sẽ chọn nếu biết đáp án; không có trong lựa chọn thì "Không rõ"."""
    values = [o["value"] for o in question.options]
    for row in truth:
        wanted = row["phuong_tien"] if question.dimension == "phuong_tien" else [row["attributes"].get(question.dimension)]
        for value in wanted:
            if value in values:
                return value
    return UNKNOWN


def ask_flow(service: QAService, q: dict, truth: list[dict], use_followup: bool) -> tuple:
    """Trả (câu trả lời cuối, số vòng hỏi phụ)."""
    as_of = date.fromisoformat(q["as_of_date"])
    response = service.ask(q["question"], None, as_of, None)
    rounds = 0
    while response.status == "need_clarification" and rounds < MAX_ROUNDS:
        rounds += 1
        selected = {f.dimension: oracle_choice(f, truth) if use_followup else UNKNOWN
                    for f in response.follow_up_questions}
        response = service.ask("", response.session_id, None, selected)
    return response, rounds


def fine_exact(response, truth: list[dict]) -> bool:
    """Fact đầu tiên có đúng mức phạt của điều khoản đáp án."""
    if not response.facts:
        return False
    first = response.facts[0]
    return any((first.muc_phat_min, first.muc_phat_max) == (t["muc_phat_min"], t["muc_phat_max"]) for t in truth)


def evaluate_qa(service: QAService, engine, questions: list[dict], use_followup: bool) -> dict:
    n_answered = cited_ok = n_citations = citations_ok = versioned = version_ok = 0
    fine_total = fine_ok = facts_total = followup_questions = rounds_total = 0
    for q in questions:
        truth = truth_for(engine, q)
        response, rounds = ask_flow(service, q, truth, use_followup)
        expected = set(q["expected_provision_keys"])
        matching = [c for c in response.citations if c.provision_key in expected]
        if response.status == "answered":
            n_answered += 1
            cited_ok += bool(matching)
            n_citations += len(response.citations)
            citations_ok += len(matching)
        if rounds:
            followup_questions += 1
            rounds_total += rounds
        if "expected_version_no" in q:
            versioned += 1
            version_ok += any(c.version_no == q["expected_version_no"] for c in matching)
        if truth:
            fine_total += 1
            fine_ok += fine_exact(response, truth)
            facts_total += len(response.facts)
    return {"answered": n_answered, "cited": cited_ok / max(n_answered, 1), "precision": citations_ok / max(n_citations, 1),
            "versioned": versioned, "version": version_ok / max(versioned, 1), "fine_total": fine_total,
            "fine": fine_ok / max(fine_total, 1), "facts": facts_total / max(fine_total, 1),
            "with_followup": followup_questions, "rounds": rounds_total / max(followup_questions, 1)}


def qa_section(settings, engine, embedder, questions: list[dict]) -> list[str]:
    service = QAService(settings, engine, embedder, None)
    with engine.connect() as conn:
        started = conn.execute(text("SELECT now()")).scalar_one()
    try:
        with_followup = evaluate_qa(service, engine, questions, True)
        without = evaluate_qa(service, engine, questions, False)
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM qa_sessions WHERE created_at >= :t"), {"t": started})
    n = len(questions)
    r = with_followup
    return [
        "## Chỉ số câu trả lời", "",
        "| Chỉ số | Giá trị | Mẫu |", "|---|---|---|",
        f"| Citation accuracy: câu trả lời có trích đúng điều khoản | {r['cited']:.1%} | {r['answered']}/{n} câu được trả lời |",
        f"| Tỉ lệ trích dẫn trỏ đúng trên tổng trích dẫn | {r['precision']:.1%} | gồm cả trích dẫn phụ của hành vi gần nghĩa |",
        f"| Version correctness | {r['version']:.1%} | {r['versioned']} câu kiểm tra phiên bản |",
        f"| Avg follow-up rounds | {r['rounds']:.2f} | {r['with_followup']} câu có hỏi lại |", "",
        "## Thí nghiệm: có và không có câu hỏi phụ (spec 16.3-2)", "",
        "| Cấu hình | Dòng đầu đúng mức phạt | Số dòng trung bình mỗi câu trả lời | Mẫu |", "|---|---|---|---|",
        f"| Có câu hỏi phụ | {r['fine']:.1%} | {r['facts']:.1f} | {r['fine_total']} câu có mức phạt |",
        f"| Bỏ qua câu hỏi phụ | {without['fine']:.1%} | {without['facts']:.1f} | {without['fine_total']} câu có mức phạt |", "",
    ]


def main() -> None:
    settings = get_settings()
    questions = yaml.safe_load((ROOT / "questions.yaml").read_text("utf-8"))
    engine, embedder = make_engine(settings), SentenceTransformerEmbedder(settings)
    n_versioned = sum("expected_version_no" in q for q in questions)
    lines = [f"# Báo cáo đánh giá LuậtGT ({datetime.now():%d/%m/%Y %H:%M})", "",
             (f"**Bộ câu hỏi:** {len(questions)} câu (spec cần ≥ {SPEC_MIN_QUESTIONS}), {n_versioned} câu kiểm tra phiên bản "
             f"(spec cần ≥ {SPEC_MIN_VERSIONED}). Đáp án là **bản nháp, nhóm chưa đối chiếu với văn bản gốc**. "
             "`query_expansions` được chọn sau khi xem câu trượt của chính bộ này nên Recall lạc quan (D-021)."), "",
             "## Retrieval (spec 16.3-1)", "",
             "| Cấu hình | Recall@5 | Recall@20 | MRR@5 | Đúng phiên bản | Bản sai xếp trước |", "|---|---|---|---|---|---|"]
    final = None
    for name, mode, validity in CONFIGS:
        r = evaluate(engine, embedder, settings.retrieval, questions, mode, validity)
        lines.append(f"| {name} | {r['recall']:.1%} | {r['recall20']:.1%} | {r['mrr']:.3f} | {r['version']:.1%} | {r['wrong_version']} |")
        final = r
    lines.append("")
    lines += qa_section(settings, engine, embedder, questions)
    lines += ["## Chỉ số chưa đo được tự động", "",
              "- **Parse accuracy:** cần đối chiếu tay trên 3 văn bản.",
              "- **Extraction accuracy:** cần nhóm kiểm tay mẫu 50 dòng ở `docs/M5_SAMPLE_CHECK.md`; 50/50 khớp hiện là so bằng máy với câu dẫn.",
              "- **Watermark (spec 16.3-3):** xem `docs/M9_WATERMARK.md`.", "",
              "## Câu trượt Recall@5 (Hybrid + lọc)", ""]
    lines += [f"- {q['id']} ({q['as_of_date']}): {q['question']} → {q['expected_provision_keys']}" for q in final["misses"]]
    report = "\n".join(lines) + "\n"
    (ROOT / "reports").mkdir(exist_ok=True)
    (ROOT / "reports" / "report.md").write_text(report, "utf-8")
    sys.stdout.write(report)


if __name__ == "__main__":
    main()
