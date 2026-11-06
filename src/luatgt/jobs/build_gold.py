"""Spark job: Silver → Gold (spec 8.7): `provision_versions`, `violations`.

Luồng: đọc Silver (documents, provisions, amendments) → dựng phiên bản (modeling/versions.py)
→ quality check (chồng lấn thời gian = error → dừng, không publish Gold mới, spec 8.6)
→ trích xuất violations (modeling/violations.py) → Parquet Gold (staging + bucket gold) → nạp Postgres trong MỘT transaction.

Nạp Postgres: thay toàn bộ provisions/amendments/provision_versions/violations của các văn bản trên Silver bằng
bản mới trong cùng transaction. Kết quả như upsert theo khoá nhưng xử lý được cả dòng bị xoá; lỗi giữa
chừng thì rollback, Gold cũ vẫn phục vụ.
"""

from __future__ import annotations

import json
import shutil
import uuid
from dataclasses import asdict

from pyspark.sql import SparkSession
from pyspark.sql import types as T
from sqlalchemy import Engine, text

from luatgt.common.config import Settings, get_settings
from luatgt.common.db import make_engine
from luatgt.common.job_runs import job_run
from luatgt.common.logging import get_logger, setup_logging
from luatgt.common.storage import Storage
from luatgt.jobs.spark import get_spark, read_silver
from luatgt.modeling.versions import Version, VersionIssue, build_versions
from luatgt.modeling.violations import (
    Violation,
    extract_violations,
    load_violation_config,
)
from luatgt.quality.checks import (
    check_amendment_targets,
    check_dieu_sequence,
    check_violations,
    summarize,
)

log = get_logger(__name__)

VERSIONS_SCHEMA = T.StructType([
    T.StructField("provision_key", T.StringType(), False),
    T.StructField("version_no", T.IntegerType(), False),
    T.StructField("text", T.StringType()),
    T.StructField("source_vbpl_id", T.StringType(), False),
    T.StructField("valid_from", T.DateType(), False),
    T.StructField("valid_to", T.DateType(), False),
    T.StructField("is_current", T.BooleanType(), False),
    T.StructField("level", T.StringType(), False),
    T.StructField("amendment_id", T.StringType()),
])
VIOLATIONS_SCHEMA = T.StructType([
    T.StructField("violation_id", T.StringType(), False),
    T.StructField("provision_key", T.StringType(), False),
    T.StructField("version_no", T.IntegerType(), False),
    T.StructField("hanh_vi", T.StringType(), False),
    T.StructField("phuong_tien", T.ArrayType(T.StringType()), False),
    T.StructField("doi_tuong", T.StringType()),
    T.StructField("muc_phat_min", T.LongType()),
    T.StructField("muc_phat_max", T.LongType()),
    T.StructField("tru_diem_gplx", T.IntegerType()),
    T.StructField("tuoc_gplx_min_thang", T.IntegerType()),
    T.StructField("tuoc_gplx_max_thang", T.IntegerType()),
    T.StructField("bien_phap_bo_sung", T.ArrayType(T.StringType())),
    T.StructField("attributes", T.StringType(), False),  # JSON
    T.StructField("valid_from", T.DateType(), False),
    T.StructField("valid_to", T.DateType(), False),
    T.StructField("extraction_method", T.StringType(), False),
    T.StructField("confidence", T.FloatType()),
    T.StructField("needs_review", T.BooleanType(), False),
])


class QualityError(RuntimeError):
    """Vi phạm rule mức error: dừng job, không publish Gold mới."""


def _read(spark: SparkSession, settings: Settings, table: str) -> list[dict]:
    try:
        return [r.asDict() for r in read_silver(spark, settings, table).collect()]
    except Exception as e:
        if "PATH_NOT_FOUND" in str(e) or "Path does not exist" in str(e):
            return []
        raise


def _violation_row(v: Violation) -> dict:
    row = asdict(v)
    row["phuong_tien"], row["bien_phap_bo_sung"] = list(v.phuong_tien), list(v.bien_phap_bo_sung)
    row["attributes"] = json.dumps(v.attributes, ensure_ascii=False, sort_keys=True)
    return row


