"""Sensible defaults derived from a country at signup (FR-02-6 "pre-filled from country").

Currency comes from CLDR (babel); timezone, locale and data-residency region from the
table below, which covers launch markets. Unknown countries fall back to UTC/en-GB/eu and
the user can change everything in the wizard.
"""

from __future__ import annotations

from dataclasses import dataclass

from babel.numbers import get_territory_currencies

EU = {
    "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR", "HU", "IE", "IT",
    "LV", "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SK", "SI", "ES", "SE",
}  # fmt: skip

# country -> (timezone, locale, region)
KNOWN: dict[str, tuple[str, str, str]] = {
    "GB": ("Europe/London", "en-GB", "uk"),
    "IE": ("Europe/Dublin", "en-GB", "eu"),
    "US": ("America/New_York", "en-US", "us"),
    "CA": ("America/Toronto", "en-US", "us"),
    "AU": ("Australia/Sydney", "en-GB", "au"),
    "NZ": ("Pacific/Auckland", "en-GB", "au"),
    "FR": ("Europe/Paris", "en-GB", "eu"),
    "DE": ("Europe/Berlin", "en-GB", "eu"),
    "ES": ("Europe/Madrid", "en-GB", "eu"),
    "NL": ("Europe/Amsterdam", "en-GB", "eu"),
    "PL": ("Europe/Warsaw", "en-GB", "eu"),
    "ZA": ("Africa/Johannesburg", "en-GB", "uk"),
    "AE": ("Asia/Dubai", "en-GB", "uk"),
    "SG": ("Asia/Singapore", "en-GB", "au"),
    "HK": ("Asia/Hong_Kong", "en-GB", "au"),
}


@dataclass(frozen=True)
class CountryDefaults:
    country: str
    currency: str
    timezone: str
    locale: str
    region: str
    fiscal_year_start_month: int
    week_start_day: int  # 0 = Monday


def defaults_for(country: str) -> CountryDefaults:
    code = country.strip().upper()
    currencies = get_territory_currencies(code) if len(code) == 2 else []
    currency = currencies[0] if currencies else "GBP"
    tz, locale, region = KNOWN.get(code, ("UTC", "en-GB", "eu" if code in EU else "uk"))
    if code in EU and code not in KNOWN:
        region = "eu"
    return CountryDefaults(
        country=code or "GB",
        currency=currency,
        timezone=tz,
        locale=locale,
        region=region,
        fiscal_year_start_month={"GB": 4, "AU": 7, "NZ": 4}.get(code, 1),
        week_start_day=6 if code in {"US", "CA"} else 0,
    )
