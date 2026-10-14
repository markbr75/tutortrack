"""Household self-service in the portal (gap batch G2):

* **Invite another guardian** (FR-15-8): a parent, guardian or carer of the household (or
  its primary or bill-paying contact) adds another adult and invites them to the portal. The
  inviter confirms the person has parental responsibility or their permission to see the
  children's details; the new contact gets no marketing; the invitation email goes through
  comms (``guardian_invite``) and staff see it on the record (``portal.guardian_invited``).
* **Guardian-managed logins** (FR-15-1): for a student under 13 (or with no date of birth),
  that guardian sets a username and a PIN or password; no email is needed. Parental consent
  (E29, ``parental-consent``) is recorded from the guardian's confirmation if it isn't on
  record, and ``privacy.children.require_login_allowed`` still decides. The guardian can
  change the PIN (which signs the student out everywhere) or remove the login.
"""

from __future__ import annotations

import re
from itertools import pairwise
from typing import Any

from django.db import transaction
from django.http import HttpRequest
from django.utils.translation import gettext as _

from tutortrack.core import audit
from tutortrack.core.context import require_organisation_id
from tutortrack.core.events import publish
from tutortrack.core.exceptions import BusinessRuleViolation, NotFound, PermissionDenied
from tutortrack.core.time import now
from tutortrack.people import services as people
from tutortrack.people.models import Client, Contact, Student
from tutortrack.tenancy.settings_service import get_setting

from .events import GuardianInvited, StudentLoginChanged
from .household import Household
from .models import StudentLogin

RESPONSIBLE = {
    Contact.Relationship.PARENT,
    Contact.Relationship.GUARDIAN,
    Contact.Relationship.CARER,
}
INVITABLE = {"parent", "guardian", "carer", "other"}
MANAGED_EMAIL_DOMAIN = "managed-students.invalid"
USERNAME = re.compile(r"^[a-z0-9][a-z0-9._-]{2,39}$")
LOGIN_AGE = 13


def _invalid(field_name: str, message: str) -> BusinessRuleViolation:
    return BusinessRuleViolation(message, extra={"errors": {field_name: [message]}})


def has_responsibility(contact: Contact) -> bool:
    return contact.relationship in RESPONSIBLE or contact.is_primary or contact.is_bill_payer


def guardian_for(household: Household, client_id: Any) -> Contact:
    """The signed-in person's contact on ``client_id`` if they may manage that household."""
    contact = next((c for c in household.contacts if str(c.client_id) == str(client_id)), None)
    if contact is None:
        raise NotFound()
    if not has_responsibility(contact):
        raise PermissionDenied(_("Only a parent, guardian or the main contact can do this."))
    return contact


# --- invite another guardian (FR-15-8) ------------------------------------------------------------


def _deliver(contact: Contact, inviter: Contact) -> Any:
    def send(invitation: Any, raw_token: str) -> None:
        from tutortrack.comms import services as comms

        payload = (str(contact.pk), raw_token, inviter.full_name)
        comms.notify_on_commit(
            "guardian_invite", payload, key=f"guardian-invite:{invitation.pk}:{now():%Y%m%d%H%M}"
        )

    return send


@transaction.atomic
def invite_guardian(
    household: Household,
    *,
    client_id: Any,
    first_name: str,
    last_name: str = "",
    email: str,
    relationship: str = "guardian",
    confirm: bool = False,
) -> Contact:
    from tutortrack.identity.models import Invitation, Membership
    from tutortrack.identity.services import invite

    if not get_setting("portal.allow_guardian_invites"):
        raise PermissionDenied(_("Inviting another guardian is turned off."))
    inviter = guardian_for(household, client_id)
    if not confirm:
        raise _invalid(
            "confirm",
            _(
                "Confirm that they have parental responsibility or your permission to see "
                "your children's details."
            ),
        )
    address = email.strip().lower()
    if not address or "@" not in address:
        raise _invalid("email", _("Enter their email address."))
    if not first_name.strip():
        raise _invalid("first_name", _("Enter their first name."))
    if relationship not in INVITABLE:
        raise _invalid("relationship", _("Choose how they are related."))
    client = Client.objects.get(pk=inviter.client_id)
    contact = client.contacts.filter(email__iexact=address, archived_at__isnull=True).first()
    if contact is not None and contact.user_id is not None:
        raise _invalid("email", _("They already have access to this household."))
    if Invitation.objects.filter(email=address, status=Invitation.Status.PENDING).exists():
        raise _invalid("email", _("They have already been invited."))
    if contact is None:
        contact = people.create_contact(
            client,
            first_name=first_name.strip()[:100],
            last_name=last_name.strip()[:100],
            email=address,
            relationship=relationship,
            receives_marketing=False,
        )
    invite(
        address,
        role=Membership.Role.CLIENT,
        target_type="people.contact",
        target_id=str(contact.pk),
        deliver=_deliver(contact, inviter),
    )
    audit.record(contact, "guardian_invited", {"invited_by": [None, inviter.full_name]})
    publish(
        GuardianInvited(
            subject_id=contact.pk, client_id=str(client.pk), invited_by=inviter.full_name
        )
    )
    return contact


