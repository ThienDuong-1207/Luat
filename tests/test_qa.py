"""M7: câu hỏi phụ, kiểm tra câu trả lời, API. LLM luôn là client giả, không gọi mạng."""

from __future__ import annotations

import json
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from luatgt.api.main import create_app
from luatgt.common.config import load_settings
from luatgt.jobs.build_index import build_chunks, load_chunks
from luatgt.modeling.versions import OPEN_END
from luatgt.qa.answer import (
    AskResponse,
    Citation,
    Fact,
    check_answer,
    make_fact,
    render_with_llm,
    template_answer,
)
from luatgt.qa.followup import (
    UNKNOWN,
    Candidate,
    build_questions,
    decide,
    filter_candidates,
    gain,
    load_followup_config,
)
from luatgt.qa.llm_client import LLMError, make_llm_client
from luatgt.qa.service import (
    RELATED_HEADING,
    QAService,
    citation_label,
    covers_all_words,
    doc_label,
    fold,
    merge_related,
)
from luatgt.retrieval.search import SearchHit
from tests.helpers import ROOT
from tests.test_retrieval import FakeEmbedder

CFG = load_followup_config(ROOT / "config" / "followup.yaml")
AS_OF = date(2026, 10, 20)


def _vio(key="A/D1/K1/Pa", vehicles=("xe_may",), low=1_000_000, high=2_000_000, attrs=None, who="ca_nhan", **kw):
    return {"provision_key": key, "version_no": 1, "hanh_vi": "Hành vi", "phuong_tien": list(vehicles),
            "doi_tuong": who, "muc_phat_min": low, "muc_phat_max": high, "tru_diem_gplx": kw.get("points"),
            "tuoc_gplx_min_thang": kw.get("t_min"), "tuoc_gplx_max_thang": kw.get("t_max"),
            "bien_phap_bo_sung": [], "attributes": attrs or {}}


def _c(*a, score=1.0, **kw):
    return Candidate(_vio(*a, **kw), score)


ALCOHOL = [
    _c("A/D7/K6/Pa", ("xe_may",), 2_000_000, 3_000_000, {"nong_do_con": "duoi_50mg"}),
    _c("A/D7/K9/Pd", ("xe_may",), 8_000_000, 10_000_000, {"nong_do_con": "tren_80mg"}),
    _c("A/D6/K6/Pc", ("o_to",), 6_000_000, 8_000_000, {"nong_do_con": "duoi_50mg"}),
    _c("A/D6/K11/Pa", ("o_to",), 30_000_000, 40_000_000, {"nong_do_con": "tren_80mg"}),
]


def test_no_candidate_is_not_found():
    assert decide([], {}, 0, CFG).status == "not_found"
    assert decide(ALCOHOL, {"phuong_tien": "xe_dap"}, 0, CFG).status == "not_found"


def test_single_candidate_answers():
    assert decide(ALCOHOL[:1], {}, 0, CFG).status == "answered"


def test_same_outcome_answers_without_asking():
    same = [_c("A/D1/K1/Pa", ("xe_may",)), _c("A/D1/K1/Pb", ("o_to",))]
    assert decide(same, {}, 0, CFG).status == "answered"


def test_asks_highest_gain_dimensions_limited_per_round():
    d = decide(ALCOHOL, {}, 0, CFG)
    assert d.status == "need_clarification" and set(d.dimensions) == {"phuong_tien", "nong_do_con"}
    assert len(d.dimensions) <= CFG.max_questions_per_round


def test_selecting_slots_narrows_to_one():
    d = decide(ALCOHOL, {"phuong_tien": "xe_may", "nong_do_con": "tren_80mg"}, 1, CFG)
    assert d.status == "answered" and d.candidates[0].violation["muc_phat_max"] == 10_000_000


def test_unknown_does_not_filter_and_dimension_is_not_asked_again():
    assert len(filter_candidates(ALCOHOL, {"phuong_tien": UNKNOWN})) == 4
    d = decide(ALCOHOL, {"phuong_tien": UNKNOWN}, 1, CFG)
    assert "phuong_tien" not in d.dimensions


def test_round_limit_returns_table_of_cases():
    d = decide(ALCOHOL, {}, CFG.max_rounds, CFG)
    assert d.status == "answered" and d.exhausted and len(d.candidates) == 4


