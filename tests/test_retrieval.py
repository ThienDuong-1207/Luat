"""M6: chunking, phân tích câu hỏi, RRF (không mạng); bộ lọc hiệu lực trên Postgres thật (integration)."""

from __future__ import annotations

import hashlib
from datetime import date

import pytest

from luatgt.common.config import RetrievalSettings
from luatgt.jobs.build_index import build_chunks, load_chunks
from luatgt.modeling.versions import OPEN_END
from luatgt.retrieval.query import parse_question
from luatgt.retrieval.search import hybrid_search, keyword_query, rrf_merge

DOCS = [{"vbpl_id": "1", "so_hieu": "1/2024/NĐ-CP", "ten_van_ban": "Nghị định 1"},
        {"vbpl_id": "2", "so_hieu": "2/2026/NĐ-CP", "ten_van_ban": "Nghị định sửa đổi"}]
K = "1-2024-ND-CP"
D1, D2 = date(2025, 1, 1), date(2026, 8, 15)


def _prov(key, level, pid, title=None, parent=None):
    return {"provision_id": pid, "provision_key": key, "level": level, "title": title, "parent_id": parent}


PROV = [_prov(f"{K}/CII", "chuong", "1:CII"),
        _prov(f"{K}/D6", "dieu", "1:D6", "Xử phạt người lái xe", "1:CII")]


def _ver(key, no, body, start=D1, end=OPEN_END):
    return {"provision_key": key, "version_no": no, "text": body, "valid_from": start, "valid_to": end}


VERSIONS = [
    _ver(f"{K}/D6", 1, ""), _ver(f"{K}/D6/K1", 1, "Phạt tiền từ 1 đồng đến 2 đồng đối với:"),
    _ver(f"{K}/D6/K1/Pa", 1, "Vượt đèn đỏ;"),
    _ver(f"{K}/D6/K2", 1, "Phạt tiền từ 3 đồng đến 4 đồng đối với người đi sai làn."),
    _ver(f"{K}/D7", 1, "Điều không có khoản."),
    _ver("2-2026-ND-CP/D1", 1, "Sửa đổi khoản 1 Điều 6."),
]


def test_chunks_are_leaves_only():
    keys = {c.provision_key for c in build_chunks(DOCS, PROV, VERSIONS, {"2"})}
    assert keys == {f"{K}/D6/K1/Pa", f"{K}/D6/K2", f"{K}/D7"}


def test_diem_embed_text_has_khoan_head_and_path():
    c = next(c for c in build_chunks(DOCS, PROV, VERSIONS, {"2"}) if c.provision_key.endswith("Pa"))
    assert c.embed_text == ("[Nghị định 1] - [Chương II > Điều 6. Xử phạt người lái xe > Khoản 1 > Điểm a] : "
                            "Phạt tiền từ 1 đồng đến 2 đồng đối với: Vượt đèn đỏ;")
    assert c.display_text == "Vượt đèn đỏ;" and c.chunk_id == f"{K}/D6/K1/Pa@v1"


def test_each_version_is_a_chunk_and_repealed_has_none():
    vs = [*VERSIONS, _ver(f"{K}/D8", 1, "Cũ", D1, D2), _ver(f"{K}/D8", 2, "Mới", D2),
          _ver(f"{K}/D9", 1, "Có", D1, D2), _ver(f"{K}/D9", 2, None, D2)]
    chunks = {c.chunk_id: c for c in build_chunks(DOCS, PROV, vs, {"2"})}
    assert chunks[f"{K}/D8@v1"].valid_to == D2 and chunks[f"{K}/D8@v2"].valid_from == D2
    assert f"{K}/D9@v2" not in chunks


def test_changed_head_splits_diem_chunk():
    vs = [_ver(f"{K}/D6/K1", 1, "Phạt cũ:", D1, D2), _ver(f"{K}/D6/K1", 2, "Phạt mới:", D2),
          _ver(f"{K}/D6/K1/Pa", 1, "Vượt đèn đỏ;")]
    a, b = build_chunks(DOCS, PROV, vs, set())
    assert (a.chunk_id, a.valid_to) == (f"{K}/D6/K1/Pa@v1", D2) and "Phạt cũ" in a.embed_text
    assert (b.chunk_id, b.valid_from) == (f"{K}/D6/K1/Pa@v1#2", D2) and "Phạt mới" in b.embed_text


def test_rrf_rewards_presence_in_both_branches():
    a, b, c = {"chunk_id": "a"}, {"chunk_id": "b"}, {"chunk_id": "c"}
    out = rrf_merge([[a, b], [c, b]], 60)
    assert out[0][0] == b and out[0][1] == pytest.approx(2 / 62)


