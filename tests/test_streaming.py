"""M9: sinh event, sink idempotent, watermark, khử trùng và chạy lại từ checkpoint."""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).parent.parent / "eval"))
from gen_events import GenConfig, generate

from luatgt.jobs.spark import get_spark
from luatgt.streaming.qa_events_stream import dropped_rows, start_query, upsert_counts

T0 = datetime(2026, 1, 5, 8, 0, tzinfo=UTC)


def event(i: str, minute: float, kind: str = "ask", thumbs: str | None = None, ingest: float | None = None) -> str:
    at = T0 + timedelta(minutes=minute)
    return json.dumps({"event_id": i, "event_time": at.isoformat(), "type": kind, "session_id": "s", "topic": "t",
                       "thumbs": thumbs, "ingest_time": (T0 + timedelta(minutes=ingest or minute)).isoformat()})


def write(folder: Path, name: str, lines: list[str]) -> None:
    folder.mkdir(exist_ok=True)
    (folder / name).write_text("\n".join(lines) + "\n", "utf-8")


def counts(engine) -> dict:
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT window_start, n_questions, n_thumbs_down FROM qa_topic_counts")).all()
    return {int((r[0] - T0).total_seconds() // 60): (r[1], r[2]) for r in rows}


def test_generate_is_deterministic_and_truth_excludes_duplicates():
    cfg = GenConfig(n_events=300, minutes=30)
    a, truth_a = generate(cfg)
    b, truth_b = generate(cfg)
    assert a == b and truth_a == truth_b
    n_rows = sum(map(len, a.values()))
    assert n_rows == 300 + truth_a["n_duplicates"]
    assert truth_a["n_questions"] + sum(r["type"] == "feedback" for rows in a.values() for r in rows) <= n_rows


@pytest.mark.integration
def test_upsert_overwrites_same_key(ctx):
    _, engine, *_ = ctx
    row = {"window_start": T0, "window_end": T0 + timedelta(minutes=10), "topic": "t", "n_questions": 3, "n_thumbs_down": 1}
    upsert_counts(engine, [row], 1)
    upsert_counts(engine, [row], 1)
    upsert_counts(engine, [{**row, "n_questions": 5}], 2)
    assert counts(engine) == {0: (5, 1)}


@pytest.fixture(scope="module")
def spark(env):
    s = get_spark(env[0])
    s.conf.set("spark.sql.streaming.noDataMicroBatches.enabled", "true")
    yield s
    s.stop()


def run(spark, settings, engine, source, checkpoint):
    query = start_query(spark, settings, engine, source, checkpoint, watermark="5 minutes", max_files=1)
    query.awaitTermination()
    assert query.exception() is None
    return [json.loads(p.json) for p in query.recentProgress]


@pytest.mark.integration
def test_stream_dedupes_drops_late_and_survives_replay(ctx, spark, tmp_path):
    settings, engine, *_ = ctx
    source, checkpoint = tmp_path / "src", tmp_path / "cp"
    write(source, "a.jsonl", [event("1", 1), event("1", 1), event("2", 2, "feedback", "down")])
    write(source, "b.jsonl", [event("3", 30)])                    # đẩy watermark lên 25
    write(source, "b2.jsonl", [event("7", 30.5)])                 # Spark loại event trễ theo watermark của batch trước
    write(source, "c.jsonl", [event("4", 3, ingest=31), event("5", 31)])  # 4 trễ quá watermark
    write(source, "d.jsonl", [event("6", 500, ingest=32)])        # đồng hồ client sai, phải bị loại
    for i, name in enumerate(["a", "b", "b2", "c", "d"]):               # đọc đúng thứ tự
        os.utime(source / f"{name}.jsonl", (1_800_000_000 + i, 1_800_000_000 + i))

    progress = run(spark, settings, engine, source, checkpoint)
    assert counts(engine) == {0: (1, 1), 30: (3, 0)}
    assert sum(map(dropped_rows, progress)) == 1

    last = max(int(p.name) for p in (checkpoint / "commits").glob("[0-9]*"))
    (checkpoint / "commits" / str(last)).unlink()
    (checkpoint / "commits" / f".{last}.crc").unlink(missing_ok=True)
    run(spark, settings, engine, source, checkpoint)
    assert counts(engine) == {0: (1, 1), 30: (3, 0)}
