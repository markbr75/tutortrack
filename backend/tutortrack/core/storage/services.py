"""Direct-to-storage uploads.

1. ``create_upload`` validates type/size and returns a presigned PUT URL.
2. The browser PUTs the bytes straight to S3.
3. ``complete_upload`` verifies the object and queues the antivirus scan.
4. ``download_url`` returns a short-lived presigned GET once the file is clean.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from botocore.exceptions import ClientError
from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.db import models, transaction

from .. import audit
from ..context import get_request_context, require_organisation_id
from ..exceptions import BusinessRuleViolation, Conflict, PermissionDenied
from ..models import StoredFile
from ..time import now
from .client import bucket, presign_client, s3_client

_SAFE_CHARS = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass(frozen=True)
class PresignedUpload:
    url: str
    method: str
    headers: dict[str, str]
    expires_in: int


def safe_filename(filename: str) -> str:
    name = filename.replace("\\", "/").rsplit("/", 1)[-1].strip() or "file"
    cleaned = _SAFE_CHARS.sub("-", name).strip("-.") or "file"
    return cleaned[-120:]


def _upload_policy() -> dict[str, Any]:
    # E02 adds per-organisation overrides on top of the platform defaults.
    policy: dict[str, Any] = settings.FILE_UPLOADS
    return policy


def _validate(content_type: str, size_bytes: int) -> None:
    policy = _upload_policy()
    if content_type not in policy["ALLOWED_CONTENT_TYPES"]:
        raise BusinessRuleViolation(
            f"Files of type {content_type!r} are not allowed.",
            extra={"code": "file_type_not_allowed"},
        )
    if size_bytes <= 0 or size_bytes > policy["MAX_SIZE_BYTES"]:
        raise BusinessRuleViolation(
            f"File size must be between 1 byte and {policy['MAX_SIZE_BYTES']} bytes.",
            extra={"code": "file_too_large"},
        )


def _check_quota(size_bytes: int) -> None:
    """The plan's ``storage_gb`` (E04)."""
    from django.db.models import Sum

    from tutortrack.core import entitlements

    if entitlements.limit("storage_gb") is None:
        return
    used = StoredFile.objects.exclude(status=StoredFile.Status.REJECTED).aggregate(
        total=Sum("size_bytes")
    )["total"]
    entitlements.require_capacity(
        "storage_gb", used=int(used or 0), adding=size_bytes, unit=1024**3
    )


@transaction.atomic
def create_upload(
    *,
    filename: str,
    content_type: str,
    size_bytes: int,
    visibility: str = StoredFile.Visibility.PRIVATE,
    owner: models.Model | None = None,
) -> tuple[StoredFile, PresignedUpload]:
    _validate(content_type, size_bytes)
    org_id = require_organisation_id()
    _check_quota(size_bytes)
    today = now()
    key = f"org/{org_id}/{today:%Y/%m}/{uuid.uuid4().hex}/{safe_filename(filename)}"
    stored = StoredFile(
        filename=filename[:255],
        content_type=content_type,
        size_bytes=size_bytes,
        storage_key=key,
        visibility=visibility,
        uploaded_by_id=get_request_context().user_id,
    )
    if owner is not None:
        stored.owner_content_type = ContentType.objects.get_for_model(owner)
        stored.owner_object_id = str(owner.pk)
    stored.save()

    expires = _upload_policy()["PRESIGN_EXPIRY_SECONDS"]
    url = presign_client().generate_presigned_url(
        "put_object",
        Params={"Bucket": bucket(), "Key": key, "ContentType": content_type},
        ExpiresIn=expires,
    )
    return stored, PresignedUpload(
        url=url, method="PUT", headers={"Content-Type": content_type}, expires_in=expires
    )