def build_violations(
    settings: Settings, provisions: list[dict], versions: list[Version]
) -> tuple[list[Violation], list[VersionIssue], list[VersionIssue]]:
    """Trích xuất theo các văn bản trong config. Trả (violations, cảnh báo trích xuất, lỗi chất lượng)."""
    cfg = load_violation_config(settings.path(settings.paths.violation_attributes))
    out: list[Violation] = []
    extract_issues: list[VersionIssue] = []
    for src in cfg.sources:
        dkey = src["so_hieu"].replace("/", "-").replace("Đ", "D")
        titles = {p["provision_key"].rsplit("/D", 1)[-1]: p["title"] or "" for p in provisions
                  if p["level"] == "dieu" and p["provision_key"].startswith(dkey + "/")}
        found, issues = extract_violations(src["so_hieu"], (src["dieu_from"], src["dieu_to"]), titles, versions, cfg)
        out += found
        extract_issues += issues
    q = settings.quality
    kept, quality_issues = check_violations(out, q.fine_min_vnd, q.fine_max_vnd)
    return kept, extract_issues, quality_issues


def load_postgres(
    engine: Engine, documents: list[dict], provisions: list[dict], amendments: list[dict],
    versions: list[Version], issues: list[VersionIssue],
    violations: list[Violation] = (), extract_issues: list[VersionIssue] = (),
    run_id: uuid.UUID | None = None,
) -> dict:
    vids = sorted({d["vbpl_id"] for d in documents})
    with engine.begin() as conn:
        known = set(conn.execute(text("SELECT vbpl_id FROM documents WHERE vbpl_id = ANY(:v)"),
                                 {"v": vids}).scalars())
        missing = sorted(set(vids) - known)
        if missing:
            log.warning("gold_documents_missing_in_postgres ids=%s (chạy crawl trước)", missing)

        conn.execute(text("DELETE FROM violations"))
        conn.execute(text("DELETE FROM provision_versions"))
        conn.execute(text("DELETE FROM amendments"))
        conn.execute(text("DELETE FROM provisions WHERE vbpl_id = ANY(:v)"), {"v": vids})

        prov_rows = [
            {k: p[k] for k in ("provision_id", "vbpl_id", "provision_key", "level", "number", "title",
                               "text", "parent_id", "ordinal", "pdf_page")}
            for p in provisions if p["vbpl_id"] in known
        ]
        if prov_rows:
            conn.execute(text("""
                INSERT INTO provisions (provision_id, vbpl_id, provision_key, level, number, title, text,
                                        parent_id, ordinal, pdf_page)
                VALUES (:provision_id, :vbpl_id, :provision_key, :level, :number, :title, :text,
                        :parent_id, :ordinal, :pdf_page)"""), prov_rows)

        am_rows = [
            {k: a[k] for k in ("amendment_id", "amending_vbpl_id", "target_so_hieu", "target_key",
                               "action", "new_text", "effective_date", "raw_instruction", "parse_status")}
            for a in amendments if a["effective_date"] is not None
        ]
        if am_rows:
            conn.execute(text("""
                INSERT INTO amendments (amendment_id, amending_vbpl_id, target_so_hieu, target_key, action,
                                        new_text, effective_date, raw_instruction, parse_status)
                VALUES (:amendment_id, :amending_vbpl_id, :target_so_hieu, :target_key, :action,
                        :new_text, :effective_date, :raw_instruction, :parse_status)"""), am_rows)

        v_rows = [{k: getattr(v, k) for k in ("provision_key", "version_no", "text", "source_vbpl_id",
                                               "valid_from", "valid_to", "is_current")} for v in versions]
        if v_rows:
            conn.execute(text("""
                INSERT INTO provision_versions (provision_key, version_no, text, source_vbpl_id,
                                                valid_from, valid_to, is_current)
                VALUES (:provision_key, :version_no, :text, :source_vbpl_id,
                        :valid_from, :valid_to, :is_current)"""), v_rows)

        if violations:
            conn.execute(text("""
                INSERT INTO violations (violation_id, provision_key, version_no, hanh_vi, phuong_tien, doi_tuong,
                                        muc_phat_min, muc_phat_max, tru_diem_gplx, tuoc_gplx_min_thang,
                                        tuoc_gplx_max_thang, bien_phap_bo_sung, attributes, valid_from, valid_to,
                                        extraction_method, confidence, needs_review)
                VALUES (:violation_id, :provision_key, :version_no, :hanh_vi, :phuong_tien, :doi_tuong,
                        :muc_phat_min, :muc_phat_max, :tru_diem_gplx, :tuoc_gplx_min_thang,
                        :tuoc_gplx_max_thang, :bien_phap_bo_sung, CAST(:attributes AS jsonb), :valid_from, :valid_to,
                        :extraction_method, :confidence, :needs_review)"""),
                [_violation_row(v) for v in violations])
        conn.execute(text("DELETE FROM quarantine WHERE stage = 'extract' AND NOT resolved"))
        if extract_issues:
            conn.execute(text("""INSERT INTO quarantine (stage, entity_ref, rule, detail, run_id)
                                 VALUES ('extract', :ref, :rule, CAST(:detail AS jsonb), :run)"""),
                         [{"ref": i.provision_key, "rule": i.rule, "run": run_id,
                           "detail": json.dumps({**i.detail, "severity": i.severity}, ensure_ascii=False)}
                          for i in extract_issues])

        # Hàng đợi xử lý tay: amendment needs_review + cảnh báo khi dựng phiên bản
        conn.execute(text("DELETE FROM quarantine WHERE stage = 'amend' AND NOT resolved"))
        q = [{"ref": a["target_key"] or a["amendment_id"], "rule": "amendment_needs_review", "run": run_id,
              "detail": json.dumps({"amendment_id": a["amendment_id"], "action": a["action"],
                                    "reason": a.get("review_reason"),
                                    "instruction": a["raw_instruction"]}, ensure_ascii=False)}
             for a in amendments if a["parse_status"] != "ok"]
        q += [{"ref": i.provision_key, "rule": i.rule, "run": run_id,
               "detail": json.dumps({**i.detail, "severity": i.severity}, ensure_ascii=False)}
              for i in issues]
        if q:
            conn.execute(text("""INSERT INTO quarantine (stage, entity_ref, rule, detail, run_id)
                                 VALUES ('amend', :ref, :rule, CAST(:detail AS jsonb), :run)"""), q)
    return {"provisions": len(prov_rows), "amendments": len(am_rows), "versions": len(v_rows),
            "violations": len(violations),
            "quarantine_amend": len(q), "documents_missing_in_postgres": missing}


