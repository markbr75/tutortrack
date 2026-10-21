"""G5a: anonymous uploads on public forms (``core.storage.public``): contexts, type and size
limits, signature checks, single-use tokens and the retention purge."""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

import pytest
from django.conf import settings
from django.test import Client as HttpClient

from tutortrack.core.context import tenant_context
from tutortrack.core.exceptions import BusinessRuleViolation
from tutortrack.core.models import StoredFile
from tutortrack.core.storage import public
from tutortrack.core.time import now
from tutortrack.leads.models import Enquiry, Form

pytestmark = pytest.mark.django_db

PDF = b"%PDF-1.7 curriculum vitae"
SCHEMA = {
    "steps": [
        {
            "title": "You",
            "fields": [
                {"key": "email", "label": "Email", "type": "email", "maps_to": "contact.email"},
                {"key": "report", "label": "School report", "type": "file", "multiple": True},
            ],
        }
    ]
}


def anonymous(org: Any) -> HttpClient:
    return HttpClient(HTTP_HOST=f"{org.slug}.{settings.TENANT_BASE_DOMAIN}")


@pytest.fixture
def form(org: Any) -> Form:
    with tenant_context(org):
        return Form.objects.create(name="Enquire", slug="enquire", schema=SCHEMA, published=True)


def start(org: Any, **overrides: Any) -> Any:
    body = {
        "target": "form",
        "slug": "enquire",
        "kind": "document",
        "filename": "report.pdf",
        "content_type": "application/pdf",
        "size_bytes": len(PDF),
        **overrides,
    }
    return anonymous(org).post(
        "/api/v1/public/uploads", data=json.dumps(body), content_type="application/json"
    )


def put(org: Any, s3: Any, token: str, data: bytes = PDF, content_type: str = "application/pdf"):
    with tenant_context(org):
        stored = StoredFile.objects.get(pk=public.read_token(token).file_id)
    s3.put_object(
        Bucket=settings.AWS_STORAGE_BUCKET_NAME,
        Key=stored.storage_key,
        Body=data,
        ContentType=content_type,
    )
    return stored


def complete(org: Any, token: str) -> Any:
    return anonymous(org).post(
        "/api/v1/public/uploads/complete",
        data=json.dumps({"token": token}),
        content_type="application/json",
    )


def test_upload_flow_returns_a_token_and_checks_the_file(org, form, s3):
    created = start(org)
    assert created.status_code == 201, created.json()
    body = created.json()
    assert body["upload"]["method"] == "PUT"
    assert body["max_bytes"] == settings.PUBLIC_UPLOADS["DOCUMENT_MAX_BYTES"]
    stored = put(org, s3, body["token"])
    assert stored.storage_key.startswith(f"org/{org.pk}/public/")
    assert stored.uploaded_by_id is None
    assert stored.visibility == "private"
    done = complete(org, body["token"])
    assert done.status_code == 200, done.json()
    assert done.json()["filename"] == "report.pdf"
    with tenant_context(org):
        stored.refresh_from_db()
    assert stored.status == StoredFile.Status.UPLOADED
    assert complete(org, body["token"]).status_code == 200  # a retry is harmless


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"slug": "nope"}, "uploads_not_accepted"),
        ({"kind": "video", "content_type": "video/mp4"}, "uploads_not_accepted"),
        ({"content_type": "application/x-msdownload"}, "file_type_not_allowed"),
        ({"size_bytes": 50 * 1024 * 1024}, "file_too_large"),
    ],
)
def test_limits_and_contexts(org, form, s3, overrides, code):
    response = start(org, **overrides)
    assert response.status_code == 422, response.json()
    assert response.json()["code"] == code


def test_a_form_without_file_fields_takes_no_uploads(org, s3):
    with tenant_context(org):
        Form.objects.create(
            name="Plain",
            slug="enquire",
            schema={"steps": [{"title": "x", "fields": [SCHEMA["steps"][0]["fields"][0]]}]},
            published=True,
        )
    assert start(org).json()["code"] == "uploads_not_accepted"


