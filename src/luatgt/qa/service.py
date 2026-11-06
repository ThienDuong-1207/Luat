"""Luồng hỏi đáp: phiên, truy xuất, câu hỏi phụ, trả lời (spec 10, 11, 12)."""

from __future__ import annotations

import json
import re
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy import Engine, text

from luatgt.common.config import Settings
from luatgt.qa.answer import (
    RE_CITE,
    AskResponse,
    Citation,
    dedupe,
    make_fact,
    provision_answer,
    render_with_llm,
    template_answer,
)
from luatgt.qa.followup import (
    UNKNOWN,
    Candidate,
    Decision,
    FollowupConfig,
    build_questions,
    decide,
    load_followup_config,
    related_questions,
)
from luatgt.qa.llm_client import LLMClient
from luatgt.retrieval.embed import Embedder
from luatgt.retrieval.query import parse_question, today_vn
from luatgt.retrieval.search import SearchHit, hybrid_search

RE_PENALTY_INTENT = re.compile(r"phạt|xử lý|xử phạt|mức|tước|trừ điểm|bị gì|có sao không", re.IGNORECASE)
RE_BASIS = re.compile(r"^Căn cứ:.*$", re.MULTILINE)
RELATED_HEADING = "**Mức phạt liên quan:**"
NOT_FOUND = ("Chưa tìm thấy quy định phù hợp trong các văn bản hiện có. "
             "Bạn thử mô tả rõ hành vi, loại xe hoặc chọn một chủ đề khác.")


@dataclass
class Session:
    session_id: str
    question: str
    as_of: date
    slots: dict
    rounds: int
    mode: str | None = None  # "penalty" | "rule": chọn ở vòng đầu, giữ nguyên khi hỏi lại (D-030)


