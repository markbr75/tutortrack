"""The DSAR export compiler (E29-T05, FR-29-4).

``compile_draft`` asks every registered provider for its sections about the person and
stores the result as a private JSON draft. Staff review it and mark redactions (a whole
record, one field, or a file); ``build_package`` then applies them and produces the zip
that is delivered: ``data.json`` (machine-readable, also for portability), ``summary.pdf``
(a readable overview with the person's rights) and ``files/`` (their documents).
"""

from __future__ import annotations

import hashlib
import io
import json
import uuid
import zipfile
from typing import Any

from django.contrib.contenttypes.models import ContentType
from django.template.loader import render_to_string
from django.utils.translation import gettext as _

from tutortrack.core.context import require_organisation_id
from tutortrack.core.events.base import to_json_safe
from tutortrack.core.models import StoredFile
from tutortrack.core.storage.client import bucket, s3_client
from tutortrack.core.storage.services import safe_filename
from tutortrack.core.time import now

from . import registry
from .models import DataSubjectRequest

REDACTED = "[redacted]"
MAX_FILE_BYTES = 50 * 1024 * 1024


def _save(request: DataSubjectRequest, filename: str, content_type: str, data: bytes) -> StoredFile:
    org_id = require_organisation_id()
    key = f"org/{org_id}/{now():%Y/%m}/privacy/{uuid.uuid4().hex}/{safe_filename(filename)}"
    s3_client().put_object(Bucket=bucket(), Key=key, Body=data, ContentType=content_type)
    return StoredFile.objects.create(
        filename=filename[:255],
        content_type=content_type,
        size_bytes=len(data),
        checksum_sha256=hashlib.sha256(data).hexdigest(),
        storage_key=key,
        status=StoredFile.Status.UPLOADED,
        scan_status=StoredFile.ScanStatus.CLEAN,
        visibility=StoredFile.Visibility.PRIVATE,
        owner_content_type=ContentType.objects.get_for_model(DataSubjectRequest),
        owner_object_id=str(request.pk),
    )


def read(stored: StoredFile) -> bytes:
    body: Any = s3_client().get_object(Bucket=bucket(), Key=stored.storage_key)["Body"]
    data: bytes = body.read()
    return data


def _file_entry(stored: Any, section: str) -> dict[str, Any]:
    return {
        "id": str(stored.pk),
        "section": section,
        "filename": stored.filename,
        "content_type": stored.content_type,
        "size_bytes": stored.size_bytes,
    }


def compile_document(request: DataSubjectRequest) -> dict[str, Any]:
    person = registry.resolve(request.subject_type, request.subject_id)
    sections: list[dict[str, Any]] = []
    files: list[dict[str, Any]] = []
    for provider in registry.providers():
        if provider.export is not None:
            for section in provider.export(person):
                if section.records:
                    sections.append(
                        {
                            "key": section.key,
                            "title": section.title,
                            "provider": provider.key,
                            "records": to_json_safe(section.records),
                        }
                    )
        if provider.files is not None:
            files += [
                _file_entry(f, provider.key)
                for f in provider.files(person)
                if getattr(f, "is_downloadable", False)
            ]
    return {
        "format": "tutortrack.dsar/1",
        "request": {
            "reference": request.reference,
            "kind": request.kind,
            "received_at": request.received_at.isoformat(),
            "generated_at": now().isoformat(),
        },
        "subject": {"type": request.subject_type, "id": request.subject_id},
        "sections": sections,
        "files": files,
    }


def summary_of(document: dict[str, Any]) -> dict[str, Any]:
    """Counts only (stored on the request; never personal data)."""
    return {
        "sections": {s["key"]: len(s["records"]) for s in document.get("sections", [])},
        "files": len(document.get("files", [])),
    }


def compile_draft(request: DataSubjectRequest) -> StoredFile:
    document = compile_document(request)
    data = json.dumps(document, indent=2, ensure_ascii=False).encode()
    return _save(request, f"{request.reference}-draft.json", "application/json", data)


def load_draft(request: DataSubjectRequest) -> dict[str, Any]:
    if request.draft_file is None:
        return {"sections": [], "files": []}
    loaded: dict[str, Any] = json.loads(read(request.draft_file))
    return loaded


def apply_redactions(document: dict[str, Any], redactions: list[dict[str, Any]]) -> dict[str, Any]:
    """Redactions: ``{"section", "record_id"}`` removes a record, ``{"section", "record_id",
    "field"}`` blanks one field, ``{"file_id"}`` leaves a file out."""
    drop_records = {
        (r["section"], str(r["record_id"]))
        for r in redactions
        if r.get("section") and not r.get("field")
    }
    drop_fields = {
        (r["section"], str(r["record_id"]), r["field"])
        for r in redactions
        if r.get("section") and r.get("field")
    }
    drop_files = {str(r["file_id"]) for r in redactions if r.get("file_id")}
    sections = []
    for section in document.get("sections", []):
        records = []
        for record in section["records"]:
            rid = str(record.get("id", ""))
            if (section["key"], rid) in drop_records:
                continue
            records.append(
                {
                    k: (REDACTED if (section["key"], rid, k) in drop_fields else v)
                    for k, v in record.items()
                }
            )
        sections.append({**section, "records": records})
    files = [f for f in document.get("files", []) if f["id"] not in drop_files]
    return {**document, "sections": sections, "files": files, "redacted": len(redactions) > 0}


def _summary_pdf(request: DataSubjectRequest, document: dict[str, Any]) -> bytes:
    from weasyprint import HTML

    from tutortrack.tenancy.models import Organisation

    org = Organisation.objects.get(pk=request.organisation_id)
    html = render_to_string(
        "privacy/dsar_summary.html",
        {
            "organisation": org.name,
            "request": request,
            "sections": [
                {"title": s["title"], "count": len(s["records"]), "records": s["records"][:50]}
                for s in document.get("sections", [])
            ],
            "files": document.get("files", []),
            "generated_at": now(),
        },
    )
    return bytes(HTML(string=html).write_pdf())


def build_package(request: DataSubjectRequest) -> StoredFile:
    """The delivered zip: redacted ``data.json``, ``summary.pdf`` and ``files/``."""
    document = apply_redactions(load_draft(request), list(request.redactions or []))
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("data.json", json.dumps(document, indent=2, ensure_ascii=False))
        archive.writestr("summary.pdf", _summary_pdf(request, document))
        archive.writestr(
            "README.txt",
            _(
                "This is a copy of the personal data we hold about you. data.json is "
                "machine-readable; summary.pdf is a readable overview; files/ holds your "
                "documents."
            ),
        )
        wanted = {f["id"]: f for f in document.get("files", [])}
        for stored in StoredFile.objects.filter(pk__in=list(wanted)):
            if not stored.is_downloadable or stored.size_bytes > MAX_FILE_BYTES:
                continue
            entry = wanted[str(stored.pk)]
            name = f"files/{entry['section']}/{str(stored.pk)[:8]}-{safe_filename(stored.filename)}"
            archive.writestr(name, read(stored))
    return _save(request, f"{request.reference}.zip", "application/zip", buffer.getvalue())
