from __future__ import annotations

import pytest
import yaml
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from luatgt.common.config import Settings, get_settings
from luatgt.common.db import migrate
from luatgt.common.storage import Storage
from luatgt.crawler.selectors import load_source_config
from luatgt.crawler.state import CrawlState
from tests.helpers import CRAWL_TABLES, GOLD_TABLES, ROOT, SEED_URLS, TEST_DB


@pytest.fixture(scope="session")
def settings() -> Settings:
    return get_settings()


@pytest.fixture(scope="session")
def engine(settings: Settings):
    from luatgt.common.db import make_engine, migrate

    eng = make_engine(settings)
    try:
        migrate(eng, settings.path(settings.root / "db" / "migrations"))
    except Exception as e:  # noqa: BLE001
        pytest.fail(f"Không kết nối/migrate được Postgres ({e}). Chạy `docker compose up -d` trước.")
    yield eng
    eng.dispose()


@pytest.fixture(scope="session")
def storage(settings: Settings):
    from luatgt.common.storage import Storage

    st = Storage(settings)
    try:
        st.ensure_buckets()
    except Exception as e:  # noqa: BLE001
        pytest.fail(f"Không kết nối được MinIO ({e}). Chạy `docker compose up -d` trước.")
    return st


@pytest.fixture(scope="session")
def env(settings, tmp_path_factory):
    """Settings trỏ tới DB `luatgt_test`, bucket test-*, seed list tạm, không delay."""
    admin = create_engine(settings.postgres_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        if not conn.execute(text("SELECT 1 FROM pg_database WHERE datname = :d"), {"d": TEST_DB}).first():
            conn.execute(text(f'CREATE DATABASE "{TEST_DB}"'))
    admin.dispose()

    seed = tmp_path_factory.mktemp("seed") / "seed.yaml"
    seed.write_text(yaml.safe_dump({"documents": [{"url": u} for u in SEED_URLS.values()]}), "utf-8")
    url = make_url(settings.postgres_url).set(database=TEST_DB).render_as_string(hide_password=False)
    s = settings.model_copy(update={
        "postgres_url": url,
        "storage": settings.storage.model_copy(
            update={"buckets": {"bronze": "test-bronze", "silver": "test-silver", "gold": "test-gold"}}
        ),
        "paths": settings.paths.model_copy(update={
            "seed_documents": seed, "silver_staging": tmp_path_factory.mktemp("silver"),
            "gold_staging": tmp_path_factory.mktemp("gold"),
        }),
        "crawler": settings.crawler.model_copy(update={"min_delay_s": 0, "max_delay_s": 0}),
    })
    engine = create_engine(s.postgres_url)
    migrate(engine, ROOT / "db" / "migrations")
    storage = Storage(s)
    storage.ensure_buckets()
    yield s, engine, storage
    engine.dispose()


@pytest.fixture
def ctx(env):
    s, engine, storage = env
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {', '.join(CRAWL_TABLES + GOLD_TABLES)} RESTART IDENTITY CASCADE"))
    for b in storage.buckets.values():
        for key in storage.list_keys(b, ""):
            storage.remove(b, key)  # bucket test, không phải Bronze thật
    source = load_source_config(ROOT / "config" / "sources" / "vbpl.yaml")
    return s, engine, storage, CrawlState(engine), source

