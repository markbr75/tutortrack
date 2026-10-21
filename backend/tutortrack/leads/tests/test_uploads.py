"""G5a (FR-17-1): file uploads on the public enquiry form become enquiry attachments that
staff can open; schema rules for file fields; DSAR and erasure cover them."""

from __future__ import annotations

import json
from typing import Any

import pytest
from django.conf import settings
from django.test import Client as HttpClient

from tutortrack.core.context import tenant_context
from tutortrack.core.exceptions import BusinessRuleViolation
from tutortrack.core.models import StoredFile
from tutortrack.core.storage import public
from tutortrack.core.storage.services import can_access
from tutortrack.core.testing import client_for
from tutortrack.identity.tests.factories import MembershipFactory
from tutortrack.leads import forms
from tutortrack.leads.models import Enquiry, Form, FormSubmission

pytestmark = pytest.mark.django_db

PDF = b"%PDF-1.4 school report"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20
SCHEMA = {
    "steps": [
        {
            "title": "You",
            "fields": [
                {
                    "key": "first",
                    "label": "First name",
                    "type": "text",
                    "maps_to": "contact.first_name",
                    "required": True,
                },
                {"key": "email", "label": "Email", "type": "email", "maps_to": "contact.email"},
                {
                    "key": "reports",
                    "label": "Recent school reports",
                    "type": "file",
                    "file_kind": "document",
                    "multiple": True,
                },
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


def upload(org: Any, s3: Any, data: bytes, content_type: str, name: str) -> str:
    client = anonymous(org)
    created = client.post(
        "/api/v1/public/uploads",
        data=json.dumps(
            {
                "target": "form",
                "slug": "enquire",
                "kind": "document",
                "filename": name,
                "content_type": content_type,
                "size_bytes": len(data),
            }
        ),
        content_type="application/json",
    )
    assert created.status_code == 201, created.json()
    token = created.json()["token"]
    with tenant_context(org):
        stored = StoredFile.objects.get(pk=public.read_token(token).file_id)
    s3.put_object(
        Bucket=settings.AWS_STORAGE_BUCKET_NAME,
        Key=stored.storage_key,
        Body=data,
        ContentType=content_type,
    )
    done = client.post(
        "/api/v1/public/uploads/complete",
        data=json.dumps({"token": token}),
        content_type="application/json",
    )
    assert done.status_code == 200, done.json()
    return token


def submit(org: Any, data: dict[str, Any]) -> Any:
    return anonymous(org).post(
        "/api/v1/public/forms/enquire",
        data=json.dumps({"data": data}),
        content_type="application/json",
    )


def test_enquiry_form_uploads_become_attachments(org, form, s3):
    tokens = [
        upload(org, s3, PDF, "application/pdf", "report.pdf"),
        upload(org, s3, PNG, "image/png", "certificate.png"),
    ]
    response = submit(org, {"first": "Ama", "email": "ama@example.com", "reports": tokens})
    assert response.status_code == 201, response.json()
    with tenant_context(org):
        enquiry = Enquiry.objects.get()
        files = sorted(enquiry.attachments.all(), key=lambda f: f.filename)
        assert [f.filename for f in files] == ["certificate.png", "report.pdf"]
        assert all(f.owner_object_id == str(enquiry.pk) for f in files)
        submission = FormSubmission.objects.get()
        # The submission keeps file references, not the upload tokens.
        assert {r["filename"] for r in submission.data["reports"]} == {
            "report.pdf",
            "certificate.png",
        }
        assert "Recent school reports" not in enquiry.notes
        coordinator = MembershipFactory(organisation=org, role="coordinator").user
        tutor = MembershipFactory(organisation=org, role="tutor").user
        assert can_access(coordinator, files[0])
        assert not can_access(tutor, files[0])
    staff = client_for(org, coordinator)
    detail = staff.get(f"/api/v1/enquiries/{enquiry.pk}").json()
    assert {a["filename"] for a in detail["attachments"]} == {"report.pdf", "certificate.png"}
    # A token can't be sent twice.
    again = submit(org, {"first": "Ama", "email": "ama@example.com", "reports": tokens[:1]})
    assert again.status_code == 422
    assert "reports" in again.json()["errors"]


def test_file_answers_are_validated(org, form, s3):
    response = submit(org, {"first": "Ama", "email": "a@example.com", "reports": ["x"] * 6})
    assert response.status_code == 422
    assert "reports" in response.json()["errors"]
    bogus = submit(org, {"first": "Ama", "email": "a@example.com", "reports": ["not-a-token"]})
    assert bogus.status_code == 422
    with tenant_context(org):
        assert not Enquiry.objects.exists()


def test_schema_rules_for_file_fields():
    base = [{"key": "email", "label": "E", "type": "email", "maps_to": "contact.email"}]

    def schema(*fields: dict[str, Any]) -> dict[str, Any]:
        return {"steps": [{"title": "x", "fields": [*base, *fields]}]}

    cleaned = forms.clean_schema(schema({"key": "f", "label": "F", "type": "file"}))
    assert cleaned["steps"][0]["fields"][1]["file_kind"] == "document"
    with pytest.raises(BusinessRuleViolation):
        forms.clean_schema(schema({"key": "f", "label": "F", "type": "file", "file_kind": "exe"}))
    cv = {"key": "cv", "label": "CV", "type": "file", "file_kind": "cv", "maps_to": "applicant.cv"}
    with pytest.raises(BusinessRuleViolation, match="Unknown mapping"):
        forms.clean_schema(schema(cv))  # applicant mappings belong to application forms
    assert forms.clean_schema(schema(cv), form_type="application")
    with pytest.raises(BusinessRuleViolation):
        forms.clean_schema(schema({**cv, "file_kind": "video"}), form_type="application")
    with pytest.raises(BusinessRuleViolation):
        forms.clean_schema(
            schema({"key": "cv", "label": "CV", "type": "text", "maps_to": "applicant.cv"}),
            form_type="application",
        )


def test_dsar_and_erasure_cover_enquiry_uploads(org, form, s3):
    from tutortrack.leads import privacy
    from tutortrack.privacy.registry import ErasureContext, resolve

    token = upload(org, s3, PDF, "application/pdf", "report.pdf")
    assert (
        submit(org, {"first": "Ama", "email": "ama@example.com", "reports": [token]}).status_code
        == 201
    )
    with tenant_context(org):
        enquiry = Enquiry.objects.get()
        person = resolve("people.contact", str(enquiry.contact_id))
        assert [f.filename for f in privacy.files(person)] == ["report.pdf"]
        from tutortrack.core.time import now

        outcome = privacy.erase(person, ErasureContext(labels={}, financial_cutoff=now()))
        assert len(outcome.file_ids) == 1
        assert not enquiry.attachments.exists()
