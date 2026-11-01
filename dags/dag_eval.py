"""Chạy tay: đánh giá và ghi báo cáo vào `eval/reports/` (spec 14)."""

from __future__ import annotations

from airflow import DAG
from airflow.operators.bash import BashOperator
from luatgt_common import DEFAULTS, PYTHON, START

with DAG("dag_eval", schedule=None, start_date=START, catchup=False, max_active_runs=1,
         default_args={**DEFAULTS, "retries": 0}, tags=["luatgt"]) as dag:
    BashOperator(task_id="run_eval", bash_command=f"{PYTHON} eval/run_eval.py")