class QAService:
    def __init__(self, settings: Settings, engine: Engine, embedder: Embedder, llm: LLMClient | None,
                 followup: FollowupConfig | None = None) -> None:
        self.settings, self.engine, self.embedder, self.llm = settings, engine, embedder, llm
        self.followup = followup or load_followup_config(settings.path(settings.paths.followup))

    def ask(self, question: str, session_id: str | None = None, as_of: date | None = None,
            selected: dict | None = None) -> AskResponse:
        session = self._session(question, session_id, as_of, selected or {})
        query = self._query(session)
        hits = hybrid_search(self.engine, self.embedder, query, session.as_of, self.settings.retrieval)
        ranked = self._ranked(hits, query)
        if ranked is None:
            return self._save(session, self._not_found(session))
        candidates = [Candidate(v, h.score) for h in ranked for v in h.violations]
        if session.mode is None:
            # Câu không có từ hỏi mức phạt nhưng đoạn đứng đầu đã là điều khoản xử phạt ("không đội mũ bảo hiểm"):
            # đi luồng mức phạt luôn, tránh trích nguyên văn rồi lặp lại cùng mức phạt bên dưới (D-030)
            penalty = RE_PENALTY_INTENT.search(session.question) or bool(ranked and ranked[0].violations)
            session.mode = "penalty" if penalty else "rule"
        if session.mode == "penalty":
            return self._save(session, self._penalties(session, candidates, ranked) or self._not_found(session))
        # Câu hỏi về quy định: trích nguyên văn, rồi kèm mức phạt liên quan nếu tìm được (D-029)
        provisions = self._provisions(session, ranked[:3] or hits[:3])
        return self._save(session, merge_related(provisions, self._related_penalties(session, query)))

    def _query(self, s: Session) -> str:
        """Loại xe người dùng chọn ở câu hỏi phụ mà câu gốc không có: thêm vào truy vấn để tìm lại đúng loại xe."""
        chosen = s.slots.get("phuong_tien")
        if not chosen or parse_question(s.question).slots.get("phuong_tien"):
            return s.question
        values = chosen if isinstance(chosen, list) else [chosen]
        labels = [self.followup.label("phuong_tien", v) for v in values if v != UNKNOWN]
        return " ".join([s.question, *labels])

    def _ranked(self, hits: list[SearchHit], query: str) -> list[SearchHit] | None:
        """Chunk đủ gần chunk tốt nhất. None nếu không đủ liên quan.

        Hai tầng (D-030): cosine ≥ `min_similarity`, hoặc cosine ≥ `min_similarity_keyword` và mọi từ của câu
        (trừ từ dừng) có trong chunk đứng đầu. Câu ngắn như "không đội mũ bảo hiểm" có cosine thấp hơn câu đầy đủ.
        """
        best = max((h.similarity or 0.0 for h in hits), default=0.0)
        qa = self.settings.qa
        relevant = best >= qa.min_similarity or (
            best >= qa.min_similarity_keyword
            and covers_all_words(query, hits[0], self.settings.retrieval.stopwords))
        if not relevant:
            return None
        cutoff = best - self.settings.qa.similarity_margin
        return [h for h in hits[: self.settings.qa.candidate_chunks] if (h.similarity or 0.0) >= cutoff]

    def _penalties(self, s: Session, candidates: list[Candidate], ranked: list[SearchHit]) -> AskResponse | None:
        """Luồng mức phạt: hỏi lại hoặc trả lời. None nếu không còn ứng viên."""
        decision = decide(candidates, s.slots, s.rounds, self.followup)
        if decision.status == "not_found":
            return None
        if decision.status == "need_clarification":
            return AskResponse(
                status="need_clarification", as_of_date=s.as_of, disclaimer=self.settings.qa.disclaimer,
                answer_markdown="Mức phạt khác nhau tuỳ trường hợp, bạn cho biết thêm:",
                follow_up_questions=build_questions(decision, self.followup),
            )
        return self._answered(s, decision, ranked)

    def _related_penalties(self, s: Session, query: str) -> AskResponse | None:
        """Tìm lại chỉ trong điều khoản có mức phạt. None nếu không có gì đủ liên quan."""
        hits = hybrid_search(self.engine, self.embedder, query, s.as_of, self.settings.retrieval,
                             penalties_only=True)
        ranked = self._ranked(hits, query)
        if not ranked:
            return None
        return self._penalties(s, [Candidate(v, h.score) for h in ranked for v in h.violations], ranked)

    def _session(self, question: str, session_id: str | None, as_of: date | None, selected: dict) -> Session:
        if session_id:
            with self.engine.connect() as conn:
                row = conn.execute(text("SELECT question, as_of_date, slots FROM qa_sessions WHERE session_id = :i"),
                                   {"i": session_id}).mappings().first()
            if row is None:
                raise KeyError(session_id)
            slots = dict(row["slots"])
            rounds = slots.pop("_rounds", 0) + 1
            mode = slots.pop("_mode", None)
            return Session(session_id, row["question"], as_of or row["as_of_date"], {**slots, **selected}, rounds, mode)
        parsed = parse_question(question, today_vn())
        return Session(str(uuid.uuid4()), question, as_of or parsed.as_of, {**parsed.slots, **selected}, 0)

    def _save(self, s: Session, response: AskResponse) -> AskResponse:
        response.session_id = s.session_id
        with self.engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO qa_sessions (session_id, question, as_of_date, slots, status, answer)
                VALUES (:i, :q, :d, CAST(:s AS jsonb), :st, CAST(:a AS jsonb))
                ON CONFLICT (session_id) DO UPDATE SET as_of_date = EXCLUDED.as_of_date, slots = EXCLUDED.slots,
                    status = EXCLUDED.status, answer = EXCLUDED.answer"""),
                {"i": s.session_id, "q": s.question, "d": s.as_of, "st": response.status,
                 "s": json.dumps({**s.slots, "_rounds": s.rounds, "_mode": s.mode}, ensure_ascii=False),
                 "a": response.model_dump_json()})
        return response

    def _not_found(self, s: Session) -> AskResponse:
        return AskResponse(status="not_found", answer_markdown=NOT_FOUND, as_of_date=s.as_of,
                           disclaimer=self.settings.qa.disclaimer)

    def _citations(self, items: list[tuple[str, int]]) -> list[Citation]:
        """(provision_key, version_no) → trích dẫn; `sửa đổi bởi` lấy từ văn bản nguồn của phiên bản."""
        with self.engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT v.provision_key, v.version_no, v.valid_from, src.so_hieu AS source_so_hieu,
                       (SELECT d.source_url FROM documents d WHERE d.vbpl_id = COALESCE(p.vbpl_id, v.source_vbpl_id)) AS url,
                       (SELECT d.so_hieu FROM documents d WHERE d.vbpl_id = COALESCE(p.vbpl_id, v.source_vbpl_id)) AS so_hieu,
                       p.pdf_page
                FROM provision_versions v
                JOIN documents src ON src.vbpl_id = v.source_vbpl_id
                LEFT JOIN provisions p ON p.provision_key = v.provision_key
                WHERE v.provision_key = ANY(:k)"""), {"k": [k for k, _ in items]}).mappings().all()
        by = {(r["provision_key"], r["version_no"]): r for r in rows}
        out = []
        for i, (key, no) in enumerate(items, 1):
            r = by[(key, no)]
            label = f"{citation_label(key)} {doc_label(r['so_hieu'] or r['source_so_hieu'])}"
            if r["so_hieu"] and r["source_so_hieu"] != r["so_hieu"]:
                label += f" (sửa đổi bởi {doc_label(r['source_so_hieu'])})"
            out.append(Citation(id=f"c{i}", provision_key=key, version_no=no, label=label, valid_from=r["valid_from"],
                                source_url=r["url"], pdf_page=r["pdf_page"]))
        return out

    def _answered(self, s: Session, decision: Decision, ranked: list[SearchHit]) -> AskResponse:
        chosen = dedupe(decision.candidates)[: self.settings.qa.max_facts]
        keys = list(dict.fromkeys((c.violation["provision_key"], c.violation["version_no"]) for c in chosen))
        citations = self._citations(keys)
        ids = {(c.provision_key, c.version_no): c.id for c in citations}
        facts = [make_fact(c.violation, ids[(c.violation["provision_key"], c.violation["version_no"])]) for c in chosen]
        fallback = template_answer(facts, citations, s.as_of, self.followup, decision.exhausted)
        wanted = {k for k, _ in keys}
        context = [h.display_text for h in ranked if h.provision_key in wanted]
        body = render_with_llm(self.llm, s.question, facts, citations, context, s.as_of, fallback)
        return AskResponse(status="answered", answer_markdown=body, facts=facts, citations=citations,
                           related_questions=self._related(keys, s.as_of), as_of_date=s.as_of,
                           disclaimer=self.settings.qa.disclaimer)

    def _provisions(self, s: Session, hits: list[SearchHit]) -> AskResponse:
        citations = self._citations([(h.provision_key, h.version_no) for h in hits])
        heads = self._heads(hits, s.as_of)
        fallback = provision_answer(hits, citations, s.as_of, heads)
        context = [f"{heads.get(h.provision_key, '')} {h.display_text}".strip() for h in hits]
        body = render_with_llm(self.llm, s.question, [], citations, context, s.as_of, fallback)
        return AskResponse(status="answered", answer_markdown=body, citations=citations, as_of_date=s.as_of,
                           disclaimer=self.settings.qa.disclaimer)

    def _heads(self, hits: list[SearchHit], as_of: date) -> dict[str, str]:
        """Câu dẫn Khoản của các chunk cấp Điểm."""
        parents = {h.provision_key: h.provision_key.rsplit("/", 1)[0] for h in hits
                   if h.provision_key.rsplit("/", 1)[-1].startswith("P")}
        with self.engine.connect() as conn:
            rows = dict(conn.execute(text("""
                SELECT provision_key, text FROM provision_versions
                WHERE provision_key = ANY(:k) AND :d >= valid_from AND :d < valid_to"""),
                {"k": list(parents.values()), "d": as_of}).all())
        return {k: rows[p] for k, p in parents.items() if rows.get(p)}

    def _related(self, keys: list[tuple[str, int]], as_of: date) -> list[str]:
        dieu = sorted({"/".join(k.split("/")[:2]) for k, _ in keys})
        with self.engine.connect() as conn:
            rows = [dict(r) for r in conn.execute(text("""
                SELECT provision_key, hanh_vi, phuong_tien FROM violations
                WHERE split_part(provision_key, '/', 1) || '/' || split_part(provision_key, '/', 2) = ANY(:d)
                  AND :as_of >= valid_from AND :as_of < valid_to
                ORDER BY md5(provision_key) LIMIT 20"""), {"d": dieu, "as_of": as_of}).mappings()]
        return related_questions(rows, {k for k, _ in keys}, self.followup)


