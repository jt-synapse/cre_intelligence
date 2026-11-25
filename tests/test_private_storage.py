import os
from uuid import uuid4

import boto3
import pytest
from botocore.config import Config


@pytest.mark.skipif(
    not os.getenv("CRE_TEST_S3_ENDPOINT"), reason="requires a disposable S3 endpoint"
)
def test_private_s3_roundtrip(monkeypatch):
    endpoint = os.environ["CRE_TEST_S3_ENDPOINT"]
    if not endpoint.startswith("http://127.0.0.1:"):
        pytest.fail("Use loopback S3 test service")
    monkeypatch.setenv("CRE_S3_ENDPOINT", endpoint)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "cre-local-test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "local-only-storage-test")
    bucket = "cre-qualification-" + uuid4().hex
    monkeypatch.setenv("CRE_S3_BUCKET", bucket)
    client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        region_name="us-east-1",
        config=Config(s3={"addressing_style": "path"}),
    )
    client.create_bucket(Bucket=bucket)
    from cre.storage import get_bytes, put_bytes

    key = put_bytes(b"S3 integration fixture")
    assert put_bytes(b"S3 integration fixture") == key
    assert get_bytes(key) == b"S3 integration fixture"
    assert client.list_objects_v2(Bucket=bucket)["KeyCount"] == 1


def test_s3_retries_conflicting_concurrent_create(monkeypatch):
    from botocore.exceptions import ClientError
    from cre import storage

    attempts = []

    class ConcurrentWriter:
        def put_object(self, **kwargs):
            attempts.append(kwargs)
            status = 409 if len(attempts) == 1 else 412
            raise ClientError(
                {
                    "Error": {"Code": "Conflict"},
                    "ResponseMetadata": {"HTTPStatusCode": status},
                },
                "PutObject",
            )

    monkeypatch.setenv("CRE_S3_BUCKET", "fixture")
    monkeypatch.setattr(storage, "_s3", lambda: ConcurrentWriter())
    key = storage.put_bytes(b"concurrent")
    assert len(attempts) == 2 and all(a["Key"] == "objects/" + key for a in attempts)
