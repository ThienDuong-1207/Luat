"""Chủ nhật đánh dấu lại văn bản còn hiệu lực để `dag_crawl_daily` kiểm tra thay đổi (spec 14)."""

from __future__ import annotations

from airflow import DAG
from airflow.operators.bash import BashOperator
from luatgt_common import CLI, DEFAULTS, START

with DAG("dag_recheck_weekly", schedule="0 3 * * 0", start_date=START, catchup=False, max_active_runs=1,
         default_args=DEFAULTS, tags=["luatgt"]) as dag:
    BashOperator(task_id="mark_pending", bash_command=f"{CLI} recheck")
