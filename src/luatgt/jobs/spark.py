"""Khởi tạo SparkSession (local mode) và đọc bảng Silver."""

from __future__ import annotations

import os
import sys

from pyspark.sql import DataFrame, SparkSession

from luatgt.common.config import Settings


def get_spark(settings: Settings) -> SparkSession:
    # Worker Python dùng cùng virtualenv với driver (để import được luatgt)
    os.environ["PYSPARK_PYTHON"] = sys.executable
    os.environ["PYSPARK_DRIVER_PYTHON"] = sys.executable
    cfg = settings.spark
    return (
        SparkSession.builder.master(cfg.master)
        .appName(cfg.app_name)
        .config("spark.ui.enabled", "false")
        .config("spark.sql.shuffle.partitions", str(cfg.shuffle_partitions))
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.sql.sources.partitionOverwriteMode", "dynamic")
        # vbpl_id có cả số lẫn UUID: không để Spark tự đoán kiểu cột phân vùng (sẽ thành int)
        .config("spark.sql.sources.partitionColumnTypeInference.enabled", "false")
        .getOrCreate()
    )


def read_silver(spark: SparkSession, settings: Settings, table: str) -> DataFrame:
    """Đọc một bảng Silver từ thư mục staging (bản đồng bộ với bucket silver)."""
    return spark.read.parquet(str(settings.path(settings.paths.silver_staging) / table))
