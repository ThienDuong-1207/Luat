"""Spark job: Bronze → Silver (spec 8.7), gồm cả `amendments` (spec 8.4, M4). Chạy: `luatgt reparse --all | --vbpl-id X` hoặc
`python -m luatgt.jobs.build_silver --all`.

Luồng:
1. Driver liệt kê Bronze, chọn bản HTML mới nhất của từng (văn bản, tab) và meta mới nhất.
2. Spark phân tán việc parse theo văn bản (mapPartitions, mỗi partition một client MinIO).
3. Ghi Parquet phân vùng theo `vbpl_id` vào thư mục staging (ghi đè đúng các partition đã parse),
   rồi đồng bộ các partition đó lên bucket `silver` (D-014). Chạy lại → cùng dữ liệu.
4. Cập nhật Postgres: quarantine (stage=parse) của văn bản được làm mới, `needs_reparse = false`.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import uuid
from collections import defaultdict
from datetime import date
from pathlib import Path

from pyspark.sql import SparkSession
from pyspark.sql import types as T
from sqlalchemy import Engine, text

from luatgt.common.config import Settings, get_settings
from luatgt.common.db import make_engine
from luatgt.common.job_runs import job_run
from luatgt.common.logging import get_logger, setup_logging
from luatgt.common.storage import Storage
from luatgt.crawler.selectors import SourceConfig, load_source_config
from luatgt.jobs.spark import get_spark
from luatgt.modeling.versions import has_amending_title
from luatgt.parsing.amendments import parse_amendments
from luatgt.parsing.document import DocumentInputs, parse_document

log = get_logger(__name__)

SCHEMAS: dict[str, T.StructType] = {
    "documents": T.StructType([
        T.StructField("vbpl_id", T.StringType(), False),
        T.StructField("so_hieu", T.StringType()),
        T.StructField("ten_van_ban", T.StringType()),
        T.StructField("loai_van_ban", T.StringType()),
        T.StructField("co_quan_ban_hanh", T.StringType()),
        T.StructField("nguoi_ky", T.StringType()),
        T.StructField("ngay_ban_hanh", T.DateType()),
        T.StructField("ngay_hieu_luc", T.DateType()),
        T.StructField("ngay_het_hieu_luc", T.DateType()),
        T.StructField("tinh_trang", T.StringType()),
        T.StructField("tinh_trang_norm", T.StringType()),
        T.StructField("source_url", T.StringType()),
        T.StructField("content_hash", T.StringType()),
        T.StructField("crawled_at", T.StringType()),
        T.StructField("selector_version", T.StringType()),
        T.StructField("parser_version", T.StringType()),
        T.StructField("fulltext_source", T.StringType()),
        T.StructField("n_provisions", T.IntegerType()),
        T.StructField("n_dieu", T.IntegerType()),
        T.StructField("preamble", T.StringType()),
        T.StructField("trailer", T.StringType()),
        T.StructField("bronze_keys", T.ArrayType(T.StringType())),
    ]),
    "document_relations": T.StructType([
        T.StructField("src_vbpl_id", T.StringType(), False),
        T.StructField("dst_so_hieu", T.StringType(), False),
        T.StructField("relation_type", T.StringType(), False),
        T.StructField("dst_title", T.StringType()),
        T.StructField("dst_vbpl_id", T.StringType()),
        T.StructField("effective_date", T.DateType()),
        T.StructField("origin", T.StringType()),
        T.StructField("source_section", T.StringType()),
        T.StructField("vbpl_id", T.StringType(), False),  # = src_vbpl_id, cột phân vùng
    ]),
    "provisions": T.StructType([
        T.StructField("provision_id", T.StringType(), False),
        T.StructField("vbpl_id", T.StringType(), False),
        T.StructField("provision_key", T.StringType(), False),
        T.StructField("level", T.StringType(), False),
        T.StructField("number", T.StringType(), False),
        T.StructField("number_raw", T.StringType()),
        T.StructField("title", T.StringType()),
        T.StructField("text", T.StringType(), False),
        T.StructField("parent_id", T.StringType()),
        T.StructField("ordinal", T.IntegerType(), False),
        T.StructField("pdf_page", T.IntegerType()),
        T.StructField("has_quoted_content", T.BooleanType(), False),
        T.StructField("vbpl_annotations", T.ArrayType(T.StringType())),
        T.StructField("line_no", T.IntegerType()),
    ]),
    "parse_issues": T.StructType([
        T.StructField("vbpl_id", T.StringType(), False),
        T.StructField("rule", T.StringType(), False),
        T.StructField("provision_key", T.StringType()),
        T.StructField("detail", T.StringType()),
    ]),
}
TABLES = list(SCHEMAS)  # bảng parse theo từng văn bản

AMENDMENTS_SCHEMA = T.StructType([
    T.StructField("amendment_id", T.StringType(), False),
    T.StructField("amending_vbpl_id", T.StringType(), False),
    T.StructField("target_so_hieu", T.StringType(), False),
    T.StructField("target_key", T.StringType(), False),
    T.StructField("action", T.StringType(), False),
    T.StructField("new_text", T.StringType()),
    T.StructField("effective_date", T.DateType()),
    T.StructField("raw_instruction", T.StringType(), False),
    T.StructField("parse_status", T.StringType(), False),
    T.StructField("origin", T.StringType(), False),
    T.StructField("review_reason", T.StringType()),
    T.StructField("level", T.StringType()),
    T.StructField("title", T.StringType()),
    T.StructField("phrase_op", T.StringType()),
    T.StructField("phrase_old", T.StringType()),
    T.StructField("phrase_scope", T.StringType()),
    T.StructField("vbpl_id", T.StringType(), False),  # = amending_vbpl_id, cột phân vùng
])


# ---------------------------------------------------------------- đầu vào từ Bronze
def latest_bronze_inputs(storage: Storage) -> dict[str, dict]:
    """vbpl_id → {"html": {tab: key}, "meta": key}, lấy bản mới nhất theo tên (crawled_at)."""
    bronze = storage.bucket("bronze")
    out: dict[str, dict] = defaultdict(lambda: {"html": {}, "meta": None})
    for key in storage.list_keys(bronze, "html/"):
        _, vid, tab, _name = key.split("/", 3)
        out[vid]["html"][tab] = key  # list_keys sắp xếp tăng dần → bản sau cùng là mới nhất
    for key in storage.list_keys(bronze, "meta/"):
        _, vid, _name = key.split("/", 2)
        out[vid]["meta"] = key
    return {k: v for k, v in out.items() if v["meta"]}


def pdf_keys(engine: Engine) -> dict[str, str]:
    """vbpl_id → object_key PDF mới nhất (document_files)."""
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT DISTINCT ON (vbpl_id) vbpl_id, object_key FROM document_files
            WHERE file_type = 'pdf' ORDER BY vbpl_id, downloaded_at DESC""")).all()
    return {r.vbpl_id: r.object_key for r in rows}


