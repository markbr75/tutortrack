"""Tenant health scoring for customer success (E30 FR-30-6).

``collect_inputs()`` counts usage in the organisation in context (read-only, tenant
context, so RLS applies); ``score()`` turns the counts into components of 0-100 and a
weighted score. A component without data (no payments taken through TutorTrack, no NPS
answers) is left out and the other weights are scaled up.

| Component | Weight | 100 means |
|---|---|---|
| usage depth | 30 | all six modules used in 30 days (lessons, invoices, payments, |
|   |    | messages, lesson reports, leads) and all staff active in 14 days |
| active tutors trend | 20 | as many tutors teaching as in the previous 30 days (or more) |
| payments volume | 20 | as many payments as in the previous 30 days (or more) |
| reliability | 10 | no failed messages, webhooks or dead letters in 7 days (-10 each) |
| support | 10 | no support conversations in 30 days (-25 each) |
| NPS | 10 | NPS of +100 from the organisation's answers in 180 days (-100 is 0) |

Risk: 70+ healthy, 40-69 watch, under 40 at risk.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from tutortrack.core.time import now

WEIGHTS = {"usage": 30, "tutors": 20, "payments": 20, "reliability": 10, "support": 10, "nps": 10}
MODULES = 6
HEALTHY = 70
WATCH = 40


@dataclass(frozen=True)
class HealthInputs:
    modules_used: int = 0
    staff_total: int = 0
    staff_active: int = 0
    tutors_now: int = 0
    tutors_before: int = 0
    payments_now: int = 0
    payments_before: int = 0
    errors: int = 0
    support_conversations: int = 0
    nps: int | None = None  # -100..100
    nps_answers: int = 0


def _clamp(value: Decimal) -> int:
    return int(max(Decimal(0), min(Decimal(100), value)).quantize(Decimal(1), ROUND_HALF_UP))


def _trend(current: int, before: int) -> int:
    if before == 0:
        return 100 if current > 0 else 0
    return _clamp(Decimal(current) * 100 / before)


def components(inputs: HealthInputs) -> dict[str, int | None]:
    usage = Decimal(min(inputs.modules_used, MODULES)) * 70 / MODULES
    if inputs.staff_total:
        usage += Decimal(min(inputs.staff_active, inputs.staff_total)) * 30 / inputs.staff_total
    no_payments = inputs.payments_now == 0 and inputs.payments_before == 0
    return {
        "usage": _clamp(usage),
        "tutors": _trend(inputs.tutors_now, inputs.tutors_before),
        "payments": None if no_payments else _trend(inputs.payments_now, inputs.payments_before),
        "reliability": _clamp(Decimal(100 - 10 * inputs.errors)),
        "support": _clamp(Decimal(100 - 25 * inputs.support_conversations)),
        "nps": None if inputs.nps is None else _clamp(Decimal(inputs.nps + 100) / 2),
    }


def score(inputs: HealthInputs) -> tuple[int, str, dict[str, int | None]]:
    parts = components(inputs)
    weighted = [(WEIGHTS[k], v) for k, v in parts.items() if v is not None]
    total_weight = sum(w for w, _v in weighted)
    value = _clamp(Decimal(sum(w * v for w, v in weighted)) / total_weight)
    return value, risk_for(value), parts


def risk_for(value: int) -> str:
    if value >= HEALTHY:
        return "healthy"
    if value >= WATCH:
        return "watch"
    return "at_risk"


def nps(scores: list[int]) -> int | None:
    """Net Promoter Score: % promoters (9-10) minus % detractors (0-6), rounded."""
    if not scores:
        return None
    promoters = sum(1 for s in scores if s >= 9)
    detractors = sum(1 for s in scores if s <= 6)
    return int(
        (Decimal(promoters - detractors) * 100 / len(scores)).quantize(Decimal(1), ROUND_HALF_UP)
    )


def collect_inputs() -> HealthInputs:
    """Counts for the organisation in context (call inside ``tenant_context``)."""
    from tutortrack.billing.models import Invoice
    from tutortrack.comms.models import Message
    from tutortrack.core.context import require_organisation_id
    from tutortrack.core.models import OutboxEvent
    from tutortrack.delivery.models import LessonReport
    from tutortrack.identity.models import Membership
    from tutortrack.leads.models import Enquiry
    from tutortrack.payments.models import Payment, ProviderWebhookEvent
    from tutortrack.scheduling.models import Lesson, LessonTutor
    from tutortrack.success.models import SupportConversation, SurveyResponse

    at = now()
    month, previous, week = at - timedelta(days=30), at - timedelta(days=60), at - timedelta(days=7)
    lessons = Lesson.objects.exclude(status="cancelled")
    succeeded = Payment.objects.filter(status="succeeded")
    used = [
        lessons.filter(start__gte=month, start__lt=at).exists(),
        Invoice.objects.filter(issued_at__gte=month).exists(),
        succeeded.filter(received_at__gte=month).exists(),
        Message.objects.filter(created_at__gte=month).exists(),
        LessonReport.objects.filter(created_at__gte=month).exists(),
        Enquiry.objects.filter(created_at__gte=month).exists(),
    ]
    staff = Membership.objects.filter(
        status=Membership.Status.ACTIVE,
        role__in=["owner", "admin", "branch_manager", "coordinator", "finance"],
    )
    tutors = LessonTutor.objects.exclude(lesson__status="cancelled")
    errors = (
        Message.objects.filter(status="failed", created_at__gte=week).count()
        + ProviderWebhookEvent.objects.exclude(last_error="").filter(created_at__gte=week).count()
        + OutboxEvent.objects.filter(
            organisation_id=require_organisation_id(), dead_lettered_at__gte=week
        ).count()
    )
    answers = list(
        SurveyResponse.objects.filter(
            kind="nps", score__isnull=False, created_at__gte=at - timedelta(days=180)
        ).values_list("score", flat=True)
    )
    return HealthInputs(
        modules_used=sum(used),
        staff_total=staff.count(),
        staff_active=staff.filter(last_active_at__gte=at - timedelta(days=14)).count(),
        tutors_now=tutors.filter(lesson__start__gte=month, lesson__start__lt=at)
        .values("tutor")
        .distinct()
        .count(),
        tutors_before=tutors.filter(lesson__start__gte=previous, lesson__start__lt=month)
        .values("tutor")
        .distinct()
        .count(),
        payments_now=succeeded.filter(received_at__gte=month).count(),
        payments_before=succeeded.filter(received_at__gte=previous, received_at__lt=month).count(),
        errors=errors,
        support_conversations=SupportConversation.objects.filter(created_at__gte=month).count(),
        nps=nps([int(s) for s in answers if s is not None]),
        nps_answers=len(answers),
    )


def as_dict(inputs: HealthInputs) -> dict[str, Any]:
    return asdict(inputs)
