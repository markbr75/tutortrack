"""Cancellation policy evaluation (FR-09-2, FR-09-3, E09-T02).

A policy's ``rules`` (JSON, merged over ``DEFAULT_RULES``)::

    {"free_window_hours": 24,                       # notice needed for a free cancellation
     "late_cancellation": {"charge_percent": 100, "pay_percent": 50},
     "no_show": {"charge_percent": 100, "pay_percent": 100},
     "absent_notified": {"charge_percent": 0, "pay_percent": 0},
     "late": {"charge_percent": 100, "pay_percent": 100},
     "tutor_cancellation": {"charge_percent": 0, "pay_percent": 0},
     "admin_cancellation": {"charge_percent": 0, "pay_percent": 0},
     "max_free_per_month": null,                     # then further ones count as late
     "makeup_credit": {"on_free_cancellation": false, "on_tutor_cancellation": false,
                       "valid_days": 60}}

Resolution: the most specific active policy wins, client → job → service → branch →
organisation; without one the defaults apply. A client policy applies when every attendee
belongs to that client.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from django.utils.translation import gettext as _

from tutortrack.core.exceptions import BusinessRuleViolation
from tutortrack.scheduling.models import Lesson, LessonAttendee

from .models import CancellationPolicy

PERCENT_KEYS = (
    "late_cancellation",
    "no_show",
    "absent_notified",
    "late",
    "tutor_cancellation",
    "admin_cancellation",
)
DEFAULT_RULES: dict[str, Any] = {
    "free_window_hours": 24,
    "late_cancellation": {"charge_percent": 100, "pay_percent": 50},
    "no_show": {"charge_percent": 100, "pay_percent": 100},
    "absent_notified": {"charge_percent": 0, "pay_percent": 0},
    "late": {"charge_percent": 100, "pay_percent": 100},
    "tutor_cancellation": {"charge_percent": 0, "pay_percent": 0},
    "admin_cancellation": {"charge_percent": 0, "pay_percent": 0},
    "max_free_per_month": None,
    "makeup_credit": {
        "on_free_cancellation": False,
        "on_tutor_cancellation": False,
        "valid_days": 60,
    },
}
FULL = Decimal(100)
NONE = Decimal(0)


def _invalid(message: str) -> BusinessRuleViolation:
    return BusinessRuleViolation(message, extra={"errors": {"rules": [message]}})


def _percent(value: Any) -> Decimal:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise _invalid(_("Percentages must be numbers from 0 to 100.")) from None
    if not NONE <= number <= FULL:
        raise _invalid(_("Percentages must be numbers from 0 to 100."))
    return number


def clean_rules(raw: dict[str, Any] | None) -> dict[str, Any]:
    """Merge ``raw`` over the defaults and validate. Returns JSON-safe rules."""
    rules = copy.deepcopy(DEFAULT_RULES)
    raw = raw or {}
    unknown = set(raw) - set(rules)
    if unknown:
        raise _invalid(_("Unknown policy rule: %(name)s.") % {"name": sorted(unknown)[0]})
    for key in PERCENT_KEYS:
        part = raw.get(key) or {}
        for side in ("charge_percent", "pay_percent"):
            if side in part:
                rules[key][side] = str(_percent(part[side]))
            else:
                rules[key][side] = str(rules[key][side])
    hours = raw.get("free_window_hours", rules["free_window_hours"])
    if not isinstance(hours, int) or isinstance(hours, bool) or not 0 <= hours <= 24 * 30:
        raise _invalid(_("The free cancellation window is a whole number of hours."))
    rules["free_window_hours"] = hours
    limit = raw.get("max_free_per_month", rules["max_free_per_month"])
    if limit is not None and (not isinstance(limit, int) or isinstance(limit, bool) or limit < 0):
        raise _invalid(_("The monthly free cancellation limit is a whole number."))
    rules["max_free_per_month"] = limit
    makeup = {**rules["makeup_credit"], **(raw.get("makeup_credit") or {})}
    if set(makeup) - set(DEFAULT_RULES["makeup_credit"]):
        raise _invalid(_("Unknown makeup credit option."))
    days = makeup["valid_days"]
    if not isinstance(days, int) or isinstance(days, bool) or not 1 <= days <= 730:
        raise _invalid(_("Makeup credits last between 1 and 730 days."))
    makeup["on_free_cancellation"] = bool(makeup["on_free_cancellation"])
    makeup["on_tutor_cancellation"] = bool(makeup["on_tutor_cancellation"])
    rules["makeup_credit"] = makeup
    return rules


@dataclass(frozen=True)
class ResolvedPolicy:
    policy: CancellationPolicy | None
    rules: dict[str, Any]

    def snapshot(self) -> dict[str, Any]:
        return {
            "policy_id": str(self.policy.pk) if self.policy else None,
            "name": self.policy.name if self.policy else _("Default policy"),
            "version": self.policy.version if self.policy else 0,
            "rules": self.rules,
        }

    def percents(self, key: str) -> tuple[Decimal, Decimal]:
        part = self.rules[key]
        return Decimal(part["charge_percent"]), Decimal(part["pay_percent"])


def resolve(lesson: Lesson) -> ResolvedPolicy:
    clients = {a.client_id for a in lesson.attendees.all()}
    candidates: list[tuple[str, Any]] = []
    if len(clients) == 1:
        candidates.append((CancellationPolicy.Scope.CLIENT, clients.pop()))
    if lesson.job_id:
        candidates.append((CancellationPolicy.Scope.JOB, lesson.job_id))
    candidates += [
        (CancellationPolicy.Scope.SERVICE, lesson.service_id),
        (CancellationPolicy.Scope.BRANCH, lesson.branch_id),
    ]
    active = CancellationPolicy.objects.filter(active=True)
    for scope_type, scope_id in candidates:
        policy = active.filter(scope_type=scope_type, scope_id=scope_id).first()
        if policy is not None:
            return ResolvedPolicy(policy, clean_rules(policy.rules))
    default = active.filter(scope_type=CancellationPolicy.Scope.ORGANISATION).first()
    if default is not None:
        return ResolvedPolicy(default, clean_rules(default.rules))
    return ResolvedPolicy(None, clean_rules({}))


@dataclass(frozen=True)
class CancellationDecision:
    kind: str  # free | late | tutor | admin
    charge_percent: Decimal
    pay_percent: Decimal
    notice_minutes: int
    makeup_credit: bool
    makeup_valid_days: int
    free_used: int = 0
    policy: ResolvedPolicy = field(default_factory=lambda: ResolvedPolicy(None, DEFAULT_RULES))

    @property
    def message(self) -> str:
        values = {
            "charge": _format_percent(self.charge_percent),
            "pay": _format_percent(self.pay_percent),
        }
        if self.kind == "free":
            text = _("This is a free cancellation: no charge to the client.")
        elif self.kind == "late":
            text = (
                _("This is a late cancellation: client charged %(charge)s, tutor paid %(pay)s.")
                % values
            )
        elif self.kind == "tutor":
            text = _("The tutor cancelled: client charged %(charge)s, tutor paid %(pay)s.") % values
        else:
            text = _("Cancelled by us: client charged %(charge)s, tutor paid %(pay)s.") % values
        if self.makeup_credit:
            text += " " + _("The student gets a makeup lesson credit.")
        return text


def _format_percent(value: Decimal) -> str:
    return f"{value.normalize():f}%"


def evaluate_cancellation(
    lesson: Lesson,
    *,
    cancelled_by: str,
    at: datetime,
    free_used_this_month: int = 0,
    resolved: ResolvedPolicy | None = None,
) -> CancellationDecision:
    policy = resolved or resolve(lesson)
    rules = policy.rules
    notice = int((lesson.start - at).total_seconds() // 60)
    makeup = rules["makeup_credit"]
    if cancelled_by == "tutor":
        charge, pay = policy.percents("tutor_cancellation")
        return CancellationDecision(
            "tutor", charge, pay, notice, makeup["on_tutor_cancellation"], makeup["valid_days"],
            free_used_this_month, policy,
        )  # fmt: skip
    if cancelled_by == "admin":
        charge, pay = policy.percents("admin_cancellation")
        return CancellationDecision(
            "admin", charge, pay, notice, False, makeup["valid_days"], free_used_this_month, policy
        )
    limit = rules["max_free_per_month"]
    in_window = notice >= rules["free_window_hours"] * 60
    if in_window and (limit is None or free_used_this_month < limit):
        return CancellationDecision(
            "free", NONE, NONE, notice, makeup["on_free_cancellation"], makeup["valid_days"],
            free_used_this_month, policy,
        )  # fmt: skip
    charge, pay = policy.percents("late_cancellation")
    return CancellationDecision(
        "late", charge, pay, notice, False, makeup["valid_days"], free_used_this_month, policy
    )


OUTCOME_RULE = {
    LessonAttendee.Outcome.PRESENT: None,
    LessonAttendee.Outcome.LATE: "late",
    LessonAttendee.Outcome.ABSENT_NOTIFIED: "absent_notified",
    LessonAttendee.Outcome.NO_SHOW: "no_show",
    LessonAttendee.Outcome.CANCELLED_CLIENT: "late_cancellation",
    LessonAttendee.Outcome.CANCELLED_TUTOR: "tutor_cancellation",
    LessonAttendee.Outcome.CANCELLED_ADMIN: "admin_cancellation",
}


def attendance_percents(policy: ResolvedPolicy, outcome: str) -> tuple[Decimal, Decimal]:
    """(charge %, pay %) for one attendee's outcome at completion."""
    key = OUTCOME_RULE.get(outcome)  # type: ignore[call-overload]
    return (FULL, FULL) if key is None else policy.percents(key)


def tutor_pay_percent(policy: ResolvedPolicy, outcomes: list[str]) -> Decimal:
    """The tutor is paid in full if anyone attended; otherwise the best outcome's share."""
    if not outcomes:
        return FULL
    return max(attendance_percents(policy, outcome)[1] for outcome in outcomes)
