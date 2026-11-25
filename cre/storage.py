"""Immutable, content-addressed private blobs. Object keys never leave trusted services."""

import hashlib
import os
import re
import tempfile
from functools import lru_cache
from pathlib import Path

import boto3
from botocore.exceptions import ClientError


@lru_cache
def _client(endpoint, region):
    return boto3.client("s3", endpoint_url=endpoint, region_name=region)


def _s3():
    return _client(
        os.getenv("CRE_S3_ENDPOINT") or None, os.getenv("AWS_REGION", "us-east-1")
    )


def _path(key: str) -> Path:
    if os.getenv("CRE_ENV") == "production":
        raise RuntimeError("Production requires private object storage (CRE_S3_BUCKET)")
    return Path(os.getenv("CRE_STORAGE_DIR", ".local/objects")) / key[:2] / key


def put_bytes(data: bytes) -> str:
    key = hashlib.sha256(data).hexdigest()
    bucket = os.getenv("CRE_S3_BUCKET")
    if bucket:
        for attempt in range(3):
            try:
                _s3().put_object(
                    Bucket=bucket,
                    Key=f"objects/{key}",
                    Body=data,
                    IfNoneMatch="*",
                    ServerSideEncryption="AES256",
                )
                break
            except ClientError as exc:
                status = exc.response["ResponseMetadata"]["HTTPStatusCode"]
                if status == 412:
                    break  # Another writer published the same content.
                if status != 409 or attempt == 2:
                    raise
        return key
    path = _path(key)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.NamedTemporaryFile(dir=path.parent) as temp:
        temp.write(data)
        temp.flush()
        os.fsync(temp.fileno())
        try:
            os.link(temp.name, path)
        except FileExistsError:
            pass
    return key


def get_bytes(key: str) -> bytes:
    if not re.fullmatch(r"[a-f0-9]{64}", key):
        raise ValueError("Invalid content key")
    bucket = os.getenv("CRE_S3_BUCKET")
    if bucket:
        stream = _s3().get_object(Bucket=bucket, Key=f"objects/{key}")["Body"]
        try:
            data = stream.read()
        finally:
            stream.close()
    else:
        data = _path(key).read_bytes()
    if hashlib.sha256(data).hexdigest() != key:
        raise OSError("Stored artifact failed integrity verification")
    return data
