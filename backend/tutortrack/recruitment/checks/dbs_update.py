"""DBS Update Service status checks (UK, E18-T11).

The government's free status check: with the tutor's consent, an employer checks whether
an existing DBS certificate (on the Update Service) is still current. No account is
needed; the request names the organisation and the person checking. The answer is one of
``BLANK_NO_NEW_INFO``, ``NON_BLANK_NO_NEW_INFO`` (still current), ``NEW_INFO`` (new
information since issue: apply for a new check) or ``NO_MATCH_FOUND``.

The response is a small XML document; we read the one element we need with a regular
expression rather than an XML parser (no entity expansion of untrusted XML). The check
is re-run on a timer by ``BackgroundCheckWorkflow`` (``recheck_days``).
"""

from __future__ import annotations

import re
import urllib.parse
from datetime import date

from django.conf import settings

from tutortrack.integrations.providers import Credentials, ProviderError, http

from . import Candidate, CheckError, CheckState, Initiated

RESULT = {
    "BLANK_NO_NEW_INFO": "clear",
    "NON_BLANK_NO_NEW_INFO": "clear",
    "NEW_INFO": "consider",
    "NO_MATCH_FOUND": "unable",
}
ELEMENT = re.compile(r"<statusCheckResultType>\s*([A-Z_]+)\s*</statusCheckResultType>")


def parse(body: bytes) -> str:
    match = ELEMENT.search(body.decode("utf-8", "replace"))
    return match.group(1) if match else ""


def status_url(candidate: Candidate) -> str:
    dob = date.fromisoformat(candidate.date_of_birth) if candidate.date_of_birth else None
    query = urllib.parse.urlencode(
        {
            "dateOfBirth": dob.strftime("%d/%m/%Y") if dob else "",
            "surname": candidate.last_name.upper(),
            "hasAgreedTermsAndConditions": "true",
            "organisationName": candidate.organisation_name,
            "employeeSurname": candidate.requester_last_name,
            "employeeForename": candidate.requester_first_name,
        }
    )
    base = str(settings.BACKGROUND_CHECKS["DBS_UPDATE_SERVICE_URL"]).rstrip("/")
    number = re.sub(r"\D", "", candidate.certificate_number)
    return f"{base}/{number}?{query}"


class DBSUpdateServiceClient:
    def _check(self, candidate: Candidate) -> CheckState:
        if not candidate.certificate_number or not candidate.date_of_birth:
            raise CheckError("A status check needs the certificate number and date of birth.")
        try:
            response = http.request(
                "GET",
                status_url(candidate),
                headers={"Accept": "application/xml"},
                user_url=True,
                provider="dbs_update",
            )
        except ProviderError as exc:
            raise CheckError(str(exc)) from exc
        outcome = parse(response.body)
        if not outcome:
            raise CheckError("The DBS Update Service gave no answer.")
        return CheckState(
            status="completed",
            result=RESULT.get(outcome, "unable"),
            certificate_number=re.sub(r"\D", "", candidate.certificate_number),
            summary={"status_check": outcome},
        )

    def initiate(self, creds: Credentials, candidate: Candidate, package: str) -> Initiated:
        self._check(candidate)  # fails early on a wrong number or name
        return Initiated(external_id=f"dbs-update-{candidate.ref}", status="completed")

    def fetch(self, creds: Credentials, external_id: str, candidate: Candidate) -> CheckState:
        return self._check(candidate)

    def cancel(self, creds: Credentials, external_id: str) -> None:
        return None
