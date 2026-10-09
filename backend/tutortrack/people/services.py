"""People writes (E05). Every mutation is audited and announced with a domain event."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from django.db import transaction
from django.utils.translation import gettext as _

from tutortrack.core import audit
from tutortrack.core.events import DomainEvent, publish
from tutortrack.core.exceptions import BusinessRuleViolation
from tutortrack.core.time import now
from tutortrack.crm.custom_fields import clean_custom_fields

from . import events
from .models import Address, Client, Contact, Student, TutorProfile, TutorSubject

ADDRESS_FIELDS = ("line1", "line2", "city", "region", "postcode", "country")


# --- helpers ------------------------------------------------------------------------------------


def save_address(current: Address | None, data: dict[str, Any] | None) -> Address | None:
    """Create/update an address from a dict (None = leave as is, {} = remove)."""
    if data is None:
        return current
    values = {k: str(data.get(k, "") or "").strip()[:200] for k in ADDRESS_FIELDS}
    if not any(values.values()):
        return None
    address = current or Address()
    changed = any(getattr(address, k) != v for k, v in values.items())
    for k, v in values.items():
        setattr(address, k, v)
    if changed:
        address.lat = address.lng = address.geocoded_at = None
    address.save()
    if changed:
        from .tasks import geocode_address

        transaction.on_commit(
            lambda: geocode_address.delay(
                address_id=str(address.pk), organisation_id=str(address.organisation_id)
            )
        )
    return address


def _apply(
    instance: Any,
    changes: dict[str, Any],
    allowed: Iterable[str],
    *,
    entity_type: str,
    event: type[DomainEvent] | None,
    event_data: dict[str, Any] | None = None,
) -> list[str]:
    unknown = set(changes) - set(allowed) - {"custom_fields"}
    if unknown:
        raise BusinessRuleViolation(f"Cannot change: {', '.join(sorted(unknown))}")
    if "custom_fields" in changes:
        changes["custom_fields"] = clean_custom_fields(
            entity_type, changes["custom_fields"], instance.custom_fields, creating=False
        )
    with audit.track(instance) as tracker:
        for key, value in changes.items():
            setattr(instance, key, value)
        instance.save()
    changed = sorted(tracker.entry.changes) if tracker.entry else []
    if changed and event is not None:
        payload: dict[str, Any] = {"fields": changed, **(event_data or {})}
        publish(event(subject_id=instance.pk, **payload))
    return changed


# --- clients ------------------------------------------------------------------------------------

CLIENT_FIELDS = {
    "type", "display_name", "status", "currency", "payment_terms_days", "invoice_delivery",
    "invoice_grouping", "preferred_payment_method", "auto_pay", "credit_limit_amount",
    "prevent_negative_balance", "tax_exempt", "tax_id", "po_number", "referral_source",
    "account_manager", "account_manager_id", "branch", "branch_id", "primary_contact",
    "billing_contact",
}  # fmt: skip


def household_name(last_name: str) -> str:
    return _("The %(name)s Family") % {"name": last_name} if last_name else _("New family")


@transaction.atomic
def create_client(
    *, display_name: str = "", billing_address: dict[str, Any] | None = None,
    custom_fields: dict[str, Any] | None = None, **fields: Any,
) -> Client:  # fmt: skip
    unknown = set(fields) - CLIENT_FIELDS
    if unknown:
        raise BusinessRuleViolation(f"Unknown client fields: {', '.join(sorted(unknown))}")
    client = Client(display_name=display_name.strip() or _("New client"), **fields)
    if not client.currency:
        from tutortrack.tenancy.models import Branch
        from tutortrack.tenancy.selectors import default_branch_id

        branch_id = client.branch_id or default_branch_id(client_org_id())
        client.currency = Branch.objects.get(pk=branch_id).currency
    client.custom_fields = clean_custom_fields("people.client", custom_fields, None, creating=True)
    client.billing_address = save_address(None, billing_address)
    client.save()
    audit.record_create(client)
    publish(events.ClientCreated(subject_id=client.pk, display_name=client.display_name),
            branch_id=client.branch_id)  # fmt: skip
    return client


def client_org_id() -> Any:
    from tutortrack.core.context import require_organisation_id

    return require_organisation_id()


@transaction.atomic
def update_client(client: Client, **changes: Any) -> Client:
    if "billing_address" in changes:
        client.billing_address = save_address(
            client.billing_address, changes.pop("billing_address")
        )
        client.save(update_fields=["billing_address", "updated_at"])
    if "status" in changes and changes["status"] == Client.Status.ARCHIVED:
        changes.pop("status")
        archive_client(client)
    _apply(client, changes, CLIENT_FIELDS, entity_type="people.client", event=events.ClientUpdated)
    return client


@transaction.atomic
def archive_client(client: Client) -> Client:
    """Hide from default lists and block new lessons (FR-05-14). Students are archived too."""
    if client.archived_at is not None:
        return client
    with audit.track(client, action="archive"):
        client.archived_at = now()
        client.status = Client.Status.ARCHIVED
        client.save(update_fields=["archived_at", "status", "updated_at"])
    for student in Student.objects.filter(client=client, archived_at__isnull=True):
        change_student_status(student, Student.Status.ARCHIVED)
    publish(events.ClientArchived(subject_id=client.pk), branch_id=client.branch_id)
    return client


@transaction.atomic
def restore_client(client: Client) -> Client:
    with audit.track(client, action="restore"):
        client.archived_at = None
        client.status = Client.Status.ACTIVE
        client.save(update_fields=["archived_at", "status", "updated_at"])
    return client


# --- contacts -----------------------------------------------------------------------------------

CONTACT_FIELDS = {
    "first_name", "last_name", "relationship", "email", "phone", "mobile",
    "preferred_contact_method", "use_client_address", "is_primary", "is_bill_payer",
    "receives_reminders", "receives_invoices", "receives_reports", "receives_marketing",
    "is_emergency_contact", "language",
}  # fmt: skip


def _set_primary(contact: Contact) -> None:
    Contact.objects.filter(client=contact.client, is_primary=True).exclude(pk=contact.pk).update(
        is_primary=False
    )
    if contact.client.primary_contact_id != contact.pk:
        contact.client.primary_contact = contact
        contact.client.save(update_fields=["primary_contact", "updated_at"])


@transaction.atomic
def create_contact(
    client: Client, *, address: dict[str, Any] | None = None,
    custom_fields: dict[str, Any] | None = None, **fields: Any,
) -> Contact:  # fmt: skip
    unknown = set(fields) - CONTACT_FIELDS
    if unknown:
        raise BusinessRuleViolation(f"Unknown contact fields: {', '.join(sorted(unknown))}")
    if "email" in fields:
        fields["email"] = str(fields["email"]).strip().lower()
    contact = Contact(client=client, **fields)
    contact.custom_fields = clean_custom_fields(
        "people.contact", custom_fields, None, creating=True
    )
    if not contact.use_client_address:
        contact.address = save_address(None, address)
    first = not Contact.objects.filter(client=client).exists()
    if first:
        contact.is_primary = True
        contact.is_bill_payer = contact.is_bill_payer or first
    contact.save()
    if contact.is_primary:
        _set_primary(contact)
    if contact.is_bill_payer and client.billing_contact_id is None:
        client.billing_contact = contact
        client.save(update_fields=["billing_contact", "updated_at"])
    audit.record_create(contact)
    publish(events.ContactCreated(subject_id=contact.pk, client_id=str(client.pk)))
    return contact


@transaction.atomic
def update_contact(contact: Contact, **changes: Any) -> Contact:
    if "address" in changes:
        contact.address = save_address(contact.address, changes.pop("address"))
        contact.save(update_fields=["address", "updated_at"])
    if "email" in changes:
        changes["email"] = str(changes["email"]).strip().lower()
    _apply(
        contact, changes, CONTACT_FIELDS, entity_type="people.contact",
        event=events.ContactUpdated, event_data={"client_id": str(contact.client_id)},
    )  # fmt: skip
    if changes.get("is_primary"):
        _set_primary(contact)
    return contact


# --- students -----------------------------------------------------------------------------------

STUDENT_FIELDS = {
    "first_name", "last_name", "preferred_name", "date_of_birth", "year_group", "school",
    "subjects", "goals", "learning_needs", "exam_boards", "target_grades", "availability",
    "branch", "branch_id",
}  # fmt: skip


def _validate_subjects(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        raise BusinessRuleViolation(_("Subjects must be a list."))
    out = []
    for item in value:
        if not isinstance(item, dict):
            raise BusinessRuleViolation(_("Each subject needs a name."))
        if item.get("subject_id") or item.get("level_id"):
            from tutortrack.catalogue.selectors import resolve_subject_ids

            subject, level = resolve_subject_ids(item.get("subject_id"), item.get("level_id"))
            if subject is None:
                raise BusinessRuleViolation(_("Choose a subject from the catalogue."))
            item = {"subject": subject.name, "level": level.name if level else ""}
        if not str(item.get("subject", "")).strip():
            raise BusinessRuleViolation(_("Each subject needs a name."))
        out.append({"subject": str(item["subject"]).strip()[:100],
                    "level": str(item.get("level", "")).strip()[:100]})  # fmt: skip
    return out


@transaction.atomic
def create_student(
    client: Client, *, status: str = Student.Status.ACTIVE,
    lesson_address: dict[str, Any] | None = None,
    custom_fields: dict[str, Any] | None = None, **fields: Any,
) -> Student:  # fmt: skip
    unknown = set(fields) - STUDENT_FIELDS
    if unknown:
        raise BusinessRuleViolation(f"Unknown student fields: {', '.join(sorted(unknown))}")
    if client.archived_at is not None:
        raise BusinessRuleViolation(_("The client is archived."))
    if "subjects" in fields:
        fields["subjects"] = _validate_subjects(fields["subjects"])
    fields.setdefault("branch_id", client.branch_id)
    student = Student(client=client, status=status, status_changed_at=now(), **fields)
    student.custom_fields = clean_custom_fields(
        "people.student", custom_fields, None, creating=True
    )
    student.lesson_address = save_address(None, lesson_address)
    student.save()
    audit.record_create(student)
    publish(
        events.StudentCreated(subject_id=student.pk, client_id=str(client.pk), status=status),
        branch_id=student.branch_id,
    )
    return student


@transaction.atomic
def update_student(student: Student, **changes: Any) -> Student:
    if "lesson_address" in changes:
        student.lesson_address = save_address(student.lesson_address, changes.pop("lesson_address"))
        student.save(update_fields=["lesson_address", "updated_at"])
    if "status" in changes:
        change_student_status(student, changes.pop("status"))
    if "subjects" in changes:
        changes["subjects"] = _validate_subjects(changes["subjects"])
    _apply(
        student, changes, STUDENT_FIELDS, entity_type="people.student", event=events.StudentUpdated
    )
    return student


@transaction.atomic
def change_student_status(student: Student, status: str) -> Student:
    if status not in Student.Status.values:
        raise BusinessRuleViolation(_("Unknown status."))
    old = student.status
    if old == status:
        return student
    with audit.track(student, action="status_change"):
        student.status = status
        student.status_changed_at = now()
        student.archived_at = now() if status == Student.Status.ARCHIVED else None
        student.save(update_fields=["status", "status_changed_at", "archived_at", "updated_at"])
    publish(
        events.StudentStatusChanged(subject_id=student.pk, old_status=old, new_status=status),
        branch_id=student.branch_id,
    )
    return student


# --- quick add (FR-05-1 AC) -----------------------------------------------------------------------


@transaction.atomic
def quick_add_family(
    *, contact: dict[str, Any], students: list[dict[str, Any]],
    client: dict[str, Any] | None = None,
) -> tuple[Client, Contact, list[Student]]:  # fmt: skip
    """Client + primary contact + students in one transaction (one-screen quick add)."""
    client_data = dict(client or {})
    is_adult = not students and contact.get("relationship") == Contact.Relationship.SELF
    client_type = client_data.pop(
        "type", Client.Type.INDIVIDUAL if is_adult else Client.Type.HOUSEHOLD
    )
    last_name = str(contact.get("last_name", "")).strip()
    name = client_data.pop("display_name", "") or (
        f"{contact.get('first_name', '')} {last_name}".strip()
        if client_type == Client.Type.INDIVIDUAL
        else household_name(last_name)
    )
    new_client = create_client(display_name=name, type=client_type, **client_data)
    new_contact = create_contact(
        new_client, **{**contact, "is_primary": True, "is_bill_payer": True}
    )
    created = [create_student(new_client, **{"last_name": last_name, **s}) for s in students]
    if is_adult:
        created.append(
            create_student(
                new_client, first_name=new_contact.first_name, last_name=new_contact.last_name
            )
        )
        created[-1].contact = new_contact
        created[-1].save(update_fields=["contact", "updated_at"])
    return new_client, new_contact, created


# --- tutors -------------------------------------------------------------------------------------

TUTOR_FIELDS = {
    "first_name", "last_name", "display_name", "phone", "headline", "bio_public",
    "bio_private", "languages", "years_experience", "employment_type", "pay_rate_amount",
    "travel_radius_km", "delivers_online", "delivers_in_person", "max_weekly_hours",
    "min_lesson_minutes", "public_profile", "tax_reference", "date_of_birth",
    "emergency_contact",
}  # fmt: skip


@transaction.atomic
def create_tutor(
    *, email: str, first_name: str, invite: bool = True,
    address: dict[str, Any] | None = None, custom_fields: dict[str, Any] | None = None,
    branches: Iterable[Any] = (), **fields: Any,
) -> TutorProfile:  # fmt: skip
    """Add a tutor; with ``invite`` they get an invitation (role Tutor) to join."""
    unknown = set(fields) - TUTOR_FIELDS
    if unknown:
        raise BusinessRuleViolation(f"Unknown tutor fields: {', '.join(sorted(unknown))}")
    email = email.strip().lower()
    if TutorProfile.objects.filter(email=email).exists():
        raise BusinessRuleViolation(
            _("A tutor with this email already exists."),
            extra={"errors": {"email": [_("Already a tutor here.")]}},
        )
    tutor = TutorProfile(email=email, first_name=first_name, status_changed_at=now(), **fields)
    tutor.custom_fields = clean_custom_fields("people.tutor", custom_fields, None, creating=True)
    tutor.address = save_address(None, address)
    from tutortrack.identity.models import Membership

    tutor.membership = Membership.objects.filter(
        user__email=email, status=Membership.Status.ACTIVE
    ).first()
    if tutor.membership is not None:
        tutor.status = TutorProfile.Status.ACTIVE
    tutor.save()
    tutor.branches.set(list(branches))
    audit.record_create(tutor)
    publish(events.TutorCreated(subject_id=tutor.pk, email=email))
    if invite and tutor.membership is None:
        from tutortrack.identity.models import Invitation
        from tutortrack.identity.services import invite as send_invite

        if not Invitation.objects.filter(email=email, status=Invitation.Status.PENDING).exists():
            send_invite(email, role=Membership.Role.TUTOR, target_type="people.tutor",
                        target_id=str(tutor.pk))  # fmt: skip
    return tutor


@transaction.atomic
def update_tutor(tutor: TutorProfile, **changes: Any) -> TutorProfile:
    if "address" in changes:
        tutor.address = save_address(tutor.address, changes.pop("address"))
        tutor.save(update_fields=["address", "updated_at"])
    if "branches" in changes:
        tutor.branches.set(list(changes.pop("branches")))
    if "status" in changes:
        change_tutor_status(tutor, changes.pop("status"))
    _apply(tutor, changes, TUTOR_FIELDS, entity_type="people.tutor", event=events.TutorUpdated)
    return tutor


@transaction.atomic
def change_tutor_status(tutor: TutorProfile, status: str) -> TutorProfile:
    if status not in TutorProfile.Status.values:
        raise BusinessRuleViolation(_("Unknown status."))
    old = tutor.status
    if old == status:
        return tutor
    with audit.track(tutor, action="status_change"):
        tutor.status = status
        tutor.status_changed_at = now()
        tutor.archived_at = now() if status == TutorProfile.Status.ARCHIVED else None
        tutor.save(update_fields=["status", "status_changed_at", "archived_at", "updated_at"])
    publish(events.TutorStatusChanged(subject_id=tutor.pk, old_status=old, new_status=status))
    return tutor


@transaction.atomic
def set_tutor_subjects(tutor: TutorProfile, subjects: list[dict[str, Any]]) -> list[TutorSubject]:
    """Replace the tutor's subjects; approval is kept for unchanged subject/level pairs."""
    approved = {
        (s.subject, s.level): (s.approved, s.approved_by_id)
        for s in TutorSubject.objects.filter(tutor=tutor)
    }
    TutorSubject.objects.filter(tutor=tutor).delete()
    created = []
    from tutortrack.catalogue.selectors import match_subject

    for item in _validate_subjects(subjects):
        was_approved, by = approved.get((item["subject"], item["level"]), (False, None))
        cat_subject, cat_level = match_subject(item["subject"], item["level"])
        created.append(
            TutorSubject.objects.create(
                tutor=tutor, subject=item["subject"], level=item["level"],
                catalogue_subject=cat_subject, catalogue_level=cat_level,
                approved=was_approved, approved_by_id=by,
            )
        )  # fmt: skip
    audit.record(tutor, "set_subjects", {"subjects": [None, [str(s) for s in created]]})
    return created


@transaction.atomic
def approve_subject(subject: TutorSubject, approver: Any, approved: bool = True) -> TutorSubject:
    with audit.track(subject, action="approve" if approved else "unapprove"):
        subject.approved = approved
        subject.approved_by = approver if approved else None
        subject.save(update_fields=["approved", "approved_by", "updated_at"])
    return subject


def link_membership(tutor: TutorProfile, membership: Any) -> TutorProfile:
    """Called when the invited tutor accepts (user.joined)."""
    if tutor.membership_id is None:
        tutor.membership = membership
        tutor.save(update_fields=["membership", "updated_at"])
        if tutor.status in {TutorProfile.Status.APPLICANT, TutorProfile.Status.ONBOARDING}:
            change_tutor_status(tutor, TutorProfile.Status.ACTIVE)
    return tutor