def test_vehicle_neutral_row_only_used_without_exact_match():
    rows = [_c("A/D1/K1/Pa", ("xe_may",)), _c("A/D12/K2/Pa", ("khong_ap_dung",), low=1, high=2)]
    assert [c.violation["provision_key"] for c in filter_candidates(rows, {"phuong_tien": "xe_may"})] == ["A/D1/K1/Pa"]
    assert [c.violation["provision_key"] for c in filter_candidates(rows, {"phuong_tien": "o_to"})] == ["A/D12/K2/Pa"]


def test_gain_zero_when_dimension_does_not_change_fine():
    rows = [_c("A/D1/K1/Pa", ("xe_may",)), _c("A/D1/K1/Pb", ("o_to",))]
    assert gain(rows, "phuong_tien") == 0.0
    assert gain(ALCOHOL, "nong_do_con") > CFG.gain_threshold


def test_questions_use_config_labels_and_unknown_option():
    q = build_questions(decide(ALCOHOL, {}, 0, CFG), CFG)
    vehicle = next(x for x in q if x["dimension"] == "phuong_tien")
    assert vehicle["question"] == "Bạn điều khiển loại phương tiện nào?"
    assert {"value": "xe_may", "label": "Xe máy"} in vehicle["options"]
    assert vehicle["options"][-1]["value"] == UNKNOWN


def test_always_asks_vehicle_when_fines_differ_by_vehicle_even_with_low_gain():
    """D-029: câu không nêu loại xe, mức phạt khác theo loại xe → hỏi loại xe dù entropy thấp."""
    rows = [_c("A/D7/K1/Pa", ("xe_may",), score=10.0), _c("A/D6/K1/Pa", ("o_to",), 3_000_000, 4_000_000, score=0.1)]
    assert gain(rows, "phuong_tien") < CFG.gain_threshold
    d = decide(rows, {}, 0, CFG)
    assert d.status == "need_clarification" and d.dimensions[0] == "phuong_tien"
    old = type(CFG)(CFG.max_rounds, CFG.max_questions_per_round, CFG.gain_threshold,
                    {**CFG.dimensions, "phuong_tien": {**CFG.dimensions["phuong_tien"], "always_ask": False}})
    assert decide(rows, {}, 0, old).status == "answered"


def test_vehicle_not_asked_when_named_or_fine_is_the_same():
    rows = [_c("A/D7/K1/Pa", ("xe_may",)), _c("A/D6/K1/Pa", ("o_to",), 3_000_000, 4_000_000)]
    assert decide(rows, {"phuong_tien": ["xe_may"]}, 0, CFG).status == "answered"
    same = [_c("A/D7/K1/Pa", ("xe_may",)), _c("A/D8/K1/Pa", ("xe_dap",))]
    assert decide(same, {}, 0, CFG).status == "answered"


def test_vehicle_question_always_offers_common_vehicles_first():
    vehicle = next(x for x in build_questions(decide(ALCOHOL, {}, 0, CFG), CFG) if x["dimension"] == "phuong_tien")
    values = [o["value"] for o in vehicle["options"]]
    assert values[:3] == ["xe_may", "o_to", "xe_dap"] and values[-1] == UNKNOWN
    assert len(values) == len(set(values))


def test_merge_related_renumbers_citations_and_keeps_one_basis():
    cit = lambda i, key: Citation(id=f"c{i}", provision_key=key, version_no=1, label=key, valid_from=date(2025, 1, 1))
    provisions = AskResponse(status="answered", as_of_date=AS_OF, disclaimer="d",
                             answer_markdown="Quy định:\n- Cấm X [c1]\n- Cấm Y [c2]\n\nCăn cứ: [c1] L1; [c2] L2.",
                             citations=[cit(1, "L/D33/K1"), cit(2, "L/D33/K2")])
    fact = make_fact(_vio(key="N/D7/K3/Pe"), "c1")
    related = AskResponse(status="answered", as_of_date=AS_OF, disclaimer="d", facts=[fact],
                          answer_markdown="Theo quy định:\n- Phạt X [c1]\n\nCăn cứ: [c1] N.",
                          citations=[cit(1, "N/D7/K3/Pe")], related_questions=["q?"])
    merged = merge_related(provisions, related)
    assert [c.id for c in merged.citations] == ["c1", "c2", "c3"]
    assert merged.citations[2].provision_key == "N/D7/K3/Pe" and merged.facts[0].citation_ids == ["c3"]
    assert "- Phạt X [c3]" in merged.answer_markdown and RELATED_HEADING in merged.answer_markdown
    assert merged.answer_markdown.count("Căn cứ:") == 1 and merged.answer_markdown.rstrip().endswith("[c3] N/D7/K3/Pe.")
    assert merged.related_questions == ["q?"]
    assert merge_related(provisions, None) is provisions


