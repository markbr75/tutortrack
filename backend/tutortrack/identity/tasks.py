"""Account emails (E03). G4: they are sent through ``comms.account_emails``: inside an
organisation they use its branding and its edited template (when there is one) and are
logged without their secret links; with no organisation they use the platform template.

Every task takes an optional ``organisation_id``: the organisation the request was made
in, captured by the caller when it queued the task (``current_org()``)."""

from __future__ import annotations

from typing import Any

from celery import shared_task
from django.utils import translation
from django.utils.translation import gettext as _

from .models import User
from .tokens import email_verification_token


def current_org() -> str | None:
    """The organisation in context, as a task argument (None on the platform host)."""
    from tutortrack.core.context import current_organisation_id

    org = current_organisation_id()
    return str(org) if org else None


def _send(
    type_key: str,
    user: User,
    *,
    to: str = "",
    subject: Any,
    template: str,
    legacy: dict[str, Any],
    variables: dict[str, Any],
    organisation_id: str | None,
    secrets: tuple[str, ...] = (),
) -> None:
    from tutortrack.comms import account_emails

    account_emails.send(
        type_key,
        to=to or user.email,
        subject=subject,
        django_template=template,
        legacy={"user": user, **legacy},
        variables=variables,
        first_name=user.get_short_name() or user.first_name,
        locale=user.locale,
        organisation_id=organisation_id,
        secrets=secrets,
        recipient=("user", str(user.pk)),
    )


@shared_task(name="tutortrack.identity.tasks.send_verification_email", ignore_result=True)
def send_verification_email(*, user_id: str, organisation_id: str | None = None) -> None:
    user = User.objects.filter(pk=user_id, email_verified_at__isnull=True).first()
    if user is None:
        return
    from django.conf import settings

    url = f"{settings.APP_URL}/verify-email?token={email_verification_token(user)}"
    with translation.override(user.locale):
        subject = _("Confirm your email address")
    _send(
        "account_verify_email",
        user,
        subject=subject,
        template="identity/email/verify_email.txt",
        legacy={"url": url},
        variables={"link": url},
        organisation_id=organisation_id,
        secrets=(url,),
    )


@shared_task(name="tutortrack.identity.tasks.send_magic_link", ignore_result=True)
def send_magic_link(*, user_id: str, url: str, organisation_id: str | None = None) -> None:
    user = User.objects.filter(pk=user_id, is_active=True).first()
    if user is None:
        return
    with translation.override(user.locale):
        subject = _("Your sign-in link")
    _send(
        "account_magic_link",
        user,
        subject=subject,
        template="identity/email/magic_link.txt",
        legacy={"url": url},
        variables={"link": url},
        organisation_id=organisation_id,
        secrets=(url,),
    )


@shared_task(name="tutortrack.identity.tasks.send_password_reset", ignore_result=True)
def send_password_reset(*, user_id: str, url: str, organisation_id: str | None = None) -> None:
    user = User.objects.filter(pk=user_id, is_active=True).first()
    if user is None:
        return
    with translation.override(user.locale):
        subject = _("Reset your password")
    _send(
        "account_password_reset",
        user,
        subject=subject,
        template="identity/email/password_reset.txt",
        legacy={"url": url},
        variables={"link": url},
        organisation_id=organisation_id,
        secrets=(url,),
    )


@shared_task(name="tutortrack.identity.tasks.send_new_device_alert", ignore_result=True)
def send_new_device_alert(
    *, user_id: str, ip: str, user_agent: str, organisation_id: str | None = None
) -> None:
    user = User.objects.filter(pk=user_id, is_active=True).first()
    if user is None:
        return
    with translation.override(user.locale):
        subject = _("New sign-in to your TutorTrack account")
    _send(
        "account_new_device",
        user,
        subject=subject,
        template="identity/email/new_device.txt",
        legacy={"ip": ip, "user_agent": user_agent},
        variables={"device": {"ip": ip, "user_agent": user_agent}},
        organisation_id=organisation_id,
    )


