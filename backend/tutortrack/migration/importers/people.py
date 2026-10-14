"""Clients with contacts (household rows), students and tutors (E28-T02)."""

from __future__ import annotations

from typing import Any

from django.utils.translation import gettext as _

from . import refs
from .base import (
    Context,
    FieldSpec,
    Importer,
    Outcome,
    Plan,
    RowError,
    first,
    register,
)
from .base import (
    label as _l,
)
from .common import (
    address_fields,
    address_from,
    apply_consents,
    apply_tags,
    batch_target,
    consent_fields,
    custom_values,
    ref,
    remember_household,
    update_tracked,
)

STUDENT_STATUSES = ("lead", "trial", "active", "waiting", "paused", "finished")
TUTOR_STATUSES = ("applicant", "onboarding", "active", "restricted", "inactive")


def _people() -> Any:
    from tutortrack.people import services

    return services


# --- clients (households) -------------------------------------------------------------------------


@register
class ClientImporter(Importer):
    """One row per contact; rows with the same client id (or, without one, the same
    client name) form one household. A row may also name one student."""

    key = "clients"
    label = _l("Clients and contacts")
    description = _l("Families or organisations that pay, with their contacts and students.")
    permissions = ("people.client.create", "people.contact.create", "people.student.create")
    target_type = "people.client"
    upsert_keys = ("external_id", "email", "none")
    default_upsert = "email"
    fields = [
        FieldSpec(
            "external_id",
            _l("Client ID"),
            synonyms=("client id", "family id", "account id", "customer id", "client number", "id"),
        ),
        FieldSpec(
            "client_name",
            _l("Client or family name"),
            synonyms=(
                "client name",
                "family",
                "household",
                "account name",
                "customer name",
                "billing name",
            ),
        ),
        FieldSpec(
            "client_type",
            _l("Client type"),
            "choice",
            choices=("household", "individual", "organisation"),
            synonyms=("type",),
        ),
        FieldSpec(
            "status",
            _l("Client status"),
            "choice",
            choices=("prospect", "active", "dormant"),
            synonyms=("status", "client status"),
        ),
        FieldSpec(
            "first_name",
            _l("Contact first name"),
            required=True,
            synonyms=(
                "first name",
                "forename",
                "given name",
                "parent first name",
                "contact first name",
            ),
        ),
        FieldSpec(
            "last_name",
            _l("Contact last name"),
            synonyms=("last name", "surname", "parent last name", "contact last name"),
        ),
        FieldSpec(
            "email",
            _l("Contact email"),
            "email",
            synonyms=("email", "email address", "e-mail", "parent email", "contact email"),
        ),
        FieldSpec(
            "phone", _l("Phone"), synonyms=("phone", "telephone", "home phone", "phone number")
        ),
        FieldSpec(
            "mobile", _l("Mobile"), synonyms=("mobile", "cell", "cell phone", "mobile phone")
        ),
        FieldSpec(
            "relationship",
            _l("Relationship"),
            "choice",
            choices=("parent", "guardian", "carer", "self", "finance", "other"),
        ),
        *address_fields(),
        FieldSpec("payment_terms_days", _l("Payment terms (days)"), "int"),
        FieldSpec(
            "referral_source",
            _l("How they heard about us"),
            synonyms=("source", "referral source", "lead source"),
        ),
        FieldSpec("tags", _l("Tags"), "list", synonyms=("labels", "tags")),
        FieldSpec(
            "student_first_name",
            _l("Student first name"),
            synonyms=("student first name", "child first name", "student"),
        ),
        FieldSpec(
            "student_last_name",
            _l("Student last name"),
            synonyms=("student last name", "child last name"),
        ),
        FieldSpec(
            "student_year_group",
            _l("Student year group"),
            synonyms=("year group", "grade", "year"),
        ),
        FieldSpec("student_school", _l("Student school"), synonyms=("school",)),
        FieldSpec(
            "student_date_of_birth",
            _l("Student date of birth"),
            "date",
            synonyms=("date of birth", "dob", "birthday"),
        ),
        FieldSpec("student_status", _l("Student status"), "choice", choices=STUDENT_STATUSES),
        *consent_fields(
            "consent_marketing_email",
            "consent_marketing_sms",
            "consent_data_processing",
            "consent_photo_video",
        ),
    ]
    example = {
        "external_id": "C-1001",
        "client_name": "The Smith Family",
        "first_name": "Jane",
        "last_name": "Smith",
        "email": "jane@example.com",
        "phone": "07700 900123",
        "address_postcode": "SW1A 1AA",
        "student_first_name": "Tom",
        "student_year_group": "Year 9",
    }

    def _household(self, values: dict[str, Any]) -> str:
        return str(
            first(values, "external_id", "client_name", "email")
            or f"{values.get('first_name', '')} {values.get('last_name', '')}"
        ).strip()

    def _existing(self, values: dict[str, Any], ctx: Context) -> Any:
        if ctx.upsert_key == "external_id" or values.get("external_id"):
            found = refs.find_client(ctx, {"client_external_id": values.get("external_id")})
            if found is not None or ctx.upsert_key == "external_id":
                return found
        if ctx.upsert_key == "email" and values.get("email"):
            return refs.find_client(ctx, {"client_email": values["email"]})
        return None

    def check(self, values: dict[str, Any], ctx: Context) -> Plan:
        key = self._household(values)
        plan = Plan(extra={"_household": key.lower()})
        earlier = ctx.claim("household", key)
        existing = self._existing(values, ctx)
        if earlier is not None:
            plan.action = "update"
            plan.effects.append(("people.contact", "create"))
            ctx.warn("", _("Adds to the household from row %(row)s.") % {"row": earlier})
        elif existing is not None:
            plan.action = "update"
            plan.effects += [("people.client", "update"), ("people.contact", "update")]
            plan.target_type, plan.target_id = "people.client", str(existing.pk)
        else:
            plan.effects += [("people.client", "create"), ("people.contact", "create")]
            if values.get("email") and refs.find_client(ctx, {"client_email": values["email"]}):
                ctx.warn("email", _("A contact with this email already exists elsewhere."))
        if values.get("student_first_name"):
            plan.effects.append(("people.student", "create"))
        return plan

    def apply(self, values: dict[str, Any], ctx: Context) -> Outcome:
        people = _people()
        from tutortrack.people.models import Contact, Student

        client = batch_target(ctx, values.get("_household", ""), before=ctx.row_number)
        out = Outcome(action="update", target_type="people.client")
        if client is None:
            client = self._existing(values, ctx)
            if client is not None:
                wanted = {
                    "display_name": values.get("client_name"),
                    "status": values.get("status"),
                    "payment_terms_days": values.get("payment_terms_days"),
                    "referral_source": values.get("referral_source"),
                }
                update_tracked(client, wanted, people.update_client, out.previous)
        if client is None:
            out.action = "create"
            name = values.get("client_name") or (
                f"{values['first_name']} {values.get('last_name', '')}".strip()
                if values.get("client_type") == "individual"
                else people.household_name(values.get("last_name") or "")
            )
            client = people.create_client(
                display_name=name,
                type=values.get("client_type") or "household",
                status=values.get("status") or "active",
                billing_address=address_from(values),
                custom_fields=custom_values(values) or None,
                **{
                    k: values[k]
                    for k in ("payment_terms_days", "referral_source")
                    if values.get(k) is not None
                },
            )
            out.created.append(ref(client))
            if values.get("external_id"):
                out.created.append(
                    refs.remember(ctx, "people.client", values["external_id"], client)
                )
        out.target_id = str(client.pk)
        remember_household(ctx, values.get("_household", ""), client)
        contact = None
        if values.get("email"):
            contact = Contact.objects.filter(client=client, email=values["email"]).first()
        if contact is None:
            contact = Contact.objects.filter(
                client=client,
                first_name__iexact=values["first_name"],
                last_name__iexact=values.get("last_name") or "",
            ).first()
        contact_fields = {
            k: values[k]
            for k in ("last_name", "email", "phone", "mobile", "relationship")
            if values.get(k)
        }
        if contact is None:
            contact = people.create_contact(
                client, first_name=values["first_name"], **contact_fields
            )
            out.created.append(ref(contact))
        else:
            update_tracked(contact, contact_fields, people.update_contact, out.previous)
        out.created += apply_tags("people.client", client, values.get("tags"))
        student = None
        if values.get("student_first_name"):
            exists = Student.objects.filter(
                client=client,
                first_name__iexact=values["student_first_name"],
                last_name__iexact=values.get("student_last_name") or client_last(values),
            ).exists()
            if exists:
                out.warnings.append(_("The student already exists; not added again."))
            else:
                student = people.create_student(
                    client,
                    status=values.get("student_status") or "active",
                    first_name=values["student_first_name"],
                    last_name=values.get("student_last_name") or client_last(values),
                    **{
                        f: values[f"student_{f}"]
                        for f in ("year_group", "school", "date_of_birth")
                        if values.get(f"student_{f}") not in (None, "")
                    },
                )
                out.created.append(ref(student))
        out.created += apply_consents(
            ctx, values, {"people.contact": [contact], "people.student": [student]}
        )
        return out


