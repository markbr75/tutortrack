"""Files this app reads and writes in object storage: uploaded spreadsheets (scanned by the
core upload flow), generated error reports and export archives (server-generated, so no
scan is needed). Export archives are only handed out after re-authentication, so the
generic file download refuses them."""

from __future__ import annotations

import hashlib
import uuid
from typing import IO, Any

from django.contrib.contenttypes.models import ContentType

from tutortrack.core.context import require_organisation_id
from tutortrack.core.models import StoredFile
from tutortrack.core.permissions import has_perm
from tutortrack.core.storage.client import bucket, presign_client, s3_client
from tutortrack.core.storage.services import register_access_rule, safe_filename
from tutortrack.core.time import now

MAX_UPLOAD_BYTES = 30 * 1024 * 1024


def key_for(kind: str, filename: str) -> str:
    org_id = require_organisation_id()
    return f"org/{org_id}/{now():%Y/%m}/{kind}/{uuid.uuid4().hex}/{safe_filename(filename)}"


def save(
    owner: Any,
    filename: str,
    content_type: str,
    data: bytes,
    *,
    uploaded_by_id: Any = None,
    kind: str = "imports",
) -> StoredFile:
    key = key_for(kind, filename)
    s3_client().put_object(Bucket=bucket(), Key=key, Body=data, ContentType=content_type)
    return _record(
        owner,
        filename,
        content_type,
        key,
        len(data),
        hashlib.sha256(data).hexdigest(),
        uploaded_by_id,
    )


def save_stream(
    owner: Any, filename: str, content_type: str, stream: IO[bytes], size: int
) -> StoredFile:
    """Upload a large generated file (export archives) without holding it in memory."""
    key = key_for("exports", filename)
    stream.seek(0)
    digest = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(chunk)
    stream.seek(0)
    s3_client().upload_fileobj(stream, bucket(), key, ExtraArgs={"ContentType": content_type})
    return _record(owner, filename, content_type, key, size, digest.hexdigest(), None)


def _record(
    owner: Any, filename: str, content_type: str, key: str, size: int, checksum: str, by: Any
) -> StoredFile:
    return StoredFile.objects.create(
        filename=filename[:255],
        content_type=content_type,
        size_bytes=size,
        checksum_sha256=checksum,
        storage_key=key,
        status=StoredFile.Status.UPLOADED,
        scan_status=StoredFile.ScanStatus.CLEAN,
        visibility=StoredFile.Visibility.PRIVATE,
        uploaded_by_id=by,
        owner_content_type=ContentType.objects.get_for_model(owner),
        owner_object_id=str(owner.pk),
    )


def read(stored: StoredFile, *, limit: int = MAX_UPLOAD_BYTES) -> bytes:
    body: Any = s3_client().get_object(Bucket=bucket(), Key=stored.storage_key)["Body"]
    data: bytes = body.read(limit + 1)
    if len(data) > limit:
        raise ValueError("file too large")
    return data


def read_key(key: str) -> bytes:
    body: Any = s3_client().get_object(Bucket=bucket(), Key=key)["Body"]
    data: bytes = body.read()
    return data


def put_key(key: str, data: bytes, content_type: str) -> None:
    s3_client().put_object(Bucket=bucket(), Key=key, Body=data, ContentType=content_type)


def delete_key(key: str) -> None:
    s3_client().delete_object(Bucket=bucket(), Key=key)


def presigned_get(stored: StoredFile, *, expires: int = 300) -> str:
    url: str = presign_client().generate_presigned_url(
        "get_object",
        Params={
            "Bucket": bucket(),
            "Key": stored.storage_key,
            "ResponseContentDisposition": (
                f'attachment; filename="{safe_filename(stored.filename)}"'
            ),
            "ResponseContentType": stored.content_type,
        },
        ExpiresIn=expires,
    )
    return url


def _import_file(user: Any, stored: StoredFile) -> bool:
    return has_perm(user, "migration.import.view")


def _export_file(user: Any, stored: StoredFile) -> bool:
    return False  # only through the re-authenticated export download


register_access_rule("migration.importbatch", _import_file)
register_access_rule("migration.exportjob", _export_file)
