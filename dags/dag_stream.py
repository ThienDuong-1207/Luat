"""Cập nhật `qa_topic_counts` mỗi 10 phút, thêm ngoài spec 14 để dashboard có số mới (D-024)."""

from __future__ import annotations

from airflow import DAG
from airflow.operators.bash import BashOperator
from luatgt_common import CLI, DEFAULTS, START

with DAG("dag_stream", schedule="*/10 * * * *", start_date=START, catchup=False, max_active_runs=1,
         default_args=DEFAULTS, tags=["luatgt"]) as dag:
    BashOperator(task_id="process_events", bash_command=f"{CLI} stream --once")
