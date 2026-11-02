"""FR-05-13 merge tool (gap batch G1): preview, merge, providers and the "no dangling
references" guarantee, checked against every FK found through model meta and every known
generic ``*_type``/``*_id`` reference."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from django.apps import apps
from django.db import transaction
from django.db.models import Sum
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from tutortrack.billing import services as billing
from tutortrack.billing.models import ClientLedgerEntry, Invoice
from tutortrack.catalogue.tests.factories import ServiceFactory
from tutortrack.comms.models import CommunicationPreference, Message
from tutortrack.core.context import tenant_context
from tutortrack.core.exceptions import BusinessRuleViolation
from tutortrack.core.models import AuditEntry, OutboxEvent
from tutortrack.core.money import Money
from tutortrack.core.testing import client_for, result_ids
from tutortrack.core.time import now
from tutortrack.crm import services as crm
from tutortrack.crm.models import Note, TaggedItem
from tutortrack.crm.tests.factories import TagFactory
from tutortrack.delivery import services as delivery
from tutortrack.identity.tests.factories import MembershipFactory, UserFactory
from tutortrack.jobs import services as jobs
from tutortrack.payments import services as payments
from tutortrack.people import merging, services
from tutortrack.people.models import Client, Contact, Student
from tutortrack.people.tests.factories import (
    ClientFactory,
    ContactFactory,
    StudentFactory,
    TutorProfileFactory,
)
from tutortrack.privacy import holds
from tutortrack.privacy import services as privacy
from tutortrack.scheduling import services as scheduling

pytestmark = pytest.mark.django_db

# FK references that deliberately stay on the merged record: immutable history.
HISTORY = {"billing.ClientLedgerEntry.client", "growth.CommissionItem.client"}

# Every generic reference to people we know of: (model, type field, id field, values).
SUBJECTS = ("people.client", "people.contact", "people.student")
KNOWN_GENERIC = {
    ("crm.Note", "target_type", "target_id"): {s: (s,) for s in SUBJECTS},
    ("crm.Task", "target_type", "target_id"): {s: (s,) for s in SUBJECTS},
    ("crm.Document", "target_type", "target_id"): {s: (s,) for s in SUBJECTS},
    ("crm.TaggedItem", "target_type", "target_id"): {s: (s,) for s in SUBJECTS},
    ("comms.Message", "recipient_type", "recipient_id"): {
        "people.contact": ("contact",),
        "people.student": ("student",),
    },
    ("comms.Message", "target_type", "target_id"): {s: (s,) for s in SUBJECTS},
    ("comms.Message", "related_type", "related_id"): {s: (s,) for s in SUBJECTS},
    ("comms.CommunicationPreference", "person_type", "person_id"): {
        "people.contact": ("contact",),
        "people.student": ("student",),
    },
    ("comms.DigestPreference", "person_type", "person_id"): {  # G4 digests
        "people.contact": ("contact",),
        "people.student": ("student",),
    },
    ("comms.BroadcastRecipient", "recipient_type", "recipient_id"): {
        "people.contact": ("contact",),
    },
    ("comms.ThreadParticipant", "person_type", "person_id"): {
        "people.contact": ("contact",),
        "people.student": ("student",),
    },
    ("comms.ThreadMessage", "author_type", "author_id"): {
        "people.contact": ("contact",),
        "people.student": ("student",),
    },
    ("privacy.ConsentRecord", "subject_type", "subject_id"): {s: (s,) for s in SUBJECTS},
    ("privacy.DataSubjectRequest", "subject_type", "subject_id"): {s: (s,) for s in SUBJECTS},
    ("identity.Invitation", "target_type", "target_id"): {
        "people.contact": ("people.contact",),
        "people.student": ("people.student",),
    },
    ("automations.AutomationRun", "subject_type", "subject_id"): {
        "people.client": ("client",),
        "people.student": ("student",),
    },
    ("ai.AIAssist", "subject_type", "subject_id"): {s: (s, s.split(".")[1]) for s in SUBJECTS},
    ("migration.ExternalRef", "target_type", "target_id"): {s: (s,) for s in SUBJECTS},
    ("migration.ImportRow", "target_type", "target_id"): {s: (s,) for s in SUBJECTS},
    ("core.WorkflowLink", "subject_type", "subject_id"): {
        s: (s, s.split(".")[1]) for s in SUBJECTS
    },
    ("delivery.CancellationPolicy", "scope_type", "scope_id"): {"people.client": ("client",)},
    ("scheduling.ICalFeedToken", "kind", "subject_id"): {
        "people.client": ("client",),
        "people.student": ("student",),
    },
}
# Generic references that are not moved, and why.
EXEMPT_GENERIC = {
    ("core.AuditEntry", "object_type", "object_id"),  # the audit trail is history
    ("privacy.LegalHold", "subject_type", "subject_id"),  # a hold blocks the merge
    ("privacy.ErasureRecord", "subject_type", "subject_id"),  # erased people only
    ("accounting.ExternalRecordLink", "object_type", "object_id"),  # ledger contacts: a note
    ("billing.ClientLedgerEntry", "ref_type", "ref_id"),  # immutable ledger history
    ("privacy.SafeguardingFlag", "source_type", "source_id"),  # flags messages, not people
    ("pathways.PathwayRun", "subject_type", "subject_id"),  # jobs and runs, never merged
}


def _generic_pairs() -> set[tuple[str, str, str]]:
    """Every ``x_type``/``x_id`` pair of plain fields on any model."""
    out = set()
    for model in apps.get_models():
        names = {f.name for f in model._meta.concrete_fields if not f.is_relation}
        for name in names:
            if name.endswith("_type") and f"{name[:-5]}_id" in names:
                out.add((model._meta.label, name, f"{name[:-5]}_id"))
    return out


def dangling(subject_type: str, record_id: object) -> dict[str, int]:
    """Rows that still point at ``record_id``: an independent check of the engine's."""
    model = apps.get_model(subject_type)
    out = {}
    for m, f in merging.foreign_keys(model):
        label = f"{m._meta.label}.{f.name}"
        if label in HISTORY:
            continue
        qs = m._base_manager.filter(**{f.name: record_id})
        if m is model:
            qs = qs.exclude(pk=record_id)
        if qs.exists():
            out[label] = qs.count()
    for (label, type_field, id_field), types in KNOWN_GENERIC.items():
        values = types.get(subject_type, ())
        if not values:
            continue
        rows = apps.get_model(label)._base_manager.filter(
            **{f"{type_field}__in": values, id_field: str(record_id)}
        )
        if rows.exists():
            out[f"{label}.{type_field}"] = rows.count()
    return out


