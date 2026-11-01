"""M7: câu hỏi phụ, kiểm tra câu trả lời, API. LLM luôn là client giả, không gọi mạng."""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from luatgt.api.main import create_app
from luatgt.common.config import load_settings
from luatgt.jobs.build_index import build_chunks, load_chunks
from luatgt.modeling.versions import OPEN_END
from luatgt.qa.answer import (
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
from luatgt.qa.service import citation_label, doc_label
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


@pytest.mark.integration
def test_api_writes_events_and_feedback(client):
    sid = client.post("/api/ask", json={"question": "uống rượu lái xe", "as_of_date": "2026-10-20"}).json()["session_id"]
    assert client.post("/api/feedback", json={"session_id": sid, "thumbs": "down"}).json() == {"ok": True}
    assert client.post("/api/feedback", json={"session_id": sid, "thumbs": "x"}).status_code == 422
    lines = next(client.settings.paths.events_dir.glob("*.jsonl")).read_text("utf-8").splitlines()
    assert len(lines) == 2 and '"thumbs": "down"' in lines[1] and '"ingest_time"' in lines[1]


@pytest.mark.integration
def test_api_health_and_stats(client):
    assert client.get("/api/health").json()["postgres"] == "ok"
    assert client.get("/api/stats/topics", params={"from": "2026-01-01T00:00:00", "to": "2026-02-01T00:00:00"}).json() == []