def guardians(household: Household) -> list[dict[str, Any]]:
    """The adults on the household's records and whether they can sign in."""
    from tutortrack.identity.models import Invitation

    contacts = list(
        Contact.objects.filter(client__in=household.clients, archived_at__isnull=True).order_by(
            "first_name"
        )
    )
    pending = set(
        Invitation.objects.filter(
            target_type="people.contact",
            target_id__in=[str(c.pk) for c in contacts],
            status=Invitation.Status.PENDING,
        ).values_list("target_id", flat=True)
    )
    return [
        {
            "id": str(c.pk),
            "client_id": str(c.client_id),
            "name": c.full_name,
            "relationship": c.relationship,
            "portal": "active" if c.user_id else ("invited" if str(c.pk) in pending else "none"),
        }
        for c in contacts
    ]


# --- guardian-managed student logins (FR-15-1) ----------------------------------------------------


def eligible(student: Student) -> bool:
    """Under 13 (an unknown date of birth counts as a child)."""
    from tutortrack.privacy.children import student_age

    age = student_age(student)
    return age is None or age < LOGIN_AGE


def _check_pin(pin: str) -> None:
    if len(pin) < 6 or len(pin) > 64:
        raise _invalid("pin", _("Use at least 6 characters (or a 6-digit PIN)."))
    if pin.isdigit():
        digits = [int(d) for d in pin]
        steps = {b - a for a, b in pairwise(digits)}
        if len(set(digits)) == 1 or steps in ({1}, {-1}):
            raise _invalid("pin", _("That PIN is too easy to guess."))


def managed_email(username: str) -> str:
    return f"{username}.{require_organisation_id().hex[:12]}@{MANAGED_EMAIL_DOMAIN}"


def _student(household: Household, student_id: Any) -> Student:
    student = next((s for s in household.students if str(s.pk) == str(student_id)), None)
    if student is None:
        raise NotFound()
    guardian_for(household, student.client_id)
    return student


def logins(household: Household) -> list[dict[str, Any]]:
    by_student = {
        str(login.student_id): login
        for login in StudentLogin.objects.filter(student__in=household.students)
    }
    return [
        {
            "student_id": str(s.pk),
            "student_name": s.full_name,
            "eligible": eligible(s),
            "has_email_login": s.user_id is not None and str(s.pk) not in by_student,
            "username": by_student[str(s.pk)].username if str(s.pk) in by_student else "",
            "pin_changed_at": (
                by_student[str(s.pk)].pin_changed_at if str(s.pk) in by_student else None
            ),
        }
        for s in household.students
    ]


