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

# --- Phase 2: broadcasts and the inbox (E13-T10/T11) ---------------------------------------------
register(
    "comms.broadcast_batch_size",
    type="int",
    default=200,
    min_value=1,
    max_value=5000,
    label=_("Broadcasts: messages per batch"),
)
register(
    "comms.broadcast_batch_pause_seconds",
    type="int",
    default=60,
    min_value=0,
    max_value=3600,
    label=_("Broadcasts: seconds between batches"),
)
register(
    "comms.inbox_sla_hours",
    type="int",
    default=24,
    min_value=1,
    max_value=24 * 14,
    label=_("Inbox: reply within (hours)"),
)
register(
    "comms.block_contact_sharing",
    type="bool",
    default=False,
    label=_("Stop tutors and families sharing email addresses or phone numbers in messages"),
)
