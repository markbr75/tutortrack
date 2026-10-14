"""In-memory background check providers (development and tests).

A fake check starts ``invited`` (or, for the DBS Update Service, completes at once) and
moves on when ``advance(external_id, ...)`` is called; ``outcome`` sets what the next
completion reports. State lives on the class so webhooks, workflows and tests share it."""

from __future__ import annotations

import uuid
from datetime import date
from typing import ClassVar

from tutortrack.integrations.providers import Credentials

from . import Candidate, CheckError, CheckState, Initiated


class FakeChecks:
    checks: ClassVar[dict[str, CheckState]] = {}
    by_ref: ClassVar[dict[str, str]] = {}
    outcome: ClassVar[str] = "clear"
    refuse: ClassVar[bool] = False

    def __init__(self, provider: str) -> None:
        self.provider = provider

    @classmethod
    def reset(cls) -> None:
        cls.checks.clear()
        cls.by_ref.clear()
        cls.outcome = "clear"
        cls.refuse = False

    @classmethod
    def advance(cls, external_id: str, status: str = "completed", result: str = "") -> None:
        result = result or (cls.outcome if status == "completed" else "")
        cls.checks[external_id] = CheckState(
            status=status,
            result=result,
            certificate_number="001234567890" if status == "completed" else "",
            issue_date=date(2026, 9, 1) if status == "completed" else None,
            report_url=f"https://checks.example.test/{external_id}"
            if status == "completed"
            else "",
            summary={"provider_status": status, "result": result},
        )

    def initiate(self, creds: Credentials, candidate: Candidate, package: str) -> Initiated:
        if self.refuse:
            raise CheckError("The provider refused the request (fake).")
        if candidate.ref in self.by_ref:
            external = self.by_ref[candidate.ref]
            return Initiated(external, self.checks[external].status)
        external = f"{self.provider}_{uuid.uuid4().hex[:12]}"
        self.by_ref[candidate.ref] = external
        if self.provider == "dbs_update":
            self.advance(external, "completed")
            return Initiated(external, "completed")
        self.checks[external] = CheckState(status="invited")
        return Initiated(external, "invited", f"https://checks.example.test/invite/{external}")

    def fetch(self, creds: Credentials, external_id: str, candidate: Candidate) -> CheckState:
        if external_id not in self.checks:
            raise CheckError("Unknown check (fake).")
        return self.checks[external_id]

    def cancel(self, creds: Credentials, external_id: str) -> None:
        if external_id in self.checks:
            self.checks[external_id] = CheckState(status="cancelled")


class ManualChecks:
    """Providers without an API (AU WWCC): staff verify on the state's page."""

    def initiate(self, creds: Credentials, candidate: Candidate, package: str) -> Initiated:
        return Initiated(f"manual_{candidate.ref}", "in_progress")

    def fetch(self, creds: Credentials, external_id: str, candidate: Candidate) -> CheckState:
        return CheckState(status="in_progress")

    def cancel(self, creds: Credentials, external_id: str) -> None:
        return None