def _hit(text_: str, similarity: float, key: str = "N/D7/K2/Ph") -> SearchHit:
    return SearchHit(chunk_id=key, provision_key=key, version_no=1, so_hieu="168/2024/NĐ-CP",
                     hierarchy_path="NĐ 168 > Điều 7 > Khoản 2 > Điểm h", display_text=text_,
                     valid_from=date(2025, 1, 1), valid_to=date(9999, 12, 31), score=1.0, similarity=similarity)


HELMET = "Không đội “mũ bảo hiểm cho người đi mô tô, xe máy” khi tham gia giao thông"


def test_fold_and_word_coverage():
    assert fold("Đội MŨ bảo hiểm") == "doi mu bao hiem"
    stop = ["bị", "phạt"]
    assert covers_all_words("không đội mũ bảo hiểm", _hit(HELMET, 0.5), stop)
    assert covers_all_words("KHONG DOI MU BAO HIEM", _hit(HELMET, 0.5), stop)   # gõ không dấu
    assert not covers_all_words("không bật đèn", _hit(HELMET, 0.5), stop)
    assert not covers_all_words("mũ", _hit("mũi tên chỉ hướng", 0.5), stop)       # khớp nguyên từ, không khớp chuỗi con
    assert not covers_all_words("bị phạt", _hit(HELMET, 0.5), stop)               # chỉ có từ dừng


@pytest.mark.parametrize("query, similarity, relevant", [
    ("không đội mũ bảo hiểm", 0.56, True),    # tầng một
    ("không đội mũ bảo hiểm", 0.541, True),   # tầng hai: dưới 0,55 nhưng khớp đủ từ (D-030)
    ("không đội mũ bảo hiểm", 0.49, False),   # dưới mức sàn
    ("bóng đá", 0.53, False),                 # đủ điểm sàn nhưng không khớp từ
    ("thời tiết hôm nay", 0.49, False),
])
def test_two_tier_relevance(settings, query, similarity, relevant):
    service = object.__new__(QAService)
    service.settings = settings
    ranked = service._ranked([_hit(HELMET, similarity)], query)
    assert (ranked is not None) is relevant


def _fact():
    return make_fact(_vio(attrs={"che_tai_co_dieu_kien": [{"dieu_kien": "chủ xe trực tiếp lái", "tru_diem_gplx": 2}]}), "c1")


CIT = [Citation(id="c1", provision_key="A/D1", version_no=1, label="Điều 1", valid_from=date(2025, 1, 1))]


def test_template_includes_numbers_citation_date_and_condition():
    body = template_answer([_fact()], CIT, AS_OF, CFG, False)
    assert "1.000.000–2.000.000 đồng" in body and "[c1]" in body and "20/10/2026" in body
    assert "chủ xe trực tiếp lái" in body and "trừ 2 điểm" in body
    assert check_answer(body, [_fact()], CIT) == []


@pytest.mark.parametrize("body, problem", [
    ("Phạt 1.000.000 đồng.", "không có trích dẫn"),
    ("Phạt 1.000.000 đồng [c9].", "trích dẫn lạ c9"),
    ("Phạt 5.000.000 đồng [c1].", "số tiền lạ 5.000.000"),
])
def test_check_answer_rejects(body, problem):
    assert problem in check_answer(body, [_fact()], CIT)


class FakeLLM:
    def __init__(self, *replies):
        self.replies, self.calls = list(replies), 0

    def complete(self, system, user):
        self.calls += 1
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


GOOD = "Phạt từ 1.000.000 đến 2.000.000 đồng [c1]."
BAD = "Phạt 9.000.000 đồng [c1]."