def client_last(values: dict[str, Any]) -> str:
    return str(values.get("last_name") or "")


# --- students -----------------------------------------------------------------------------------


@register
class StudentImporter(Importer):
    """One row per student. The client is found by its id, a contact's email or its name;
    otherwise a household is created from the parent columns (rows naming the same parent
    email share it), or an individual client for an adult learner."""

    key = "students"
    label = _l("Students")
    description = _l("Learners, linked to an existing client or with their parent's details.")
    permissions = ("people.student.create",)
    target_type = "people.student"
    upsert_keys = ("external_id", "none")
    default_upsert = "external_id"
    fields = [
        FieldSpec(
            "external_id",
            _l("Student ID"),
            synonyms=("student id", "id", "recipient id", "student number"),
        ),
        FieldSpec(
            "first_name",
            _l("First name"),
            required=True,
            synonyms=("first name", "student first name", "forename", "given name"),
        ),
        FieldSpec(
            "last_name", _l("Last name"), synonyms=("last name", "surname", "student last name")
        ),
        FieldSpec("preferred_name", _l("Preferred name"), synonyms=("nickname", "known as")),
        FieldSpec(
            "date_of_birth",
            _l("Date of birth"),
            "date",
            synonyms=("dob", "date of birth", "birthday", "birth date"),
        ),
        FieldSpec(
            "year_group",
            _l("Year group or grade"),
            synonyms=("year", "grade", "year group", "school year"),
        ),
        FieldSpec("school", _l("School"), synonyms=("school", "school name")),
        FieldSpec(
            "status",
            _l("Status"),
            "choice",
            choices=STUDENT_STATUSES,
            synonyms=("status", "student status"),
        ),
        FieldSpec(
            "subjects",
            _l("Subjects (Subject: Level; ...)"),
            "list",
            synonyms=("subjects", "subject"),
        ),
        FieldSpec("goals", _l("Goals"), synonyms=("goals", "objectives")),
        FieldSpec(
            "learning_needs",
            _l("Learning needs or medical notes"),
            synonyms=("learning needs", "sen", "medical", "special needs"),
        ),
        FieldSpec(
            "client_external_id",
            _l("Client ID"),
            synonyms=("client id", "family id", "account id", "customer id"),
        ),
        FieldSpec(
            "client_email",
            _l("Client email"),
            "email",
            synonyms=("client email", "account email"),
        ),
        FieldSpec(
            "client_name",
            _l("Client or family name"),
            synonyms=("client", "family", "client name", "family name"),
        ),
        FieldSpec(
            "parent_first_name",
            _l("Parent first name"),
            synonyms=("parent first name", "guardian first name", "parent name", "parent"),
        ),
        FieldSpec(
            "parent_last_name",
            _l("Parent last name"),
            synonyms=("parent last name", "guardian last name"),
        ),
        FieldSpec(
            "parent_email",
            _l("Parent email"),
            "email",
            synonyms=("parent email", "guardian email", "family email", "email"),
        ),
        FieldSpec(
            "parent_phone",
            _l("Parent phone"),
            synonyms=("parent phone", "guardian phone", "phone", "mobile"),
        ),
        FieldSpec("tags", _l("Tags"), "list", synonyms=("labels", "tags")),
        *consent_fields("consent_photo_video", "consent_lesson_recording"),
    ]
    example = {
        "external_id": "S-501",
        "first_name": "Tom",
        "last_name": "Smith",
        "year_group": "Year 9",
        "subjects": "Maths: GCSE; Physics",
        "parent_first_name": "Jane",
        "parent_email": "jane@example.com",
    }

    def _key(self, values: dict[str, Any]) -> str:
        return str(
            first(values, "client_external_id", "client_email", "parent_email", "client_name") or ""
        )

    def _client(self, values: dict[str, Any], ctx: Context) -> Any:
        found = refs.find_client(ctx, values)
        if found is None and values.get("parent_email"):
            found = refs.find_client(ctx, {"client_email": values["parent_email"]})
        return found

    def _existing(self, values: dict[str, Any], ctx: Context) -> Any:
        from tutortrack.people.models import Student

        if values.get("external_id"):
            target = refs.ref_for(ctx, "people.student", values["external_id"])
            if target:
                return Student.objects.filter(pk=target).first()
        return None

    def check(self, values: dict[str, Any], ctx: Context) -> Plan:
        from tutortrack.people.models import Student

        key = self._key(values)
        plan = Plan(extra={"_household": key.lower()})
        if values.get("external_id") and ctx.claim("student", values["external_id"]):
            ctx.error("external_id", _("This student id appears earlier in the file."))
        existing = self._existing(values, ctx)
        if existing is not None:
            plan.action, plan.target_type, plan.target_id = (
                "update",
                "people.student",
                str(existing.pk),
            )
            plan.effects.append(("people.student", "update"))
            return plan
        client = self._client(values, ctx)
        if client is None and not (key and ctx.claimed("household", key)):
            if values.get("client_external_id") and not first(
                values, "parent_first_name", "parent_email", "client_name"
            ):
                ctx.error("client_external_id", _("No client with this id; import clients first."))
            plan.effects += [("people.client", "create"), ("people.contact", "create")]
            ctx.claim("household", key)
        elif client is not None:
            duplicate = Student.objects.filter(
                client=client,
                first_name__iexact=values.get("first_name") or "",
                last_name__iexact=values.get("last_name") or "",
            ).first()
            if duplicate is not None:
                ctx.warn("first_name", _("Already a student of this client; will be skipped."))
                plan.action, plan.target_type, plan.target_id = (
                    "skip",
                    "people.student",
                    str(duplicate.pk),
                )
                return plan
        plan.effects.append(("people.student", "create"))
        return plan

    def _subjects(self, values: dict[str, Any]) -> list[dict[str, str]] | None:
        items = values.get("subjects")
        if not items:
            return None
        out = []
        for item in items:
            subject, _sep, level = str(item).partition(":")
            out.append({"subject": subject.strip(), "level": level.strip()})
        return out

    def apply(self, values: dict[str, Any], ctx: Context) -> Outcome:
        people = _people()
        from tutortrack.people.models import Student

        fields = {
            k: values[k]
            for k in (
                "last_name",
                "preferred_name",
                "date_of_birth",
                "year_group",
                "school",
                "goals",
                "learning_needs",
            )
            if values.get(k) not in (None, "")
        }
        subjects = self._subjects(values)
        if subjects:
            fields["subjects"] = subjects
        existing = self._existing(values, ctx)
        out = Outcome(action="create", target_type="people.student")
        if existing is not None:
            out.action = "update"
            wanted = {"first_name": values["first_name"], **fields}
            update_tracked(existing, wanted, people.update_student, out.previous)
            if values.get("status") and values["status"] != existing.status:
                out.previous.setdefault(f"people.student:{existing.pk}", {})["status"] = (
                    existing.status
                )
                people.change_student_status(existing, values["status"])
            out.target_id = str(existing.pk)
            out.created += apply_tags("people.student", existing, values.get("tags"))
            out.created += apply_consents(ctx, values, {"people.student": [existing]})
            return out
        client = batch_target(ctx, values.get("_household", ""), before=ctx.row_number)
        client = client or self._client(values, ctx)
        if client is None:
            parent = values.get("parent_first_name") or values.get("parent_email")
            if parent or values.get("client_name"):
                contact = {
                    "first_name": values.get("parent_first_name") or _("Parent"),
                    "last_name": values.get("parent_last_name") or values.get("last_name") or "",
                    "email": values.get("parent_email") or "",
                    "phone": values.get("parent_phone") or "",
                }
                client, contact_obj, _none = people.quick_add_family(
                    contact=contact,
                    students=[],
                    client={"display_name": values["client_name"]}
                    if values.get("client_name")
                    else None,
                )
            else:  # an adult learner is their own client
                client = people.create_client(
                    display_name=f"{values['first_name']} {values.get('last_name', '')}".strip(),
                    type="individual",
                )
                contact_obj = None
            out.created.append(ref(client))
            if contact_obj is not None:
                out.created.append(ref(contact_obj))
            if values.get("client_external_id"):
                out.created.append(
                    refs.remember(ctx, "people.client", values["client_external_id"], client)
                )
        elif Student.objects.filter(
            client=client,
            first_name__iexact=values["first_name"],
            last_name__iexact=values.get("last_name") or "",
        ).exists():
            raise RowError(_("Already a student of this client."), "first_name")
        remember_household(ctx, values.get("_household", ""), client)
        student = people.create_student(
            client,
            status=values.get("status") or "active",
            first_name=values["first_name"],
            custom_fields=custom_values(values) or None,
            **fields,
        )
        out.created.append(ref(student))
        if values.get("external_id"):
            out.created.append(refs.remember(ctx, "people.student", values["external_id"], student))
        out.created += apply_tags("people.student", student, values.get("tags"))
        out.created += apply_consents(ctx, values, {"people.student": [student]})
        out.target_id = str(student.pk)
        return out


