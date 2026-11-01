"""Bronze → Silver → Gold → index, chạy sau khi Bronze cập nhật (Q-2: Airflow Dataset).

Kiểm tra chất lượng nằm trong `build_gold`: lỗi mức error dừng task trước khi publish, Gold cũ vẫn phục vụ (D-024).
"""

from __future__ import annotations

from airflow import DAG
from airflow.operators.bash import BashOperator
from luatgt_common import BRONZE_UPDATED, CLI, DEFAULTS, START

with DAG("dag_build", schedule=[BRONZE_UPDATED], start_date=START, catchup=False, max_active_runs=1,
         default_args=DEFAULTS, tags=["luatgt"]) as dag:
    silver = BashOperator(task_id="build_silver", bash_command=f"{CLI} reparse")
    gold = BashOperator(task_id="build_gold_with_quality_checks", bash_command=f"{CLI} build-gold")
    index = BashOperator(task_id="build_index", bash_command=f"{CLI} build-index")
    silver >> gold >> index
