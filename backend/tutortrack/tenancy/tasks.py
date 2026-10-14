from __future__ import annotations

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
    from tutortrack.comms import account_emails

    with translation.override(org.locale):
        subject = _("Your TutorTrack account has been closed")
    # G4: on the organisation's (editable) account template, with its branding.
    for email in emails:
        account_emails.send(
            "account_closure_notice",
            to=email,
            subject=subject,
            django_template="tenancy/email/closure_notice.txt",
            legacy={"organisation": org, "days": days, "deletion_date": deletion.date()},
            variables={"closure": {"days": days, "deletion_date": deletion.date()}},
            locale=org.locale,
            organisation_id=str(org.pk),
            recipient=("owner", ""),
        )