def test_keyword_query_uses_or_and_drops_stopwords():
    assert keyword_query("Vượt đèn đỏ bị phạt bao nhiêu?", ["bị", "phạt", "bao", "nhiêu"]) == "vượt | đèn | đỏ"
    assert keyword_query("bị phạt", ["bị", "phạt"]) == ""


@pytest.mark.parametrize("q, slots", [
    ("Xe máy vượt đèn đỏ", {"phuong_tien": ["xe_may"]}),
    ("xe máy chuyên dùng chạy quá tốc độ", {"phuong_tien": ["xe_may_chuyen_dung"]}),
    ("Ô tô có nồng độ cồn 60 mg", {"phuong_tien": ["o_to"], "nong_do_con": "50_80mg"}),
    ("mô tô vượt 25 km/h", {"phuong_tien": ["xe_may"], "vuot_toc_do": "20_35kmh"}),
    ("đi bộ qua đường", {"phuong_tien": ["nguoi_di_bo"]}),
])
def test_parse_question_slots(q, slots):
    assert parse_question(q, date(2026, 10, 20)).slots == slots


def test_parse_question_date():
    today = date(2026, 10, 20)
    assert parse_question("hôm 1/8 tôi bị phạt", today).as_of == date(2026, 8, 1)
    assert parse_question("ngày 15/08/2025", today).as_of == date(2025, 8, 15)
    assert parse_question("nồng độ 0,25 mg", today).as_of == today


class FakeEmbedder:
    """Vector tất định theo từ, đủ để kiểm tra lọc; không phản ánh chất lượng thật."""

    def embed(self, texts):
        out = []
        for t in texts:
            v = [0.0] * 1024
            for w in t.lower().split():
                v[int(hashlib.md5(w.encode()).hexdigest(), 16) % 1024] += 1.0
            norm = sum(x * x for x in v) ** 0.5 or 1.0
            out.append([x / norm for x in v])
        return out


@pytest.fixture
def indexed(ctx):
    _, engine, *_ = ctx
    vs = [_ver(f"{K}/D8", 1, "Vượt đèn đỏ phạt mức cũ", D1, D2), _ver(f"{K}/D8", 2, "Vượt đèn đỏ phạt mức mới", D2),
          _ver(f"{K}/D9", 1, "Đi sai làn đường"), _ver(f"{K}/D10", 1, "Vượt đèn đỏ quy định đã hết", D1, D2)]
    load_chunks(engine, build_chunks(DOCS, PROV, vs, {"2"}), FakeEmbedder())
    return engine


CFG = RetrievalSettings(k=5, stopwords=["phạt"])


@pytest.mark.integration
@pytest.mark.parametrize("mode", ["hybrid", "vector", "keyword"])
def test_validity_filter_applies_to_every_branch(indexed, mode):
    q = "vượt đèn đỏ"
    before = hybrid_search(indexed, FakeEmbedder(), q, date(2026, 8, 1), CFG, mode=mode)
    after = hybrid_search(indexed, FakeEmbedder(), q, date(2026, 10, 20), CFG, mode=mode)
    assert f"{K}/D8@v1" in {h.chunk_id for h in before} and f"{K}/D8@v2" not in {h.chunk_id for h in before}
    ids = {h.chunk_id for h in after}
    assert f"{K}/D8@v2" in ids and f"{K}/D8@v1" not in ids and f"{K}/D10@v1" not in ids


@pytest.mark.integration
def test_boundary_date_uses_new_version(indexed):
    ids = {h.chunk_id for h in hybrid_search(indexed, FakeEmbedder(), "vượt đèn đỏ", D2, CFG)}
    assert f"{K}/D8@v2" in ids and f"{K}/D8@v1" not in ids


@pytest.mark.integration
def test_without_filter_all_versions_return(indexed):
    ids = {h.chunk_id for h in hybrid_search(indexed, FakeEmbedder(), "vượt đèn đỏ", D2, CFG, apply_validity=False)}
    assert {f"{K}/D8@v1", f"{K}/D8@v2"} <= ids


@pytest.mark.integration
def test_load_chunks_only_embeds_changes(indexed):
    class Counting(FakeEmbedder):
        calls = 0

        def embed(self, texts):
            Counting.calls += len(texts)
            return super().embed(texts)

    vs = [_ver(f"{K}/D8", 1, "Vượt đèn đỏ phạt mức cũ", D1, D2), _ver(f"{K}/D9", 1, "Đi sai làn đường mới")]
    stats = load_chunks(indexed, build_chunks(DOCS, PROV, vs, {"2"}), Counting())
    assert stats == {"chunks": 2, "embedded": 1, "removed": 2} and Counting.calls == 1
