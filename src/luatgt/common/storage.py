"""Client object storage (MinIO, tương thích S3) cho Bronze/Silver/Gold."""

from __future__ import annotations

import hashlib
import io
from urllib.parse import urlparse

from minio import Minio
from minio.error import S3Error

from luatgt.common.config import Settings, get_settings
from luatgt.common.logging import get_logger

log = get_logger(__name__)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class Storage:
    """Bọc Minio client với các thao tác pipeline cần: ghi idempotent, đọc, kiểm tra tồn tại."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        cfg = self.settings.storage
        url = urlparse(cfg.endpoint)
        self.client = Minio(
            url.netloc or url.path,
            access_key=cfg.access_key,
            secret_key=cfg.secret_key.get_secret_value(),
            secure=url.scheme == "https",
        )
        self.buckets = cfg.buckets

    def bucket(self, layer: str) -> str:
        """Tên bucket theo tầng: bronze | silver | gold."""
        return self.buckets[layer]

    def ensure_buckets(self) -> list[str]:
        """Tạo bucket còn thiếu. Trả về danh sách bucket vừa tạo (idempotent)."""
        created = []
        for name in self.buckets.values():
            if not self.client.bucket_exists(name):
                self.client.make_bucket(name)
                created.append(name)
                log.info("bucket_created bucket=%s", name)
        return created

    def exists(self, bucket: str, key: str) -> bool:
        try:
            self.client.stat_object(bucket, key)
            return True
        except S3Error as e:
            if e.code in ("NoSuchKey", "NoSuchObject", "NotFound"):
                return False
            raise

    def put_bytes(
        self,
        bucket: str,
        key: str,
        data: bytes,
        content_type: str = "application/octet-stream",
        overwrite: bool = False,
    ) -> bool:
        """Ghi object. Mặc định không ghi đè (Bronze bất biến). Trả True nếu đã ghi."""
        if not overwrite and self.exists(bucket, key):
            return False
        self.client.put_object(
            bucket, key, io.BytesIO(data), length=len(data), content_type=content_type
        )
        return True

    def get_bytes(self, bucket: str, key: str) -> bytes:
        resp = self.client.get_object(bucket, key)
        try:
            return resp.read()
        finally:
            resp.close()
            resp.release_conn()

    def list_keys(self, bucket: str, prefix: str) -> list[str]:
        """Tên object theo prefix, sắp xếp tăng dần."""
        return sorted(
            o.object_name for o in self.client.list_objects(bucket, prefix=prefix, recursive=True)
        )

    def remove(self, bucket: str, key: str) -> None:
        """Chỉ dùng cho test/tầng tái tạo được. Không gọi trên Bronze trong pipeline."""
        self.client.remove_object(bucket, key)

    def ping(self) -> bool:
        self.client.list_buckets()
        return True
