"""Anonymous uploads from public forms (gap batch G5a: FR-17-1 enquiry attachments, FR-18-1
CV and video).

The same direct-to-storage flow as signed-in uploads, made safe for anonymous visitors:

1. ``create`` checks the *context* (a published form or job opening that has a file field
   of this kind), the kind's types and size limit and the storage quota, creates a private
   ``StoredFile`` under ``org/<org>/public/`` with no uploader, and returns a presigned PUT
   plus a signed *upload token* (``core.signing``; the only handle the visitor gets).
2. The browser PUTs the bytes to storage.
3. ``complete`` checks the object's size and declared type (``complete_upload``), then its
   first bytes against the type's signature (a renamed ``.exe`` is rejected and deleted),
   and queues the usual antivirus scan.
4. The form submission carries the token; the owning service ``claim``s it, which attaches
   the file to the new record (enquiry or application) exactly once.

Files are private: only staff with the owner's access rule can download them, and only
once the scan is clean. Uploads never claimed are deleted by the ``unclaimed_public_uploads``
retention category (``core/privacy.py``).

Apps declare which contexts may receive uploads with ``register_context(name, resolver)``:
the resolver turns a reference (a form slug) into the set of kinds it accepts, or ``None``
when it is not open for uploads.
"""

from __future__ import annotations

import contextlib
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from botocore.exceptions import ClientError
from django.conf import settings
from django.core import signing
from django.db import models, transaction
from django.utils.translation import gettext as _

from ..context import require_organisation_id
from ..exceptions import BusinessRuleViolation
from ..models import StoredFile
from ..time import now
from .client import bucket, presign_client, s3_client
from .services import PresignedUpload, _check_quota, _reject, attach, complete_upload, safe_filename

SALT = "tutortrack.public-upload"
PREFIX = "public"
MAX_FILES_PER_FIELD = 5

DOCUMENT_TYPES = (
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
)
IMAGE_TYPES = ("image/jpeg", "image/png", "image/webp", "image/heic")
VIDEO_TYPES = ("video/mp4", "video/quicktime", "video/webm")


@dataclass(frozen=True)
class Kind:
    key: str
    content_types: tuple[str, ...]
    max_bytes_setting: str


KINDS: dict[str, Kind] = {
    "cv": Kind("cv", DOCUMENT_TYPES, "DOCUMENT_MAX_BYTES"),
    "document": Kind("document", (*DOCUMENT_TYPES, *IMAGE_TYPES), "DOCUMENT_MAX_BYTES"),
    "video": Kind("video", VIDEO_TYPES, "VIDEO_MAX_BYTES"),
}


KIND_CHOICES = sorted(KINDS)


def max_bytes(kind: str) -> int:
    return int(settings.PUBLIC_UPLOADS[KINDS[kind].max_bytes_setting])


# --- contexts ----------------------------------------------------------------------------------

Resolver = Callable[[str], set[str] | None]
_contexts: dict[str, Resolver] = {}


def register_context(name: str, resolver: Resolver) -> None:
    """``resolver(reference)`` → the upload kinds the published form accepts, or ``None``."""
    _contexts[name] = resolver


def file_kinds(fields: Iterable[dict[str, Any]]) -> set[str]:
    """The upload kinds used by a form schema's ``file`` fields."""
    return {
        str(f.get("file_kind") or "document")
        for f in fields
        if f.get("type") == "file" and str(f.get("file_kind") or "document") in KINDS
    }


def _accepted(context: str, reference: str) -> set[str]:
    resolver = _contexts.get(context)
    kinds = resolver(reference) if resolver else None
    if not kinds:
        raise BusinessRuleViolation(
            _("This form doesn't take file uploads."), extra={"code": "uploads_not_accepted"}
        )
    return kinds


# --- signature sniffing ------------------------------------------------------------------------


def _ftyp(head: bytes) -> bool:
    return head[4:8] == b"ftyp"


