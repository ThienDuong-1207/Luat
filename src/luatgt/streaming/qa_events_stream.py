"""Đếm event hành vi theo cửa sổ event time rồi upsert vào Postgres (spec 13.2).

`foreachBatch` là at-least-once: chạy lại một batch sau sự cố sẽ ghi lại đúng các dòng đó, nên sink phải idempotent.
Giá trị mỗi dòng là tổng tích luỹ từ state (output mode update) nên `ON CONFLICT DO UPDATE` ghi đè là đúng.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.streaming import StreamingQuery
from pyspark.sql.types import StringType, StructField, StructType, TimestampType
from sqlalchemy import Engine, text

from luatgt.common.config import Settings, get_settings
from luatgt.common.db import make_engine
from luatgt.common.logging import get_logger
from luatgt.jobs.spark import get_spark

log = get_logger(__name__)

SINK_TABLE = "qa_topic_counts"
EVENT_SCHEMA = StructType([
    StructField("event_id", StringType()),
    StructField("event_time", TimestampType()),
    StructField("type", StringType()),
    StructField("session_id", StringType()),
    StructField("topic", StringType()),
    StructField("thumbs", StringType()),
    StructField("client_sent_at", StringType()),
    StructField("ingest_time", TimestampType()),
])


def upsert_counts(engine: Engine, rows: list[dict], batch_id: int, table: str = SINK_TABLE) -> None:
    """Sink idempotent theo (window_start, topic). `table` chỉ nhận tên do code truyền vào."""
    if not rows:
        return
    params = [{**r, "batch_id": batch_id} for r in rows]
    with engine.begin() as conn:
        conn.execute(text(f"""
            INSERT INTO {table} (window_start, window_end, topic, n_questions, n_thumbs_down, updated_batch_id)
            VALUES (:window_start, :window_end, :topic, :n_questions, :n_thumbs_down, :batch_id)
            ON CONFLICT (window_start, topic) DO UPDATE
            SET window_end = EXCLUDED.window_end, n_questions = EXCLUDED.n_questions,
                n_thumbs_down = EXCLUDED.n_thumbs_down, updated_batch_id = EXCLUDED.updated_batch_id"""), params)


def windowed_counts(events: DataFrame, watermark: str, window: str, max_ahead: str) -> DataFrame:
    """Event → số đếm. Bỏ event_time vượt xa ingest_time trước watermark, vì một event tương lai sẽ loại event thật."""
    clean = events.filter(F.col("event_time").isNotNull() & F.col("event_id").isNotNull()
                          & (F.col("event_time") <= F.col("ingest_time") + F.expr(f"INTERVAL {max_ahead}")))
    return (clean.withWatermark("event_time", watermark)
            .dropDuplicatesWithinWatermark(["event_id"])
            .groupBy(F.window("event_time", window).alias("w"), F.coalesce(F.col("topic"), F.lit("unknown")).alias("topic"))
            .agg(F.count(F.when(F.col("type") == "ask", 1)).alias("n_questions"),
                 F.count(F.when(F.col("thumbs") == "down", 1)).alias("n_thumbs_down")))


def _rows(df: DataFrame) -> list[dict]:
    # Qua epoch để không phụ thuộc múi giờ máy: collect() trả datetime naive theo giờ local
    out = df.select(F.col("w.start").cast("long").alias("s"), F.col("w.end").cast("long").alias("e"),
                    "topic", "n_questions", "n_thumbs_down").collect()
    return [{"window_start": datetime.fromtimestamp(r.s, UTC), "window_end": datetime.fromtimestamp(r.e, UTC),
             "topic": r.topic, "n_questions": r.n_questions, "n_thumbs_down": r.n_thumbs_down} for r in out]


def start_query(spark: SparkSession, settings: Settings, engine: Engine, source: Path, checkpoint: Path,
                *, watermark: str, table: str = SINK_TABLE, once: bool = True,
                max_files: int | None = None) -> StreamingQuery:
    source.mkdir(parents=True, exist_ok=True)
    reader = spark.readStream.schema(EVENT_SCHEMA)
    if max_files:
        reader = reader.option("maxFilesPerTrigger", max_files)
    cfg = settings.streaming
    counts = windowed_counts(reader.json(str(source)), watermark, cfg.window, cfg.max_client_ahead)

    def sink(df: DataFrame, batch_id: int) -> None:
        upsert_counts(engine, _rows(df), batch_id, table)

    writer = (counts.writeStream.outputMode("update").option("checkpointLocation", str(checkpoint))
              .foreachBatch(sink))
    return (writer.trigger(availableNow=True) if once else writer.trigger(processingTime=cfg.trigger_interval)).start()


def dropped_rows(progress: dict | None) -> int:
    """`numRowsDroppedByWatermark` của mọi toán tử có state trong một batch."""
    return sum(op.get("numRowsDroppedByWatermark", 0) for op in (progress or {}).get("stateOperators", []))


def run_stream(settings: Settings | None = None, engine: Engine | None = None, *, once: bool = False) -> dict:
    settings = settings or get_settings()
    engine = engine or make_engine(settings)
    spark = get_spark(settings)
    query = start_query(spark, settings, engine, settings.path(settings.paths.events_dir),
                        settings.path(settings.paths.checkpoint_dir), watermark=settings.streaming.watermark_delay,
                        once=once)
    seen, batches, dropped = -1, 0, 0

    def collect() -> None:
        nonlocal seen, batches, dropped
        for p in query.recentProgress:
            if p.batchId > seen:
                seen, batches = p.batchId, batches + 1
                n = dropped_rows(json.loads(p.json))
                dropped += n
                log.info("stream_batch", extra={"batch_id": p.batchId, "rows": p.numInputRows, "dropped_by_watermark": n})

    try:
        while not query.awaitTermination(30):
            collect()
    finally:
        collect()
    return {"batches": batches, "dropped_by_watermark": dropped}
