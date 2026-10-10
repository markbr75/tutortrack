"""Travel distance between lessons (FR-12-3), behind a routing provider.

``STRAIGHT_LINE`` (default) is the great-circle distance x 1.25 (a road-distance
approximation); ``GOOGLE`` uses the Distance Matrix API with ``GOOGLE_MAPS_API_KEY``
(fetched through ``core.net.safe_urlopen``). Tutors confirm suggestions in their claim.
"""

from __future__ import annotations

import json
import math
import urllib.parse
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import structlog
from django.conf import settings

ROAD_FACTOR = Decimal("1.25")
KM_PER_MILE = Decimal("1.609344")


@dataclass(frozen=True)
class Place:
    label: str
    lat: Decimal
    lng: Decimal


def straight_line_km(a: Place, b: Place) -> Decimal:
    lat1, lng1, lat2, lng2 = map(math.radians, map(float, (a.lat, a.lng, b.lat, b.lng)))
    h = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2
    )
    return Decimal(str(round(6371.0088 * 2 * math.asin(math.sqrt(h)), 3)))


def road_km(a: Place, b: Place) -> Decimal:
    key = getattr(settings, "GOOGLE_MAPS_API_KEY", "")
    if key:
        try:
            return _google_km(a, b, key)
        except Exception as exc:
            structlog.get_logger(__name__).warning("payroll.distance_failed", error=str(exc))
    return (straight_line_km(a, b) * ROAD_FACTOR).quantize(Decimal("0.1"))


def _google_km(a: Place, b: Place, key: str) -> Decimal:
    from tutortrack.core.net import safe_urlopen

    query = urllib.parse.urlencode(
        {"origins": f"{a.lat},{a.lng}", "destinations": f"{b.lat},{b.lng}", "key": key}
    )
    url = f"https://maps.googleapis.com/maps/api/distancematrix/json?{query}"
    with safe_urlopen(url, timeout=5) as response:
        body = json.loads(response.read())
    metres = body["rows"][0]["elements"][0]["distance"]["value"]
    return (Decimal(metres) / 1000).quantize(Decimal("0.1"))


def in_unit(km: Decimal, unit: str) -> Decimal:
    return (km / KM_PER_MILE).quantize(Decimal("0.1")) if unit == "mi" else km


def _lesson_place(lesson: Any) -> Place | None:
    address = None
    if lesson.location_id and lesson.location and lesson.location.address_id:
        address = lesson.location.address
    else:
        attendee = lesson.attendees.select_related("student__lesson_address").first()
        if attendee and attendee.student.lesson_address_id:
            address = attendee.student.lesson_address
    if address is None or address.lat is None or address.lng is None:
        return None
    return Place(lesson.title, address.lat, address.lng)


def suggest_legs(tutor: Any, day: date, *, from_home: bool) -> list[dict[str, Any]]:
    """Legs between the tutor's in-person lessons on ``day`` (and from home, optionally)."""
    from tutortrack.core.context import require_organisation_id
    from tutortrack.scheduling.models import Lesson
    from tutortrack.tenancy.models import Organisation

    zone = ZoneInfo(Organisation.objects.get(pk=require_organisation_id()).timezone)
    start = datetime.combine(day, time.min, tzinfo=zone)
    lessons = (
        Lesson.objects.filter(
            tutors__tutor=tutor, online=False, start__gte=start,
            start__lt=start + timedelta(days=1),
        )
        .exclude(status=Lesson.Status.CANCELLED)
        .select_related("location__address")
        .order_by("start")
    )  # fmt: skip
    places = [(lesson, _lesson_place(lesson)) for lesson in lessons]
    previous: Place | None = None
    if from_home and tutor.address_id and tutor.address.lat is not None:
        previous = Place("Home", tutor.address.lat, tutor.address.lng)
    legs = []
    for lesson, place in places:
        if place is None:
            continue
        if previous is not None:
            legs.append({"from": previous.label, "to": place.label, "lesson": str(lesson.pk),
                         "km": road_km(previous, place)})  # fmt: skip
        previous = place
    return legs