SIGNATURES: dict[str, Callable[[bytes], bool]] = {
    "application/pdf": lambda h: h.startswith(b"%PDF-"),
    "application/msword": lambda h: h.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"),
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": (
        lambda h: h.startswith(b"PK\x03\x04")
    ),
    "image/jpeg": lambda h: h.startswith(b"\xff\xd8\xff"),
    "image/png": lambda h: h.startswith(b"\x89PNG\r\n\x1a\n"),
    "image/webp": lambda h: h.startswith(b"RIFF") and h[8:12] == b"WEBP",
    "image/heic": _ftyp,
    "video/mp4": _ftyp,
    "video/quicktime": lambda h: _ftyp(h) or h[4:8] in (b"moov", b"mdat", b"wide", b"free"),
    "video/webm": lambda h: h.startswith(b"\x1a\x45\xdf\xa3"),
}


def matches_signature(content_type: str, head: bytes) -> bool:
    check = SIGNATURES.get(content_type)
    return bool(check and check(head))


def _head_bytes(stored: StoredFile, length: int = 64) -> bytes:
    try:
        body: Any = s3_client().get_object(
            Bucket=bucket(), Key=stored.storage_key, Range=f"bytes=0-{length - 1}"
        )["Body"]
    except ClientError as exc:
        raise BusinessRuleViolation(
            _("The file has not been uploaded yet."), extra={"code": "upload_missing"}
        ) from exc
    data: bytes = body.read()
    return data


# --- tokens ------------------------------------------------------------------------------------


def _token(stored: StoredFile, kind: str, context: str, reference: str) -> str:
    return signing.dumps(
        {
            "f": str(stored.pk),
            "o": str(stored.organisation_id),
            "k": kind,
            "c": f"{context}:{reference}",
        },
        salt=SALT,
        compress=True,
    )


@dataclass(frozen=True)
class Ticket:
    file_id: str
    kind: str
    context: str


def read_token(token: str) -> Ticket:
    try:
        data = signing.loads(
            str(token), salt=SALT, max_age=int(settings.PUBLIC_UPLOADS["TOKEN_MAX_AGE_SECONDS"])
        )
    except signing.BadSignature as exc:  # includes SignatureExpired
        raise BusinessRuleViolation(
            _("The upload has expired. Please add the file again."),
            extra={"code": "upload_token_invalid"},
        ) from exc
    if data.get("o") != str(require_organisation_id()):
        raise BusinessRuleViolation(
            _("The upload has expired. Please add the file again."),
            extra={"code": "upload_token_invalid"},
        )
    return Ticket(file_id=str(data["f"]), kind=str(data["k"]), context=str(data["c"]))


# --- the flow ----------------------------------------------------------------------------------


