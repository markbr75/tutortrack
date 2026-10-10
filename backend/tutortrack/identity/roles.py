"""Built-in roles (FR-03-5) as permission *patterns* with data scopes.

A grant is ``"pattern"`` or ``"pattern:scope"`` where scope is ``all`` (default),
``branch`` (records in the member's branches) or ``own`` (records linked to the user).
Patterns use shell wildcards over registered codenames, so permissions added by later
apps (``billing.invoice.issue``...) are covered by ``"billing.*"`` without editing roles.
Custom roles (clone + edit) arrive in Phase 2 (E03-T11) as database rows using the same
grant format.
"""

from __future__ import annotations

from dataclasses import dataclass

SCOPES = ("all", "branch", "own")
SCOPE_RANK = {"own": 0, "branch": 1, "all": 2}


@dataclass(frozen=True)
class Grant:
    pattern: str
    scope: str = "all"

    @classmethod
    def parse(cls, raw: str) -> Grant:
        pattern, _, scope = raw.partition(":")
        scope = scope or "all"
        if scope not in SCOPES:
            raise ValueError(f"Unknown scope in grant {raw!r}")
        return cls(pattern, scope)


@dataclass(frozen=True)
class RoleDef:
    key: str
    name: str
    description: str
    grants: tuple[Grant, ...]
    denies: tuple[str, ...] = ()  # patterns removed even if granted
    is_staff: bool = True  # staff roles are subject to "require 2FA for staff"


def _g(*raw: str) -> tuple[Grant, ...]:
    return tuple(Grant.parse(r) for r in raw)


# Codenames an Admin never gets (ownership and the SaaS subscription, FR-03-5).
OWNER_ONLY = ("org.close", "subscription.manage", "membership.transfer_ownership")

ROLES: dict[str, RoleDef] = {
    r.key: r
    for r in (
        RoleDef("owner", "Owner", "Everything, including subscription and closing the account.",
                _g("*")),
        RoleDef("admin", "Admin", "Everything except changing the subscription and ownership.",
                _g("*"), denies=(*OWNER_ONLY, "impersonation.write")),
        RoleDef(
            "branch_manager", "Branch Manager", "Admin rights within assigned branches.",
            _g("*:branch", "org.settings.view"),
            denies=(*OWNER_ONLY, "subscription.view", "org.settings.manage", "org.branch.manage",
                    "audit.*"),
        ),
        RoleDef(
            "coordinator", "Coordinator",
            "People, jobs, scheduling, communications and leads; can view invoices.",
            _g("people.*", "crm.*", "jobs.*", "scheduling.*", "delivery.*", "comms.*", "leads.*",
               "matching.*", "billing.invoice.view", "billing.rates.view_charge", "catalogue.view",
               "org.settings.view", "team.view", "privacy.consent.view",
               "privacy.consent.record"),
            denies=("people.tutor.view_financial", "scheduling.edit_locked"),
        ),
        RoleDef(
            "finance", "Finance",
            "Billing, payments, payroll, accounting integrations and reports.",
            _g("billing.*", "payments.*", "payroll.*", "integrations.accounting.*",
               "reporting.*", "people.client.view", "org.settings.view", "team.view",
               "crm.note.view", "crm.search", "catalogue.view", "rates.manage",
               "subscription.view"),
        ),
        RoleDef(
            "tutor", "Tutor",
            "Own schedule and students, lesson reports, own pay and expenses, availability.",
            _g("scheduling.lesson.view:own", "scheduling.lesson.complete:own",
               "scheduling.availability.*:own", "scheduling.event.view:own",
               "people.tutor.view:own", "people.tutor.edit:own", "crm.note.view",
               "crm.note.create", "crm.task.view:own", "crm.task.edit:own", "crm.search",
               "catalogue.view", "jobs.job.view:own",
               "people.student.view:own", "delivery.report.view:own", "delivery.report.write:own",
               "delivery.attendance.edit:own", "payroll.payitem.view:own",
               "payroll.expense.*:own", "learning.*:own"),
        ),
        RoleDef("client", "Client", "Portal: own household's students, lessons and invoices.",
                _g("portal.client.*:own"), is_staff=False),
        RoleDef("student", "Student", "Portal: own lessons, homework and shared reports.",
                _g("portal.student.*:own"), is_staff=False),
        RoleDef("affiliate", "Affiliate", "Affiliate portal.",
                _g("portal.affiliate.*:own"), is_staff=False),
    )
}  # fmt: skip


def role(key: str) -> RoleDef:
    return ROLES[key]
