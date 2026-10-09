"""Geocoding provider abstraction (E05 FR-05-15).

``GEOCODER`` selects the provider: ``NullGeocoder`` (default; local/tests) returns nothing,
``GoogleGeocoder`` uses the Geocoding API with ``GOOGLE_MAPS_API_KEY``. Mapbox can be added
behind the same interface.
"""

from __future__ import annotations

import json
import urllib.parse
from dataclasses import dataclass
from decimal import Decimal
from functools import cache
from typing import Protocol

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


@cache
def geocoder() -> Geocoder:
    provider: Geocoder = import_string(settings.GEOCODER)()
    return provider