@pytest.mark.parametrize("replies, calls, result", [
    ([GOOD], 1, GOOD), ([BAD, GOOD], 2, GOOD), ([BAD, BAD], 2, "TEMPLATE"), ([LLMError("x")], 1, "TEMPLATE"),
])
def test_llm_retries_once_then_template(replies, calls, result):
    llm = FakeLLM(*replies)
    assert render_with_llm(llm, "q", [_fact()], CIT, [], AS_OF, "TEMPLATE") == result
    assert llm.calls == calls


def test_no_llm_uses_template():
    assert render_with_llm(None, "q", [], [], [], AS_OF, "TEMPLATE") == "TEMPLATE"
    assert make_llm_client(load_settings(env={})) is None


def test_labels():
    assert citation_label("168-2024-ND-CP/D18/K4/Pdd") == "Điểm đ khoản 4 Điều 18"
    assert citation_label("X/D5/K2") == "Khoản 2 Điều 5"
    assert doc_label("168/2024/NĐ-CP") == "NĐ 168/2024/NĐ-CP" and doc_label("36/2024/QH15") == "Luật 36/2024/QH15"


def test_fact_type():
    assert isinstance(_fact(), Fact)


K = "1-2024-ND-CP"
START = date(2025, 1, 1)


@pytest.fixture
def client(ctx, tmp_path):
    settings, engine, *_ = ctx
    settings = settings.model_copy(deep=True)
    settings.paths.events_dir = tmp_path / "events"
    settings.qa.min_similarity = 0.3   # FakeEmbedder không phản ánh độ liên quan thật
    settings.retrieval.query_expansions = {}
    rows = [("D7/K1/Pa", "xe_may", 2_000_000, 3_000_000, "duoi_50mg", "uống rượu lái xe cồn thấp"),
            ("D7/K2/Pa", "xe_may", 8_000_000, 10_000_000, "tren_80mg", "uống rượu lái xe cồn cao"),
            ("D6/K1/Pa", "o_to", 30_000_000, 40_000_000, "tren_80mg", "uống rượu lái xe ô tô")]
    with engine.begin() as conn:
        conn.execute(text("""INSERT INTO documents (vbpl_id, so_hieu, ten_van_ban, source_url, first_seen_at, last_crawled_at)
                             VALUES ('1', '1/2024/NĐ-CP', 'Nghị định 1', 'https://vbpl.vn/x', now(), now())"""))
        conn.execute(text("""INSERT INTO provisions (provision_id, vbpl_id, provision_key, level, number, text, ordinal)
                             VALUES ('1:D7', '1', :k, 'dieu', '7', '', 0)"""), {"k": f"{K}/D7"})
        for key, vehicle, low, high, level, act in rows:
            conn.execute(text("""INSERT INTO provision_versions (provision_key, version_no, text, source_vbpl_id,
                                 valid_from, valid_to, is_current)
                                 VALUES (:k, 1, :t, '1', :s, :e, true)"""),
                         {"k": f"{K}/{key}", "t": act, "s": START, "e": OPEN_END})
            conn.execute(text("""INSERT INTO violations (violation_id, provision_key, version_no, hanh_vi, phuong_tien,
                                 doi_tuong, muc_phat_min, muc_phat_max, attributes, valid_from, valid_to,
                                 extraction_method, needs_review)
                                 VALUES (:i, :k, 1, :a, :p, 'ca_nhan', :l, :h, CAST(:j AS jsonb), :s, :e, 'regex', false)"""),
                         {"i": f"{K}/{key}@v1#1", "k": f"{K}/{key}", "a": act, "p": [vehicle], "l": low, "h": high,
                          "j": f'{{"nong_do_con": "{level}"}}', "s": START, "e": OPEN_END})
    docs = [{"vbpl_id": "1", "so_hieu": "1/2024/NĐ-CP", "ten_van_ban": "Nghị định 1"}]
    versions = [{"provision_key": f"{K}/{r[0]}", "version_no": 1, "text": r[5], "valid_from": START, "valid_to": OPEN_END}
                for r in rows]
    load_chunks(engine, build_chunks(docs, [], versions, set()), FakeEmbedder())
    with TestClient(create_app(settings, engine, FakeEmbedder(), None)) as c:
        c.settings = settings
        yield c


