"""Online lesson settings added in E22-T10 (attendance, recordings, classroom). The E22
Phase 2 settings stay in ``integrations.org_settings``."""

from django.utils.translation import gettext_lazy as _

from tutortrack.tenancy.settings_registry import register

register(
    "integrations.video_attendance",
    type="bool",
    default=True,
    label=_("Suggest the register from who joined the online lesson"),
)
register(
    "integrations.recording_requires_consent",
    type="bool",
    default=True,
    label=_("Restrict recordings until every student has agreed to recording"),
    help_text=_("Restricted recordings are hidden from tutors and families until released."),
)
register(
    "integrations.classroom_recording",
    type="bool",
    default=False,
    label=_("Record lessons in the built-in classroom"),
)
register(
    "integrations.classroom_banner",
    type="str",
    default="",
    label=_("Safeguarding message shown in the online classroom"),
)