def select_ids(engine: Engine, available: set[str], all_docs: bool, ids: list[str] | None) -> list[str]:
    if ids:
        missing = set(ids) - available
        if missing:
            raise SystemExit(f"Không có trên Bronze: {sorted(missing)}")
        return sorted(ids)
    if all_docs:
        return sorted(available)
    with engine.connect() as conn:
        flagged = set(conn.execute(text("SELECT vbpl_id FROM documents WHERE needs_reparse")).scalars())
    return sorted(flagged & available)


# ---------------------------------------------------------------- phần chạy trên executor
def _parse_partition(items, settings: Settings, source: SourceConfig):
    storage = Storage(settings)
    bronze = storage.bucket("bronze")
    tab_key = {v: k for k, v in source.tabs.items()}  # "toan-van" → "fulltext"
    for vid, inp, pdf_key in items:
        tab_html = {tab_key[t]: storage.get_bytes(bronze, k).decode("utf-8") for t, k in inp["html"].items()}
        meta = json.loads(storage.get_bytes(bronze, inp["meta"]))
        pdf = storage.get_bytes(bronze, pdf_key) if pdf_key else None
        keys = sorted(inp["html"].values()) + [inp["meta"]] + ([pdf_key] if pdf_key else [])
        rows = parse_document(DocumentInputs(vid, tab_html, meta, pdf, keys), source, settings.parsing)
        for table in TABLES:
            for row in getattr(rows, table):
                if table == "document_relations":
                    row = {**row, "vbpl_id": row["src_vbpl_id"]}
                yield table, tuple(row.get(f.name) for f in SCHEMAS[table].fields)


