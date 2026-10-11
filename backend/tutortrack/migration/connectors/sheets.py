"""Google Sheets import (FR-28-6): a personal, read-only Google connection on the E22
framework (provider ``google_sheets``, scope ``spreadsheets.readonly``) and a small client
for the Sheets API v4. The sheet's rows go through the normal CSV pipeline.

Only the spreadsheet id is taken from the pasted URL; requests go to Google's fixed API
host, so no user-influenced URL is ever fetched.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

from django.utils.translation import gettext as _

from tutortrack.core.exceptions import BusinessRuleViolation
from tutortrack.integrations.providers import Credentials, ProviderError

API = "https://sheets.googleapis.com/v4/spreadsheets"
SCOPES = ("openid", "email", "https://www.googleapis.com/auth/spreadsheets.readonly")
PROVIDER = "google_sheets"
ID = re.compile(r"/spreadsheets/d/([A-Za-z0-9_-]{20,})")
MAX_CELLS = 2_000_000


def spreadsheet_id(url: str) -> str:
    url = url.strip()
    match = ID.search(url)
    if match:
        return match.group(1)
    if re.fullmatch(r"[A-Za-z0-9_-]{20,}", url):
        return url
    raise BusinessRuleViolation(
        _("Paste the link of a Google Sheet."),
        extra={"errors": {"url": [_("Not a Google Sheets link.")]}},
    )


class SheetsClient:
    """The live Sheets API."""

    def read(
        self, credentials: Credentials, sheet_id: str, sheet: str
    ) -> tuple[list[list[str]], str]:
        from tutortrack.integrations.providers import http

        meta = http.request(
            "GET",
            f"{API}/{quote(sheet_id)}",
            token=credentials.access_token,
            params={"fields": "properties.title,sheets.properties.title"},
            provider=PROVIDER,
        ).json()
        title = str((meta.get("properties") or {}).get("title") or "Google Sheet")
        names = [str((s.get("properties") or {}).get("title")) for s in meta.get("sheets") or []]
        name = sheet if sheet in names else (names[0] if names else "Sheet1")
        body = http.request(
            "GET",
            f"{API}/{quote(sheet_id)}/values/{quote(name, safe='')}",
            token=credentials.access_token,
            params={"majorDimension": "ROWS", "valueRenderOption": "FORMATTED_VALUE"},
            provider=PROVIDER,
        ).json()
        rows = [[str(cell) for cell in row] for row in body.get("values") or []]
        return rows, title


class FakeSheetsClient:
    def read(
        self, credentials: Credentials, sheet_id: str, sheet: str
    ) -> tuple[list[list[str]], str]:
        from .fake import dataset

        data = dataset(PROVIDER)
        rows: Any = data.get("values") or []
        title = str(((data.get("title") or [{}])[0]).get("name") or "Google Sheet")
        return [[str(c) for c in row] for row in rows], title


def read_sheet(user: Any, url: str, sheet: str = "") -> tuple[list[list[str]], str]:
    from tutortrack.integrations import providers as registry
    from tutortrack.integrations import services as integrations
    from tutortrack.integrations.models import IntegrationConnection

    sheet_id = spreadsheet_id(url)
    connection = (
        IntegrationConnection.objects.filter(user=user, provider=PROVIDER)
        .exclude(status=IntegrationConnection.Status.DISCONNECTED)
        .first()
    )
    if connection is None:
        raise BusinessRuleViolation(
            _("Connect your Google account first."), extra={"code": "google_not_connected"}
        )
    client = registry.client(PROVIDER, "sheets")
    try:
        rows, title = client.read(integrations.credentials(connection), sheet_id, sheet)
    except ProviderError as exc:
        integrations.record_failure(connection, exc)
        raise BusinessRuleViolation(
            _("Google didn't let us read that sheet: %(error)s") % {"error": exc},
            extra={"errors": {"url": [str(exc)]}},
        ) from exc
    if sum(len(r) for r in rows) > MAX_CELLS:
        raise BusinessRuleViolation(_("The sheet is too large to import."))
    return rows, title
