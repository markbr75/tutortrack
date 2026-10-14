"""uCheck (UK DBS checks) client (E18-T11).

The organisation's uCheck account is connected with an API key. ``initiate`` creates an
application for the DBS level and returns the applicant's link (the tutor fills in the
DBS form and ID details on uCheck); ``fetch`` polls the application until the
certificate is issued. uCheck has no webhooks we rely on, so the workflow polls every
6 hours.

The endpoint shapes follow uCheck's partner REST API as configured by
``BACKGROUND_CHECKS["UCHECK_API_URL"]``; like the other real clients, this one is tested
against request shapes only (there are no sandbox credentials in CI).
"""

from __future__ import annotations

from datetime import date
from typing import Any

from django.conf import settings

from tutortrack.integrations.providers import AccountInfo, Credentials, ProviderError, http

from . import Candidate, CheckError, CheckState, Initiated

STATUS = {
    "invited": "invited",
    "awaiting_applicant": "invited",
    "submitted": "in_progress",
    "with_dbs": "in_progress",
    "processing": "in_progress",
    "complete": "completed",
    "completed": "completed",
    "withdrawn": "cancelled",
    "cancelled": "cancelled",
    "expired": "expired",
}


def _base() -> str:
    return str(settings.BACKGROUND_CHECKS["UCHECK_API_URL"]).rstrip("/")


class UCheckClient:
    def _call(self, creds: Credentials, method: str, path: str, body: Any = None) -> Any:
        try:
            return http.request(
                method,
                f"{_base()}{path}",
                token=creds.secret,
                json_body=body,
                user_url=True,
                provider="ucheck",
            ).json()
        except ProviderError as exc:
            raise CheckError(str(exc)) from exc

    def verify(self, credentials: Credentials) -> AccountInfo:
        account = self._call(credentials, "GET", "/account")
        return AccountInfo(str(account.get("id", "")), str(account.get("name", "")))

    def initiate(self, creds: Credentials, candidate: Candidate, package: str) -> Initiated:
        created = self._call(
            creds,
            "POST",
            "/applications",
            {
                "reference": candidate.ref,
                "check_type": package or "enhanced",
                "workforce": "child",
                "applicant": {
                    "forename": candidate.first_name,
                    "surname": candidate.last_name,
                    "email": candidate.email,
                    "date_of_birth": candidate.date_of_birth or None,
                },
            },
        )
        return Initiated(
            external_id=str(created["id"]),
            status=STATUS.get(str(created.get("status", "")), "invited"),
            invite_url=str(created.get("applicant_url", "")),
        )

    def fetch(self, creds: Credentials, external_id: str, candidate: Candidate) -> CheckState:
        app = self._call(creds, "GET", f"/applications/{external_id}")
        status = STATUS.get(str(app.get("status", "")), "in_progress")
        result = ""
        issued = None
        if status == "completed":
            disclosed = bool(app.get("information_disclosed"))
            result = "consider" if disclosed else "clear"
            raw_date = app.get("certificate_issue_date")
            issued = date.fromisoformat(str(raw_date)[:10]) if raw_date else None
        return CheckState(
            status=status,
            result=result,
            certificate_number=str(app.get("certificate_number") or ""),
            issue_date=issued,
            summary={
                "status": app.get("status"),
                "check_type": app.get("check_type"),
                "information_disclosed": app.get("information_disclosed"),
            },
        )

    def cancel(self, creds: Credentials, external_id: str) -> None:
        self._call(creds, "POST", f"/applications/{external_id}/withdraw", {})