@pytest.mark.integration
def test_api_clarify_then_answer_flow(client):
    first = client.post("/api/ask", json={"question": "uống rượu lái xe bị phạt bao nhiêu", "as_of_date": "2026-10-20"})
    body = first.json()
    assert first.status_code == 200 and body["status"] == "need_clarification"
    assert {q["dimension"] for q in body["follow_up_questions"]} == {"phuong_tien", "nong_do_con"}

    second = client.post("/api/ask", json={"session_id": body["session_id"],
                                           "selected": {"phuong_tien": "xe_may", "nong_do_con": "tren_80mg"}}).json()
    assert second["status"] == "answered" and second["session_id"] == body["session_id"]
    fact = second["facts"][0]
    assert (fact["muc_phat_min"], fact["muc_phat_max"]) == (8_000_000, 10_000_000)
    assert second["citations"][0]["id"] in fact["citation_ids"]
    assert second["citations"][0]["source_url"] == "https://vbpl.vn/x"
    assert second["disclaimer"] and second["as_of_date"] == "2026-10-20"


@pytest.mark.integration
def test_api_question_without_penalty_word_on_penalty_provision_goes_straight_to_fines(client):
    """D-030: đoạn đứng đầu đã là điều khoản xử phạt → luồng mức phạt luôn, không trích rồi lặp lại mức phạt."""
    first = client.post("/api/ask", json={"question": "uống rượu lái xe", "as_of_date": "2026-10-20"}).json()
    assert first["status"] == "need_clarification" and RELATED_HEADING not in first["answer_markdown"]
    assert first["follow_up_questions"][0]["dimension"] == "phuong_tien"
    second = client.post("/api/ask", json={"session_id": first["session_id"],
                                           "selected": {"phuong_tien": "xe_may", "nong_do_con": "tren_80mg"}}).json()
    assert second["status"] == "answered" and RELATED_HEADING not in second["answer_markdown"]
    assert [(f["muc_phat_min"], f["muc_phat_max"]) for f in second["facts"]] == [(8_000_000, 10_000_000)]


@pytest.mark.integration
def test_api_rule_question_quotes_rule_then_related_fines(client, ctx):
    """D-029: đoạn đứng đầu là quy định thuần (không có mức phạt) → trích quy định, rồi kèm mức phạt liên quan.
    Nhánh đã chọn ở vòng đầu được giữ ở vòng sau, kể cả khi truy vấn có thêm tên loại xe."""
    engine = ctx[1]
    client.settings.qa.min_similarity = 0.25   # FakeEmbedder: đoạn xử phạt chỉ đạt 0,276 với câu này
    rule = "uống rượu lái xe là hành vi bị nghiêm cấm"
    with engine.begin() as conn:
        conn.execute(text("""INSERT INTO provision_versions (provision_key, version_no, text, source_vbpl_id,
                             valid_from, valid_to, is_current) VALUES (:k, 1, :t, '1', :s, :e, true)"""),
                     {"k": f"{K}/D9/K2", "t": rule, "s": START, "e": OPEN_END})
        versions = [dict(r) for r in conn.execute(text(
            "SELECT provision_key, version_no, text, valid_from, valid_to FROM provision_versions")).mappings()]
    docs = [{"vbpl_id": "1", "so_hieu": "1/2024/NĐ-CP", "ten_van_ban": "Nghị định 1"}]
    load_chunks(engine, build_chunks(docs, [], versions, set()), FakeEmbedder())   # load_chunks thay toàn bộ chỉ mục
    first = client.post("/api/ask", json={"question": rule, "as_of_date": "2026-10-20"}).json()
    assert first["citations"][0]["provision_key"] == f"{K}/D9/K2"
    assert first["answer_markdown"].startswith("Quy định áp dụng") and RELATED_HEADING in first["answer_markdown"]
    assert first["status"] == "need_clarification" and first["follow_up_questions"][0]["dimension"] == "phuong_tien"
    second = client.post("/api/ask", json={"session_id": first["session_id"],
                                           "selected": {"phuong_tien": "xe_may", "nong_do_con": "tren_80mg"}}).json()
    assert second["status"] == "answered" and second["answer_markdown"].startswith("Quy định áp dụng")
    assert {f["phuong_tien"][0] for f in second["facts"]} == {"xe_may"}
    ids = {c["id"] for c in second["citations"]}
    assert all(i in ids for f in second["facts"] for i in f["citation_ids"])
    assert second["answer_markdown"].count("Căn cứ:") == 1