def merge_related(provisions: AskResponse, related: AskResponse | None) -> AskResponse:
    """Ghép trích dẫn quy định với mức phạt liên quan thành một câu trả lời; đánh số lại trích dẫn của phần sau.

    Mức phạt cần hỏi lại thì giữ phần quy định ở trên và hỏi tiếp bên dưới.
    """
    if related is None:
        return provisions
    offset = len(provisions.citations)
    rename = {c.id: f"c{offset + i}" for i, c in enumerate(related.citations, 1)}
    body = RE_CITE.sub(lambda m: f"[{rename.get(m.group(1), m.group(1))}]", strip_basis(related.answer_markdown))
    citations = provisions.citations + [c.model_copy(update={"id": rename[c.id]}) for c in related.citations]
    facts = [f.model_copy(update={"citation_ids": [rename[i] for i in f.citation_ids]}) for f in related.facts]
    basis = "Căn cứ: " + "; ".join(f"[{c.id}] {c.label}" for c in citations) + "."
    answer = "\n\n".join([strip_basis(provisions.answer_markdown), RELATED_HEADING, body, basis])
    return related.model_copy(update={"answer_markdown": answer, "citations": citations, "facts": facts})


def fold(text_: str) -> str:
    """Chữ thường, bỏ dấu tiếng Việt (đ → d), để so từ không phụ thuộc cách gõ dấu."""
    decomposed = unicodedata.normalize("NFD", text_.lower().replace("đ", "d"))
    return "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")


