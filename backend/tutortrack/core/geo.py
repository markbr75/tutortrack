"""Geocoding provider abstraction (E05 FR-05-15).

``GEOCODER`` selects the provider: ``NullGeocoder`` (default) returns nothing,
``FakeGeocoder`` (local development and tests, E05-T12) places every address at a stable
made-up point, ``GoogleGeocoder`` uses the Geocoding API with ``GOOGLE_MAPS_API_KEY`` and
``MapboxGeocoder`` the Mapbox Geocoding API with ``MAPBOX_ACCESS_TOKEN``. Real providers are
only ever reached through ``core.net.safe_urlopen``; keys come from the environment.
"""

from __future__ import annotations

import hashlib
import json
import urllib.parse
from dataclasses import dataclass
from decimal import Decimal
from functools import cache
from typing import Any, Protocol

from django.conf import settings
from django.utils.module_loading import import_string


@dataclass(frozen=True)
class GeoPoint:
    lat: Decimal
    lng: Decimal


class Geocoder(Protocol):
    def geocode(self, address: str, country: str = "") -> GeoPoint | None: ...


class NullGeocoder:
    def geocode(self, address: str, country: str = "") -> GeoPoint | None:
        return None


class FakeGeocoder:
    """No network: a stable point for any address (same text, same point), spread over a
    box around central London so local maps and tests look plausible."""

    SOUTH, WEST, HEIGHT, WIDTH = (
        Decimal("51.30"),
        Decimal("-0.50"),
        Decimal("0.40"),
        Decimal("0.70"),
    )

    def geocode(self, address: str, country: str = "") -> GeoPoint | None:
        text = " ".join(address.lower().split())
        if not text:
            return None
        digest = hashlib.sha256(f"{text}|{country.lower()}".encode()).digest()
        a = Decimal(int.from_bytes(digest[:4], "big")) / Decimal(2**32)
        b = Decimal(int.from_bytes(digest[4:8], "big")) / Decimal(2**32)
        q = Decimal("0.000001")
        return GeoPoint(
            (self.SOUTH + a * self.HEIGHT).quantize(q), (self.WEST + b * self.WIDTH).quantize(q)
        )


class GoogleGeocoder:
    URL = "https://maps.googleapis.com/maps/api/geocode/json"

    def geocode(self, address: str, country: str = "") -> GeoPoint | None:
        from .net import safe_urlopen

        params = {"address": address, "key": settings.GOOGLE_MAPS_API_KEY}
        if country:
            params["components"] = f"country:{country}"
        with safe_urlopen(f"{self.URL}?{urllib.parse.urlencode(params)}", timeout=10) as response:
            body = json.loads(response.read())
        results = body.get("results") or []
        if body.get("status") != "OK" or not results:
            return None
        location = results[0]["geometry"]["location"]
        q = Decimal("0.000001")
        return GeoPoint(
            Decimal(str(location["lat"])).quantize(q), Decimal(str(location["lng"])).quantize(q)
        )


class MapboxGeocoder:
    URL = "https://api.mapbox.com/geocoding/v5/mapbox.places/"

    def geocode(self, address: str, country: str = "") -> GeoPoint | None:
        from .net import safe_urlopen

        params = {"access_token": settings.MAPBOX_ACCESS_TOKEN, "limit": "1"}
        if country:
            params["country"] = country.lower()
        url = f"{self.URL}{urllib.parse.quote(address)}.json?{urllib.parse.urlencode(params)}"
        with safe_urlopen(url, timeout=10) as response:
            body = json.loads(response.read())
        features = body.get("features") or []
        if not features:
            return None
        lng, lat = features[0]["center"][:2]
        q = Decimal("0.000001")
        return GeoPoint(Decimal(str(lat)).quantize(q), Decimal(str(lng)).quantize(q))


def area_of(address: Any) -> str:
    """A neighbourhood, not an address: the postcode's outward part, else the town."""
    if address is None:
        return ""
    postcode = (address.postcode or "").strip()
    if postcode:
        if " " in postcode:
            return str(postcode.split()[0].upper())
        return postcode[:-3].upper() if len(postcode) > 5 else postcode.upper()
    return str(address.city or "")


def rounded(lat: Decimal | float, lng: Decimal | float, places: int = 3) -> tuple[float, float]:
    """A point coarsened for display (3 places is about 100 m): maps show where people
    are roughly, never a doorstep."""
    q = Decimal(1).scaleb(-places)
    return (
        float(Decimal(str(lat)).quantize(q)),
        float(Decimal(str(lng)).quantize(q)),
    )


@cache
def geocoder() -> Geocoder:
    provider: Geocoder = import_string(settings.GEOCODER)()
    return provider