# --- tutors -------------------------------------------------------------------------------------


@register
class TutorImporter(Importer):
    """Tutors are added without an invitation; the cutover assistant invites them later."""

    key = "tutors"
    label = _l("Tutors")
    description = _l("Tutors and their subjects. Invitations are sent separately.")
    permissions = ("people.tutor.create",)
    target_type = "people.tutor"
    upsert_keys = ("email", "external_id", "none")
    default_upsert = "email"
    fields = [
        FieldSpec(
            "external_id",
            _l("Tutor ID"),
            synonyms=("tutor id", "contractor id", "employee id", "teacher id", "id"),
        ),
        FieldSpec(
            "email",
            _l("Email"),
            "email",
            required=True,
            synonyms=("email", "email address", "e-mail", "tutor email"),
        ),
        FieldSpec(
            "first_name",
            _l("First name"),
            required=True,
            synonyms=("first name", "forename", "given name"),
        ),
        FieldSpec("last_name", _l("Last name"), synonyms=("last name", "surname")),
        FieldSpec("phone", _l("Phone"), synonyms=("phone", "mobile", "telephone", "cell")),
        FieldSpec("status", _l("Status"), "choice", choices=TUTOR_STATUSES, synonyms=("status",)),
        FieldSpec(
            "employment_type",
            _l("Employment type"),
            "choice",
            choices=("self_employed", "employee", "other"),
            synonyms=("employment", "employment type", "contract type"),
        ),
        FieldSpec(
            "pay_rate",
            _l("Default pay rate (per hour)"),
            "decimal",
            synonyms=("pay rate", "hourly rate", "wage", "rate"),
        ),
        FieldSpec("headline", _l("Headline"), synonyms=("headline", "title")),
        FieldSpec("bio", _l("Profile"), synonyms=("bio", "biography", "profile", "about")),
        FieldSpec(
            "subjects",
            _l("Subjects (Subject: Level; ...)"),
            "list",
            synonyms=("subjects", "skills", "subject"),
        ),
        FieldSpec("languages", _l("Languages"), "list", synonyms=("languages",)),
        FieldSpec(
            "years_experience",
            _l("Years of experience"),
            "int",
            synonyms=("experience", "years experience"),
        ),
        FieldSpec("delivers_online", _l("Teaches online"), "bool", synonyms=("online",)),
        FieldSpec(
            "delivers_in_person",
            _l("Teaches in person"),
            "bool",
            synonyms=("in person", "face to face"),
        ),
        FieldSpec("travel_radius_km", _l("Travel radius (km)"), "int"),
        FieldSpec("date_of_birth", _l("Date of birth"), "date", synonyms=("dob",)),
        *address_fields(),
        FieldSpec("tags", _l("Tags"), "list", synonyms=("labels", "tags")),
        FieldSpec(
            "pay_tier",
            _l("Pay tier"),
            synonyms=("pay tier", "wage tier", "tier", "pay band"),
            help=_l("Created if new; the tutor is put on it from the cutover date (E06)."),
        ),
    ]
    example = {
        "external_id": "T-77",
        "email": "alex@example.com",
        "first_name": "Alex",
        "last_name": "Jones",
        "subjects": "Maths: A-Level; Physics: GCSE",
        "pay_rate": "25.00",
    }

    def _existing(self, values: dict[str, Any], ctx: Context) -> Any:
        if ctx.upsert_key == "none":
            return None
        if ctx.upsert_key == "external_id" or values.get("external_id"):
            found = refs.find_tutor(ctx, {"tutor_external_id": values.get("external_id")})
            if found is not None or ctx.upsert_key == "external_id":
                return found
        return refs.find_tutor(ctx, {"tutor_email": values.get("email")})

    def check(self, values: dict[str, Any], ctx: Context) -> Plan:
        if ctx.claim("tutor", str(values.get("email") or "")):
            ctx.error("email", _("This email appears earlier in the file."))
        existing = self._existing(values, ctx)
        if existing is not None:
            return Plan(
                action="update",
                effects=[("people.tutor", "update")],
                target_type="people.tutor",
                target_id=str(existing.pk),
            )
        if ctx.upsert_key == "none" and refs.find_tutor(ctx, {"tutor_email": values.get("email")}):
            ctx.error("email", _("A tutor with this email already exists."))
        return Plan(effects=[("people.tutor", "create")])

    def _fields(self, values: dict[str, Any]) -> dict[str, Any]:
        fields = {
            k: values[k]
            for k in (
                "last_name",
                "phone",
                "employment_type",
                "headline",
                "languages",
                "years_experience",
                "delivers_online",
                "delivers_in_person",
                "travel_radius_km",
                "date_of_birth",
            )
            if values.get(k) not in (None, "")
        }
        if values.get("bio"):
            fields["bio_public"] = values["bio"]
        if values.get("pay_rate") is not None:
            fields["pay_rate_amount"] = values["pay_rate"]
        return fields

    def _subjects(self, tutor: Any, values: dict[str, Any]) -> None:
        if not values.get("subjects"):
            return
        items = []
        for item in values["subjects"]:
            subject, _sep, level = str(item).partition(":")
            items.append({"subject": subject.strip(), "level": level.strip()})
        _people().set_tutor_subjects(tutor, items)

    def apply(self, values: dict[str, Any], ctx: Context) -> Outcome:
        people = _people()
        existing = self._existing(values, ctx)
        fields = self._fields(values)
        if existing is not None:
            out = Outcome(action="update", target_type="people.tutor", target_id=str(existing.pk))
            update_tracked(
                existing,
                {"first_name": values["first_name"], **fields},
                people.update_tutor,
                out.previous,
            )
            if values.get("status") and values["status"] != existing.status:
                out.previous.setdefault(f"people.tutor:{existing.pk}", {})["status"] = (
                    existing.status
                )
                people.change_tutor_status(existing, values["status"])
            self._subjects(existing, values)
            out.created += apply_tags("people.tutor", existing, values.get("tags"))
            out.created += self._tier(existing, values, ctx)
            return out
        tutor = people.create_tutor(
            email=values["email"],
            first_name=values["first_name"],
            invite=False,
            address=address_from(values),
            custom_fields=custom_values(values) or None,
            **fields,
        )
        out = Outcome(action="create", target_type="people.tutor", target_id=str(tutor.pk))
        out.created.append(ref(tutor))
        if values.get("status") and values["status"] != tutor.status:
            people.change_tutor_status(tutor, values["status"])
        self._subjects(tutor, values)
        if values.get("external_id"):
            out.created.append(refs.remember(ctx, "people.tutor", values["external_id"], tutor))
        out.created += apply_tags("people.tutor", tutor, values.get("tags"))
        out.created += self._tier(tutor, values, ctx)
        return out

    def _tier(self, tutor: Any, values: dict[str, Any], ctx: Context) -> list[dict[str, Any]]:
        """G6: the old system's wage tier becomes an E06 pay tier the tutor is on."""
        name = str(values.get("pay_tier") or "").strip()[:100]
        if not name:
            return []
        from tutortrack.catalogue import services as catalogue
        from tutortrack.catalogue.models import PayTier

        created = []
        tier = PayTier.objects.filter(name__iexact=name).first()
        if tier is None:
            tier = catalogue.save_pay_tier(None, name=name)
            created.append({"type": "catalogue.paytier", "id": str(tier.pk)})
        assignment = catalogue.assign_tier(tutor, tier, effective_from=ctx.cutover)
        created.append({"type": "catalogue.tutorpaytierassignment", "id": str(assignment.pk)})
        return created