@pytest.mark.integration
def test_api_low_similarity_is_not_found(client):
    r = client.post("/api/ask", json={"question": "zzzz qqqq", "as_of_date": "2026-10-20"}).json()
    assert r["status"] == "not_found" and r["facts"] == []


@pytest.mark.integration
def test_api_unknown_session_and_empty_question(client):
    assert client.post("/api/ask", json={"session_id": "00000000-0000-0000-0000-000000000000"}).status_code == 404
    assert client.post("/api/ask", json={"question": "  "}).status_code == 422


@pytest.mark.integration
def test_api_provision_history_and_documents(client):
    r = client.get(f"/api/provisions/{K}/D7/K2/Pa", params={"as_of": "2026-10-20"}).json()
    assert r["current"]["version_no"] == 1 and len(r["versions"]) == 1
    assert client.get("/api/provisions/khong/co").status_code == 404
    assert client.get("/api/documents").json()[0]["so_hieu"] == "1/2024/NĐ-CP"
    assert client.get("/api/documents/1").json()["relations"] == []
    assert client.get("/api/documents/9").status_code == 404
    assert r["label"] == "Điểm a khoản 2 Điều 7" and r["document"]["so_hieu"] == "1/2024/NĐ-CP"
    tree = client.get("/api/documents/1/provisions", params={"as_of": "2026-10-20"}).json()["provisions"]
    assert tree and all("n_versions" in p for p in tree)
    added = client.get("/api/documents/1/provisions", params={"as_of": "2026-10-20"}).json()["added"]
    assert {a["label"] for a in added} >= {"Điểm a khoản 2 Điều 7", "Điểm a khoản 1 Điều 6"}
    assert client.get("/api/documents/9/provisions").status_code == 404


@pytest.mark.integration
def test_api_writes_events_and_feedback(client):
    sid = client.post("/api/ask", json={"question": "uống rượu lái xe", "as_of_date": "2026-10-20"}).json()["session_id"]
    assert client.post("/api/feedback", json={"session_id": sid, "thumbs": "down"}).json() == {"ok": True}
    assert client.post("/api/feedback", json={"session_id": sid, "thumbs": "x"}).status_code == 422
    files = sorted(client.settings.paths.events_dir.glob("*.jsonl"))
    assert len(files) == 2   # mỗi event một file, Spark không đọc lại file đã nối thêm
    lines = sorted((f.read_text("utf-8").strip() for f in files), key=lambda x: json.loads(x)["ingest_time"])
    assert len(lines) == 2 and '"thumbs": "down"' in lines[1] and '"ingest_time"' in lines[1]


@pytest.mark.integration
def test_api_health_and_stats(client):
    assert client.get("/api/health").json()["postgres"] == "ok"
    summary = client.get("/api/stats/summary").json()
    assert summary["n_questions"] == 0 and summary["last_run"] is None
    assert summary["jobs"] == [] and summary["quarantine_by_run"] == []
    assert client.get("/api/stats/topics", params={"from": "2026-01-01T00:00:00", "to": "2026-02-01T00:00:00"}).json() == []


@pytest.mark.integration
def test_api_stats_shows_job_runs_and_freshness(client, ctx):
    """M11 mục 2: dashboard thấy lần chạy từng job, thời gian chạy, độ tươi dữ liệu và quarantine theo run."""
    from luatgt.common.job_runs import job_run

    engine = ctx[1]
    with job_run(engine, "build_gold") as run, engine.begin() as conn:
        conn.execute(text("""INSERT INTO quarantine (stage, entity_ref, rule, run_id)
                                 VALUES ('extract', 'x', 'r', :id)"""), {"id": run.run_id})
    with pytest.raises(RuntimeError), job_run(engine, "build_index"):
        raise RuntimeError("hỏng")
    summary = client.get("/api/stats/summary").json()
    jobs = {j["job"]: j for j in summary["jobs"]}
    assert jobs["build_gold"]["status"] == "success" and jobs["build_gold"]["duration_s"] >= 0
    assert jobs["build_gold"]["data_crawled_at"] is not None and summary["last_crawled_at"] is not None
    assert jobs["build_index"]["status"] == "failed"
    gold_run = next(r for r in summary["quarantine_by_run"] if r["run_id"] == str(run.run_id))
    assert gold_run["job"] == "build_gold" and gold_run["n"] == 1
    assert summary["quarantine_without_run"] == 0
