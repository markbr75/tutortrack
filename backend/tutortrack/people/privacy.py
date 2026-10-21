"""People's personal data for DSARs, erasure and retention (E29 Part 2, ADR 0028).

Expansion: a client (household) covers its contacts and students; a contact, student or
tutor covers their login; a login covers the contacts, students or tutor it belongs to.
Erasure replaces names with the token label ("Erased Student #12"), clears every other
personal field (date of birth, notes, school, custom fields, addresses...), removes portal
links and archives the record, so it disappears from search, lists and exports.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from django.db.models import Q
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from tutortrack.core.time import now
from tutortrack.privacy import subjects
from tutortrack.privacy.registry import (
    ErasureContext,
    ErasureOutcome,
    Person,
    Provider,
    RetentionCategory,
    Section,
    register,
    register_retention,
)

from .models import Address, Client, Contact, Student, TutorProfile, TutorQualification

YEARS_6 = 365 * 6 + 2


# --- subjects -----------------------------------------------------------------------------------


def _tutor_exists(subject_id: str) -> bool:
    return TutorProfile.objects.filter(pk=subject_id).exists()


def _label(model: Any) -> Any:
    def label(subject_id: str) -> str:
        obj = model.objects.filter(pk=subject_id).first()
        if obj is None:
            return ""
        return str(getattr(obj, "display_name", "") or obj.full_name)

    return label


subjects.register("people.tutor", _tutor_exists, _label(TutorProfile))
subjects.register_label("people.client", _label(Client))
subjects.register_label("people.contact", _label(Contact))
subjects.register_label("people.student", _label(Student))


# --- expansion ----------------------------------------------------------------------------------


def expand(person: Person) -> None:
    # Duplicates merged into this person (FR-05-13) are archived tombstones of the same
    # person: they are exported and erased with them.
    for model, kind in (
        (Client, "people.client"),
        (Contact, "people.contact"),
        (Student, "people.student"),
    ):
        ids = person.of(kind)
        if ids:
            person.add(
                kind, *model.objects.filter(merged_into_id__in=ids).values_list("pk", flat=True)
            )
    clients = person.of("people.client")
    if clients:
        person.add(
            "people.contact",
            *Contact.objects.filter(client_id__in=clients).values_list("pk", flat=True),
        )
        person.add(
            "people.student",
            *Student.objects.filter(client_id__in=clients).values_list("pk", flat=True),
        )
        for client in Client.objects.filter(pk__in=clients):
            person.add_terms(names=[client.display_name])
    users = person.of("identity.user")
    if users:
        person.add(
            "people.contact",
            *Contact.objects.filter(user_id__in=users).values_list("pk", flat=True),
        )
        person.add(
            "people.student",
            *Student.objects.filter(user_id__in=users).values_list("pk", flat=True),
        )
        person.add(
            "people.tutor",
            *TutorProfile.objects.filter(membership__user_id__in=users).values_list(
                "pk", flat=True
            ),
        )
    for contact in Contact.objects.filter(pk__in=person.of("people.contact")):
        person.add("identity.user", contact.user_id)
        person.add_context("people.client", contact.client_id)
        person.add_terms(
            names=[contact.full_name, contact.first_name if len(contact.first_name) > 2 else ""],
            emails=[contact.email],
            phones=[contact.phone, contact.mobile],
        )
    for student in Student.objects.filter(pk__in=person.of("people.student")):
        person.add("identity.user", student.user_id)
        person.add_context("people.client", student.client_id)
        person.add_terms(
            names=[
                student.full_name,
                f"{student.first_name} {student.last_name}",
                student.first_name if len(student.first_name) > 2 else "",
            ]
        )
    for tutor in TutorProfile.objects.filter(pk__in=person.of("people.tutor")).select_related(
        "membership"
    ):
        if tutor.membership is not None:
            person.add("identity.user", tutor.membership.user_id)
        person.add_terms(
            names=[tutor.full_name, f"{tutor.first_name} {tutor.last_name}"],
            emails=[tutor.email],
            phones=[tutor.phone],
        )


# --- export -------------------------------------------------------------------------------------


def _address(address: Address | None) -> dict[str, Any] | None:
    if address is None:
        return None
    return {
        "line1": address.line1,
        "line2": address.line2,
        "city": address.city,
        "region": address.region,
        "postcode": address.postcode,
        "country": address.country,
    }


def export(person: Person) -> list[Section]:
    clients = [
        {
            "id": str(c.pk),
            "name": c.display_name,
            "type": c.type,
            "status": c.status,
            "billing_address": _address(c.billing_address),
            "tax_id": c.tax_id,
            "po_number": c.po_number,
            "referral_source": c.referral_source,
            "custom_fields": c.custom_fields,
            "created_at": c.created_at,
        }
        for c in Client.objects.filter(pk__in=person.of("people.client")).select_related(
            "billing_address"
        )
    ]
    contacts = [
        {
            "id": str(c.pk),
            "first_name": c.first_name,
            "last_name": c.last_name,
            "relationship": c.relationship,
            "email": c.email,
            "phone": c.phone,
            "mobile": c.mobile,
            "address": _address(c.address),
            "language": c.language,
            "preferences": {
                "reminders": c.receives_reminders,
                "invoices": c.receives_invoices,
                "reports": c.receives_reports,
                "marketing": c.receives_marketing,
            },
            "custom_fields": c.custom_fields,
            "created_at": c.created_at,
        }
        for c in Contact.objects.filter(pk__in=person.of("people.contact")).select_related(
            "address"
        )
    ]
    students = [
        {
            "id": str(s.pk),
            "first_name": s.first_name,
            "last_name": s.last_name,
            "preferred_name": s.preferred_name,
            "date_of_birth": s.date_of_birth,
            "year_group": s.year_group,
            "school": s.school,
            "status": s.status,
            "subjects": s.subjects,
            "goals": s.goals,
            "learning_needs": s.learning_needs,
            "exam_boards": s.exam_boards,
            "sen_tags": s.sen_tags,
            "tutor_gender_preference": s.tutor_gender_preference,
            "target_grades": s.target_grades,
            "availability": s.availability,
            "lesson_address": _address(s.lesson_address),
            "custom_fields": s.custom_fields,
            "created_at": s.created_at,
        }
        for s in Student.objects.filter(pk__in=person.of("people.student")).select_related(
            "lesson_address"
        )
    ]
    tutors = [
        {
            "id": str(t.pk),
            "first_name": t.first_name,
            "last_name": t.last_name,
            "display_name": t.display_name,
            "email": t.email,
            "phone": t.phone,
            "headline": t.headline,
            "bio_public": t.bio_public,
            "date_of_birth": t.date_of_birth,
            "languages": t.languages,
            "gender": t.gender,
            "sen_tags": t.sen_tags,
            "exam_boards": t.exam_boards,
            "address": _address(t.address),
            "emergency_contact": t.emergency_contact,
            "qualifications": [
                {"title": q.title, "institution": q.institution, "year": q.year}
                for q in t.qualifications.all()
            ],
            "created_at": t.created_at,
        }
        for t in TutorProfile.objects.filter(pk__in=person.of("people.tutor")).select_related(
            "address"
        )
    ]
    return [
        Section("people.clients", _("Accounts"), clients),
        Section("people.contacts", _("Contact details"), contacts),
        Section("people.students", _("Students"), students),
        Section("people.tutors", _("Tutor profile"), tutors),
    ]


def files(person: Person) -> list[Any]:
    tutors = person.of("people.tutor")
    if not tutors:
        return []
    return [
        q.document
        for q in TutorQualification.objects.filter(
            tutor_id__in=tutors, document__isnull=False
        ).select_related("document")
    ]


# --- erasure ------------------------------------------------------------------------------------


def _blank_addresses(ids: list[Any]) -> int:
    ids = [i for i in ids if i]
    if not ids:
        return 0
    return Address.objects.filter(pk__in=ids).update(
        line1="", line2="", city="", region="", postcode="", lat=None, lng=None, geocoded_at=None
    )


def erase(person: Person, ctx: ErasureContext) -> ErasureOutcome:
    out = ErasureOutcome()
    moment = now()
    students = Student.objects.filter(pk__in=person.of("people.student"))
    out.anonymised += _blank_addresses(list(students.values_list("lesson_address_id", flat=True)))
    for student in students:
        student.preferred_tutors.clear()
        student.excluded_tutors.clear()
        Student.objects.filter(pk=student.pk).update(
            first_name=ctx.label("people.student", student.pk, _("Erased student")),
            last_name="",
            preferred_name="",
            date_of_birth=None,
            year_group="",
            school="",
            goals="",
            learning_needs="",
            subjects=[],
            exam_boards=[],
            sen_tags=[],
            tutor_gender_preference="",
            target_grades={},
            availability={},
            custom_fields={},
            lesson_address=None,
            user=None,
            status=Student.Status.ARCHIVED,
            archived_at=student.archived_at or moment,
            updated_at=moment,
        )
        out.anonymised += 1
    contacts = Contact.objects.filter(pk__in=person.of("people.contact"))
    out.anonymised += _blank_addresses(list(contacts.values_list("address_id", flat=True)))
    for contact in contacts:
        Contact.objects.filter(pk=contact.pk).update(
            first_name=ctx.label("people.contact", contact.pk, _("Erased contact")),
            last_name="",
            relationship="",
            email="",
            phone="",
            mobile="",
            address=None,
            language="",
            receives_reminders=False,
            receives_invoices=False,
            receives_reports=False,
            receives_marketing=False,
            custom_fields={},
            user=None,
            archived_at=contact.archived_at or moment,
            updated_at=moment,
        )
        out.anonymised += 1
    clients = Client.objects.filter(pk__in=person.of("people.client"))
    out.anonymised += _blank_addresses(list(clients.values_list("billing_address_id", flat=True)))
    for client in clients:
        Client.objects.filter(pk=client.pk).update(
            display_name=ctx.label("people.client", client.pk, _("Erased client")),
            tax_id="",
            po_number="",
            referral_source="",
            custom_fields={},
            billing_address=None,
            status=Client.Status.ARCHIVED,
            archived_at=client.archived_at or moment,
            updated_at=moment,
        )
        out.anonymised += 1
    tutors = TutorProfile.objects.filter(pk__in=person.of("people.tutor"))
    out.anonymised += _blank_addresses(list(tutors.values_list("address_id", flat=True)))
    for qualification in TutorQualification.objects.filter(tutor__in=tutors):
        if qualification.document_id:
            out.file_ids.append(str(qualification.document_id))
        qualification.delete()
        out.deleted += 1
    for tutor in tutors:
        TutorProfile.objects.filter(pk=tutor.pk).update(
            first_name=ctx.label("people.tutor", tutor.pk, _("Erased tutor")),
            last_name="",
            display_name="",
            email="",
            phone="",
            headline="",
            bio_public="",
            bio_private="",
            languages=[],
            gender="",
            sen_tags=[],
            exam_boards=[],
            date_of_birth=None,
            emergency_contact={},
            tax_reference="",
            custom_fields={},
            address=None,
            public_profile=False,
            status=TutorProfile.Status.ARCHIVED,
            archived_at=tutor.archived_at or moment,
            updated_at=moment,
        )
        out.anonymised += 1
    return out


register(
    Provider(
        key="people",
        label="People",
        expand=expand,
        export=export,
        files=files,
        erase=erase,
        order=990,  # last: other apps scrub free text before the names change
    )
)


# --- retention ----------------------------------------------------------------------------------


def _not_erased(qs: Any, subject_type: str) -> Any:
    """Skip people already erased (or planned) and anyone under a legal hold."""
    from tutortrack.privacy.selectors import erased_ids, held_ids

    return qs.exclude(pk__in=list(erased_ids(subject_type) | held_ids(subject_type)))


def _archived_students(cutoff: datetime, limit: int) -> list[tuple[str, str]]:
    from tutortrack.privacy.selectors import held_ids

    qs = _not_erased(Student.objects.filter(archived_at__lt=cutoff), "people.student")
    qs = qs.exclude(client_id__in=list(held_ids("people.client")))
    return [("people.student", str(pk)) for pk in qs.values_list("pk", flat=True)[:limit]]


def _archived_clients(cutoff: datetime, limit: int) -> list[tuple[str, str]]:
    qs = _not_erased(Client.objects.filter(archived_at__lt=cutoff), "people.client")
    qs = qs.exclude(Q(students__archived_at__isnull=True) | Q(students__archived_at__gte=cutoff))
    return [("people.client", str(pk)) for pk in qs.values_list("pk", flat=True).distinct()[:limit]]


register_retention(
    RetentionCategory(
        key="archived_students",
        label=gettext_lazy("Archived students (erased after the period)"),
        default_days=YEARS_6,
        find=_archived_students,
        order=10,
    )
)
register_retention(
    RetentionCategory(
        key="archived_clients",
        label=gettext_lazy("Archived clients and their contacts (erased after the period)"),
        default_days=YEARS_6,
        find=_archived_clients,
        order=11,
    )
)
