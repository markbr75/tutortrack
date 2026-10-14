"""The website booking widget ``<tt-booking>`` (E24 FR-24-3 on the E08-T14 engine) and the
hosted-site ``booking`` block (FR-24-4, gap G3)."""

from __future__ import annotations

from typing import Any

from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from tutortrack.sites import blocks, widgets


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


class BookingBlockProps(serializers.Serializer):
    heading = serializers.CharField(max_length=150, required=False, allow_blank=True)
    intro = serializers.CharField(max_length=300, required=False, allow_blank=True)
    days = serializers.IntegerField(min_value=1, max_value=31, default=7)


def _booking(props: dict[str, Any], org: Any) -> dict[str, Any]:
    """Live data for the block: whether booking is on and the services families can book
    (shown without JavaScript, and as the widget's fallback)."""
    from .services import bookable_services

    if not _enabled():
        return {"enabled": False, "services": []}
    return {
        "enabled": True,
        "services": [
            {"name": s.name, "duration_minutes": s.default_duration_minutes}
            for s in bookable_services()[:12]
        ],
    }


blocks.register(
    blocks.BlockType("booking", _("Online booking"), BookingBlockProps, load=_booking, widget=True)
)
