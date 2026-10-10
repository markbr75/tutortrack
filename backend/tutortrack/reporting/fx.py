"""Daily exchange rates and conversion into a reporting currency (FR-26-6).

Rates are platform data (``FxRate``), fetched once a day by a Celery Beat task from a
provider: the ECB reference rates (no key needed), Open Exchange Rates (with an app id)
or, when ``FX_RATES_PROVIDER`` is empty (development, tests), a fixed fake table.
Conversion uses the latest rate on or before the day and crosses through the provider's
base currency; results are rounded half-up to the target currency's minor unit.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Protocol

import structlog
from django.conf import settings
from django.db import transaction

from tutortrack.core.money import minor_units

from .models import FxRate

logger = structlog.get_logger(__name__)


class FxError(Exception):
    pass


@dataclass(frozen=True)
class RateTable:
    day: date
    base: str
    rates: dict[str, Decimal]  # 1 base = rate quote


class FxProvider(Protocol):
    name: str

    def latest(self) -> RateTable: ...


class EcbProvider:
    """European Central Bank euro reference rates (published on working days)."""

    name = "ecb"
    url = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"

    def latest(self) -> RateTable:
        import urllib.request

        # A fixed, trusted URL (not user-influenced), so plain urllib is fine here.
        with urllib.request.urlopen(self.url, timeout=15) as response:  # noqa: S310
            return self.parse(response.read())

    @staticmethod
    def parse(payload: bytes) -> RateTable:
        root = ET.fromstring(payload)  # noqa: S314 - trusted ECB feed
        day: date | None = None
        rates: dict[str, Decimal] = {}
        for node in root.iter():
            if node.tag.endswith("Cube") and "time" in node.attrib:
                day = date.fromisoformat(node.attrib["time"])
            if node.tag.endswith("Cube") and "currency" in node.attrib:
                rates[node.attrib["currency"]] = Decimal(node.attrib["rate"])
        if day is None or not rates:
            raise FxError("The ECB feed had no rates.")
        return RateTable(day=day, base="EUR", rates=rates)


class OpenExchangeRatesProvider:
    name = "oxr"
    url = "https://openexchangerates.org/api/latest.json?app_id="

    def __init__(self, app_id: str) -> None:
        self.app_id = app_id

    def latest(self) -> RateTable:
        import urllib.request

        with urllib.request.urlopen(self.url + self.app_id, timeout=15) as response:  # noqa: S310
            body = json.loads(response.read())
        rates = {k: Decimal(str(v)) for k, v in body["rates"].items()}
        from datetime import UTC, datetime

        day = datetime.fromtimestamp(int(body["timestamp"]), tz=UTC).date()
        return RateTable(day=day, base=str(body.get("base") or "USD"), rates=rates)


@dataclass
class FakeProvider:
    """Fixed rates so every flow works without network access."""

    name: str = "fake"
    day: date | None = None
    rates: dict[str, Decimal] = field(
        default_factory=lambda: {
            "GBP": Decimal("0.85"),
            "USD": Decimal("1.10"),
            "AUD": Decimal("1.65"),
            "CAD": Decimal("1.50"),
            "NZD": Decimal("1.80"),
            "CHF": Decimal("0.95"),
            "SEK": Decimal("11.50"),
            "NOK": Decimal("11.70"),
            "DKK": Decimal("7.46"),
            "PLN": Decimal("4.30"),
            "ZAR": Decimal("20.00"),
            "INR": Decimal("90.00"),
            "SGD": Decimal("1.45"),
            "HKD": Decimal("8.60"),
        }
    )

    def latest(self) -> RateTable:
        from tutortrack.core.time import now

        return RateTable(day=self.day or now().date(), base="EUR", rates=dict(self.rates))


def get_provider() -> FxProvider:
    name = getattr(settings, "FX_RATES_PROVIDER", "")
    if name == "ecb":
        return EcbProvider()
    app_id = str(getattr(settings, "OPENEXCHANGERATES_APP_ID", "") or "")
    if name in ("oxr", "openexchangerates") and app_id:
        return OpenExchangeRatesProvider(app_id)
    return FakeProvider()


@transaction.atomic
def store(table: RateTable, source: str) -> int:
    for quote, rate in table.rates.items():
        FxRate.objects.update_or_create(
            date=table.day,
            base=table.base,
            quote=quote,
            defaults={"rate": rate, "source": source},
        )
    return len(table.rates)


def fetch_latest(provider: FxProvider | None = None) -> int:
    """Fetch today's rates (idempotent per day)."""
    provider = provider or get_provider()
    table = provider.latest()
    count = store(table, provider.name)
    logger.info("fx.rates_stored", day=str(table.day), base=table.base, count=count)
    return count


class Converter:
    """Converts amounts on given days; caches each day's table for one report run."""

    def __init__(self) -> None:
        self._tables: dict[date, tuple[str, dict[str, Decimal]] | None] = {}

    def _table(self, day: date) -> tuple[str, dict[str, Decimal]] | None:
        if day not in self._tables:
            latest = FxRate.objects.filter(date__lte=day).order_by("-date").first()
            if latest is None:
                self._tables[day] = None
            else:
                rows = FxRate.objects.filter(date=latest.date, base=latest.base)
                rates = {r.quote: r.rate for r in rows}
                rates[latest.base] = Decimal(1)
                self._tables[day] = (latest.base, rates)
        return self._tables[day]

    def rate(self, source: str, target: str, day: date) -> Decimal | None:
        if source == target:
            return Decimal(1)
        table = self._table(day)
        if table is None:
            return None
        _base, rates = table
        if source not in rates or target not in rates:
            return None
        return rates[target] / rates[source]

    def convert(self, amount: Decimal, source: str, target: str, day: date) -> Decimal | None:
        """``amount`` in ``target`` rounded to its minor unit, or None without a rate."""
        rate = self.rate(source, target, day)
        if rate is None:
            return None
        quantum = Decimal(1).scaleb(-minor_units(target))
        return (amount * rate).quantize(quantum, rounding=ROUND_HALF_UP)