def build_gold(
    settings: Settings,
    spark: SparkSession | None = None,
    storage: Storage | None = None,
    engine: Engine | None = None,
) -> dict:
    """Chạy job, ghi một dòng job_runs (lỗi chất lượng → status=failed, Gold cũ giữ nguyên)."""
    storage = storage or Storage(settings)
    engine = engine or make_engine(settings)
    with job_run(engine, "build_gold") as run:
        run.stats = _build_gold(settings, spark, storage, engine, run.run_id)
    return {**run.stats, "run_id": str(run.run_id)}


def _build_gold(settings: Settings, spark: SparkSession | None, storage: Storage, engine: Engine,
                run_id: uuid.UUID) -> dict:
    staging = settings.path(settings.paths.gold_staging)
    own_spark = spark is None
    spark = spark or get_spark(settings)
    try:
        documents = _read(spark, settings, "documents")
        provisions = _read(spark, settings, "provisions")
        amendments, target_issues = check_amendment_targets(_read(spark, settings, "amendments"), provisions)
        versions, issues = build_versions(documents, provisions, amendments)

        # Chỉ chồng lấn thời gian mới dừng job; lỗi khác đã quarantine theo spec 8.6
        errors = [i for i in issues if i.severity == "error"]
        if errors:
            raise QualityError(f"{len(errors)} lỗi chất lượng, không publish Gold: {errors[:5]}")
        issues = issues + target_issues + check_dieu_sequence(provisions)

        violations, extract_issues, quality_issues = build_violations(settings, provisions, versions)
        extract_issues = extract_issues + quality_issues

        for table, schema, rows in (
            ("provision_versions", VERSIONS_SCHEMA, [asdict(v) for v in versions]),
            ("violations", VIOLATIONS_SCHEMA, [_violation_row(v) for v in violations]),
        ):
            shutil.rmtree(staging / table, ignore_errors=True)
            data = [tuple(r[f.name] for f in schema.fields) for r in rows]
            spark.createDataFrame(data, schema).coalesce(1).write.mode("overwrite").parquet(str(staging / table))
    finally:
        if own_spark:
            spark.stop()

    uploaded = _sync_gold(storage, staging, "provision_versions") + _sync_gold(storage, staging, "violations")
    stats = load_postgres(engine, documents, provisions, amendments, versions, issues, violations, extract_issues,
                          run_id)
    stats.update({
        "quality": summarize(len(violations), extract_issues + target_issues),
        "multi_version_keys": len({v.provision_key for v in versions if v.version_no > 1}),
        "warnings": len(issues), "uploaded": uploaded,
    })
    log.info("build_gold_done %s", stats)
    return stats


def _sync_gold(storage: Storage, staging, table: str) -> int:
    """Như sync_table_to_bucket nhưng sang bucket gold."""
    gold = storage.bucket("gold")
    for key in storage.list_keys(gold, f"{table}/"):
        storage.remove(gold, key)
    n = 0
    for f in sorted((staging / table).rglob("*.parquet")):
        storage.put_bytes(gold, f"{table}/{f.relative_to(staging / table).as_posix()}",
                          f.read_bytes(), "application/octet-stream")
        n += 1
    return n


def main() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)
    print(build_gold(settings))


if __name__ == "__main__":
    main()
