"""Built-in click-to-sign with an audit trail (FR-05-9, FR-15-8, FR-18-5; gap batch G2).

Staff mark a document on a family or tutor record as needing a signature; the family signs
it in the portal (a tutor signs theirs, and their onboarding agreements, in the tutor
portal). Signing records a ``Signature``: the signer (login, typed name, email, role), the
time, IP address and browser, the SHA-256 of exactly what was signed, and a signed PDF
copy: a signature page that states all of this, with the original file embedded in the PDF
(PDF attachment), or with the agreement text above it. The copy is stored privately and is
open to staff with ``crm.document.view`` and to the signer.

No third-party e-signature provider is used (DocuSign/Dropbox Sign stay an option).
"""

from __future__ import annotations

import hashlib
import io
import uuid
from typing import Any

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.template.loader import render_to_string
from django.utils import translation
from django.utils.translation import gettext as _

from tutortrack.core import audit
from tutortrack.core.context import get_request_context, require_organisation_id
from tutortrack.core.events import publish
from tutortrack.core.exceptions import BusinessRuleViolation
from tutortrack.core.models import StoredFile
from tutortrack.core.permissions import has_perm
from tutortrack.core.storage.client import bucket, s3_client
from tutortrack.core.storage.services import register_access_rule, safe_filename
from tutortrack.core.time import now

from . import events
from .models import Document, Note, Signature


def statement(title: str, name: str) -> str:
    return _(
        "I, %(name)s, have read “%(title)s” and agree to it. I understand that signing "
        "electronically has the same effect as signing on paper."
    ) % {"name": name, "title": title}


def _read(stored: StoredFile) -> bytes:
    body: Any = s3_client().get_object(Bucket=bucket(), Key=stored.storage_key)["Body"]
    data: bytes = body.read()
    return data


def _store(owner: Signature, filename: str, data: bytes, user: Any) -> StoredFile:
    """Keep the signed copy (server-generated: no upload or malware scan needed)."""
    org_id = require_organisation_id()
    key = f"org/{org_id}/{now():%Y/%m}/signatures/{uuid.uuid4().hex}/{safe_filename(filename)}"
    s3_client().put_object(Bucket=bucket(), Key=key, Body=data, ContentType="application/pdf")
    return StoredFile.objects.create(
        filename=filename[:255],
        content_type="application/pdf",
        size_bytes=len(data),
        checksum_sha256=hashlib.sha256(data).hexdigest(),
        storage_key=key,
        status=StoredFile.Status.UPLOADED,
        scan_status=StoredFile.ScanStatus.CLEAN,
        visibility=StoredFile.Visibility.PRIVATE,
        uploaded_by=user if getattr(user, "pk", None) else None,
        owner_content_type=ContentType.objects.get_for_model(Signature),
        owner_object_id=str(owner.pk),
    )


def render_pdf(
    signature: Signature, *, text: str = "", original: tuple[str, bytes] | None = None
) -> bytes:
    """The signed copy: the agreement text (if any) and a signature page; an original file
    is embedded as a PDF attachment, so the copy holds exactly what was signed."""
    from weasyprint import HTML, Attachment

    from tutortrack.tenancy.models import Organisation

    org = Organisation.objects.get(pk=require_organisation_id())
    with translation.override(org.locale or "en-GB"):
        html = render_to_string(
            "crm/signature.html",
            {
                "signature": signature,
                "org": org,
                "text": text,
                "original_name": original[0] if original else "",
            },
        )
    attachments = []
    if original is not None:
        attachments.append(
            Attachment(
                file_obj=io.BytesIO(original[1]),
                name=original[0],
                description=_("The signed document"),
            )
        )
    return bytes(HTML(string=html).write_pdf(attachments=attachments))


def _new_signature(
    *, title: str, signer: Any, name: str, role: str, digest: str, **fields: Any
) -> Signature:
    name = " ".join(str(name or "").split())[:200]
    if len(name) < 2:
        raise BusinessRuleViolation(
            _("Type your full name to sign."), extra={"errors": {"full_name": [_("Required.")]}}
        )
    ctx = get_request_context()
    return Signature.objects.create(
        title=title[:200],
        statement=statement(title, name),
        signer=signer if getattr(signer, "pk", None) else None,
        signer_name=name,
        signer_email=str(getattr(signer, "email", "") or "")[:254],
        signer_role=role,
        signed_at=now(),
        ip=ctx.ip,
        user_agent=(ctx.user_agent or "")[:500],
        content_sha256=digest,
        **fields,
    )


def request_signature(document: Document, *, required: bool = True) -> Document:
    """Staff ask for (or stop asking for) a signature. A document to sign is shown to the
    family, so it becomes "shared with the client"."""
    if document.signed_at is not None:
        raise BusinessRuleViolation(_("This document is already signed."))
    with audit.track(document, action="request_signature" if required else "cancel_signature"):
        document.signature_required = required
        if required and document.target_type != "people.tutor":
            document.visibility = Note.Visibility.CLIENT
        document.save(update_fields=["signature_required", "visibility", "updated_at"])
    return document


@transaction.atomic
def sign_document(document: Document, *, signer: Any, full_name: str, role: str) -> Signature:
    """Click-to-sign a document (the caller has checked the signer may see it)."""
    document = Document.objects.select_for_update().select_related("file").get(pk=document.pk)
    if not document.signature_required:
        raise BusinessRuleViolation(_("This document doesn't need a signature."))
    if document.signed_at is not None:
        raise BusinessRuleViolation(_("This document has already been signed."))
    original = _read(document.file)
    signature = _new_signature(
        title=document.title,
        signer=signer,
        name=full_name,
        role=role,
        digest=hashlib.sha256(original).hexdigest(),
        kind=Signature.Kind.DOCUMENT,
        document=document,
    )
    pdf = render_pdf(signature, original=(document.file.filename, original))
    signature.signed_file = _store(signature, f"{document.title} (signed).pdf", pdf, signer)
    signature.save(update_fields=["signed_file", "updated_at"])
    with audit.track(document, action="sign"):
        document.signed_at = signature.signed_at
        document.save(update_fields=["signed_at", "updated_at"])
    audit.record_create(signature)
    publish(
        events.DocumentSigned(
            subject_id=document.pk,
            signature_id=str(signature.pk),
            target_type=document.target_type,
            target_id=document.target_id,
        )
    )
    return signature


@transaction.atomic
def sign_agreement(
    *, tutor: Any, key: str, title: str, text: str, signer: Any, full_name: str
) -> Signature:
    """A tutor signs an onboarding agreement (FR-18-5): the text they were shown is hashed
    and printed on the signed copy."""
    body = text.strip() or title
    signature = _new_signature(
        title=title,
        signer=signer,
        name=full_name,
        role="tutor",
        digest=hashlib.sha256(body.encode()).hexdigest(),
        kind=Signature.Kind.AGREEMENT,
        tutor=tutor,
        agreement_key=key[:80],
    )
    pdf = render_pdf(signature, text=body)
    signature.signed_file = _store(signature, f"{title} (signed).pdf", pdf, signer)
    signature.save(update_fields=["signed_file", "updated_at"])
    audit.record_create(signature)
    publish(events.AgreementSigned(subject_id=signature.pk, tutor_id=str(tutor.pk), key=key))
    return signature


def _may_open(user: Any, stored: StoredFile) -> bool:
    signature = Signature.objects.filter(pk=stored.owner_object_id).first()
    if signature is None:
        return False
    return signature.signer_id == user.pk or has_perm(user, "crm.document.view")


register_access_rule("crm.signature", _may_open)
