"""Background check providers (E18-T11, FR-18-7).

Each provider turns a tutor (``Candidate``) into a check at an online screening service and
reports where it got to (``CheckState``). Providers:

* ``ucheck`` (UK, DBS basic/standard/enhanced through uCheck's API: the tutor completes
  the application from an invitation link; polled);
* ``dbs_update`` (UK, DBS Update Service status check of an existing certificate: the
  government's free API; re-checked on a timer);
* ``checkr`` (US, criminal background checks through Checkr invitations; signed webhooks);
* ``wwcc`` (Australia, Working With Children Checks: no API, the state's verification page
  for staff to confirm by hand).

The organisation connects uCheck and Checkr with an API key (integration framework,
stored encrypted); the DBS Update Service needs no account. Without live credential
providers (development, tests) every provider is the in-memory ``FakeChecks``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Protocol

from django.conf import settings
from django.utils.translation import gettext_lazy as _

from tutortrack.integrations.providers import Credentials


@dataclass(frozen=True)
class Candidate:
    ref: str  # our check id (the provider's reference / idempotency key)
    first_name: str
    last_name: str
    email: str
    phone: str = ""
    date_of_birth: str = ""  # ISO date
    country: str = ""
    certificate_number: str = ""  # DBS Update Service status checks
    work_location: str = ""  # Checkr: state, e.g. "CA"
    organisation_name: str = ""  # DBS Update Service: who is checking
    requester_first_name: str = ""
    requester_last_name: str = ""


@dataclass(frozen=True)
class Initiated:
    external_id: str
    status: str = "invited"  # invited | in_progress | completed
    invite_url: str = ""
    candidate_ref: str = ""  # the provider's id for the person (Checkr candidate)


@dataclass(frozen=True)
class CheckState:
    status: str  # invited | in_progress | completed | cancelled | expired
    result: str = ""  # clear | consider | unable
    certificate_number: str = ""
    issue_date: date | None = None
    report_url: str = ""
    summary: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderInfo:
    key: str
    label: Any
    countries: tuple[str, ...]
    requirement_keys: tuple[str, ...]  # compliance requirement types a clear check satisfies
    packages: tuple[tuple[str, Any], ...] = ()
    connection: bool = True  # needs an API key connection
    webhooks: bool = False
    poll_hours: int = 6
    manual: bool = False  # verification links only (no API)
    recheck_days: int = 0  # re-run on a timer (DBS Update Service)


class CheckClient(Protocol):
    def initiate(self, creds: Credentials, candidate: Candidate, package: str) -> Initiated: ...

    def fetch(self, creds: Credentials, external_id: str, candidate: Candidate) -> CheckState: ...

    def cancel(self, creds: Credentials, external_id: str) -> None: ...


class CheckError(Exception):
    """The provider refused or is unreachable (message is safe to show staff)."""


PROVIDERS: dict[str, ProviderInfo] = {
    "ucheck": ProviderInfo(
        "ucheck",
        _("uCheck (DBS checks)"),
        ("GB",),
        ("dbs_enhanced",),
        packages=(
            ("enhanced", _("Enhanced DBS")),
            ("enhanced_barred", _("Enhanced DBS with children's barred list")),
            ("standard", _("Standard DBS")),
            ("basic", _("Basic DBS")),
        ),
        poll_hours=6,
    ),
    "dbs_update": ProviderInfo(
        "dbs_update",
        _("DBS Update Service status check"),
        ("GB",),
        ("dbs_enhanced",),
        connection=False,
        recheck_days=90,
    ),
    "checkr": ProviderInfo(
        "checkr",
        _("Checkr (US background checks)"),
        ("US",),
        ("background_check",),
        packages=(
            ("tasker_standard", _("Standard criminal")),
            ("driver_pro", _("Criminal and driving")),
        ),
        webhooks=True,
        poll_hours=12,
    ),
    "wwcc": ProviderInfo(
        "wwcc",
        _("Working With Children Check (Australia)"),
        ("AU",),
        ("wwcc",),
        connection=False,
        manual=True,
    ),
}

# State verification pages for AU Working With Children Checks (FR-18-7 "verification links").
WWCC_LINKS = {
    "NSW": "https://wwccheck.ocg.nsw.gov.au/Employers/Search",
    "VIC": "https://online.justice.vic.gov.au/wwccu/checkstatus.doj",
    "QLD": "https://www.bluecard.qld.gov.au/onlineservices/",
    "WA": "https://workingwithchildren.wa.gov.au/card-validation",
    "SA": "https://screening.sa.gov.au/",
    "TAS": "https://www.cbos.tas.gov.au/topics/licensing-and-registration/registrations/work-with-vulnerable-people",
    "ACT": "https://www.accesscanberra.act.gov.au/",
    "NT": "https://forms.pfes.nt.gov.au/safent/",
}


def info(provider: str) -> ProviderInfo:
    try:
        return PROVIDERS[provider]
    except KeyError:
        raise CheckError(f"Unknown background check provider {provider!r}.") from None


def live() -> bool:
    return bool(settings.INTEGRATIONS["CREDENTIAL_PROVIDERS_LIVE"])


def client(provider: str) -> CheckClient:
    if info(provider).manual:
        from .fake import ManualChecks

        return ManualChecks()
    if not live():
        from .fake import FakeChecks

        return FakeChecks(provider)
    if provider == "ucheck":
        from .ucheck import UCheckClient

        return UCheckClient()
    if provider == "dbs_update":
        from .dbs_update import DBSUpdateServiceClient

        return DBSUpdateServiceClient()
    if provider == "checkr":
        from .checkr import CheckrClient

        return CheckrClient()
    from .fake import ManualChecks

    return ManualChecks()


def _register() -> None:
    """uCheck and Checkr connect with an API key in the integration framework."""
    from tutortrack.integrations import providers as registry
    from tutortrack.integrations.providers import Provider, ProviderSpec

    def verifier(key: str) -> Any:
        def make() -> Any:
            if key == "checkr":
                from .checkr import CheckrClient

                return CheckrClient()
            from .ucheck import UCheckClient

            return UCheckClient()

        return make

    for key in ("ucheck", "checkr"):
        registry.register(
            Provider(
                ProviderSpec(
                    key,
                    str(PROVIDERS[key].label),
                    frozenset({"background_checks"}),
                    "credentials",
                    ("organisation",),
                    credential_fields=("api_key",),
                    manage_permission="compliance.manage_types",
                ),
                live=live,
                credentials=verifier(key),
            )
        )


_register()
