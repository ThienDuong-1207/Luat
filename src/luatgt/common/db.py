"""Kết nối PostgreSQL (SQLAlchemy 2 + psycopg 3) và trình chạy migration SQL."""

from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path

from sqlalchemy import Engine, create_engine, text

from luatgt.common.config import Settings, get_settings
from luatgt.common.logging import get_logger

log = get_logger(__name__)

MIGRATIONS_TABLE = "schema_migrations"


def make_engine(settings: Settings | None = None) -> Engine:
    settings = settings or get_settings()
    return create_engine(settings.postgres_url, pool_pre_ping=True, future=True)


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    return make_engine()


def ping(engine: Engine | None = None) -> bool:
    with (engine or get_engine()).connect() as conn:
        return conn.execute(text("SELECT 1")).scalar_one() == 1


def migration_files(migrations_dir: Path) -> list[Path]:
    """File migration dạng NNNN_ten.sql, chạy theo thứ tự tên."""
    return sorted(migrations_dir.glob("[0-9][0-9][0-9][0-9]_*.sql"))


def migrate(engine: Engine | None = None, migrations_dir: Path | None = None) -> list[str]:
    """Áp các migration chưa chạy, mỗi file trong một transaction. Trả về tên file vừa áp.

    Chạy lại nhiều lần là an toàn (idempotent). Nếu nội dung file đã áp bị sửa,
    báo lỗi thay vì âm thầm bỏ qua: thay đổi schema phải đi qua file migration mới.
    """
    engine = engine or get_engine()
    migrations_dir = migrations_dir or get_settings().path(Path("db/migrations"))
    applied_now: list[str] = []

    with engine.begin() as conn:
        conn.exec_driver_sql(
            f"""CREATE TABLE IF NOT EXISTS {MIGRATIONS_TABLE} (
                  filename   text PRIMARY KEY,
                  checksum   text NOT NULL,
                  applied_at timestamptz NOT NULL DEFAULT now()
                )"""
        )
        applied = dict(
            conn.execute(text(f"SELECT filename, checksum FROM {MIGRATIONS_TABLE}")).all()
        )

    for path in migration_files(migrations_dir):
        sql = path.read_text(encoding="utf-8")
        checksum = hashlib.sha256(sql.encode("utf-8")).hexdigest()
        if path.name in applied:
            if applied[path.name] != checksum:
                raise RuntimeError(
                    f"Migration {path.name} đã áp nhưng nội dung bị sửa; hãy tạo file migration mới."
                )
            continue
        with engine.begin() as conn:
            # Gọi cursor DBAPI không kèm params để psycopg không hiểu '%' trong SQL là placeholder.
            with conn.connection.dbapi_connection.cursor() as cur:
                cur.execute(sql)
            conn.execute(
                text(f"INSERT INTO {MIGRATIONS_TABLE} (filename, checksum) VALUES (:f, :c)"),
                {"f": path.name, "c": checksum},
            )
        log.info("migration_applied file=%s", path.name)
        applied_now.append(path.name)
    return applied_now
