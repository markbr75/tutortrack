"""Impossible-travel alerts (G6, FR-29-2).

Each sign-in attempt records the country it came from: the CDN's country header first
(``GEOIP_COUNTRY_HEADER``, Cloudflare's ``CF-IPCountry`` by default), then an optional GeoIP
lookup behind ``GEOIP_LOOKUP`` (any class with ``country(ip) -> str``; no database ships
with TutorTrack). A successful sign-in from a different country than the person's previous
successful sign-in less than ``IMPOSSIBLE_TRAVEL_HOURS`` earlier is treated as impossible
travel: the person is emailed, and each organisation where they are staff gets a
``security.alert`` (owners are emailed by identity's handler, and the alert sits in the
outbox/audit trail as a security event).

Country-level data can't measure distance, so the rule is "another country, too soon"; VPNs
and border towns give false positives, which is acceptable for an alert that blocks nothing.
"""

from __future__ import annotations

import re
from functools import cache
from typing import Any, Protocol

from django.conf import settings
from django.http import HttpRequest
from django.utils.module_loading import import_string

from tutortrack.core.middleware import client_ip

UNKNOWN = {"XX", "T1", "A1", "A2", "O1", "EU", "AP"}  # unknown, Tor, anonymous proxies...
STAFF_ROLES = ("owner", "admin", "branch_manager", "coordinator", "finance", "tutor")


class CountryLookup(Protocol):
    def country(self, ip: str) -> str: ...


@cache
def _lookup() -> CountryLookup | None:
    path = getattr(settings, "GEOIP_LOOKUP", "")
    return import_string(path)() if path else None


def _clean(value: str) -> str:
    value = (value or "").strip().upper()
    return value if re.fullmatch(r"[A-Z]{2}", value) and value not in UNKNOWN else ""


def country_for(request: HttpRequest) -> str:
    header = getattr(settings, "GEOIP_COUNTRY_HEADER", "")
    found = _clean(request.headers.get(header, "")) if header else ""
    if found:
        return found
    lookup = _lookup()
    ip = client_ip(request)
    if lookup is None or not ip:
        return ""
    try:
        return _clean(lookup.country(ip))
    except Exception:  # a broken lookup never blocks sign-in
        return ""


def check(user: Any, event: Any) -> bool:
    """After a successful sign-in ``event``: alert when it is impossible travel."""
    from datetime import timedelta

    from django.db import transaction

    from .models import LoginEvent

    if not event.country:
        return False
    since = event.created_at - timedelta(hours=int(settings.IMPOSSIBLE_TRAVEL_HOURS))
    previous = (
        LoginEvent.objects.filter(user=user, success=True, created_at__gte=since)
        .exclude(pk=event.pk)
        .exclude(country="")
        .order_by("-created_at")
        .first()
    )
    if previous is None or previous.country == event.country:
        return False
    detail = f"{previous.country} -> {event.country} within {settings.IMPOSSIBLE_TRAVEL_HOURS}h"
    _alert_organisations(user, detail)
    from .tasks import send_impossible_travel_alert

    user_id, ip = str(user.pk), event.ip or ""
    before, now_country = previous.country, event.country
    transaction.on_commit(
        lambda: send_impossible_travel_alert.delay(
            user_id=user_id, ip=ip, previous_country=before, country=now_country
        )
    )
    return True


def _alert_organisations(user: Any, detail: str) -> None:
    from django.db import transaction

    from tutortrack.core.context import request_context
    from tutortrack.core.events import publish
    from tutortrack.core.security_alerts import SecurityAlert

    from .models import Membership

    with request_context(user_id=user.pk):
        org_ids = list(
            Membership.all_tenants.filter(
                user_id=user.pk, status=Membership.Status.ACTIVE, role__in=STAFF_ROLES
            ).values_list("organisation_id", flat=True)
        )
    with transaction.atomic():
        for org_id in org_ids:
            publish(
                SecurityAlert(subject_id=user.pk, kind="impossible_travel", detail=detail),
                organisation_id=org_id,
            )
