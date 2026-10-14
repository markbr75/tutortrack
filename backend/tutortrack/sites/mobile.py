"""Native app shells (E16-T11, FR-16-10): the configuration a Capacitor build needs.

* The generic "TutorTrack" app (App Store / Play Store) bundles a small organisation
  picker and then loads the organisation's portal (``https://<org>/portal/``).
* A white-label app (Enterprise ``white_label`` add-on) is built per organisation from its
  E24 brand kit: app name, icon, colours, and the portal of its own domain as the start
  URL. ``frontend/apps/mobile/scripts/configure.mjs`` turns this JSON into
  ``capacitor.config.json`` and the icon/splash sources; the manual "Mobile app build"
  GitHub Actions workflow runs it.

Everything here is public brand data (the same as the PWA manifest): no secrets.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

from tutortrack.core import entitlements
from tutortrack.core.branding import DEFAULT_PRIMARY

from . import brand

GENERIC_APP_ID = "app.tutortrack.portal"
GENERIC_NAME = "TutorTrack"
GENERIC_COLOUR = DEFAULT_PRIMARY


def app_id_for(slug: str) -> str:
    """A store-safe reverse-DNS id: segments start with a letter, letters/digits/_ only."""
    segment = re.sub(r"[^a-z0-9_]", "_", slug.lower()).strip("_") or "org"
    if not segment[0].isalpha():
        segment = f"o{segment}"
    return f"app.tutortrack.tenant.{segment[:60]}"


def generic_config() -> dict[str, Any]:
    return {
        "white_label": False,
        "appId": GENERIC_APP_ID,
        "appName": GENERIC_NAME,
        "serverUrl": "",  # the bundled organisation picker
        "allowNavigation": ["*.tutortrack.app"],
        "primaryColour": GENERIC_COLOUR,
        "onPrimary": brand.on_colour(GENERIC_COLOUR),
        "backgroundColour": "#ffffff",
        "iconUrl": "",
        "organisation": None,
    }


def app_config(organisation: Any) -> dict[str, Any]:
    """The white-label configuration for ``organisation`` (its brand kit), or the generic
    app's when the plan has no ``white_label``."""
    if not entitlements.has("white_label", organisation.pk):
        return {**generic_config(), "organisation": organisation.slug}
    b = brand.resolve(organisation)
    portal = f"{organisation.base_url}/portal/"
    icon_id = b.app_icon_id or b.logo_id
    return {
        "white_label": True,
        "appId": app_id_for(organisation.slug),
        "appName": (b.app_name or b.name)[:30],
        "serverUrl": portal,
        "allowNavigation": [urlsplit(portal).hostname or ""],
        "primaryColour": b.primary_colour,
        "onPrimary": b.on_primary,
        "backgroundColour": "#ffffff",
        "iconUrl": brand.asset_url(organisation, icon_id) if icon_id else "",
        "organisation": organisation.slug,
    }
