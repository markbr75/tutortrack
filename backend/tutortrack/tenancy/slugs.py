"""Organisation slug rules (FR-02-1): the slug is the subdomain, ``{slug}.tutortrack.app``."""

from __future__ import annotations

import re

from django.utils.text import slugify
from django.utils.translation import gettext as _

from tutortrack.core.exceptions import BusinessRuleViolation
from tutortrack.core.time import now

from .models import Organisation, OrganisationDomain, ReservedSlug

# Always reserved (the ReservedSlug table holds platform-admin additions).
BUILTIN_RESERVED = frozenset(
    {
        "about", "account", "accounts", "admin", "affiliate", "affiliates", "api", "app",
        "apps", "assets", "auth", "billing", "blog", "cdn", "dashboard", "demo", "dev",
        "developer", "developers", "docs", "email", "files", "ftp", "help", "home", "imap",
        "info", "login", "logout", "mail", "marketing", "media", "news", "pop", "portal",
        "pricing", "privacy", "sales", "security", "signin", "signup", "smtp", "sso",
        "staging", "static", "status", "support", "terms", "test", "tutortrack", "webhooks",
        "widgets", "www",
    }
)  # fmt: skip

SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{1,61}[a-z0-9])$")
MIN_LENGTH, MAX_LENGTH = 3, 63


class InvalidSlug(BusinessRuleViolation):
    problem_type = "invalid-slug"
    title = "Invalid subdomain"


def normalise(value: str) -> str:
    return value.strip().lower()


def is_reserved(slug: str) -> bool:
    return slug in BUILTIN_RESERVED or ReservedSlug.objects.filter(slug=slug).exists()


def slug_problem(slug: str, *, organisation: Organisation | None = None) -> str | None:
    """A user-facing reason why ``slug`` can't be used, or None if it is available."""
    if not SLUG_RE.match(slug) or "--" in slug:
        return _(
            "Use 3 to 63 lowercase letters, numbers and single hyphens, starting and ending "
            "with a letter or number."
        )
    if is_reserved(slug):
        return _("This subdomain is reserved.")
    taken = Organisation.objects.filter(slug=slug)
    if organisation is not None:
        taken = taken.exclude(pk=organisation.pk)
    if taken.exists():
        return _("This subdomain is already taken.")
    redirect = OrganisationDomain.objects.filter(
        hostname=slug, type=OrganisationDomain.Type.SUBDOMAIN, redirect_until__gt=now()
    )
    if organisation is not None:
        redirect = redirect.exclude(organisation=organisation)
    if redirect.exists():
        return _("This subdomain was recently used by another organisation.")
    return None


def validate_slug(slug: str, *, organisation: Organisation | None = None) -> str:
    slug = normalise(slug)
    problem = slug_problem(slug, organisation=organisation)
    if problem:
        raise InvalidSlug(problem, extra={"errors": {"slug": [problem]}})
    return slug


def suggest_slug(name: str) -> str:
    """An available slug derived from a business name ("Bright Minds" -> "bright-minds")."""
    base = slugify(name)[: MAX_LENGTH - 4].strip("-") or "tutoring"
    base = re.sub(r"-{2,}", "-", base)
    if len(base) < MIN_LENGTH:
        base = f"{base}-tutoring"
    candidate = base
    for n in range(2, 1000):
        if slug_problem(candidate) is None:
            return candidate
        candidate = f"{base}-{n}"
    raise InvalidSlug(_("Could not find an available subdomain; please choose one."))
