"""Gap batch G2: household switcher (FR-15-1), inviting another guardian (FR-15-8),
guardian-managed logins for under-13 students (FR-15-1, E29 COPPA consent) and documents
to sign in the portal (FR-15-8, FR-05-9)."""

from __future__ import annotations

import hashlib
import re
from datetime import date

import pytest
from django.core import mail
from rest_framework.test import APIClient

from tutortrack.comms.models import Message
from tutortrack.core.context import tenant_context
from tutortrack.core.models import AuditEntry, StoredFile
from tutortrack.core.testing import TenantIsolationTestMixin, client_for
from tutortrack.core.time import now
from tutortrack.crm import signing
from tutortrack.crm.models import Document, Signature
from tutortrack.identity.models import Invitation, LoginEvent, Membership
from tutortrack.identity.tests.factories import MembershipFactory
from tutortrack.people import services as people
from tutortrack.people.models import Contact, Student
from tutortrack.people.tests.factories import ClientFactory, ContactFactory, StudentFactory
from tutortrack.portal.models import StudentLogin
from tutortrack.privacy import children
from tutortrack.tenancy import settings_service

pytestmark = pytest.mark.django_db


def household(org, name="The Patels", *, user=None, relationship="parent", kids=("Maya",)):
    client = ClientFactory(organisation=org, display_name=name)
    if user is None:
        user = MembershipFactory(organisation=org, role="client").user
    contact = ContactFactory(
        organisation=org,
        client=client,
        first_name="Priya",
        email=user.email,
        relationship=relationship,
    )
    with tenant_context(org):
        people.link_portal_user("people.contact", str(contact.pk), user)
    students = [
        StudentFactory(
            organisation=org, client=client, first_name=n, date_of_birth=date(now().year - 9, 5, 1)
        )
        for n in kids
    ]
    return {
        "client": client,
        "contact": contact,
        "user": user,
        "students": students,
        "api": client_for(org, user),
    }


# --- household switcher (FR-15-1) -----------------------------------------------------------------


def test_switching_between_households(org):
    patels = household(org, "The Patels", kids=("Maya",))
    second = household(org, "Grandma's", user=patels["user"], kids=("Leo",))
    api = patels["api"]
    me = api.get("/api/v1/portal/me").json()
    assert {h["name"] for h in me["households"]} == {"The Patels", "Grandma's"}
    assert me["household"] == ""
    assert {s["name"].split()[0] for s in me["students"]} == {"Maya", "Leo"}

    picked = api.post(
        "/api/v1/portal/household", {"client_id": str(second["client"].pk)}, format="json"
    )
    assert picked.status_code == 200
    me = api.get("/api/v1/portal/me").json()
    assert me["household"] == str(second["client"].pk)
    assert [c["name"] for c in me["clients"]] == ["Grandma's"]
    assert [s["name"].split()[0] for s in me["students"]] == ["Leo"]
    assert len(me["households"]) == 2  # the switcher still lists both

    api.post("/api/v1/portal/household", {"client_id": ""}, format="json")
    assert len(api.get("/api/v1/portal/me").json()["clients"]) == 2


def test_cannot_switch_to_someone_elses_household(org):
    patels, smiths = household(org, "The Patels"), household(org, "The Smiths")
    response = patels["api"].post(
        "/api/v1/portal/household", {"client_id": str(smiths["client"].pk)}, format="json"
    )
    assert response.status_code == 404


# --- invite another guardian (FR-15-8) ------------------------------------------------------------


def invite(api, **overrides):
    body = {
        "first_name": "Raj",
        "last_name": "Patel",
        "email": "Raj@Example.com",
        "relationship": "parent",
        "confirm": True,
        **overrides,
    }
    return api.post("/api/v1/portal/guardians", body, format="json")


def test_parent_invites_another_guardian_through_comms(org, django_capture_on_commit_callbacks):
    patels = household(org)
    with django_capture_on_commit_callbacks(execute=True):
        response = invite(patels["api"])
    assert response.status_code == 201, response.json()
    assert response.json()["portal"] == "invited"
    with tenant_context(org):
        contact = Contact.objects.get(email="raj@example.com")
        assert contact.client_id == patels["client"].pk
        assert not contact.receives_marketing
        invitation = Invitation.objects.get(email="raj@example.com")
        assert (invitation.role, invitation.target_id) == ("client", str(contact.pk))
        message = Message.objects.get(type_key="guardian_invite")
        assert "accept-invite?token=" in message.body
        assert AuditEntry.objects.filter(action="guardian_invited", object_id=str(contact.pk))
    names = {g["name"] for g in patels["api"].get("/api/v1/portal/guardians").json()}
    assert "Raj Patel" in names

    # Accepting the emailed link links the new login to the new contact.
    token = re.search(r"token=([\w-]+)", message.body).group(1)
    accepted = APIClient(HTTP_HOST=f"{org.slug}.tutortrack.test").post(
        "/api/v1/invitations/accept",
        {"token": token, "password": "violet-harbour-lantern-42", "first_name": "Raj"},
        format="json",
    )
    assert accepted.status_code in (200, 201), accepted.json()