def complete_upload(stored: StoredFile) -> StoredFile:
    """Verify the uploaded object, then mark it uploaded and queue the scan.

    Not wrapped in a single transaction on purpose: a rejected upload must stay rejected
    (and its object deleted) even though we raise to the caller.
    """
    if stored.status != StoredFile.Status.PENDING_UPLOAD:
        raise Conflict("This upload has already been completed.")
    try:
        head = s3_client().head_object(Bucket=bucket(), Key=stored.storage_key)
    except ClientError as exc:
        raise BusinessRuleViolation(
            "The file has not been uploaded yet.", extra={"code": "upload_missing"}
        ) from exc

    actual_size = int(head["ContentLength"])
    actual_type = head.get("ContentType", "")
    if actual_size != stored.size_bytes or actual_type != stored.content_type:
        _reject(stored)
        raise BusinessRuleViolation(
            "The uploaded file does not match the declared size or type.",
            extra={"code": "upload_mismatch"},
        )

    with transaction.atomic():
        stored.status = StoredFile.Status.UPLOADED
        stored.save(update_fields=["status", "updated_at"])
        audit.record(stored, "upload", {"filename": stored.filename, "size": stored.size_bytes})

        from .tasks import scan_file

        org_id = str(stored.organisation_id)
        file_id = str(stored.id)
        transaction.on_commit(lambda: scan_file.delay(file_id=file_id, organisation_id=org_id))
    return stored


def _reject(stored: StoredFile) -> None:
    s3_client().delete_object(Bucket=bucket(), Key=stored.storage_key)
    stored.status = StoredFile.Status.REJECTED
    stored.save(update_fields=["status", "updated_at"])


AccessRule = Callable[[Any, StoredFile], bool]
_access_rules: dict[str, AccessRule] = {}


def register_access_rule(owner_label: str, rule: AccessRule) -> None:
    """Who else may open private files attached to ``owner_label`` records (e.g.
    ``recruitment.compliancerecord``: holders of ``compliance.view``)."""
    _access_rules[owner_label] = rule


def can_access(user: Any, stored: StoredFile) -> bool:
    """Uploader, superusers, non-private files, or an owner-specific rule.

    The tenant manager already guarantees the file belongs to the current organisation.
    """
    if not getattr(user, "is_authenticated", False):
        return False
    if user.is_superuser or stored.uploaded_by_id == user.pk:
        return True
    if stored.visibility != StoredFile.Visibility.PRIVATE:
        return True
    owner_type = stored.owner_content_type
    if owner_type is not None:
        label = f"{owner_type.app_label}.{owner_type.model}"
        rule = _access_rules.get(label)
        return bool(rule and rule(user, stored))
    return False


def attach(stored: StoredFile, owner: models.Model) -> StoredFile:
    """Link an uploaded file to the record it belongs to."""
    stored.owner_content_type = ContentType.objects.get_for_model(owner)
    stored.owner_object_id = str(owner.pk)
    stored.save(update_fields=["owner_content_type", "owner_object_id"])
    return stored


def download_url(user: Any, stored: StoredFile, *, inline: bool = False) -> tuple[str, int]:
    if not can_access(user, stored):
        raise PermissionDenied()
    if not stored.is_downloadable:
        raise Conflict(
            "This file is not available for download yet.",
            extra={"file_status": stored.status, "scan_status": stored.scan_status},
        )
    expires = _upload_policy()["PRESIGN_EXPIRY_SECONDS"]
    disposition = "inline" if inline else "attachment"
    url = presign_client().generate_presigned_url(
        "get_object",
        Params={
            "Bucket": bucket(),
            "Key": stored.storage_key,
            "ResponseContentDisposition": (
                f'{disposition}; filename="{safe_filename(stored.filename)}"'
            ),
            "ResponseContentType": stored.content_type,
        },
        ExpiresIn=expires,
    )
    return url, expires


def mark_scanned(stored: StoredFile, *, status: str) -> None:
    stored.scan_status = status
    stored.scanned_at = now()
    stored.save(update_fields=["scan_status", "scanned_at", "updated_at"])
    if status == StoredFile.ScanStatus.INFECTED:
        _reject(stored)
        audit.record(stored, "quarantine", {"scan_status": status})
