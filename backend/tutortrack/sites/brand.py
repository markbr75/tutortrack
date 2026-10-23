"""Brand resolution, colour contrast and the ``core.branding`` provider (E24 FR-24-1).

The effective brand merges, in order: platform defaults → ``Organisation`` (name, logo,
primary colour) → the organisation ``BrandKit`` → the branch ``BrandKit``. Colours are never
rejected; instead we compute AA-safe variants (``on_primary`` for text on the brand colour,
``link_colour`` for brand-coloured text on white) and report the contrast so the editor can
warn. Every surface uses the safe variants, so output stays WCAG 2.2 AA.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

import structlog
from django.utils.translation import gettext as _

from tutortrack.core import entitlements
from tutortrack.core.branding import DEFAULT_PRIMARY, DEFAULT_TEXT
from tutortrack.core.context import tenant_context

logger = structlog.get_logger(__name__)

WHITE = "#ffffff"
SECONDARY_DEFAULT = "#0f172a"
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
AA = 4.5
AA_LARGE = 3.0
LOGO_INLINE_LIMIT = 300 * 1024

# Curated Google Fonts (FR-24-1): name → CSS family stack.
FONTS: dict[str, str] = {
    "Inter": "'Inter', system-ui, sans-serif",
    "Roboto": "'Roboto', system-ui, sans-serif",
    "Open Sans": "'Open Sans', system-ui, sans-serif",
    "Lato": "'Lato', system-ui, sans-serif",
    "Montserrat": "'Montserrat', system-ui, sans-serif",
    "Poppins": "'Poppins', system-ui, sans-serif",
    "Nunito": "'Nunito', system-ui, sans-serif",
    "Source Sans 3": "'Source Sans 3', system-ui, sans-serif",
    "Work Sans": "'Work Sans', system-ui, sans-serif",
    "Raleway": "'Raleway', system-ui, sans-serif",
    "Merriweather": "'Merriweather', Georgia, serif",
    "Playfair Display": "'Playfair Display', Georgia, serif",
    "Lora": "'Lora', Georgia, serif",
}
SOCIAL_NETWORKS = ("facebook", "instagram", "x", "linkedin", "youtube", "tiktok")


def font_css_url(font: str) -> str:
    if font not in FONTS:
        return ""
    family = font.replace(" ", "+")
    return f"https://fonts.googleapis.com/css2?family={family}:wght@400;600;700&display=swap"


def font_stack(font: str) -> str:
    return FONTS.get(font, "system-ui, -apple-system, 'Segoe UI', sans-serif")


# --- contrast (WCAG 2.2 relative luminance) ------------------------------------------------------


def _channel(value: int) -> float:
    c = value / 255
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def luminance(hex_colour: str) -> float:
    h = hex_colour.lstrip("#")
    r, g, b = (int(h[i : i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)


def contrast(a: str, b: str) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return round((la + 0.05) / (lb + 0.05), 2)


def on_colour(background: str) -> str:
    """White or near-black text, whichever reads better on ``background``."""
    return (
        WHITE if contrast(background, WHITE) >= contrast(background, DEFAULT_TEXT) else DEFAULT_TEXT
    )


def _shade(hex_colour: str, factor: float) -> str:
    h = hex_colour.lstrip("#")
    r, g, b = (int(h[i : i + 2], 16) for i in (0, 2, 4))
    return "#{:02x}{:02x}{:02x}".format(*(max(0, min(255, round(v * factor))) for v in (r, g, b)))


def readable_on_white(colour: str) -> str:
    """``colour`` darkened just enough for 4.5:1 on white (links, headings)."""
    current = colour.lower()
    for _step in range(40):
        if contrast(current, WHITE) >= AA:
            return current
        current = _shade(current, 0.92)
    return DEFAULT_TEXT


def contrast_report(primary: str, secondary: str = "") -> dict[str, Any]:
    text_on_primary = on_colour(primary)
    report: dict[str, Any] = {
        "primary_on_white": contrast(primary, WHITE),
        "text_on_primary": contrast(primary, text_on_primary),
        "on_primary": text_on_primary,
        "link_colour": readable_on_white(primary),
        "warnings": [],
    }
    if report["primary_on_white"] < AA:
        report["warnings"].append(
            _(
                "Your main colour is too light for text on white (%(ratio)s:1, AA needs 4.5:1). "
                "We'll use a darker shade for links and headings."
            )
            % {"ratio": report["primary_on_white"]}
        )
    if report["text_on_primary"] < AA:
        report["warnings"].append(
            _(
                "No text colour reaches 4.5:1 on your main colour (best %(ratio)s:1). "
                "Buttons will use large, bold text."
            )
            % {"ratio": report["text_on_primary"]}
        )
    if secondary:
        report["secondary_on_white"] = contrast(secondary, WHITE)
        report["on_secondary"] = on_colour(secondary)
    report["passes_aa"] = not report["warnings"]
    return report


# --- effective brand -----------------------------------------------------------------------------


@dataclass
class Brand:
    organisation_id: str
    name: str
    primary_colour: str = DEFAULT_PRIMARY
    secondary_colour: str = SECONDARY_DEFAULT
    font: str = ""
    logo_id: str | None = None
    logo_dark_id: str | None = None
    favicon_id: str | None = None
    app_icon_id: str | None = None
    app_name: str = ""
    email_header: str = ""
    email_footer: str = ""
    document_footer: str = ""
    social_links: dict[str, str] = field(default_factory=dict)
    show_powered_by: bool = True
    white_label: bool = False

    @property
    def on_primary(self) -> str:
        return on_colour(self.primary_colour)

    @property
    def link_colour(self) -> str:
        return readable_on_white(self.primary_colour)

    def asset_ids(self) -> set[str]:
        return {
            str(v)
            for v in (self.logo_id, self.logo_dark_id, self.favicon_id, self.app_icon_id)
            if v
        }

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _apply(brand: Brand, kit: Any) -> None:
    for attr, target in (
        ("logo_id", "logo_id"),
        ("logo_dark_id", "logo_dark_id"),
        ("favicon_id", "favicon_id"),
        ("app_icon_id", "app_icon_id"),
    ):
        value = getattr(kit, attr)
        if value:
            setattr(brand, target, str(value))
    for name in (
        "primary_colour",
        "secondary_colour",
        "font",
        "app_name",
        "email_header",
        "email_footer",
        "document_footer",
    ):
        value = getattr(kit, name)
        if value:
            setattr(brand, name, value)
    if kit.social_links:
        brand.social_links = {**brand.social_links, **kit.social_links}
    if kit.hide_powered_by:
        brand.show_powered_by = False


def resolve(organisation: Any, branch_id: Any = None) -> Brand:
    """The effective brand of ``organisation`` (in its tenant context)."""
    from .models import BrandKit

    brand = Brand(organisation_id=str(organisation.pk), name=organisation.name)
    if organisation.primary_colour and HEX.match(organisation.primary_colour):
        brand.primary_colour = organisation.primary_colour.lower()
    if organisation.logo_id:
        brand.logo_id = str(organisation.logo_id)
    with tenant_context(organisation):
        kits = {k.branch_id: k for k in BrandKit.objects.filter(branch__isnull=True)}
        if branch_id:
            kits.update({k.branch_id: k for k in BrandKit.objects.filter(branch_id=branch_id)})
    if None in kits:
        _apply(brand, kits[None])
    if branch_id and branch_id in kits:
        _apply(brand, kits[branch_id])
    brand.white_label = entitlements.has("white_label", organisation.pk)
    if not brand.white_label:
        brand.show_powered_by = True  # FR-24-1/T08: removable only with white_label
    return brand


def asset_url(organisation: Any, file_id: str | None, *, absolute: bool = True) -> str:
    if not file_id:
        return ""
    path = f"/api/v1/public/assets/{file_id}"
    return f"{organisation.base_url}{path}" if absolute else path


def _logo_data_uri(organisation: Any, file_id: str | None) -> str:
    """Logo bytes inlined for WeasyPrint (no network fetches while rendering a PDF)."""
    from tutortrack.core.storage.inline import image_data_uri

    with tenant_context(organisation):
        return image_data_uri(file_id, limit=LOGO_INLINE_LIMIT)


class Provider:
    """Registered with ``core.branding`` by ``SitesConfig.ready``."""

    def _org(self, organisation_id: uuid.UUID) -> Any:
        from tutortrack.tenancy.models import Organisation

        return Organisation.objects.get(pk=organisation_id)

    def for_email(self, organisation_id: uuid.UUID, branch_id: Any = None) -> dict[str, Any]:
        org = self._org(organisation_id)
        brand = resolve(org, branch_id)
        return {
            "name": brand.name,
            "primary_colour": brand.primary_colour,
            "on_primary": brand.on_primary,
            "link_colour": brand.link_colour,
            "logo_url": asset_url(org, brand.logo_id),
            "header": brand.email_header,
            "footer": brand.email_footer,
            "show_powered_by": brand.show_powered_by,
            "font": brand.font,
        }

    def for_documents(self, organisation_id: uuid.UUID, branch_id: Any = None) -> dict[str, Any]:
        org = self._org(organisation_id)
        brand = resolve(org, branch_id)
        return {
            "name": brand.name,
            "primary_colour": brand.primary_colour,
            "on_primary": brand.on_primary,
            "link_colour": brand.link_colour,
            "logo_url": "",
            "logo_data_uri": _logo_data_uri(org, brand.logo_id),
            "footer": brand.document_footer,
            "show_powered_by": brand.show_powered_by,
            "font": brand.font,
        }