def test_every_generic_reference_is_known_or_exempt():
    """A new ``*_type``/``*_id`` reference must be handled by a merge provider (or exempted
    here with a reason) before it can leave a dangling id behind."""
    found = {p for p in _generic_pairs() if p[1] not in {"event_type", "workflow_type"}}
    unknown = found - set(KNOWN_GENERIC) - EXEMPT_GENERIC
    assert not unknown, unknown


def test_every_known_generic_reference_has_a_provider():
    declared = {
        (ref.model, ref.type_field, ref.id_field): ref.types
        for p in merging.providers()
        for ref in p.generic
    }
    for key, types in KNOWN_GENERIC.items():
        assert key in declared, key
        for subject_type, values in types.items():
            assert set(values) <= set(declared[key].get(subject_type, ())), key


def test_every_foreign_key_to_people_has_a_provider():
    """Each FK to a mergeable model is re-pointed by the provider of the app that owns it."""
    for subject_type in SUBJECTS:
        owners = {p.key for p in merging.providers(subject_type)}
        for m, f in merging.foreign_keys(apps.get_model(subject_type)):
            if f"{m._meta.label}.{f.name}" in HISTORY:
                continue
            assert m._meta.app_label in owners, (subject_type, m._meta.label, f.name)


# --- fixtures and builders -----------------------------------------------------------------------


