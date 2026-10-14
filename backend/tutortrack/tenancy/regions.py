"""Data residency (E29-T11, FR-29-8, ADR 0028).

TutorTrack runs one stack per region (``uk``, ``eu``, ``us``, ``au``), each with its own
database, storage, Redis and Temporal namespace; nothing is replicated across regions. A
stack's ``TT_REGION`` says which region it serves. An organisation is created in the
region of its country (``countries.defaults_for``), so signup on the wrong stack is refused
with the right regional signup address (``WrongRegion``) and the signup page redirects
there. With ``TT_REGION`` empty (development, tests, a single-stack deployment) one stack
serves every region.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from django.conf import settings
from django.utils.translation import gettext as _

from tutortrack.core.exceptions import BusinessRuleViolation

from .countries import defaults_for


class WrongRegion(BusinessRuleViolation):
    status_code = 409
    problem_type = "wrong-region"
    title = "Sign up in your region"


def current() -> str:
    return str(getattr(settings, "TT_REGION", "") or "")


def regions() -> dict[str, dict[str, Any]]:
    configured: dict[str, dict[str, Any]] = getattr(settings, "REGIONS", {})
    return configured


def serves(region: str) -> bool:
    here = current()
    return not here or here == region


def region_for_country(country: str) -> str:
    return defaults_for(country).region


def signup_url(region: str, country: str = "") -> str:
    base = str(regions().get(region, {}).get("app_url", "")).rstrip("/")
    if not base:
        return ""
    # The base comes from settings; the country is a validated two-letter code, URL-encoded.
    code = country.upper() if len(country) == 2 and country.isalpha() else ""
    suffix = "?" + urlencode({"country": code}) if code else ""
    return base + "/signup" + suffix


def describe(country: str) -> dict[str, Any]:
    region = region_for_country(country)
    return {
        "country": country.upper(),
        "region": region,
        "region_name": str(regions().get(region, {}).get("name", region)),
        "serves_here": serves(region),
        "signup_url": signup_url(region, country),
    }


def require_served(country: str) -> None:
    """Refuse to create an organisation whose data belongs in another region."""
    info = describe(country)
    if not info["serves_here"]:
        raise WrongRegion(
            _("Organisations in this country are hosted in our %(region)s region.")
            % {"region": info["region_name"]},
            extra={"region": info["region"], "signup_url": info["signup_url"]},
        )
