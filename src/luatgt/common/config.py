"""Nạp cấu hình: config/settings.yaml + biến môi trường (.env).

Thứ tự ưu tiên: biến môi trường > settings.yaml > giá trị mặc định trong model.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field, SecretStr


class CrawlerSettings(BaseModel):
    headless: bool = False
    min_delay_s: float = 3
    max_delay_s: float = 6
    page_timeout_s: float = 30
    max_retries: int = 3
    retry_backoff_s: list[float] = Field(default_factory=lambda: [10, 30, 90])
    max_relation_depth: int = 1
    download_timeout_s: float = 120
    min_file_bytes: int = 1024
    text_layer_min_chars: int = 50
    text_layer_min_ratio: float = 0.5
    respect_robots_txt: bool = True
    contact_header: str | None = None
    consent_decline_text: str | None = None
    challenge_markers: list[str] = Field(default_factory=list)


class StorageSettings(BaseModel):
    endpoint: str = "http://localhost:9000"
    access_key: str = ""
    secret_key: SecretStr = SecretStr("")
    buckets: dict[str, str] = Field(
        default_factory=lambda: {"bronze": "bronze", "silver": "silver", "gold": "gold"}
    )


class PathSettings(BaseModel):
    seed_documents: Path = Path("config/seed_documents.yaml")
    vbpl_source: Path = Path("config/sources/vbpl.yaml")
    followup: Path = Path("config/followup.yaml")
    violation_attributes: Path = Path("config/violation_attributes.yaml")
    fixtures_dir: Path = Path("tests/fixtures/vbpl")
    events_dir: Path = Path("events")
    checkpoint_dir: Path = Path("checkpoints/qa_events")
    silver_staging: Path = Path("data/silver")
    gold_staging: Path = Path("data/gold")


class ParsingSettings(BaseModel):
    parser_version: str = "dev"
    ocr_enabled: bool = True
    ocr_lang: str = "vie"
    ocr_dpi: int = 300
    pdf_min_chars_per_page: int = 50
    header_footer_ratio: float = 0.5


class SparkSettings(BaseModel):
    master: str = "local[*]"
    app_name: str = "luatgt"
    shuffle_partitions: int = 4


class EmbeddingSettings(BaseModel):
    model: str = "BAAI/bge-m3"
    dim: int = 1024
    batch_size: int = 16
    max_seq_length: int = 512


class RetrievalSettings(BaseModel):
    k: int = 20
    branch_top_n: int = 50
    rrf_k: int = 60
    rerank: bool = False
    stopwords: list[str] = Field(default_factory=list)
    query_expansions: dict[str, str] = Field(default_factory=dict)


class LLMSettings(BaseModel):
    provider: str = "anthropic"
    model: str | None = None
    api_key: SecretStr | None = None


class QASettings(BaseModel):
    min_similarity: float = 0.55
    similarity_margin: float = 0.06
    candidate_chunks: int = 12
    max_facts: int = 8
    disclaimer: str = "Thông tin tra cứu, không thay thế tư vấn pháp lý."


class QualitySettings(BaseModel):
    fine_min_vnd: int = 50_000
    fine_max_vnd: int = 150_000_000


class StreamingSettings(BaseModel):
    watermark_delay: str = "10 minutes"
    window: str = "10 minutes"


class Settings(BaseModel):
    root: Path
    timezone: str = "Asia/Ho_Chi_Minh"
    log_level: str = "INFO"
    postgres_url: str = "postgresql+psycopg://luatgt:luatgt@localhost:5432/luatgt"
    crawler: CrawlerSettings = Field(default_factory=CrawlerSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    paths: PathSettings = Field(default_factory=PathSettings)
    parsing: ParsingSettings = Field(default_factory=ParsingSettings)
    spark: SparkSettings = Field(default_factory=SparkSettings)
    embedding: EmbeddingSettings = Field(default_factory=EmbeddingSettings)
    retrieval: RetrievalSettings = Field(default_factory=RetrievalSettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    qa: QASettings = Field(default_factory=QASettings)
    quality: QualitySettings = Field(default_factory=QualitySettings)
    streaming: StreamingSettings = Field(default_factory=StreamingSettings)

    def path(self, p: Path) -> Path:
        """Đổi đường dẫn tương đối (trong config) thành tuyệt đối theo root repo."""
        return p if p.is_absolute() else self.root / p


# (tên biến môi trường, đường dẫn khoá trong Settings)
ENV_OVERRIDES: list[tuple[str, tuple[str, ...]]] = [
    ("POSTGRES_URL", ("postgres_url",)),
    ("MINIO_ENDPOINT", ("storage", "endpoint")),
    ("MINIO_ACCESS_KEY", ("storage", "access_key")),
    ("MINIO_SECRET_KEY", ("storage", "secret_key")),
    ("LLM_PROVIDER", ("llm", "provider")),
    ("LLM_MODEL", ("llm", "model")),
    ("LLM_API_KEY", ("llm", "api_key")),
    ("EMBEDDING_MODEL", ("embedding", "model")),
    ("CRAWL_MIN_DELAY_S", ("crawler", "min_delay_s")),
    ("CRAWL_MAX_DELAY_S", ("crawler", "max_delay_s")),
    ("TZ", ("timezone",)),
    ("LOG_LEVEL", ("log_level",)),
]


def find_root(start: Path | None = None) -> Path:
    """Tìm thư mục gốc repo: LUATGT_ROOT, hoặc thư mục cha gần nhất có pyproject.toml."""
    if env_root := os.environ.get("LUATGT_ROOT"):
        return Path(env_root).resolve()
    here = (start or Path.cwd()).resolve()
    for d in (here, *here.parents):
        if (d / "pyproject.toml").exists() and (d / "config").is_dir():
            return d
    return Path(__file__).resolve().parents[3]


def _set_nested(data: dict[str, Any], keys: tuple[str, ...], value: Any) -> None:
    for k in keys[:-1]:
        data = data.setdefault(k, {})
    data[keys[-1]] = value


def load_settings(
    root: Path | None = None,
    settings_file: Path | None = None,
    env: dict[str, str] | None = None,
) -> Settings:
    """Đọc settings.yaml rồi áp biến môi trường. `env` dùng cho test (mặc định os.environ)."""
    root = root or find_root()
    if env is None:
        load_dotenv(root / ".env", override=False)
        env = dict(os.environ)

    settings_file = settings_file or root / "config" / "settings.yaml"
    data: dict[str, Any] = {}
    if settings_file.exists():
        data = yaml.safe_load(settings_file.read_text(encoding="utf-8")) or {}

    for env_name, keys in ENV_OVERRIDES:
        value = env.get(env_name)
        if value not in (None, ""):
            _set_nested(data, keys, value)

    data["root"] = root
    return Settings.model_validate(data)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Settings dùng chung cho cả tiến trình."""
    return load_settings()
