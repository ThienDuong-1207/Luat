"""Đo retrieval trên eval/questions.yaml (spec 16.2, thí nghiệm 16.3-1). Xuất eval/reports/retrieval.md.

Chạy: .venv/bin/python eval/run_eval.py
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import yaml

from luatgt.common.config import get_settings
from luatgt.common.db import make_engine
from luatgt.retrieval.embed import SentenceTransformerEmbedder
from luatgt.retrieval.search import hybrid_search

ROOT = Path(__file__).parent
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


def main() -> None:
    settings = get_settings()
    questions = yaml.safe_load((ROOT / "questions.yaml").read_text("utf-8"))
    engine, embedder = make_engine(settings), SentenceTransformerEmbedder(settings)
    lines = [f"# Đánh giá retrieval ({len(questions)} câu, bản nháp đáp án)", "",
             "| Cấu hình | Recall@5 | Recall@20 | MRR@5 | Đúng phiên bản | Bản sai xếp trước |", "|---|---|---|---|---|---|"]
    final = None
    for name, mode, validity in CONFIGS:
        r = evaluate(engine, embedder, settings.retrieval, questions, mode, validity)
        lines.append(f"| {name} | {r['recall']:.1%} | {r['recall20']:.1%} | {r['mrr']:.3f} | {r['version']:.1%} | {r['wrong_version']} |")
        final = r
    lines += ["", "## Câu trượt (Hybrid + lọc)", ""]
    lines += [f"- {q['id']} ({q['as_of_date']}): {q['question']} → {q['expected_provision_keys']}" for q in final["misses"]]
    report = "\n".join(lines) + "\n"
    (ROOT / "reports").mkdir(exist_ok=True)
    (ROOT / "reports" / "retrieval.md").write_text(report, "utf-8")
    sys.stdout.write(report)


if __name__ == "__main__":
    main()