def api_as(org, role):
    return client_for(org, MembershipFactory(organisation=org, role=role).user)


@pytest.fixture
def owner(org):
    return api_as(org, "owner")


@pytest.fixture
def world(org):
    return {
        "tutor": TutorProfileFactory(organisation=org, status="active", first_name="Nia"),
        "service": ServiceFactory(organisation=org, name="Maths 1:1", max_students=4),
    }


def family(org, name="The Patels", *, students=("Arjun", "Maya"), email=None):
    client = ClientFactory(organisation=org, display_name=name, payment_terms_days=14)
    contact = ContactFactory(
        organisation=org,
        client=client,
        email=email or f"{name.split()[-1].lower()}@example.com",
        is_primary=True,
        is_bill_payer=True,
    )
    with tenant_context(org):
        client.primary_contact = client.billing_contact = contact
        client.save()
    kids = [
        StudentFactory(organisation=org, client=client, first_name=n, last_name="Patel")
        for n in students
    ]
    return {"client": client, "contact": contact, "students": kids}


LONDON = ZoneInfo("Europe/London")


def at_ten(days: int):
    """10:00 London time ``days`` from today (negative: in the past)."""
    day = now().astimezone(LONDON).date() + timedelta(days=days)
    return datetime.combine(day, time(10), tzinfo=LONDON)


def lesson_for(org, world, student, *, days_ago=1, job=None):
    start = at_ten(-days_ago)
    with tenant_context(org):
        return scheduling.create_lesson(
            start=start,
            end=start + timedelta(hours=1),
            service=world["service"],
            job=job,
            attendees=[{"student": student}],
            tutors=[{"tutor": world["tutor"]}],
            timezone="Europe/London",
            override_conflicts=True,
            notify=False,
        ).lesson


def billed(org, world, fam, *, days_ago=1):
    """A job, a delivered lesson, its charge on an issued invoice and a part payment."""
    with tenant_context(org):
        job = jobs.create_job(
            client=fam["client"],
            service=world["service"],
            students=[{"student": fam["students"][0]}],
            tutors=[{"tutor": world["tutor"]}],
            status="active",
            billing_method="pay_as_you_go",
        )
    the_lesson = lesson_for(org, world, fam["students"][0], days_ago=days_ago, job=job)
    with tenant_context(org):
        delivery.complete_lesson(the_lesson)
        billing.sync_lesson_charges(the_lesson.pk)
        invoice = billing.issue_invoice(billing.create_draft(fam["client"]), send=False)
        payments.record_manual_payment(
            client=fam["client"], amount=Money(Decimal("10.00"), invoice.currency), method="cash"
        )
    return job, the_lesson, invoice


def crm_items(org, fam, tag):
    with tenant_context(org):
        crm.create_note(target_type="people.client", target_id=fam["client"].pk, body="<p>Hi</p>")
        crm.create_note(
            target_type="people.student", target_id=fam["students"][0].pk, body="<p>Maths</p>"
        )
        crm.create_task(title="Call", target_type="people.client", target_id=fam["client"].pk)
        crm.apply_tag(tag, "people.client", [str(fam["client"].pk)])
        Message.objects.create(
            type_key="test",
            channel="email",
            recipient_type="contact",
            recipient_id=str(fam["contact"].pk),
            to=fam["contact"].email,
            body="Hello",
            target_type="people.client",
            target_id=str(fam["client"].pk),
            dedupe_key=f"merge-test:{fam['contact'].pk}",
        )
        CommunicationPreference.objects.create(
            person_type="contact",
            person_id=str(fam["contact"].pk),
            category="marketing",
            channels=["email"],
        )
        privacy.ensure_default_types()
        privacy.record_consent(
            subject_type="people.contact",
            subject_id=str(fam["contact"].pk),
            key="marketing-email",
            granted=True,
            method="form",
        )


