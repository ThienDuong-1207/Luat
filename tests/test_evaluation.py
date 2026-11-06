"""M11: tách dev/test, chỉ số theo nhóm, thẻ tái lập (spec 16.1, 16.4, 16.5)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml
from sqlalchemy import text

from luatgt.evaluation import (
    MIN_GROUP_FOR_RATE,
    QuestionSetError,
    Rate,
    amended_group,
    by_split,
    data_fingerprint,
    format_rate,
    git_state,
    group_labels,
    group_metrics,
    low_groups,
    overall,
    questions_hash,
    source_group,
    validate_questions,
    vehicle_group,
)

ROOT = Path(__file__).parent.parent


def _q(qid, split="dev", **kw):
    return {"id": qid, "split": split, "question": "Xe máy vượt đèn đỏ", "as_of_date": "2026-10-20",
            "expected_provision_keys": ["168-2024-ND-CP/D7/K4/Pc"], **kw}


def test_real_question_set_is_valid_and_all_dev():
    """66 câu cũ đã dùng để chỉnh query_expansions (D-021) nên phải là dev."""
    questions = yaml.safe_load((ROOT / "eval" / "questions.yaml").read_text("utf-8"))
    validate_questions(questions)
    old = [q for q in questions if int(q["id"][1:]) <= 66]
    assert len(old) == 66 and all(q["split"] == "dev" for q in old)


@pytest.mark.parametrize("bad, msg", [
    ({"split": None}, "split"),
    ({"split": "train"}, "split"),
    ({"wording": "binh_thuong"}, "wording"),
    ({"expected_provision_keys": []}, "expected_provision_keys"),
])
def test_validate_rejects(bad, msg):
    with pytest.raises(QuestionSetError, match=msg):
        validate_questions([{**_q("q1"), **bad}])


def test_validate_rejects_duplicate_id():
    with pytest.raises(QuestionSetError, match="trùng"):
        validate_questions([_q("q1"), _q("q1", "test")])


def test_by_split():
    s = by_split([_q("a"), _q("b", "test"), _q("c")])
    assert [q["id"] for q in s["dev"]] == ["a", "c"] and [q["id"] for q in s["test"]] == ["b"]


@pytest.mark.parametrize("question, group", [
    ("Đi xe máy uống rượu phạt bao nhiêu?", "xe_may"),
    ("Ô tô chạy quá tốc độ 15 km/h", "o_to"),
    ("Đi xe đạp sau khi uống rượu", "xe_dap"),
    ("Người đi bộ vượt đèn đỏ", "khac"),
    ("Xe máy và ô tô dừng sai chỗ", "nhieu_loai"),
    ("Không mang giấy phép lái xe", "khong_neu"),
])
def test_vehicle_group(question, group):
    assert vehicle_group(question) == group


def test_source_and_amended_group():
    q = _q("a", expected_provision_keys=["168-2024-ND-CP/D6/K1", "168-2024-ND-CP/D6/K2"])
    assert source_group(q) == "168-2024-ND-CP"
    assert source_group(_q("b", expected_provision_keys=["1-2024/D1", "2-2025/D1"])) == "nhieu_van_ban"
    assert amended_group(q, set()) == "khong_sua_doi"
    assert amended_group(q, {"168-2024-ND-CP/D6/K2"}) == "co_sua_doi"
    assert amended_group(_q("c", expected_version_no=2), set()) == "co_sua_doi"
    assert group_labels(q, set())["Cách viết"] == "chua_gan"
    assert group_labels(_q("d", wording="doi_thuong"), set())["Cách viết"] == "doi_thuong"


def test_rate_skips_none_and_formats_small_groups():
    r = Rate()
    for v in (True, None, False):
        r.add(v)
    assert (r.ok, r.n) == (1, 2)
    assert format_rate(r) == "1/2"  # dưới MIN_GROUP_FOR_RATE: chỉ số đếm
    big = Rate(ok=7, n=MIN_GROUP_FOR_RATE)
    assert format_rate(big) == "70.0% (7/10)"
    assert format_rate(Rate()) == "–"


def test_group_metrics_and_low_group_flag():
    # 20 câu xe máy đúng hết, 10 câu ô tô đúng 5 → ô tô 50% so với tổng 83,3%: bị đánh dấu
    records = [{"id": f"m{i}", "recall5": True} for i in range(20)] + \
              [{"id": f"o{i}", "recall5": i < 5} for i in range(10)]
    labels = {r["id"]: {"Phương tiện": "xe_may" if r["id"][0] == "m" else "o_to"} for r in records}
    rows = group_metrics(records, labels, ["recall5"])
    total = overall(records, ["recall5"])
    by_group = {r.group: r for r in rows}
    assert by_group["xe_may"].rates["recall5"].value == 1.0
    assert by_group["o_to"].n_questions == 10
    flagged = low_groups(rows, total)
    assert [(r.group, m) for r, m in flagged] == [("o_to", "recall5")]


def test_low_groups_ignores_small_groups():
    records = [{"id": f"m{i}", "recall5": True} for i in range(20)] + [{"id": "x", "recall5": False}]
    labels = {r["id"]: {"d": "x" if r["id"] == "x" else "m"} for r in records}
    rows = group_metrics(records, labels, ["recall5"])
    assert low_groups(rows, overall(records, ["recall5"])) == []


def test_questions_hash_ignores_order_but_not_content():
    a, b = _q("a"), _q("b", "test")
    assert questions_hash([a, b]) == questions_hash([b, a])
    assert questions_hash([a]) != questions_hash([{**a, "expected_provision_keys": ["khac"]}])


def test_git_state_excludes_reports(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "f.txt").write_text("x")
    env = ["-c", "user.email=t@t", "-c", "user.name=t"]
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", *env, "commit", "-qm", "init"], cwd=tmp_path, check=True)
    (tmp_path / "eval" / "reports").mkdir(parents=True)
    (tmp_path / "eval" / "reports" / "report.md").write_text("báo cáo")
    commit, dirty = git_state(tmp_path)
    assert len(commit) == 12 and not dirty
    (tmp_path / "f.txt").write_text("y")
    assert git_state(tmp_path)[1]


def test_git_state_without_git(tmp_path):
    def boom(*a, **kw):
        raise OSError("no git")
    assert git_state(tmp_path, run=boom) == ("không rõ", True)


@pytest.mark.integration
def test_data_fingerprint_ignores_timestamps(env):
    """md5 chỉ tính trên cột nội dung: cập nhật updated_at không đổi md5, đổi nội dung thì đổi."""
    _, engine, _ = env
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM violations"))
        conn.execute(text("DELETE FROM provision_versions"))
        conn.execute(text("""INSERT INTO provision_versions (provision_key, version_no, text, source_vbpl_id,
                             valid_from, is_current) VALUES ('K/D1', 1, 'a', 1, '2025-01-01', true)"""))
    before = data_fingerprint(engine)
    assert before["provision_versions"][0] == 1 and before["violations"] == (0, before["violations"][1])
    with engine.begin() as conn:
        conn.execute(text("UPDATE provision_versions SET updated_at = now() + interval '1 day'"))
    assert data_fingerprint(engine) == before
    with engine.begin() as conn:
        conn.execute(text("UPDATE provision_versions SET text = 'b'"))
    assert data_fingerprint(engine)["provision_versions"] != before["provision_versions"]
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM provision_versions"))