def test_guardian_invite_rules(org):
    patels = household(org)
    assert invite(patels["api"], confirm=False).status_code == 422  # must confirm
    other = household(org, "The Lees", relationship="other")  # no parental responsibility
    assert invite(other["api"]).status_code == 403
    assert invite(patels["api"], email=patels["user"].email).status_code == 422  # already in
    with tenant_context(org):
        settings_service.update_settings("portal", {"portal.allow_guardian_invites": False})
    assert invite(patels["api"]).status_code == 403
    with tenant_context(org):
        assert not Invitation.objects.filter(email="raj@example.com").exists()


# --- guardian-managed logins (FR-15-1, COPPA) ----------------------------------------------------


def create_login(api, student, **overrides):
    body = {
        "student_id": str(student.pk),
        "username": "maya.p",
        "pin": "482916",
        "parental_consent": True,
        **overrides,
    }
    return api.post("/api/v1/portal/student-logins", body, format="json")


def sign_in(org, username="maya.p", pin="482916"):
    client = APIClient(HTTP_HOST=f"{org.slug}.tutortrack.test")
    response = client.post(
        "/api/v1/auth/student-login", {"username": username, "pin": pin}, format="json"
    )
    return client, response


def test_guardian_sets_up_a_login_and_the_child_signs_in(org):
    patels = household(org)
    maya = patels["students"][0]
    with tenant_context(org):
        settings_service.update_settings("privacy", {"privacy.coppa": "on"})
        assert children.needs_parental_consent(maya)
    rows = patels["api"].get("/api/v1/portal/student-logins").json()
    assert rows[0]["eligible"]
    assert rows[0]["username"] == ""

    assert create_login(patels["api"], maya, parental_consent=False).status_code == 422
    created = create_login(patels["api"], maya)
    assert created.status_code == 201, created.json()
    assert created.json()["username"] == "maya.p"
    with tenant_context(org):
        assert children.has_parental_consent(maya)  # the E29 record, given in the portal
        login = StudentLogin.objects.get(student=maya)
        assert login.user.email.endswith("@managed-students.invalid")
        assert Student.objects.get(pk=maya.pk).user_id == login.user_id
        assert Membership.objects.get(user=login.user).role == "student"

    child, response = sign_in(org)
    assert response.status_code == 200, response.json()
    me = child.get("/api/v1/portal/me").json()
    assert me["role"] == "student"
    assert [s["id"] for s in me["students"]] == [str(maya.pk)]

    # A new PIN signs the child out everywhere; the old PIN stops working.
    assert (
        patels["api"]
        .post(f"/api/v1/portal/student-logins/{maya.pk}/pin", {"pin": "739104"}, format="json")
        .status_code
        == 200
    )
    assert child.get("/api/v1/portal/me").status_code == 403
    assert sign_in(org)[1].status_code in (400, 401)
    assert sign_in(org, pin="739104")[1].status_code == 200

    # Removing the login switches it off.
    assert patels["api"].delete(f"/api/v1/portal/student-logins/{maya.pk}").status_code == 204
    assert sign_in(org, pin="739104")[1].status_code in (400, 401)
    with tenant_context(org):
        assert not StudentLogin.objects.exists()
        assert Student.objects.get(pk=maya.pk).user_id is None


def test_student_login_rules(org):
    patels = household(org, kids=("Maya", "Arjun"))
    maya, arjun = patels["students"]
    with tenant_context(org):
        Student.objects.filter(pk=arjun.pk).update(date_of_birth=date(now().year - 15, 1, 1))
    assert create_login(patels["api"], arjun, username="arjun.p").status_code == 422  # 13+
    assert create_login(patels["api"], maya, pin="123456").status_code == 422  # guessable
    assert create_login(patels["api"], maya, pin="111111").status_code == 422
    assert create_login(patels["api"], maya, username="No Spaces").status_code == 422
    smiths = household(org, "The Smiths", kids=("Zoe",))
    assert create_login(smiths["api"], maya).status_code == 404  # not their child
    assert create_login(patels["api"], maya).status_code == 201
    assert create_login(smiths["api"], smiths["students"][0]).status_code == 422  # taken name


def test_wrong_pins_lock_the_login(org):
    patels = household(org)
    create_login(patels["api"], patels["students"][0])
    for _ in range(5):
        assert sign_in(org, pin="000001")[1].status_code in (400, 401)
    assert sign_in(org)[1].status_code == 429
    assert LoginEvent.objects.filter(method="student_pin", success=False).count() == 5


# --- documents to sign (FR-15-8, FR-05-9) ---------------------------------------------------------


def document_for(org, s3, target_type, target_id, *, sign=True, data=b"%PDF-1.4 terms"):
    with tenant_context(org):
        key = f"org/{org.pk}/terms-{now().timestamp()}.pdf"
        s3.put_object(Bucket=_bucket(), Key=key, Body=data)
        stored = StoredFile.objects.create(
            filename="terms.pdf",
            content_type="application/pdf",
            size_bytes=len(data),
            storage_key=key,
            status=StoredFile.Status.UPLOADED,
            scan_status=StoredFile.ScanStatus.CLEAN,
        )
        document = Document.objects.create(
            target_type=target_type, target_id=str(target_id), file=stored, title="Terms 2026"
        )
        return signing.request_signature(document) if sign else document