# ---------------------------------------------------------------- amendments (pha 2)
def compute_amendments(documents: list[dict], provisions: list[dict]) -> list[dict]:
    """Amendments của mọi văn bản sửa đổi trên Silver (cần provisions của cả văn bản bị sửa)."""
    from dataclasses import asdict

    by_vid: dict[str, list[dict]] = defaultdict(list)
    for p in provisions:
        by_vid[p["vbpl_id"]].append(p)
    by_so_hieu = {d["so_hieu"]: list(by_vid.get(d["vbpl_id"], [])) for d in documents}
    names = {re.sub(r"\s+số\s+\S+$", "", d["ten_van_ban"]).lower(): d["so_hieu"]
             for d in documents if (d.get("ten_van_ban") or "").lower().startswith("luật ")}
    rows = []
    # Theo thứ tự hiệu lực: sửa đổi sau kiểm tra trên trạng thái đã có sửa đổi trước (NĐ 184 → NĐ 236)
    for doc in sorted(documents, key=lambda d: (d.get("ngay_hieu_luc") or date.min, d["vbpl_id"])):
        if not has_amending_title(doc):
            continue
        for a in parse_amendments(doc, by_vid.get(doc["vbpl_id"], []), by_so_hieu, names):
            rows.append({**asdict(a), "vbpl_id": a.amending_vbpl_id})
            if a.parse_status == "ok":
                _apply_to_state(by_so_hieu[a.target_so_hieu], a)
    return rows


def _apply_to_state(target_rows: list[dict], a) -> None:
    """Cập nhật danh sách mục hiện có của văn bản đích sau một amendment."""
    if a.action == "bai_bo":
        target_rows[:] = [r for r in target_rows if r["provision_key"] != a.target_key]
    elif a.action == "bo_sung":
        target_rows.append({"provision_key": a.target_key, "level": a.level})


def write_amendments(spark: SparkSession, settings: Settings, staging: Path) -> list[dict]:
    """Tính lại toàn bộ amendments từ Silver, ghi đè cả bảng (văn bản sửa đổi và văn bản gốc phụ thuộc nhau)."""
    from luatgt.jobs.spark import read_silver

    docs = [r.asDict() for r in read_silver(spark, settings, "documents").collect()]
    provs = [r.asDict() for r in read_silver(spark, settings, "provisions").collect()]
    rows = compute_amendments(docs, provs)
    shutil.rmtree(staging / "amendments", ignore_errors=True)
    if rows:
        data = [tuple(r.get(f.name) for f in AMENDMENTS_SCHEMA.fields) for r in rows]
        df = spark.createDataFrame(data, AMENDMENTS_SCHEMA)
        df.repartition("vbpl_id").write.mode("overwrite").partitionBy("vbpl_id").parquet(
            str(staging / "amendments")
        )
    return rows


def sync_table_to_bucket(storage: Storage, staging: Path, table: str) -> int:
    """Thay toàn bộ một bảng trên bucket silver bằng bản staging."""
    bucket = storage.bucket("silver")
    for key in storage.list_keys(bucket, f"{table}/"):
        storage.remove(bucket, key)
    n = 0
    for f in sorted((staging / table).rglob("*.parquet")) if (staging / table).exists() else []:
        storage.put_bytes(bucket, f"{table}/{f.relative_to(staging / table).as_posix()}",
                          f.read_bytes(), "application/octet-stream")
        n += 1
    return n


# ---------------------------------------------------------------- ghi Silver
def _partition_dir(base: Path, table: str, vid: str) -> Path:
    return base / table / f"vbpl_id={vid}"


def sync_to_bucket(storage: Storage, staging: Path, ids: list[str]) -> int:
    """Thay các partition đã parse trên bucket silver bằng bản staging. Trả số file đã upload."""
    bucket = storage.bucket("silver")
    uploaded = 0
    for table in TABLES:
        for vid in ids:
            prefix = f"{table}/vbpl_id={vid}/"
            for key in storage.list_keys(bucket, prefix):
                storage.remove(bucket, key)  # Silver tái tạo được từ Bronze → được ghi đè
            local = _partition_dir(staging, table, vid)
            for f in sorted(local.glob("*.parquet")) if local.exists() else []:
                storage.put_bytes(bucket, prefix + f.name, f.read_bytes(), "application/octet-stream")
                uploaded += 1
    return uploaded