def ledger_total(org, client):
    with tenant_context(org):
        total = ClientLedgerEntry.objects.filter(client=client).aggregate(t=Sum("amount_amount"))
    return total["t"] or Decimal(0)


# --- the merge itself -----------------------------------------------------------------------------


def test_client_merge_moves_everything_and_keeps_financial_history(org, world, owner):
    """FR-05-13: one transaction re-points every linked record; invoices and payments keep
    their amounts; ledger entries stay as history with a balancing transfer."""
    tag = TagFactory(organisation=org, name="VIP")
    keep = family(org, "The Patel Family", students=("Arjun",))
    dupe = family(org, "Patel family", students=("Arjun", "Maya"), email="priya@example.com")
    billed(org, world, keep, days_ago=2)
    _job, _lesson, invoice = billed(org, world, dupe)
    crm_items(org, keep, tag)
    crm_items(org, dupe, tag)
    before = {
        "keep": ledger_total(org, keep["client"]),
        "dupe": ledger_total(org, dupe["client"]),
        "invoice": (invoice.total, invoice.number),
    }
    assert before["dupe"] != 0
    preview = owner.get(
        "/api/v1/merge/clients/preview",
        {"source": dupe["client"].pk, "target": keep["client"].pk},
    )
    assert preview.status_code == 200, preview.json()
    body = preview.json()
    assert body["can_merge"] is True
    assert body["problems"] == []
    moves = {m["key"]: m["count"] for m in body["moves"]}
    assert moves["people.students"] == 2
    assert moves["billing.invoices"] == 1
    assert moves["crm.notes"] == 1
    assert moves["scheduling.attendances"] == 1
    names = {v["name"]: v for v in body["values"]}
    assert names["display_name"]["source"] == "Patel family"
    assert names["display_name"]["default"] == "target"

    response = owner.post(
        "/api/v1/merge/clients",
        {
            "source": str(dupe["client"].pk),
            "target": str(keep["client"].pk),
            "choices": {"display_name": "source"},
            "confirm": True,
        },
        format="json",
    )
    assert response.status_code == 200, response.json()
    assert response.json()["moved"]["billing.invoices"] == 1

    with tenant_context(org):
        survivor = Client.objects.get(pk=keep["client"].pk)
        tombstone = Client.objects.get(pk=dupe["client"].pk)
        assert survivor.display_name == "Patel family"  # the chosen value survived
        assert tombstone.merged_into_id == survivor.pk
        assert tombstone.archived_at is not None
        assert tombstone.status == "archived"
        assert set(Student.objects.filter(client=survivor).values_list("first_name", flat=True))
        assert Student.objects.filter(client=survivor).count() == 3
        assert Contact.objects.filter(client=survivor, is_primary=True).count() == 1
        moved = Invoice.objects.get(pk=invoice.pk)
        assert moved.client_id == survivor.pk
        assert (moved.total, moved.number) == before["invoice"]  # amounts never edited
        assert TaggedItem.objects.filter(target_id=str(survivor.pk)).count() == 1  # deduped
        assert Note.objects.filter(target_id=str(survivor.pk)).count() == 2
        audit = AuditEntry.objects.get(object_id=str(survivor.pk), action="merge")
        assert audit.changes["merged_id"][1] == str(tombstone.pk)
        assert audit.changes["choices"][1]["display_name"] == "source"
        event = OutboxEvent.objects.get(event_type="client.merged")
        assert event.payload["data"]["merged_id"] == str(tombstone.pk)
    assert dangling("people.client", dupe["client"].pk) == {}
    # The merged record's ledger nets to zero; the survivor carries both balances.
    assert ledger_total(org, dupe["client"]) == 0
    assert ledger_total(org, keep["client"]) == before["keep"] + before["dupe"]


def test_merged_record_is_archived_and_points_at_the_survivor(org, owner):
    keep, dupe = family(org, "A"), family(org, "B")
    services_merge(org, "people.client", dupe["client"], keep["client"])
    listed = result_ids(owner.get("/api/v1/clients"))
    assert str(keep["client"].pk) in listed
    assert str(dupe["client"].pk) not in listed
    detail = owner.get(f"/api/v1/clients/{dupe['client'].pk}").json()
    assert detail["merged_into"] == str(keep["client"].pk)