def covers_all_words(query: str, hit: SearchHit, stopwords: list[str]) -> bool:
    """Mọi từ của câu (trừ từ dừng) xuất hiện nguyên từ trong chunk. Câu chỉ có từ dừng thì False."""
    stop = {fold(w) for w in stopwords}
    words = [w for w in re.findall(r"\w+", fold(query)) if w not in stop]
    body = set(re.findall(r"\w+", fold(f"{hit.hierarchy_path} {hit.display_text}")))
    return bool(words) and all(w in body for w in words)


def strip_basis(markdown: str) -> str:
    return RE_BASIS.sub("", markdown).strip()


def doc_label(so_hieu: str) -> str:
    return f"NĐ {so_hieu}" if "NĐ-CP" in so_hieu else f"Luật {so_hieu}" if "QH" in so_hieu else so_hieu


def citation_label(key: str) -> str:
    """"…/D18/K4/Pa" → "Điểm a khoản 4 Điều 18"."""
    parts = {p[0]: p[1:] for p in key.split("/")[1:]}
    out = []
    if "P" in parts:
        out.append(f"Điểm {'đ' if parts['P'] == 'dd' else parts['P']}")
    if "K" in parts:
        out.append(f"khoản {parts['K']}" if out else f"Khoản {parts['K']}")
    out.append(f"Điều {parts['D']}")
    return " ".join(out)