@transaction.atomic
def create_login(
    household: Household,
    *,
    user: Any,
    student_id: Any,
    username: str,
    pin: str,
    parental_consent: bool = False,
) -> StudentLogin:
    from tutortrack.identity.models import Membership, User
    from tutortrack.identity.services import add_member
    from tutortrack.privacy import services as privacy
    from tutortrack.privacy.children import (
        PARENTAL_CONSENT,
        ParentalConsentRequired,
        has_parental_consent,
        require_login_allowed,
    )

    if not get_setting("portal.guardian_managed_logins"):
        raise PermissionDenied(_("Student logins are turned off."))
    student = _student(household, student_id)
    if not eligible(student):
        raise BusinessRuleViolation(
            _("Students aged 13 or over sign in with their own email: ask us to invite them.")
        )
    if student.user_id is not None:
        raise BusinessRuleViolation(_("This student already has a login."))
    name = username.strip().lower()
    if not USERNAME.match(name):
        raise _invalid(
            "username", _("Use 3 to 40 lower-case letters, numbers, dots, dashes or underscores.")
        )
    if StudentLogin.objects.filter(username=name).exists():
        raise _invalid("username", _("That username is taken."))
    _check_pin(pin)
    if not has_parental_consent(student):
        if not parental_consent:
            raise ParentalConsentRequired(
                _("As their parent or guardian, confirm that you consent to this login."),
                extra={"code": "parental_consent_required"},
            )
        privacy.record_consent(
            subject_type="people.student",
            subject_id=str(student.pk),
            key=PARENTAL_CONSENT,
            granted=True,
            method="portal",
            given_by=user,
            on_behalf_of_child=True,
        )
    require_login_allowed(student)

    email = managed_email(name)
    login_user = User.objects.filter(email=email).first()
    if login_user is None:
        login_user = User.objects.create_user(
            email, None, first_name=student.first_name, last_name=student.last_name
        )
    login_user.set_password(pin)  # a PIN can't meet the password rules; lockout guards it
    login_user.is_active = True
    login_user.save(update_fields=["password", "is_active"])
    membership = Membership.objects.filter(user=login_user).first()
    if membership is None:
        add_member(login_user, role=Membership.Role.STUDENT)
    else:
        Membership.objects.filter(pk=membership.pk).update(
            status=Membership.Status.ACTIVE, role=Membership.Role.STUDENT
        )
    people.link_portal_user("people.student", str(student.pk), login_user)
    login = StudentLogin.objects.create(
        student=student, user=login_user, username=name, managed_by=user, pin_changed_at=now()
    )
    audit.record_create(login)
    publish(StudentLoginChanged(subject_id=student.pk, action="created"))
    return login


def _login(household: Household, student_id: Any) -> StudentLogin:
    student = _student(household, student_id)
    login = StudentLogin.objects.select_related("user").filter(student=student).first()
    if login is None:
        raise NotFound()
    return login


@transaction.atomic
def change_pin(household: Household, *, student_id: Any, pin: str) -> StudentLogin:
    from tutortrack.identity.auth import revoke_all_sessions

    login = _login(household, student_id)
    _check_pin(pin)
    login.user.set_password(pin)
    login.user.save(update_fields=["password"])
    revoke_all_sessions(login.user)
    with audit.track(login, action="change_pin"):
        login.pin_changed_at = now()
        login.save(update_fields=["pin_changed_at", "updated_at"])
    publish(StudentLoginChanged(subject_id=login.student_id, action="pin_changed"))
    return login


@transaction.atomic
def remove_login(household: Household, *, student_id: Any) -> None:
    from tutortrack.identity.auth import revoke_all_sessions
    from tutortrack.identity.models import Membership
    from tutortrack.identity.services import remove_member

    login = _login(household, student_id)
    user = login.user
    membership = Membership.objects.filter(user=user, status=Membership.Status.ACTIVE).first()
    if membership is not None:
        remove_member(membership)
    revoke_all_sessions(user)
    user.is_active = False
    user.set_unusable_password()
    user.save(update_fields=["is_active", "password"])
    people.unlink_portal_user("people.student", str(login.student_id))
    audit.record(login, "delete")
    student_id = login.student_id
    login.delete()
    publish(StudentLoginChanged(subject_id=student_id, action="removed"))


def sign_in(request: HttpRequest, username: str, pin: str) -> Any:
    """Username + PIN sign-in on the organisation's address (lockout as for passwords)."""
    from django.contrib.auth.hashers import make_password

    from tutortrack.identity import auth

    email = managed_email(username.strip().lower()[:40])
    auth._check_lockout(email)
    login = StudentLogin.objects.select_related("user").filter(username=username.strip().lower())
    found = login.first()
    user = found.user if found is not None else None
    if user is None or not user.is_active or not user.check_password(pin):
        if user is None:
            make_password(pin)  # equalise timing
        auth._record(
            request, email, "student_pin", user=user, success=False, reason="bad_credentials"
        )
        raise auth.AuthenticationFailed(_("That username and PIN don't match."))
    return auth.complete_login(request, user, method="student_pin")
