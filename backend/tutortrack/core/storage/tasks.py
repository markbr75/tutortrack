from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import structlog
from celery import shared_task
from django.conf import settings

from ..models import StoredFile
from ..tasks import TenantTask
from .clamav import ScanError, scan_stream
from .client import bucket, s3_client
from .services import mark_scanned

logger = structlog.get_logger(__name__)


def _object_chunks(key: str) -> Iterator[bytes]:
    body: Any = s3_client().get_object(Bucket=bucket(), Key=key)["Body"]
    yield from body.iter_chunks(chunk_size=64 * 1024)


@shared_task(
    base=TenantTask,
    name="tutortrack.core.storage.tasks.scan_file",
    autoretry_for=(ScanError, OSError),
    retry_backoff=True,
    max_retries=5,
    ignore_result=True,
)
def scan_file(*, file_id: str, organisation_id: str) -> str:
    stored = StoredFile.objects.get(pk=file_id)
    if stored.scan_status != StoredFile.ScanStatus.PENDING:
        return str(stored.scan_status)

    config = settings.CLAMAV
    if not config["ENABLED"]:
        mark_scanned(stored, status=StoredFile.ScanStatus.SKIPPED)
        return StoredFile.ScanStatus.SKIPPED

    result = scan_stream(
        _object_chunks(stored.storage_key), host=config["HOST"], port=config["PORT"]
    )
    status = StoredFile.ScanStatus.CLEAN if result.clean else StoredFile.ScanStatus.INFECTED
    if not result.clean:
        logger.warning("file.infected", file_id=file_id, signature=result.signature)
    mark_scanned(stored, status=status)
    return status