def test_privacy_requests_cover_merged_duplicates(org):
    """A DSAR or erasure of the survivor includes the archived duplicate (E29)."""
    from tutortrack.privacy.registry import resolve

    keep, dupe = family(org, "A"), family(org, "B")
    services_merge(org, "people.client", dupe["client"], keep["client"])
    with tenant_context(org):
        person = resolve("people.client", str(keep["client"].pk))
    assert str(dupe["client"].pk) in person.of("people.client")


def services_merge(org, subject_type, source, target, **kwargs):
    user = MembershipFactory(organisation=org, role="owner").user
    with tenant_context(org):
        return services.merge_records(
            subject_type, source.pk, target.pk, confirm=True, user=user, **kwargs
        )


def test_merge_requires_confirmation(org, owner):
    keep, dupe = family(org, "A"), family(org, "B")
    response = owner.post(
        "/api/v1/merge/clients",
        {"source": str(dupe["client"].pk), "target": str(keep["client"].pk), "confirm": False},
        format="json",
    )
    assert response.status_code == 422
    assert "confirm" in response.json()["errors"]
    with tenant_context(org):
        assert Client.objects.get(pk=dupe["client"].pk).merged_into_id is None


def test_merge_is_not_reversible(org):
    keep, dupe = family(org, "A"), family(org, "B")
    services_merge(org, "people.client", dupe["client"], keep["client"])
    with pytest.raises(BusinessRuleViolation):
        services_merge(org, "people.client", keep["client"], dupe["client"])


def test_legal_hold_blocks_a_merge(org, owner):
    keep, dupe = family(org, "A"), family(org, "B")
    with tenant_context(org):
        holds.place(
            subject_type="people.student",
            subject_id=str(dupe["students"][0].pk),
            reason="Tribunal",
        )
    preview = owner.get(
        "/api/v1/merge/clients/preview",
        {"source": dupe["client"].pk, "target": keep["client"].pk},
    ).json()
    assert preview["can_merge"] is False
    assert any("legal hold" in p for p in preview["problems"])
    response = owner.post(
        "/api/v1/merge/clients",
        {"source": str(dupe["client"].pk), "target": str(keep["client"].pk), "confirm": True},
        format="json",
    )
    assert response.status_code == 422


def test_students_in_different_families_must_merge_the_families_first(org):
    a, b = family(org, "A"), family(org, "B")
    with pytest.raises(BusinessRuleViolation, match="different families"):
        services_merge(org, "people.student", a["students"][0], b["students"][0])


def test_students_booked_on_the_same_lesson_block_the_merge(org, world):
    fam = family(org)
    start = at_ten(2)
    with tenant_context(org):
        scheduling.create_lesson(
            start=start,
            end=start + timedelta(hours=1),
            service=world["service"],
            attendees=[{"student": s} for s in fam["students"]],
            tutors=[{"tutor": world["tutor"]}],
            timezone="Europe/London",
            override_conflicts=True,
            notify=False,
        )
    with pytest.raises(BusinessRuleViolation, match="same lesson"):
        services_merge(org, "people.student", fam["students"][1], fam["students"][0])


def test_student_merge_moves_lessons_jobs_and_learning(org, world):
    fam = family(org)
    keep, dupe = fam["students"]
    lesson = lesson_for(org, world, dupe)
    with tenant_context(org):
        job = jobs.create_job(
            client=fam["client"],
            service=world["service"],
            students=[{"student": keep}, {"student": dupe}],
            tutors=[{"tutor": world["tutor"]}],
            status="active",
        )
    result = services_merge(org, "people.student", dupe, keep)
    assert result["moved"]["scheduling.attendances"] == 1
    with tenant_context(org):
        assert lesson.attendees.get().student_id == keep.pk
        assert list(job.students.values_list("student_id", flat=True)) == [keep.pk]  # deduped
        assert Student.objects.get(pk=dupe.pk).status == "archived"
    assert dangling("people.student", dupe.pk) == {}


