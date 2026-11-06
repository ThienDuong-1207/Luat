"""Ghi mỗi lần chạy job build vào bảng job_runs (spec 3.3: observability và lineage).

Dùng:
    with job_run(engine, "build_gold") as run:
        ... ghi quarantine với run.run_id ...
        run.stats = {...}

Job lỗi vẫn được ghi (status=failed, error) rồi ném lại lỗi, để Airflow thấy task fail.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.engine import Engine

log = logging.getLogger(__name__)
MAX_ERROR_CHARS = 2000


@dataclass
class JobRun:
    run_id: uuid.UUID
    job: str
    stats: dict = field(default_factory=dict)


def start(engine: Engine, job: str) -> JobRun:
    run = JobRun(uuid.uuid4(), job)
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO job_runs (run_id, job, started_at, status, data_crawled_at)
            VALUES (:id, :job, clock_timestamp(), 'running', (SELECT max(last_crawled_at) FROM documents))"""),
            {"id": run.run_id, "job": job})
    return run


def finish(engine: Engine, run: JobRun, status: str, error: str | None = None) -> None:
    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE job_runs SET finished_at = clock_timestamp(), status = :st, error = :err,
                                stats = CAST(:stats AS jsonb)
            WHERE run_id = :id"""),
            {"id": run.run_id, "st": status, "err": error and error[:MAX_ERROR_CHARS],
             "stats": json.dumps(run.stats, ensure_ascii=False, default=str)})


@contextmanager
def job_run(engine: Engine, job: str) -> Iterator[JobRun]:
    run = start(engine, job)
    log.info("job_started job=%s run_id=%s", job, run.run_id)
    try:
        yield run
    except BaseException as e:
        finish(engine, run, "failed", f"{type(e).__name__}: {e}")
        log.error("job_failed job=%s run_id=%s", job, run.run_id)
        raise
    finish(engine, run, "success")
    log.info("job_finished job=%s run_id=%s", job, run.run_id)