def update_postgres(engine: Engine, ids: list[str], issues: list[tuple], run_id: uuid.UUID | None = None) -> None:
    """Làm mới quarantine (stage=parse) của các văn bản vừa parse, tắt cờ needs_reparse."""
    names = [f.name for f in SCHEMAS["parse_issues"].fields]
    with engine.begin() as conn:
        conn.execute(
            text("""DELETE FROM quarantine WHERE stage = 'parse' AND NOT resolved
                    AND detail->>'vbpl_id' = ANY(:ids)"""),
            {"ids": ids},
        )
        for t in issues:
            row = dict(zip(names, t, strict=True))
            detail = {**json.loads(row["detail"] or "{}"), "vbpl_id": row["vbpl_id"]}
            conn.execute(
                text("""INSERT INTO quarantine (stage, entity_ref, rule, detail, run_id)
                        VALUES ('parse', :ref, :rule, CAST(:detail AS jsonb), :run)"""),
                {"ref": row["provision_key"] or row["vbpl_id"], "rule": row["rule"],
                 "detail": json.dumps(detail, ensure_ascii=False), "run": run_id},
            )
        conn.execute(text("UPDATE documents SET needs_reparse = false WHERE vbpl_id = ANY(:ids)"),
                     {"ids": ids})


def build_silver(
    settings: Settings,
    all_docs: bool = False,
    ids: list[str] | None = None,
    spark: SparkSession | None = None,
    storage: Storage | None = None,
    engine: Engine | None = None,
) -> dict:
    """Chạy job, ghi một dòng job_runs. Trả thống kê {documents, provisions, issues, uploaded, ids, run_id}."""
    storage = storage or Storage(settings)
    engine = engine or make_engine(settings)
    with job_run(engine, "build_silver") as run:
        run.stats = _build_silver(settings, all_docs, ids, spark, storage, engine, run.run_id)
    return {**run.stats, "run_id": str(run.run_id)}


def _build_silver(settings: Settings, all_docs: bool, ids: list[str] | None, spark: SparkSession | None,
                  storage: Storage, engine: Engine, run_id: uuid.UUID) -> dict:
    source = load_source_config(settings.path(settings.paths.vbpl_source))
    staging = settings.path(settings.paths.silver_staging)

    inputs = latest_bronze_inputs(storage)
    chosen = select_ids(engine, set(inputs), all_docs, ids)
    if not chosen:
        log.info("build_silver_nothing_to_do")
        return {"documents": 0, "provisions": 0, "issues": 0, "amendments": 0,
                "amendments_needs_review": 0, "uploaded": 0, "ids": []}
    pdfs = pdf_keys(engine)

    own_spark = spark is None
    spark = spark or get_spark(settings)
    try:
        work = [(vid, inputs[vid], pdfs.get(vid)) for vid in chosen]
        rdd = spark.sparkContext.parallelize(work, min(len(work), settings.spark.shuffle_partitions))
        tagged = rdd.mapPartitions(lambda it: _parse_partition(it, settings, source)).cache()

        # Xoá partition cũ của các văn bản này ở mọi bảng (kể cả bảng không còn dòng, vd hết lỗi)
        for table in TABLES:
            for vid in chosen:
                shutil.rmtree(_partition_dir(staging, table, vid), ignore_errors=True)

        counts = {}
        issues: list[tuple] = []
        for table in TABLES:
            rows = tagged.filter(lambda x, t=table: x[0] == t).map(lambda x: x[1])
            df = spark.createDataFrame(rows, SCHEMAS[table])
            if table == "parse_issues":
                issues = [tuple(r) for r in df.collect()]
            counts[table] = df.count()
            if counts[table]:
                df.repartition("vbpl_id").write.mode("overwrite").partitionBy("vbpl_id").parquet(
                    str(staging / table)
                )
        tagged.unpersist()
        amendments = write_amendments(spark, settings, staging)
    finally:
        if own_spark:
            spark.stop()

    uploaded = sync_to_bucket(storage, staging, chosen)
    uploaded += sync_table_to_bucket(storage, staging, "amendments")
    update_postgres(engine, chosen, issues, run_id)
    stats = {"documents": counts["documents"], "provisions": counts["provisions"],
             "relations": counts["document_relations"], "issues": counts["parse_issues"],
             "amendments": len(amendments),
             "amendments_needs_review": sum(a["parse_status"] != "ok" for a in amendments),
             "uploaded": uploaded, "ids": chosen}
    log.info("build_silver_done %s", stats)
    return stats


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Bronze → Silver")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--all", action="store_true", help="parse lại mọi văn bản có trên Bronze")
    g.add_argument("--vbpl-id", action="append", help="chỉ parse văn bản này (lặp được)")
    args = ap.parse_args(argv)
    settings = get_settings()
    setup_logging(settings.log_level)
    print(build_silver(settings, all_docs=args.all, ids=args.vbpl_id))


if __name__ == "__main__":
    main()
