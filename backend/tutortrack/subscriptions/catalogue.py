"""The entitlement registry and the platform's plan catalogue (FR-04-1, FR-04-2).

Plans live in the database (the platform console manages them, E30); ``sync_plans`` writes
this catalogue there. It runs from a data migration and ``manage.py sync_plans`` and is
idempotent: Stripe price ids already stored are kept.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from django.utils.translation import gettext_lazy as _

FEATURES: dict[str, Any] = {
    "multi_branch": _("Multiple branches"),
    "payroll": _("Tutor payroll and expenses"),
    "pipeline": _("Enquiry pipeline"),
    "recruitment": _("Tutor recruitment and compliance"),
    "matching": _("Matching and job board"),
    "automation": _("Automations"),
    "courses": _("Courses and group programmes"),
    "api_access": _("API access"),
    "webhooks": _("Webhooks"),
    "custom_domain": _("Custom domain"),
    "white_label": _("White-label apps"),
    "sso_saml": _("SAML single sign-on"),
    "accounting_integrations": _("Accounting integrations"),
    "advanced_reports": _("Advanced reports"),
    "ai_assistant": _("AI assistant"),
}

LIMITS: dict[str, Any] = {
    "max_tutors": _("Tutors"),
    "max_branches": _("Branches"),
    "max_active_students": _("Active students"),
    "storage_gb": _("Storage (GB)"),
    "sms_credits_monthly": _("SMS credits each month"),
    "automation_rules": _("Automation rules"),
}

CURRENCIES = ("GBP", "USD", "EUR", "AUD", "CAD", "NZD")
ANNUAL_MONTHS = 10  # annual = 10 x monthly (two months free)


@dataclass(frozen=True)
class Component:
    key: str
    monthly: dict[str, str]  # per currency; revenue_share: a percentage
    included: int = 0


@dataclass(frozen=True)
class PlanDef:
    key: str
    name: str
    description: str
    rank: int
    features: frozenset[str]
    limits: dict[str, int | None]
    components: tuple[Component, ...] = ()
    visibility: str = "public"
    seat_mode: str = "delivered"
    annual: bool = True
    trial_days: int = 30
    extra: dict[str, Any] = field(default_factory=dict)


def _same(value: str) -> dict[str, str]:
    return dict.fromkeys(CURRENCIES, value)


def _prices(gbp: str, usd: str, eur: str, aud: str, cad: str, nzd: str) -> dict[str, str]:
    return dict(zip(CURRENCIES, (gbp, usd, eur, aud, cad, nzd), strict=True))


TEAM_FEATURES = frozenset(
    {"payroll", "pipeline", "courses", "automation", "api_access", "accounting_integrations"}
)
AGENCY_FEATURES = TEAM_FEATURES | {
    "multi_branch", "recruitment", "matching", "webhooks", "advanced_reports", "ai_assistant",
}  # fmt: skip
AGENCY_LIMITS: dict[str, int | None] = {
    "max_tutors": None, "max_branches": 10, "max_active_students": None, "storage_gb": 100,
    "sms_credits_monthly": 1000, "automation_rules": 50,
}  # fmt: skip

PLANS: tuple[PlanDef, ...] = (
    PlanDef(
        "solo",
        "Solo",
        "For an independent tutor: every core feature.",
        10,
        frozenset({"courses"}),
        {
            "max_tutors": 1,
            "max_branches": 1,
            "max_active_students": 40,
            "storage_gb": 5,
            "sms_credits_monthly": 50,
            "automation_rules": 0,
        },
        (Component("base_fee", _prices("19", "24", "22", "39", "33", "42")),),
    ),
    PlanDef(
        "team",
        "Team",
        "For 2 to 15 tutors: payroll, pipeline and automations.",
        20,
        TEAM_FEATURES,
        {
            "max_tutors": 15,
            "max_branches": 1,
            "max_active_students": 300,
            "storage_gb": 25,
            "sms_credits_monthly": 300,
            "automation_rules": 10,
        },
        (
            Component("base_fee", _prices("39", "49", "45", "79", "67", "85")),
            Component("active_tutor", _prices("6", "8", "7", "12", "10", "13"), included=2),
        ),
    ),
    PlanDef(
        "agency",
        "Agency",
        "For agencies and centres: branches, recruitment and matching.",
        30,
        AGENCY_FEATURES,
        AGENCY_LIMITS,
        (
            Component("base_fee", _prices("99", "125", "115", "199", "169", "215")),
            Component("active_tutor", _prices("5", "6", "6", "10", "9", "11"), included=10),
            Component("branch", _prices("25", "32", "29", "49", "42", "54"), included=1),
        ),
    ),
    PlanDef(
        "agency_payg",
        "Agency (pay as you go)",
        "Agency features for a share of the payments you take through TutorTrack.",
        30,
        AGENCY_FEATURES,
        AGENCY_LIMITS,
        (
            Component("revenue_share", _same("1.5")),
            Component("branch", _prices("25", "32", "29", "49", "42", "54"), included=1),
        ),
        annual=False,
    ),
    PlanDef(
        "enterprise",
        "Enterprise",
        "Large and multi-branch organisations: SSO, data residency and an SLA.",
        40,
        frozenset(FEATURES),
        {**dict.fromkeys(LIMITS), "sms_credits_monthly": 5000},
        visibility="custom",
    ),
)


def plan_def(key: str) -> PlanDef | None:
    return next((p for p in PLANS if p.key == key), None)


def sync_plans(models: Any = None) -> int:
    """Write the catalogue into the database. ``models`` = (Plan, PlanPrice,
    PlanEntitlement), for data migrations; the live models otherwise."""
    if models is None:
        from . import models as live

        models = (live.Plan, live.PlanPrice, live.PlanEntitlement)
    plan_model, price_model, entitlement_model = models
    for definition in PLANS:
        plan, _created = plan_model.objects.update_or_create(
            key=definition.key,
            defaults={
                "name": definition.name,
                "description": definition.description,
                "visibility": definition.visibility,
                "rank": definition.rank,
                "trial_days": definition.trial_days,
                "seat_mode": definition.seat_mode,
            },
        )
        for key in FEATURES:
            entitlement_model.objects.update_or_create(
                plan=plan, key=key,
                defaults={"bool_value": key in definition.features, "int_value": None},
            )  # fmt: skip
        for key in LIMITS:
            entitlement_model.objects.update_or_create(
                plan=plan, key=key,
                defaults={"bool_value": None, "int_value": definition.limits.get(key)},
            )  # fmt: skip
        intervals = ("month", "year") if definition.annual else ("month",)
        for component in definition.components:
            for currency, monthly in component.monthly.items():
                for interval in intervals:
                    amount = Decimal(monthly)
                    if interval == "year" and component.key != "revenue_share":
                        amount *= ANNUAL_MONTHS
                    price_model.objects.update_or_create(
                        plan=plan, currency=currency, interval=interval,
                        component=component.key,
                        defaults={"unit_amount": amount,
                                  "included_quantity": component.included},
                    )  # fmt: skip
    return len(PLANS)
