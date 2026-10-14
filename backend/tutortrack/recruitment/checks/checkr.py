"""Checkr (US) background checks through invitations (E18-T11).

* ``initiate``: create a candidate, then an invitation for the package; the tutor completes
  their details and consent on Checkr's hosted page (``invitation_url``).
* ``fetch``: the invitation, then its report (``clear`` / ``consider``; ``suspended`` and
  ``canceled`` reports are ``unable``).
* Webhooks (``/webhooks/background-checks/checkr``): ``X-Checkr-Signature`` is the hex
  HMAC-SHA256 of the raw body keyed with the account's API key (``verify_signature``).

All calls go through ``core.net.safe_urlopen`` (``user_url=True``) with HTTP basic auth
(the API key as the user name).
"""

from __future__ import annotations

import base64
from typing import Any

from django.conf import settings

from tutortrack.integrations import routes
from tutortrack.integrations.providers import AccountInfo, Credentials, ProviderError, http

from . import Candidate, CheckError, CheckState, Initiated

REPORT_STATUS = {
    "complete": "completed",
    "pending": "in_progress",
    "suspended": "completed",
    "dispute": "in_progress",
    "canceled": "cancelled",
}


def _base() -> str:
    return str(settings.BACKGROUND_CHECKS["CHECKR_API_URL"]).rstrip("/")


def _auth(creds: Credentials) -> str:
    return "Basic " + base64.b64encode(f"{creds.secret}:".encode()).decode()


def verify_signature(secret: str, body: bytes, signature: str) -> bool:
    return routes.verify_hmac(secret, body, signature)


class CheckrClient:
    def _call(self, creds: Credentials, method: str, path: str, body: Any = None) -> Any:
        try:
            return http.request(
                method,
                f"{_base()}{path}",
                auth_header=_auth(creds),
                json_body=body,
                user_url=True,
                provider="checkr",
            ).json()
        except ProviderError as exc:
            raise CheckError(str(exc)) from exc

    def verify(self, credentials: Credentials) -> AccountInfo:
        account = self._call(credentials, "GET", "/account")
        return AccountInfo(
            str(account.get("id", "")),
            str(
                account.get("company", {}).get("name", "")
                if isinstance(account.get("company"), dict)
                else ""
            ),
        )

    def initiate(self, creds: Credentials, candidate: Candidate, package: str) -> Initiated:
        person = self._call(
            creds,
            "POST",
            "/candidates",
            {
                "first_name": candidate.first_name,
                "last_name": candidate.last_name,
                "email": candidate.email,
                "phone": candidate.phone or None,
                "dob": candidate.date_of_birth or None,
                "custom_id": candidate.ref,
            },
        )
        location: dict[str, str] = {"country": "US"}
        if candidate.work_location:
            location["state"] = candidate.work_location
        invitation = self._call(
            creds,
            "POST",
            "/invitations",
            {
                "candidate_id": person["id"],
                "package": package or "tasker_standard",
                "work_locations": [location],
            },
        )
        return Initiated(
            external_id=str(invitation["id"]),
            status="invited",
            invite_url=str(invitation.get("invitation_url", "")),
            candidate_ref=str(person["id"]),
        )

    def fetch(self, creds: Credentials, external_id: str, candidate: Candidate) -> CheckState:
        invitation = self._call(creds, "GET", f"/invitations/{external_id}")
        status = str(invitation.get("status", ""))
        if status == "expired":
            return CheckState(status="expired", summary={"invitation": status})
        report_id = invitation.get("report_id")
        if not report_id:
            return CheckState(status="invited", summary={"invitation": status})
        report = self._call(creds, "GET", f"/reports/{report_id}")
        report_status = str(report.get("status", ""))
        mapped = REPORT_STATUS.get(report_status, "in_progress")
        result = ""
        if mapped == "completed":
            result = "unable" if report_status == "suspended" else str(report.get("result") or "")
            result = result if result in ("clear", "consider", "unable") else "consider"
        return CheckState(
            status=mapped,
            result=result,
            report_url=str(report.get("uri", "")),
            summary={
                "report_id": str(report_id),
                "status": report_status,
                "result": report.get("result"),
                "package": report.get("package"),
                "adjudication": report.get("adjudication"),
            },
        )

    def cancel(self, creds: Credentials, external_id: str) -> None:
        self._call(creds, "DELETE", f"/invitations/{external_id}")