def _bucket():
    from tutortrack.core.storage.client import bucket

    return bucket()


def test_family_signs_a_document_with_an_audit_trail(org, s3):
    patels = household(org)
    document = document_for(org, s3, "people.client", patels["client"].pk)
    listed = patels["api"].get("/api/v1/portal/documents").json()
    assert [(d["title"], d["signature_status"]) for d in listed] == [("Terms 2026", "awaiting")]
    assert patels["api"].get(f"/api/v1/portal/documents/{document.pk}/download").status_code == 200

    response = patels["api"].post(
        f"/api/v1/portal/documents/{document.pk}/sign",
        {"full_name": "Priya Patel", "agree": True},
        format="json",
        HTTP_USER_AGENT="Test browser",
    )
    assert response.status_code == 201, response.json()
    assert response.json()["content_sha256"] == hashlib.sha256(b"%PDF-1.4 terms").hexdigest()
    with tenant_context(org):
        signature = Signature.objects.get()
        assert (signature.signer_id, signature.signer_name, signature.signer_role) == (
            patels["user"].pk,
            "Priya Patel",
            "client",
        )
        assert signature.user_agent == "Test browser"
        assert "Priya Patel" in signature.statement
        assert Document.objects.get(pk=document.pk).signed_at is not None
        pdf = s3.get_object(Bucket=_bucket(), Key=signature.signed_file.storage_key)["Body"].read()
        assert pdf.startswith(b"%PDF")
        assert b"EmbeddedFile" in pdf
    # Signed once; staff see the trail.
    again = patels["api"].post(
        f"/api/v1/portal/documents/{document.pk}/sign",
        {"full_name": "Priya Patel", "agree": True},
        format="json",
    )
    assert again.status_code == 422
    staff = client_for(org, MembershipFactory(organisation=org, role="admin").user)
    trail = staff.get(f"/api/v1/documents/{document.pk}/signatures").json()
    assert trail[0]["signer_name"] == "Priya Patel"
    copy = staff.get(f"/api/v1/files/{trail[0]['signed_file']}/download")
    assert copy.status_code == 200


def test_other_households_cannot_see_or_sign(org, s3):
    patels, smiths = household(org), household(org, "The Smiths")
    document = document_for(org, s3, "people.client", patels["client"].pk)
    assert smiths["api"].get("/api/v1/portal/documents").json() == []
    sign = smiths["api"].post(
        f"/api/v1/portal/documents/{document.pk}/sign",
        {"full_name": "Sam Smith", "agree": True},
        format="json",
    )
    assert sign.status_code == 404
    unticked = patels["api"].post(
        f"/api/v1/portal/documents/{document.pk}/sign",
        {"full_name": "Priya Patel", "agree": False},
        format="json",
    )
    assert unticked.status_code == 400


def test_staff_request_a_signature(org, admin_api, s3):
    patels = household(org)
    document = document_for(org, s3, "people.client", patels["client"].pk, sign=False)
    assert patels["api"].get("/api/v1/portal/documents").json() == []  # staff only
    response = admin_api.post(
        f"/api/v1/documents/{document.pk}/request-signature",
        {"signature_required": True},
        format="json",
    )
    assert response.status_code == 200, response.json()
    assert response.json()["signature_status"] == "awaiting"
    assert len(patels["api"].get("/api/v1/portal/documents").json()) == 1


class TestPortalDocumentIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/documents"

    def make_object(self, organisation):
        with tenant_context(organisation):
            client = ClientFactory(organisation=organisation)
            stored = StoredFile.objects.create(
                filename="x.pdf",
                content_type="application/pdf",
                size_bytes=1,
                storage_key=f"org/{organisation.pk}/{now().timestamp()}.pdf",
                status=StoredFile.Status.UPLOADED,
            )
            self._target = str(client.pk)
            return Document.objects.create(
                target_type="people.client", target_id=str(client.pk), file=stored, title="x"
            )

    def detail_url(self, obj):
        return f"/api/v1/documents/{obj.pk}/signatures"

    def test_list_only_returns_own_organisation(self, org, other_org):
        mine = self.make_object(org)
        theirs = self.make_object(other_org)
        response = client_for(org, self.acting_user(org)).get(
            self.list_url, {"target_type": "people.client", "target_id": mine.target_id}
        )
        ids = {row["id"] for row in response.json()["results"]}
        assert str(mine.pk) in ids
        assert str(theirs.pk) not in ids


def test_invitation_email_does_not_use_platform_mail(org, django_capture_on_commit_callbacks):
    patels = household(org)
    with django_capture_on_commit_callbacks(execute=True):
        invite(patels["api"])
    # The guardian invite goes through comms (templated, logged), not the platform email.
    assert not any("You're invited to join" in m.subject for m in mail.outbox)
