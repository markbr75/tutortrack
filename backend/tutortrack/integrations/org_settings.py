"""Integration settings (FR-22-1, FR-22-4). Served at ``/api/v1/settings/integrations``."""

from typing import Any

from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from tutortrack.tenancy.settings_registry import register

VIDEO_CHOICES = (
    ("none", _("No online meeting")),
    ("builtin", _("Built-in room (no tutor account needed)")),
    ("zoom", _("Zoom")),
    ("teams", _("Microsoft Teams")),
    ("google_meet", _("Google Meet")),
    ("lessonspace", _("Lessonspace")),
)
VIDEO_KEYS = {key for key, _label in VIDEO_CHOICES}


def _by_service(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        raise serializers.ValidationError(_("Map service ids to video providers."))
    bad = [v for v in value.values() if v not in VIDEO_KEYS]
    if bad:
        raise serializers.ValidationError(_("Unknown video provider."))
    return {str(k): str(v) for k, v in value.items()}


register(
    "integrations.video_provider",
    type="choice",
    default="builtin",
    choices=VIDEO_CHOICES,
    label=_("Default video provider for online lessons"),
    help_text=_("Jobs and tutors can choose their own; this is the fallback."),
)
register(
    "integrations.video_provider_by_service",
    type="object",
    default={},
    label=_("Video provider per service"),
    schema={"type": "object", "additionalProperties": {"type": "string"}},
    validator=_by_service,
)
register(
    "integrations.auto_create_meetings",
    type="bool",
    default=True,
    label=_("Create a meeting room automatically for online lessons"),
)
register(
    "integrations.join_window_minutes",
    type="int",
    default=10,
    min_value=0,
    max_value=120,
    label=_("Join buttons open this many minutes before the lesson"),
)
register(
    "integrations.zoom_waiting_room",
    type="bool",
    default=True,
    label=_("Zoom: use a waiting room"),
)
register(
    "integrations.zoom_passcode",
    type="bool",
    default=True,
    label=_("Zoom: require a passcode"),
)
register(
    "integrations.zoom_recording",
    type="choice",
    default="none",
    choices=(
        ("none", _("Don't record")),
        ("local", _("On the tutor's computer")),
        ("cloud", _("In the cloud")),
    ),
    label=_("Zoom: record lessons"),
    help_text=_("Make sure families have agreed to recording (safeguarding)."),
)
register(
    "integrations.lessonspace_space_per",
    type="choice",
    default="job",
    choices=(("job", _("One space per job")), ("lesson", _("One space per lesson"))),
    label=_("Lessonspace: reuse a space for all of a job's lessons"),
)
register(
    "integrations.calendar_title_format",
    type="str",
    default="{service} \N{EN DASH} {students}",
    max_length=120,
    label=_("Title of lessons in tutors' calendars"),
    help_text=_("Placeholders: {title}, {service}, {students}, {student_initials}, {tutors}."),
)
register(
    "integrations.calendar_details",
    type="bool",
    default=False,
    label=_("Include lesson notes for the tutor in calendar events"),
    help_text=_("Off by default: calendars are often shared, so events carry no notes."),
)
register(
    "integrations.calendar_two_way",
    type="bool",
    default=True,
    label=_("Let tutors turn on two-way calendar sync"),
    help_text=_("Moving a lesson in Google or Outlook then proposes a reschedule."),
)
