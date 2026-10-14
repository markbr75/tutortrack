"""Gap batch G2 (FR-18-5, FR-05-9): tutors e-sign their onboarding agreement and documents
on their record: click-to-sign with an audit trail and a signed PDF copy."""

from __future__ import annotations

import hashlib

import pytest

from tutortrack.core.context import tenant_context
from tutortrack.core.models import StoredFile
from tutortrack.core.storage.client import bucket
from tutortrack.core.testing import client_for
from tutortrack.core.time import now
from tutortrack.crm import signing
from tutortrack.crm.models import Document, Signature
from tutortrack.identity.tests.factories import MembershipFactory
from tutortrack.people.tests.factories import TutorProfileFactory
from tutortrack.recruitment import services

pytestmark = pytest.mark.django_db


@pytest.fixture
def tutor(org):
    membership = MembershipFactory(organisation=org, role="tutor")
    profile = TutorProfileFactory(
        organisation=org, membership=membership, first_name="Nia", status="onboarding"
    )
    with tenant_context(org):
        services.start_onboarding(profile)
    return {"profile": profile, "api": client_for(org, membership.user), "user": membership.user}


def test_tutor_signs_the_agreement(org, tutor, s3):
    api = tutor["api"]
    state = api.get("/api/v1/me/onboarding").json()
    agreement = next(i for i in state["items"] if i["key"] == "agreement")
    assert agreement["needs_signature"]
    assert not agreement["done"]
    policy = next(i for i in state["items"] if i["key"] == "safeguarding_policy")
    assert not policy["needs_signature"]  # an acknowledgement is still a tick

    assert (
        api.post(
            "/api/v1/me/onboarding/agreement/sign",
            {"full_name": "Nia Adeyemi", "agree": False},
            format="json",
        ).status_code
        == 400
    )
    assert api.post(
        "/api/v1/me/onboarding/agreement/sign", {"full_name": " ", "agree": True}, format="json"
    ).status_code in (400, 422)
    response = api.post(
        "/api/v1/me/onboarding/agreement/sign",
        {"full_name": "Nia Adeyemi", "agree": True},
        format="json",
        HTTP_USER_AGENT="Tutor phone",
    )
    assert response.status_code == 200, response.json()
    item = next(i for i in response.json()["items"] if i["key"] == "agreement")
    assert item["done"]
    assert item["signature_id"]
    with tenant_context(org):
        signature = Signature.objects.get(pk=item["signature_id"])
        assert signature.kind == "agreement"
        assert signature.tutor_id == tutor["profile"].pk
        assert signature.signer_id == tutor["user"].pk
        assert signature.user_agent == "Tutor phone"
        assert signature.content_sha256 == hashlib.sha256(b"Sign the tutor agreement").hexdigest()
        pdf = s3.get_object(Bucket=bucket(), Key=signature.signed_file.storage_key)["Body"].read()
        assert pdf.startswith(b"%PDF")
    # Once only; the copy downloads for the tutor.
    again = api.post(
        "/api/v1/me/onboarding/agreement/sign",
        {"full_name": "Nia Adeyemi", "agree": True},
        format="json",
    )
    assert again.status_code == 422
    assert api.get(f"/api/v1/files/{signature.signed_file_id}/download").status_code == 200


def test_tutor_signs_a_document_on_their_record(org, tutor, s3):
    with tenant_context(org):
        key = f"org/{org.pk}/contract-{now().timestamp()}.pdf"
        s3.put_object(Bucket=bucket(), Key=key, Body=b"%PDF contract")
        stored = StoredFile.objects.create(
            filename="contract.pdf",
            content_type="application/pdf",
            size_bytes=13,
            storage_key=key,
            status=StoredFile.Status.UPLOADED,
            scan_status=StoredFile.ScanStatus.CLEAN,
        )
        document = Document.objects.create(
            target_type="people.tutor",
            target_id=str(tutor["profile"].pk),
            file=stored,
            title="Contractor agreement",
            visibility="staff_and_tutors",
        )
        signing.request_signature(document)
        other = TutorProfileFactory(organisation=org)
        hidden = Document.objects.create(
            target_type="people.tutor",
            target_id=str(other.pk),
            file=stored,
            title="Other's",
            signature_required=True,
        )
    api = tutor["api"]
    rows = api.get("/api/v1/tutor/documents").json()
    assert [r["title"] for r in rows] == ["Contractor agreement"]
    assert api.get(f"/api/v1/tutor/documents/{document.pk}/download").status_code == 200
    assert (
        api.post(
            f"/api/v1/tutor/documents/{hidden.pk}/sign",
            {"full_name": "Nia", "agree": True},
            format="json",
        ).status_code
        == 404
    )
    signed = api.post(
        f"/api/v1/tutor/documents/{document.pk}/sign",
        {"full_name": "Nia Adeyemi", "agree": True},
        format="json",
    )
    assert signed.status_code == 201, signed.json()
    assert api.get("/api/v1/tutor/documents").json()[0]["signature_status"] == "signed"
