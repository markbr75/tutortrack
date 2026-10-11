"""Website themes (FR-24-4): five tutoring-specific presets.

Themes are code, not rows (the spec's ``SiteTheme``): each one is a set of CSS custom
properties layered under the brand kit's colours and font, so every theme stays on-brand
and the colour-contrast guarantees of ``sites.brand`` apply unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from django.utils.functional import Promise
from django.utils.translation import gettext_lazy as _


@dataclass(frozen=True)
class Theme:
    key: str
    label: str | Promise
    description: str | Promise
    heading_font: str = ""  # "" = the brand font
    variables: dict[str, str] = field(default_factory=dict)


_BASE = {
    "--tt-surface": "#ffffff",
    "--tt-background": "#ffffff",
    "--tt-text": "#111827",
    "--tt-muted": "#4b5563",
    "--tt-border": "#e5e7eb",
    "--tt-radius": "8px",
    "--tt-section-gap": "64px",
    "--tt-hero-background": "var(--tt-brand-soft)",
}

THEMES: dict[str, Theme] = {
    t.key: t
    for t in (
        Theme(
            "classic",
            _("Classic"),
            _("Clean and trustworthy: white pages, brand-coloured buttons."),
            variables=_BASE,
        ),
        Theme(
            "modern",
            _("Modern"),
            _("Bold hero in your brand colour, rounded cards, generous spacing."),
            variables={
                **_BASE,
                "--tt-radius": "16px",
                "--tt-section-gap": "88px",
                "--tt-hero-background": "var(--tt-brand)",
                "--tt-hero-text": "var(--tt-on-brand)",
            },
        ),
        Theme(
            "playful",
            _("Playful"),
            _("Friendly and colourful for primary and 11+ tuition."),
            heading_font="Nunito",
            variables={
                **_BASE,
                "--tt-radius": "24px",
                "--tt-background": "#fffdf7",
                "--tt-hero-background": "var(--tt-brand-soft)",
            },
        ),
        Theme(
            "academic",
            _("Academic"),
            _("Serif headings and a calm palette for GCSE, A-level and university prep."),
            heading_font="Merriweather",
            variables={**_BASE, "--tt-radius": "4px", "--tt-background": "#fbfbf9"},
        ),
        Theme(
            "minimal",
            _("Minimal"),
            _("Lots of white space and simple type for solo tutors."),
            variables={
                **_BASE,
                "--tt-radius": "0px",
                "--tt-section-gap": "96px",
                "--tt-hero-background": "#ffffff",
            },
        ),
    )
}
DEFAULT_THEME = "classic"


def get(key: str) -> Theme:
    return THEMES.get(key) or THEMES[DEFAULT_THEME]


def describe() -> list[dict[str, str]]:
    return [
        {"key": t.key, "title": str(t.label), "description": str(t.description)}
        for t in THEMES.values()
    ]
