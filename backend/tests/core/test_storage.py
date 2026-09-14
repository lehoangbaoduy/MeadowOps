"""Unit 32 (MEADOWOPS-INFRA-005): R2AttachmentStorage against a mocked
S3-compatible API (moto) - no real Cloudflare R2 credentials required to
run this test, matching Settings.attachment_storage_backend's own "local"
default that keeps the rest of the suite (and CI) unaffected."""

from collections.abc import Generator

import boto3
import pytest
from moto import mock_aws

from app.core.storage import AttachmentNotInStorageError, R2AttachmentStorage

_BUCKET = "meadowops-test-attachments"


@pytest.fixture
def r2_storage() -> Generator[R2AttachmentStorage, None, None]:
    # Dummy credentials (verify_before_shipping item #2, decision 1627):
    # if moto's interception ever fails to engage, boto3 fails closed with a
    # bogus-credentials error against real S3, rather than silently
    # attempting a real network call in CI.
    with mock_aws():
        # region_name="us-east-1", not R2's real "auto" - this fixture only
        # needs to exercise the S3-compatible put/get/delete_object surface
        # moto mocks; us-east-1 is the one region CreateBucket accepts with
        # no LocationConstraint, which is all that's different here.
        client = boto3.client(
            "s3",
            region_name="us-east-1",
            aws_access_key_id="test",
            aws_secret_access_key="test",
        )
        client.create_bucket(Bucket=_BUCKET)
        yield R2AttachmentStorage(bucket=_BUCKET, client=client)


class TestR2AttachmentStorage:
    def test_round_trips_saved_content(self, r2_storage: R2AttachmentStorage) -> None:
        r2_storage.save("key-1", b"hello world")
        assert r2_storage.load("key-1") == b"hello world"

    def test_load_of_a_missing_key_raises_not_in_storage(
        self, r2_storage: R2AttachmentStorage
    ) -> None:
        with pytest.raises(AttachmentNotInStorageError):
            r2_storage.load("does-not-exist")

    def test_delete_removes_the_object(self, r2_storage: R2AttachmentStorage) -> None:
        r2_storage.save("key-2", b"data")
        r2_storage.delete("key-2")
        with pytest.raises(AttachmentNotInStorageError):
            r2_storage.load("key-2")

    def test_delete_of_a_missing_key_is_idempotent(
        self, r2_storage: R2AttachmentStorage
    ) -> None:
        r2_storage.delete("never-existed")  # must not raise

    def test_save_overwrites_an_existing_key(self, r2_storage: R2AttachmentStorage) -> None:
        r2_storage.save("key-3", b"first")
        r2_storage.save("key-3", b"second")
        assert r2_storage.load("key-3") == b"second"
