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

# --- G4: digests and students (FR-13-2/5/7) ------------------------------------------------------
register(
    "comms.digest_agenda_time",
    type="str",
    default="07:00",
    max_length=5,
    label=_("Tutors' daily agenda arrives at (HH:MM, their time)"),
)
register(
    "comms.digest_weekly_day",
    type="choice",
    default="6",
    choices=(
        ("0", _("Monday")),
        ("1", _("Tuesday")),
        ("2", _("Wednesday")),
        ("3", _("Thursday")),
        ("4", _("Friday")),
        ("5", _("Saturday")),
        ("6", _("Sunday")),
    ),
    label=_("Families' weekly schedule arrives on"),
)
register(
    "comms.digest_weekly_time",
    type="str",
    default="18:00",
    max_length=5,
    label=_("Families' weekly schedule arrives at (HH:MM)"),
)
register(
    "comms.digest_messages_time",
    type="str",
    default="17:00",
    max_length=5,
    label=_("The daily digest of unread messages arrives at (HH:MM)"),
)
register(
    "comms.student_direct",
    type="choice",
    default="off",
    choices=(
        ("off", _("No: only their parents or guardians")),
        ("adults", _("Adult learners (18 and over)")),
        ("teens", _("Students aged 13 and over (never marketing to under-18s)")),
    ),
    label=_("Students get lesson messages themselves"),
)
register(
    "comms.low_attendance_percent",
    type="int",
    default=75,
    min_value=0,
    max_value=100,
    label=_("Alert when a student attends less than this % of their last lessons (0: off)"),
)
register(
    "comms.low_attendance_lessons",
    type="int",
    default=6,
    min_value=2,
    max_value=50,
    label=_("Low attendance: how many recent lessons to look at"),
)