def test_contact_merge_moves_links_and_portal_login(org):
    fam = family(org)
    with tenant_context(org):
        dupe = services.create_contact(fam["client"], first_name="Priya", email="p2@example.com")
        user = UserFactory()
        Contact.objects.filter(pk=dupe.pk).update(user=user)
        Client.objects.filter(pk=fam["client"].pk).update(billing_contact=dupe)
    services_merge(org, "people.contact", dupe, fam["contact"], choices={"email": "source"})
    with tenant_context(org):
        survivor = Contact.objects.get(pk=fam["contact"].pk)
        assert survivor.user_id == user.pk
        assert survivor.email == "p2@example.com"
        assert Client.objects.get(pk=fam["client"].pk).billing_contact_id == survivor.pk
        assert Contact.objects.get(pk=dupe.pk).user_id is None
    assert dangling("people.contact", dupe.pk) == {}


def test_accounting_contacts_get_a_note_not_a_merge(org):
    from tutortrack.accounting.models import AccountingConnection, ExternalRecordLink
    from tutortrack.integrations.models import IntegrationConnection

    keep, dupe = family(org, "A"), family(org, "B")
    with tenant_context(org):
        framework = IntegrationConnection.objects.create(
            provider="xero", level="organisation", external_account_id="xero:test"
        )
        conn = AccountingConnection.objects.create(
            connection=framework, provider="xero", enabled=True
        )
        ExternalRecordLink.objects.create(
            connection=conn,
            provider="xero",
            object_type="contact",
            object_id=str(dupe["client"].pk),
            external_id="XC-1",
            label="Patel family",
            status="synced",
        )
    result = services_merge(org, "people.client", dupe["client"], keep["client"])
    assert any("accounting" in n for n in result["notes"])
    with tenant_context(org):
        link = ExternalRecordLink.objects.get(external_id="XC-1")
        assert link.object_id == str(dupe["client"].pk)  # the ledger contact is untouched
        note = Note.objects.get(target_id=str(keep["client"].pk))
        assert "XC-1" not in note.body
        assert "Patel family" in note.body


def test_only_owners_and_admins_may_merge(org):
    keep, dupe = family(org, "A"), family(org, "B")
    payload = {"source": str(dupe["client"].pk), "target": str(keep["client"].pk), "confirm": True}
    for role in ("coordinator", "branch_manager", "finance", "tutor"):
        response = api_as(org, role).post("/api/v1/merge/clients", payload, format="json")
        assert response.status_code == 403, role
    assert (
        api_as(org, "admin").post("/api/v1/merge/clients", payload, format="json").status_code
        == 200
    )


def test_records_of_another_organisation_are_not_found(org, other_org, owner):
    mine = family(org, "A")
    theirs = family(other_org, "B")
    params = {"source": theirs["client"].pk, "target": mine["client"].pk}
    assert owner.get("/api/v1/merge/clients/preview", params).status_code == 404
    response = owner.post(
        "/api/v1/merge/clients",
        {"source": str(theirs["client"].pk), "target": str(mine["client"].pk), "confirm": True},
        format="json",
    )
    assert response.status_code == 404


