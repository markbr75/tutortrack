"""Website and directory settings (E24)."""

from django.utils.translation import gettext_lazy as _

from tutortrack.tenancy.settings_registry import register

register(
    "sites.profile_approval_required",
    type="bool",
    default=True,
    label=_("Tutors' public profile changes need staff approval"),
)
register(
    "sites.profile_contact_filter",
    type="bool",
    default=True,
    label=_("Block contact details and links in tutors' public profiles"),
)
register(
    "sites.directory_show_location",
    type="bool",
    default=True,
    label=_("Show tutors' town or area in the public directory"),
)
