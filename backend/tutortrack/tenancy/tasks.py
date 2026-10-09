from __future__ import annotations

from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils import translation
from django.utils.translation import gettext as _


def send_closure_notice(*, organisation_id: str) -> None:
    """Tell the owners their account is closed and when the data will be deleted."""
    from datetime import timedelta

    from tutortrack.core.context import tenant_context
    from tutortrack.identity.models import Membership

    from .closure import GRACE_SETTING
    from .models import Organisation
    from .settings_service import get_setting

    org = Organisation.objects.get(pk=organisation_id)
    with tenant_context(org):
        emails = list(
            Membership.objects.filter(role=Membership.Role.OWNER).values_list(
                "user__email", flat=True
            )
        )
        days = int(get_setting(GRACE_SETTING))
    if not emails:
        return
    deletion = (org.closed_at or org.updated_at) + timedelta(days=days)
    with translation.override(org.locale):
        send_mail(
            subject=_("Your TutorTrack account has been closed"),
            message=render_to_string(
                "tenancy/email/closure_notice.txt",
                {"organisation": org, "days": days, "deletion_date": deletion.date()},
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=emails,
        )
