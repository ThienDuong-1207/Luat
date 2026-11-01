"""Crawl hằng ngày (spec 14). Không có việc thì không mở trình duyệt. Thành công mới báo cho `dag_build`."""

from __future__ import annotations

from airflow import DAG
from airflow.operators.bash import BashOperator
from luatgt_common import BRONZE_UPDATED, CLI, CRAWL_DEFAULTS, START

with DAG("dag_crawl_daily", schedule="0 2 * * *", start_date=START, catchup=False, max_active_runs=1,
         default_args=CRAWL_DEFAULTS, tags=["luatgt"]) as dag:
    bootstrap = BashOperator(task_id="bootstrap", bash_command=f"{CLI} db migrate && {CLI} storage init")
    detail = BashOperator(task_id="crawl_detail", bash_command=f"{CLI} crawl --stage detail")
    download = BashOperator(task_id="crawl_download", bash_command=f"{CLI} crawl --stage download",
                            outlets=[BRONZE_UPDATED])
    bootstrap >> detail >> download
