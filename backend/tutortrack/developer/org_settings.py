"""Developer platform settings (E27)."""

from django.utils.translation import gettext_lazy as _

from tutortrack.tenancy.settings_registry import register

register(
    "developer.api_key_rotation_overlap_hours",
    type="int",
    default=24,
    min_value=0,
    max_value=24 * 30,
    label=_("Hours an old API key keeps working after it is rotated"),
)
register(
    "developer.sandbox_of",
    type="str",
    default="",
    max_length=36,
    label=_("The live organisation this sandbox was copied from (set automatically)"),
)