def test_duplicate_pairs_list(org, other_org, owner):
    keep = family(org, "The Patel Family", email="priya@example.com")
    dupe = family(org, "Patels", email="Priya@Example.com")
    family(other_org, "Elsewhere", email="priya@example.com")
    with tenant_context(org):
        Contact.objects.filter(pk=dupe["contact"].pk).update(email="priya@example.com")
    pairs = owner.get("/api/v1/people/duplicates/pairs", {"type": "contact"}).json()
    assert [(p["a"]["id"], p["b"]["id"], p["reason"]) for p in pairs] == [
        (str(keep["contact"].pk), str(dupe["contact"].pk), "email")
    ]
    clients = owner.get("/api/v1/people/duplicates/pairs", {"type": "client"}).json()
    assert {(p["a"]["id"], p["b"]["id"]) for p in clients} == {
        (str(keep["client"].pk), str(dupe["client"].pk))
    }
    students = owner.get("/api/v1/people/duplicates/pairs", {"type": "student"}).json()
    assert {p["reason"] for p in students} == {"name"}  # Arjun and Maya twice each
    assert len(students) == 2
    assert (
        api_as(org, "coordinator")
        .get("/api/v1/people/duplicates/pairs", {"type": "client"})
        .status_code
        == 403
    )


# --- property: no dangling references, whatever is linked -----------------------------------------

LINKS = ("note", "tag", "task", "message", "preference", "consent", "job", "lesson")


def link(org, world, fam, kind, tag, n):
    client, contact, student = fam["client"], fam["contact"], fam["students"][0]
    with tenant_context(org):
        if kind == "note":
            crm.create_note(target_type="people.student", target_id=student.pk, body="<p>x</p>")
        elif kind == "tag":
            crm.apply_tag(tag, "people.client", [str(client.pk)])
        elif kind == "task":
            crm.create_task(title="t", target_type="people.contact", target_id=contact.pk)
        elif kind == "message":
            Message.objects.create(
                type_key="test",
                channel="email",
                recipient_type="student",
                recipient_id=str(student.pk),
                to="s@example.com",
                body="b",
                target_type="people.student",
                target_id=str(student.pk),
                dedupe_key=f"prop:{student.pk}:{n}",
            )
        elif kind == "preference":
            CommunicationPreference.objects.get_or_create(
                person_type="contact",
                person_id=str(contact.pk),
                category="marketing",
                defaults={"channels": ["email"]},
            )
        elif kind == "consent":
            privacy.ensure_default_types()
            privacy.record_consent(
                subject_type="people.contact",
                subject_id=str(contact.pk),
                key="marketing-email",
                granted=bool(n % 2),
                method="form",
            )
        elif kind == "job":
            jobs.create_job(
                client=client,
                service=world["service"],
                students=[{"student": student}],
                tutors=[{"tutor": world["tutor"]}],
                status="active",
            )
    if kind == "lesson":
        lesson_for(org, world, student, days_ago=3 + n % 50)


@settings(
    max_examples=12,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
)
@given(
    source_links=st.lists(st.sampled_from(LINKS), max_size=6),
    target_links=st.lists(st.sampled_from(LINKS), max_size=4),
    subject=st.sampled_from(["people.client", "people.contact", "people.student"]),
)
def test_merging_never_leaves_dangling_references(org, world, source_links, target_links, subject):
    """Property: whatever is linked to either record, after a merge nothing points at the
    merged record except declared history (FKs via model meta, generic refs by name)."""
    with transaction.atomic():
        tag = TagFactory(organisation=org)
        keep = family(org, "Keep", students=("Arjun",))
        dupe = family(org, "Dupe", students=("Arjun",))
        if subject != "people.client":  # contacts and students merge within one family
            with tenant_context(org):
                other = StudentFactory(organisation=org, client=keep["client"], first_name="A")
                second = services.create_contact(keep["client"], first_name="P2")
            dupe = {"client": keep["client"], "contact": second, "students": [other]}
        for n, kind in enumerate(source_links):
            link(org, world, dupe, kind, tag, n)
        for n, kind in enumerate(target_links):
            link(org, world, keep, kind, tag, 100 + n)
        source, target = {
            "people.client": (dupe["client"], keep["client"]),
            "people.contact": (dupe["contact"], keep["contact"]),
            "people.student": (dupe["students"][0], keep["students"][0]),
        }[subject]
        services_merge(org, subject, source, target)
        assert dangling(subject, source.pk) == {}
        with tenant_context(org):
            assert merging.references(subject, source.pk) == {}
        transaction.set_rollback(True)