def test_a_renamed_executable_is_rejected_and_deleted(org, form, s3):
    token = start(org).json()["token"]
    stored = put(org, s3, token, data=b"MZ\x90\x00 not a pdf")
    response = complete(org, token)
    assert response.status_code == 422
    assert response.json()["code"] == "upload_mismatch"
    with tenant_context(org):
        stored.refresh_from_db()
    assert stored.status == StoredFile.Status.REJECTED
    assert s3.list_objects_v2(Bucket=settings.AWS_STORAGE_BUCKET_NAME).get("KeyCount", 0) == 0


@pytest.mark.parametrize(
    ("content_type", "head", "ok"),
    [
        ("application/pdf", b"%PDF-1.4", True),
        ("application/pdf", b"<html>", False),
        ("image/png", b"\x89PNG\r\n\x1a\n....", True),
        ("image/jpeg", b"\xff\xd8\xff\xe0", True),
        ("video/mp4", b"\x00\x00\x00\x18ftypmp42", True),
        ("video/mp4", b"\x00\x00\x00\x18moovxxxx", False),
        ("video/webm", b"\x1a\x45\xdf\xa3", True),
        (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            b"PK\x03\x04",
            True,
        ),
        ("text/html", b"<html>", False),
    ],
)
def test_signatures(content_type, head, ok):
    assert public.matches_signature(content_type, head) is ok


def test_tokens_are_single_use_and_tied_to_their_form(org, other_org, form, s3):
    token = start(org).json()["token"]
    put(org, s3, token)
    complete(org, token)
    with tenant_context(org):
        enquiry_owner = Form.objects.get(slug="enquire")
        with pytest.raises(BusinessRuleViolation, match="belong"):
            public.claim([token], owner=enquiry_owner, kinds=["document"], context="form:other")
        with pytest.raises(BusinessRuleViolation, match="belong"):
            public.claim([token], owner=enquiry_owner, kinds=["cv"], context="form:enquire")
        [claimed] = public.claim(
            [token], owner=enquiry_owner, kinds=["document"], context="form:enquire"
        )
        assert claimed.owner_object_id == str(enquiry_owner.pk)
        with pytest.raises(BusinessRuleViolation, match="already"):
            public.claim([token], owner=enquiry_owner, kinds=["document"], context="form:enquire")
    with tenant_context(other_org), pytest.raises(BusinessRuleViolation, match="expired"):
        public.read_token(token)
    with tenant_context(org), pytest.raises(BusinessRuleViolation, match="expired"):
        public.read_token(token[:-2] + "xx")


def test_unfinished_uploads_cannot_be_claimed(org, form, s3):
    token = start(org).json()["token"]
    with tenant_context(org), pytest.raises(BusinessRuleViolation, match="finished"):
        public.claim([token], owner=Form.objects.get(), kinds=["document"], context="form:enquire")


def test_unclaimed_uploads_are_purged_by_retention(org, form, s3):
    old = start(org).json()["token"]
    kept = start(org).json()["token"]
    with tenant_context(org):
        old_file = StoredFile.objects.get(pk=public.read_token(old).file_id)
        StoredFile.objects.filter(pk=old_file.pk).update(created_at=now() - timedelta(days=5))
        claimed = StoredFile.objects.get(pk=public.read_token(kept).file_id)
        StoredFile.objects.filter(pk=claimed.pk).update(created_at=now() - timedelta(days=5))
        from tutortrack.core.storage.services import attach

        attach(claimed, Form.objects.get())
        cutoff = now() - timedelta(days=2)
        assert public.purge_unclaimed(cutoff, True, 100) == 1
        assert public.purge_unclaimed(cutoff, False, 100) == 1
        assert not StoredFile.objects.filter(pk=old_file.pk).exists()
        assert StoredFile.objects.filter(pk=claimed.pk).exists()
        from tutortrack.privacy.registry import retention_category

        assert retention_category("unclaimed_public_uploads") is not None
        assert not Enquiry.objects.exists()
