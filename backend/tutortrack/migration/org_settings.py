"""Import and export settings (E28)."""

from django.utils.translation import gettext_lazy as _

from tutortrack.tenancy.settings_registry import register

register(
    "migration.rollback_days",
    type="int",
    default=7,
    min_value=1,
    max_value=30,
    label=_("Days an import can still be rolled back"),
)
register(
    "migration.export_link_days",
    type="int",
    default=7,
    min_value=1,
    max_value=30,
    label=_("Days a full data export can be downloaded"),
)
register(
    "migration.series_min_lessons",
    type="int",
    default=3,
    min_value=2,
    max_value=20,
    label=_("Imported lessons repeating this many times weekly become a series"),
)
