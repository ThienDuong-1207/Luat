import uuid

import pytest

pytestmark = pytest.mark.integration

TEST_BUCKET = "luatgt-test"  # bucket riêng cho test, không đụng Bronze


@pytest.fixture
def test_bucket(storage):
    if not storage.client.bucket_exists(TEST_BUCKET):
        storage.client.make_bucket(TEST_BUCKET)
    yield TEST_BUCKET
    for obj in storage.client.list_objects(TEST_BUCKET, recursive=True):
        storage.client.remove_object(TEST_BUCKET, obj.object_name)
    storage.client.remove_bucket(TEST_BUCKET)


def test_ping(storage):
    assert storage.ping()


def test_layer_buckets_exist(storage):
    for layer in ("bronze", "silver", "gold"):
        assert storage.client.bucket_exists(storage.bucket(layer))


def test_ensure_buckets_idempotent(storage):
    assert storage.ensure_buckets() == []


def test_put_is_write_once_by_default(storage, test_bucket):
    key = f"m0/{uuid.uuid4()}.txt"
    assert storage.put_bytes(test_bucket, key, "Điều 1".encode()) is True
    assert storage.put_bytes(test_bucket, key, b"khac") is False  # không ghi đè
    assert storage.get_bytes(test_bucket, key).decode() == "Điều 1"
    assert storage.put_bytes(test_bucket, key, b"moi", overwrite=True) is True
    assert storage.get_bytes(test_bucket, key) == b"moi"
