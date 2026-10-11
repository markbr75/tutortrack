"""Embeddable widget kinds (FR-24-3).

Each kind names its custom element, validates its options and says when it is available.
``WidgetConfig`` rows are instances. Register more kinds from other apps, e.g. E08's
self-booking (``booking`` → ``<tt-booking>``) and E20's course catalogue
(``class_catalogue`` → ``<tt-class-catalogue>``)::

    from tutortrack.sites import widgets

    widgets.register(widgets.WidgetKind("booking", _("Booking"), "tt-booking", BookingOptions))
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from django.utils.functional import Promise
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy as _l
from rest_framework import serializers

from tutortrack.core import entitlements


class TutorDirectoryOptions(serializers.Serializer):
    subjects = serializers.ListField(
        child=serializers.CharField(max_length=100), max_length=30, default=list
    )
    page_size = serializers.IntegerField(min_value=3, max_value=48, default=12)
    show_filters = serializers.BooleanField(default=True)
    enquiry_form = serializers.SlugField(max_length=80, required=False, allow_blank=True)


class EnquiryFormOptions(serializers.Serializer):
    form = serializers.SlugField(max_length=80)

    def validate_form(self, value: str) -> str:
        from tutortrack.leads.models import Form

        if not Form.objects.filter(slug=value, published=True).exists():
            raise serializers.ValidationError(_("Choose a published enquiry form."))
        return value


class ServicesOptions(serializers.Serializer):
    services = serializers.ListField(child=serializers.UUIDField(), max_length=30, default=list)
    show_prices = serializers.BooleanField(default=False)


class ReviewsOptions(serializers.Serializer):
    limit = serializers.IntegerField(min_value=1, max_value=24, default=6)
    min_rating = serializers.IntegerField(min_value=1, max_value=5, required=False)


class LoginOptions(serializers.Serializer):
    portal = serializers.ChoiceField(choices=["client", "tutor", "staff"], default="client")
    button_text = serializers.CharField(max_length=40, required=False, allow_blank=True)


class NoOptions(serializers.Serializer):
    pass


@dataclass(frozen=True)
class WidgetKind:
    key: str
    label: str | Promise
    element: str
    options: type[serializers.Serializer]
    description: str | Promise = ""
    feature: str = ""  # entitlement needed, if any
    available: Callable[[], bool] | None = None

    def is_available(self) -> bool:
        if self.feature and not entitlements.has(self.feature):
            return False
        return self.available() if self.available else True


_registry: dict[str, WidgetKind] = {}


def register(kind: WidgetKind) -> WidgetKind:
    _registry[kind.key] = kind
    return kind


def get(key: str) -> WidgetKind | None:
    return _registry.get(key)


def kinds() -> list[WidgetKind]:
    return list(_registry.values())


def clean_options(kind: WidgetKind, raw: Any) -> dict[str, Any]:
    payload = kind.options(data=raw or {})
    payload.is_valid(raise_exception=True)
    from .blocks import _json_safe

    return dict(_json_safe(dict(payload.validated_data)))


register(
    WidgetKind(
        "tutor_directory",
        _l("Tutor directory"),
        "tt-tutor-directory",
        TutorDirectoryOptions,
        _l("Searchable tutor profiles with subject and online filters, and an enquiry button."),
    )
)
register(
    WidgetKind(
        "enquiry_form",
        _l("Enquiry form"),
        "tt-enquiry-form",
        EnquiryFormOptions,
        _l("One of your enquiry forms; new enquiries go straight into your pipeline."),
    )
)
register(
    WidgetKind(
        "services",
        _l("Services and prices"),
        "tt-services",
        ServicesOptions,
        _l("What you teach, with prices if you choose to show them."),
    )
)
register(
    WidgetKind(
        "reviews",
        _l("Reviews"),
        "tt-reviews",
        ReviewsOptions,
        _l("Testimonials from families and students."),
    )
)
register(
    WidgetKind(
        "login",
        _l("Portal login"),
        "tt-login",
        LoginOptions,
        _l("A button that takes families or tutors to your portal."),
    )
)
register(
    WidgetKind(
        "job_openings",
        _l("Tutor vacancies"),
        "tt-job-openings",
        NoOptions,
        _l("Your open tutor vacancies with links to apply."),
        feature="recruitment",
    )
)