@shared_task(name="tutortrack.identity.tasks.send_impossible_travel_alert", ignore_result=True)
def send_impossible_travel_alert(
    *,
    user_id: str,
    ip: str,
    previous_country: str,
    country: str,
    organisation_id: str | None = None,
) -> None:
    user = User.objects.filter(pk=user_id, is_active=True).first()
    if user is None:
        return
    with translation.override(user.locale):
        subject = _("Sign-in from a new country on your TutorTrack account")
    legacy = {"ip": ip, "previous_country": previous_country, "country": country}
    _send(
        "account_impossible_travel",
        user,
        subject=subject,
        template="identity/email/impossible_travel.txt",
        legacy=legacy,
        variables={"travel": legacy},
        organisation_id=organisation_id,
    )


@shared_task(name="tutortrack.identity.tasks.send_invitation", ignore_result=True)
def send_invitation(
    *,
    email: str,
    organisation_name: str,
    inviter: str,
    url: str,
    locale: str,
    organisation_id: str | None = None,
) -> None:
    from tutortrack.comms import account_emails

    with translation.override(locale):
        subject = _("You're invited to join %(org)s on TutorTrack") % {"org": organisation_name}
    account_emails.send(
        "account_invitation",
        to=email,
        subject=subject,
        django_template="identity/email/invitation.txt",
        legacy={"organisation_name": organisation_name, "inviter": inviter, "url": url},
        variables={"link": url, "invite": {"inviter": inviter, "organisation": organisation_name}},
        locale=locale,
        organisation_id=organisation_id,
        secrets=(url,),
        recipient=("invitee", ""),
    )


@shared_task(name="tutortrack.identity.tasks.send_security_alert", ignore_result=True)
def send_security_alert(
    *, email: str, kind: str, detail: str, who: str, organisation_id: str | None = None
) -> None:
    from tutortrack.comms import account_emails

    user = User.objects.filter(email=email).first()
    legacy = {"kind": kind, "detail": detail, "who": who}
    account_emails.send(
        "account_security_alert",
        to=email,
        subject=_("Security alert on your TutorTrack account"),
        django_template="identity/email/security_alert.txt",
        legacy=legacy,
        variables={"alert": legacy},
        first_name=user.get_short_name() if user else "",
        locale=user.locale if user else "en-GB",
        organisation_id=organisation_id,
        recipient=("user", str(user.pk) if user else ""),
    )


@shared_task(name="tutortrack.identity.tasks.send_email_change_verification", ignore_result=True)
def send_email_change_verification(
    *, user_id: str, email: str, url: str, organisation_id: str | None = None
) -> None:
    """The confirmation link goes to the *new* address (FR-03-9)."""
    user = User.objects.filter(pk=user_id, is_active=True).first()
    if user is None:
        return
    with translation.override(user.locale):
        subject = _("Confirm your new email address")
    _send(
        "account_email_change_verify",
        user,
        to=email,
        subject=subject,
        template="identity/email/email_change_verify.txt",
        legacy={"url": url},
        variables={"link": url},
        organisation_id=organisation_id,
        secrets=(url,),
    )


@shared_task(name="tutortrack.identity.tasks.send_email_change_notice", ignore_result=True)
def send_email_change_notice(
    *, email: str, new_email: str, done: bool, organisation_id: str | None = None
) -> None:
    """Tell the *old* address that a change was asked for (or made)."""
    from tutortrack.comms import account_emails

    user = User.objects.filter(email__in=[email, new_email]).first()
    subject = (
        _("Your TutorTrack email address has changed")
        if done
        else _("A change of email address was requested")
    )
    account_emails.send(
        "account_email_change_notice",
        to=email,
        subject=subject,
        django_template="identity/email/email_change_notice.txt",
        legacy={"new_email": new_email, "done": done},
        variables={"email": {"new": new_email, "done": done}},
        first_name=user.get_short_name() if user else "",
        locale=user.locale if user else "en-GB",
        organisation_id=organisation_id,
        recipient=("user", str(user.pk) if user else ""),
    )