@transaction.atomic
def create(
    *, context: str, reference: str, kind: str, filename: str, content_type: str, size_bytes: int
) -> tuple[StoredFile, PresignedUpload, str]:
    if kind not in KINDS:
        raise BusinessRuleViolation(_("Unknown upload type."), extra={"code": "upload_kind"})
    if kind not in _accepted(context, reference):
        raise BusinessRuleViolation(
            _("This form doesn't take this kind of file."), extra={"code": "uploads_not_accepted"}
        )
    spec = KINDS[kind]
    if content_type not in spec.content_types:
        raise BusinessRuleViolation(
            _("Files of this type can't be uploaded here."),
            extra={"code": "file_type_not_allowed", "allowed": list(spec.content_types)},
        )
    limit = max_bytes(kind)
    if size_bytes <= 0 or size_bytes > limit:
        raise BusinessRuleViolation(
            _("The file is too large (the limit is %(mb)s MB).") % {"mb": limit // (1024 * 1024)},
            extra={"code": "file_too_large", "max_bytes": limit},
        )
    org_id = require_organisation_id()
    _check_quota(size_bytes)
    key = f"org/{org_id}/{PREFIX}/{now():%Y/%m}/{uuid.uuid4().hex}/{safe_filename(filename)}"
    stored = StoredFile.objects.create(
        filename=filename[:255],
        content_type=content_type,
        size_bytes=size_bytes,
        storage_key=key,
        visibility=StoredFile.Visibility.PRIVATE,
        uploaded_by=None,
    )
    expires = int(settings.FILE_UPLOADS["PRESIGN_EXPIRY_SECONDS"])
    url = presign_client().generate_presigned_url(
        "put_object",
        Params={"Bucket": bucket(), "Key": key, "ContentType": content_type},
        ExpiresIn=expires,
    )
    upload = PresignedUpload(
        url=url, method="PUT", headers={"Content-Type": content_type}, expires_in=expires
    )
    return stored, upload, _token(stored, kind, context, reference)


def _ticket_file(ticket: Ticket) -> StoredFile:
    stored = StoredFile.objects.filter(pk=ticket.file_id).first()
    if stored is None or not stored.storage_key.startswith(
        f"org/{stored.organisation_id}/{PREFIX}/"
    ):
        raise BusinessRuleViolation(
            _("The upload has expired. Please add the file again."),
            extra={"code": "upload_token_invalid"},
        )
    return stored


def complete(token: str) -> StoredFile:
    """Verify size, declared type and the file's signature, then queue the scan."""
    stored = _ticket_file(read_token(token))
    if stored.status == StoredFile.Status.UPLOADED:
        return stored  # a retried request
    if stored.status == StoredFile.Status.REJECTED:
        raise BusinessRuleViolation(_("This file was rejected."), extra={"code": "upload_rejected"})
    if not matches_signature(stored.content_type, _head_bytes(stored)):
        _reject(stored)
        raise BusinessRuleViolation(
            _("The file's contents don't match its type."), extra={"code": "upload_mismatch"}
        )
    return complete_upload(stored)


def claim(
    tokens: Iterable[str], *, owner: models.Model, kinds: Iterable[str], context: str
) -> list[StoredFile]:
    """Attach uploaded files to the record the submission created. Each token works once,
    only for its own form (``context`` = ``"form:<slug>"``) and only for the field's kinds."""
    allowed = set(kinds)
    out: list[StoredFile] = []
    for token in tokens:
        ticket = read_token(token)
        if ticket.context != context or ticket.kind not in allowed:
            raise BusinessRuleViolation(
                _("The upload doesn't belong to this form."),
                extra={"code": "upload_token_invalid"},
            )
        stored = StoredFile.objects.select_for_update().get(pk=_ticket_file(ticket).pk)
        if stored.owner_content_type_id is not None:
            raise BusinessRuleViolation(
                _("This file has already been sent."), extra={"code": "upload_claimed"}
            )
        if stored.status != StoredFile.Status.UPLOADED or (
            stored.scan_status == StoredFile.ScanStatus.INFECTED
        ):
            raise BusinessRuleViolation(
                _("The file hasn't finished uploading."), extra={"code": "upload_incomplete"}
            )
        out.append(attach(stored, owner))
    return out


def tokens_of(value: Any) -> list[str]:
    """A file field's answer: one token or a list of them."""
    if value in (None, "", []):
        return []
    items = value if isinstance(value, list) else [value]
    return [str(v) for v in items if isinstance(v, str) and v]


def purge_unclaimed(cutoff: datetime, dry_run: bool, limit: int) -> int:
    """Delete anonymous uploads that never reached a record (the visitor gave up)."""
    org_id = require_organisation_id()
    qs = StoredFile.objects.filter(
        storage_key__startswith=f"org/{org_id}/{PREFIX}/",
        owner_content_type__isnull=True,
        created_at__lt=cutoff,
    ).order_by("created_at")[:limit]
    rows = list(qs)
    if dry_run:
        return len(rows)
    client = s3_client()
    for stored in rows:
        with contextlib.suppress(ClientError):  # already gone
            client.delete_object(Bucket=bucket(), Key=stored.storage_key)
        stored.delete()
    return len(rows)
