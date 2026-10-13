"""The class catalogue on websites (E24 FR-24-3/4 with E20 FR-20-8): the embeddable
``<tt-class-catalogue>`` widget and the hosted-site ``class_catalogue`` block."""

from __future__ import annotations

from typing import Any

from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from tutortrack.sites import blocks, widgets


class ClassCatalogueOptions(serializers.Serializer):
    courses = serializers.ListField(child=serializers.UUIDField(), max_length=30, default=list)
    subject = serializers.CharField(max_length=100, required=False, allow_blank=True)
    show_prices = serializers.BooleanField(default=True)
    show_filters = serializers.BooleanField(default=True)


def _available() -> bool:
    from .models import Course

    return Course.objects.filter(is_public=True, archived_at__isnull=True).exists()


widgets.register(
    widgets.WidgetKind(
        "class_catalogue",
        _("Class catalogue"),
        "tt-class-catalogue",
        ClassCatalogueOptions,
        _("Your public courses and classes with places left, and online enrolment."),
        feature="courses",
        available=_available,
    )
)


class ClassCatalogueProps(serializers.Serializer):
    heading = serializers.CharField(max_length=150, required=False, allow_blank=True)
    subject = serializers.CharField(max_length=100, required=False, allow_blank=True)
    limit = serializers.IntegerField(min_value=1, max_value=48, default=12)


def _classes(props: dict[str, Any], org: Any) -> dict[str, Any]:
    from . import selectors

    rows = selectors.public_classes(subject=str(props.get("subject") or ""))
    return {"classes": [selectors.public_card(c) for c in rows[: int(props.get("limit", 12))]]}


blocks.register(
    blocks.BlockType("class_catalogue", _("Class catalogue"), ClassCatalogueProps, load=_classes)
)
