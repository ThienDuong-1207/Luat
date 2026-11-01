"""Cấu hình chung của DAG: mọi task gọi CLI của dự án trong virtualenv riêng của pipeline (D-024)."""

from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path

import pendulum
from airflow.datasets import Dataset

ROOT = Path(os.environ.get("LUATGT_ROOT", Path(__file__).resolve().parent.parent))
CLI = f"{ROOT}/.venv/bin/luatgt"
PYTHON = f"cd {ROOT} && .venv/bin/python"
START = pendulum.datetime(2026, 11, 1, tz="Asia/Ho_Chi_Minh")

BRONZE_UPDATED = Dataset("luatgt://bronze")

DEFAULTS = {"owner": "luatgt", "retries": 1, "retry_delay": timedelta(minutes=5)}
# Bị chặn thì dừng, lịch sau thử lại; không retry dồn dập (spec 7.2)
CRAWL_DEFAULTS = {**DEFAULTS, "retries": 0}
