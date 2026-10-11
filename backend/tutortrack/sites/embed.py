"""Embed codes for widgets and the website's address (FR-24-3, FR-24-6)."""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.utils.html import escape

from . import widgets
from .models import WidgetConfig


def script_tag(organisation: Any) -> str:
    src = escape(str(settings.WIDGETS_SCRIPT_URL))
    slug = escape(organisation.slug) if organisation is not None else ""
    api = escape(organisation.base_url) if organisation is not None else ""
    return f'<script type="module" src="{src}" data-org="{slug}" data-api="{api}"></script>'


def snippet(widget: WidgetConfig, organisation: Any) -> str:
    kind = widgets.get(widget.kind)
    element = kind.element if kind else "tt-widget"
    extra = ""
    if widget.kind == "enquiry_form" and widget.options.get("form"):
        extra = f' form="{escape(widget.options["form"])}"'
    return (
        f'{script_tag(organisation)}\n<{element} widget="{escape(widget.key)}"{extra}></{element}>'
    )


def shortcode(widget: WidgetConfig) -> str:
    """For the WordPress plugin (``[tutortrack widget="w-..."]``)."""
    return f'[tutortrack widget="{widget.key}" type="{widget.kind}"]'


def site_url(organisation: Any) -> str:
    if organisation is None:
        return ""
    from tutortrack.tenancy.models import OrganisationDomain

    custom = (
        OrganisationDomain.objects.filter(
            organisation_id=organisation.pk,
            type=OrganisationDomain.Type.CUSTOM,
            purpose=OrganisationDomain.Purpose.SITE,
            verified_at__isnull=False,
        )
        .values_list("hostname", flat=True)
        .first()
    )
    if custom:
        return f"https://{custom}"
    base = getattr(settings, "CUSTOM_DOMAINS", {}).get("SITE_BASE_DOMAIN", "")
    return f"https://{organisation.slug}.{base}" if base else ""
