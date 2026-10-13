"""The website booking widget ``<tt-booking>`` (E24 FR-24-3 on the E08-T14 engine)."""

from __future__ import annotations

from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from tutortrack.sites import widgets


class BookingOptions(serializers.Serializer):
    services = serializers.ListField(child=serializers.UUIDField(), max_length=30, default=list)
    tutor = serializers.UUIDField(required=False, allow_null=True)
    show_prices = serializers.BooleanField(default=True)
    days = serializers.IntegerField(min_value=1, max_value=31, default=7)


def _enabled() -> bool:
    from .models import BookingSettings

    found = BookingSettings.objects.first()
    return bool(found and found.enabled)


widgets.register(
    widgets.WidgetKind(
        "booking",
        _("Online booking"),
        "tt-booking",
        BookingOptions,
        _("Families pick a service, tutor and free time, and book (and pay) online."),
        available=_enabled,
    )
)
