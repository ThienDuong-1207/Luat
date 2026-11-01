"""DAG gọi đúng lệnh CLI đang có. Việc Airflow nạp DAG được kiểm tra bằng `airflow dags list-import-errors`."""

from __future__ import annotations

import re
from pathlib import Path

from typer.main import get_command

from luatgt.cli import app

DAGS = Path(__file__).parent.parent / "dags"


def test_dags_only_call_existing_commands():
    root = get_command(app)
    calls = re.findall(r"\{CLI\} ([a-z-]+)(?: ([a-z-]+))?", "".join(p.read_text("utf-8") for p in DAGS.glob("dag_*.py")))
    assert calls
    for name, sub in calls:
        assert name in root.commands, name
        group = root.commands[name]
        if hasattr(group, "commands") and sub:
            assert sub in group.commands, f"{name} {sub}"
