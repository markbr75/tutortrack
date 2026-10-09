"""Communication settings (FR-13-1, FR-13-4)."""

from django.utils.translation import gettext_lazy as _

from tutortrack.tenancy.settings_registry import register

register(
    "comms.sender_name",
    type="str",
    default="",
    max_length=100,
    label=_("Name emails come from (blank: the organisation name)"),
)
register(
    "comms.reply_to",
    type="str",
    default="",
    max_length=254,
    label=_("Replies go to this email address"),
)
register(
    "comms.quiet_hours_start",
    type="str",
    default="21:00",
    max_length=5,
    label=_("No text messages after (HH:MM)"),
)
register(
    "comms.quiet_hours_end",
    type="str",
    default="08:00",
    max_length=5,
    label=_("No text messages before (HH:MM)"),
)
