from __future__ import annotations

from functools import cache
from typing import Any

import boto3
from botocore.config import Config
from django.conf import settings


def _make_client(endpoint_url: str | None) -> Any:
    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        region_name=settings.AWS_S3_REGION_NAME,
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


@cache
def s3_client() -> Any:
    """Client used server-side (inside the network: e.g. http://s3:8333 in docker)."""
    return _make_client(settings.AWS_S3_ENDPOINT_URL)


@cache
def presign_client() -> Any:
    """Client used to presign URLs handed to browsers. Presigned signatures cover the host,
    so this must use the publicly reachable endpoint."""
    return _make_client(settings.AWS_S3_PUBLIC_ENDPOINT_URL or settings.AWS_S3_ENDPOINT_URL)


def bucket() -> str:
    name: str = settings.AWS_STORAGE_BUCKET_NAME
    return name


def reset_clients() -> None:
    """For tests that swap settings or mock AWS."""
    s3_client.cache_clear()
    presign_client.cache_clear()
