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
