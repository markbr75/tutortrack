from __future__ import annotations

from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils import translation
from django.utils.translation import gettext as _

from .models import User
from .tokens import email_verification_token


@shared_task(name="tutortrack.identity.tasks.send_verification_email", ignore_result=True)
def send_verification_email(*, user_id: str) -> None:
    """Platform email (no tenant). E13 moves this onto the comms templates."""
    user = User.objects.filter(pk=user_id, email_verified_at__isnull=True).first()
    if user is None:
        return
    with translation.override(user.locale):
        url = f"{settings.APP_URL}/verify-email?token={email_verification_token(user)}"
        context = {"user": user, "url": url}
        send_mail(
            subject=_("Confirm your email address"),
            message=render_to_string("identity/email/verify_email.txt", context),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
        )


def _send(user: User, subject: str, template: str, context: dict[str, object]) -> None:
    with translation.override(user.locale):
        send_mail(
            subject=subject,
            message=render_to_string(template, {"user": user, **context}),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
        )


@shared_task(name="tutortrack.identity.tasks.send_magic_link", ignore_result=True)
def send_magic_link(*, user_id: str, url: str) -> None:
    user = User.objects.filter(pk=user_id, is_active=True).first()
    if user is not None:
        with translation.override(user.locale):
            _send(user, _("Your sign-in link"), "identity/email/magic_link.txt", {"url": url})


@shared_task(name="tutortrack.identity.tasks.send_password_reset", ignore_result=True)
def send_password_reset(*, user_id: str, url: str) -> None:
    user = User.objects.filter(pk=user_id, is_active=True).first()
    if user is not None:
        with translation.override(user.locale):
            _send(user, _("Reset your password"), "identity/email/password_reset.txt", {"url": url})


@shared_task(name="tutortrack.identity.tasks.send_new_device_alert", ignore_result=True)
def send_new_device_alert(*, user_id: str, ip: str, user_agent: str) -> None:
    user = User.objects.filter(pk=user_id, is_active=True).first()
    if user is not None:
        with translation.override(user.locale):
            _send(
                user,
                _("New sign-in to your TutorTrack account"),
                "identity/email/new_device.txt",
                {"ip": ip, "user_agent": user_agent},
            )


@shared_task(name="tutortrack.identity.tasks.send_invitation", ignore_result=True)
def send_invitation(
    *, email: str, organisation_name: str, inviter: str, url: str, locale: str
) -> None:
    with translation.override(locale):
        send_mail(
            subject=_("You're invited to join %(org)s on TutorTrack") % {"org": organisation_name},
            message=render_to_string(
                "identity/email/invitation.txt",
                {"organisation_name": organisation_name, "inviter": inviter, "url": url},
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[email],
        )


@shared_task(name="tutortrack.identity.tasks.send_security_alert", ignore_result=True)
def send_security_alert(*, email: str, kind: str, detail: str, who: str) -> None:
    send_mail(
        subject=_("Security alert on your TutorTrack account"),
        message=render_to_string(
            "identity/email/security_alert.txt", {"kind": kind, "detail": detail, "who": who}
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[email],
    )
