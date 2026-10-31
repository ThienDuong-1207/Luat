from pathlib import Path

from luatgt.common.config import find_root, load_settings


def test_find_root_has_config():
    root = find_root()
    assert (root / "config" / "settings.yaml").exists()


def test_yaml_values_loaded():
    s = load_settings(env={})
    assert s.crawler.retry_backoff_s == [10, 30, 90]
    assert s.embedding.dim == 1024
    assert s.storage.buckets["bronze"] == "bronze"


def test_env_overrides_yaml():
    s = load_settings(
        env={
            "CRAWL_MIN_DELAY_S": "5",
            "POSTGRES_URL": "postgresql+psycopg://u:p@db:5432/x",
            "MINIO_SECRET_KEY": "s3cret",
            "LLM_MODEL": "",
        }
    )
    assert s.crawler.min_delay_s == 5.0
    assert s.postgres_url.endswith("@db:5432/x")
    assert s.storage.secret_key.get_secret_value() == "s3cret"
    assert "s3cret" not in repr(s)  # không lộ bí mật khi log
    assert s.llm.model is None  # chuỗi rỗng = không đặt


def test_relative_paths_resolve_to_root():
    s = load_settings(env={})
    assert s.path(Path("config/seed_documents.yaml")).exists()
    assert s.path(s.paths.vbpl_source).exists()
