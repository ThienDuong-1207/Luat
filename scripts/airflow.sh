#!/usr/bin/env bash
# Chạy Airflow trên máy (D-024). Ví dụ: scripts/airflow.sh standalone | scripts/airflow.sh dags list
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export LUATGT_ROOT="$ROOT"
export PATH="$ROOT/.venv-airflow/bin:$PATH"   # `standalone` gọi lại lệnh `airflow`
export AIRFLOW_HOME="$ROOT/.airflow"
export AIRFLOW__CORE__DAGS_FOLDER="$ROOT/dags"
export AIRFLOW__CORE__LOAD_EXAMPLES=False
export AIRFLOW__CORE__DEFAULT_TIMEZONE=Asia/Ho_Chi_Minh
# macOS: tiến trình fork của Airflow crash nếu thiếu các dòng dưới
export PYTHONPATH="$ROOT/scripts/airflow_shim"
export NO_PROXY="*"
export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
exec "$ROOT/.venv-airflow/bin/airflow" "$@"
