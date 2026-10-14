"""Growth reads (E25): scoped querysets, rating aggregates, portal dashboards and the reads
of other apps' records that attribution and commission need (read-only)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from django.db.models import Avg, Count, Q, QuerySet, Sum

from tutortrack.core.context import current_branch_ids
from tutortrack.core.money import Money
from tutortrack.core.permissions import permission_scope
from tutortrack.tenancy.settings_service import get_setting

from .models import (
    Affiliate,
    AffiliateLink,
    AffiliateReferral,
    AffiliateStatement,
    CommissionItem,
    CommissionRule,
    Referral,
    ReferralProgram,
    Review,
    ReviewRequest,
    TutorReferral,
)


def _scoped(
    user: Any, qs: QuerySet[Any], codename: str, *, branch_path: str | None = None
) -> QuerySet[Any]:
    """Tenant models without a branch: ``all`` sees everything, ``branch`` the records of
    clients in the user's branches (via ``branch_path``), ``own`` the model's own scope."""
    scope = permission_scope(user, codename)
    if scope is None:
        return qs.none()
    if scope == "own":
        own_q = getattr(qs.model, "own_scope_q", None)
        return qs.filter(own_q(user)) if callable(own_q) else qs.none()
    if scope == "branch" and branch_path:
        ids = current_branch_ids()
        if ids is not None:
            return qs.filter(**{f"{branch_path}__in": list(ids)})
    return qs


# --- reviews ------------------------------------------------------------------------------------


def reviews(user: Any) -> QuerySet[Review]:
    qs = Review.objects.select_related("client", "tutor", "student", "testimonial")
    if permission_scope(user, "growth.review.view") == "own" and not get_setting(
        "growth.tutors_see_reviews"
    ):
        return qs.none()
    return _scoped(user, qs, "growth.review.view", branch_path="client__branch_id")


def review_requests(user: Any) -> QuerySet[ReviewRequest]:
    qs = ReviewRequest.objects.select_related("client", "tutor", "student")
    if permission_scope(user, "growth.review.view") == "own":
        return qs.none()
    return _scoped(user, qs, "growth.review.view", branch_path="client__branch_id")


def tutor_ratings(tutor_ids: list[Any]) -> dict[str, tuple[float, int]]:
    """Average approved rating and count per tutor (E19 matching, E24 directory)."""
    rows = (
        Review.objects.filter(tutor_id__in=list(tutor_ids), status=Review.Status.APPROVED)
        .values("tutor_id")
        .annotate(avg=Avg("rating"), n=Count("id"))
    )
    return {str(r["tutor_id"]): (float(r["avg"]), int(r["n"])) for r in rows}


def rating_summary(qs: QuerySet[Review] | None = None, *, tutor_id: Any = None) -> dict[str, Any]:
    """Average, count and star distribution of approved reviews (one tutor, or the whole
    organisation)."""
    qs = (qs if qs is not None else Review.objects.all()).filter(status=Review.Status.APPROVED)
    if tutor_id is not None:
        qs = qs.filter(tutor_id=tutor_id)
    agg = qs.aggregate(avg=Avg("rating"), n=Count("id"))
    stars = {str(k): 0 for k in range(1, 6)}
    for row in qs.order_by().values("rating").annotate(n=Count("id")):
        stars[str(row["rating"])] = int(row["n"])
    average = agg["avg"]
    return {
        "average": round(float(average), 2) if average is not None else None,
        "count": int(agg["n"] or 0),
        "stars": stars,
    }


def public_rating(tutor_id: Any) -> tuple[float, int] | None:
    """For the public directory (only when ``growth.show_ratings_publicly``)."""
    if not get_setting("growth.show_ratings_publicly"):
        return None
    found = tutor_ratings([tutor_id]).get(str(tutor_id))
    return (round(found[0], 1), found[1]) if found else None


def published_reviews(limit: int, min_rating: int | None = None) -> list[dict[str, Any]]:
    """Approved reviews the family agreed to publish (for widgets that want reviews, not
    curated testimonials)."""
    qs = Review.objects.filter(status=Review.Status.APPROVED, publish_consent=True).exclude(text="")
    if min_rating:
        qs = qs.filter(rating__gte=min_rating)
    return [
        {"id": str(r.pk), "quote": r.text, "author": r.reviewer_name, "rating": r.rating}
        for r in qs.order_by("-created_at")[:limit]
    ]


# --- referrals ----------------------------------------------------------------------------------


def programs(user: Any) -> QuerySet[ReferralProgram]:
    if permission_scope(user, "growth.referral.view") in (None, "own"):
        return ReferralProgram.objects.none()
    return ReferralProgram.objects.all()


def referrals(user: Any) -> QuerySet[Referral]:
    return _scoped(
        user,
        Referral.objects.select_related("referrer", "referee", "program", "code"),
        "growth.referral.view",
        branch_path="referee__branch_id",
    )


def referral_dashboard(client_ids: list[Any]) -> dict[str, Any]:
    """The client portal's referral page: code, rewards and the families referred
    (first names of the household only: no contact details of other families)."""
    from . import services

    rows = Referral.objects.filter(referrer_id__in=client_ids).select_related("referee")
    earned: dict[str, Decimal] = {}
    for r in rows.filter(status=Referral.Status.REWARDED, referrer_credit_amount__isnull=False):
        earned[r.currency] = earned.get(r.currency, Decimal(0)) + r.referrer_credit.amount
    return {
        "referrals": [
            {
                "id": r.pk,
                "name": _first_word(r.referee.display_name),
                "status": r.status,
                "created_at": r.created_at,
                "rewarded_at": r.rewarded_at,
                "reward": r.referrer_credit.to_dict() if r.referrer_credit else None,
            }
            for r in rows.order_by("-created_at")[:100]
        ],
        "earned": [
            Money(amount, currency).to_dict() for currency, amount in sorted(earned.items())
        ],
        "program": services.active_program(),
    }


def _first_word(name: str) -> str:
    """ "The Smith Family" → "The S." (privacy-limited names for portals)."""
    words = [w for w in (name or "").split() if w]
    if not words:
        return ""
    if len(words) == 1:
        return f"{words[0][:1]}."
    return f"{words[0]} {words[1][:1]}."


# --- affiliates ---------------------------------------------------------------------------------


AFFILIATE_VIEW = "growth.affiliate.view"


def affiliates(user: Any) -> QuerySet[Affiliate]:
    return _scoped(user, Affiliate.objects.all(), AFFILIATE_VIEW)


def affiliate_links(user: Any) -> QuerySet[AffiliateLink]:
    return _scoped(user, AffiliateLink.objects.select_related("affiliate"), AFFILIATE_VIEW)


def affiliate_referrals(user: Any) -> QuerySet[AffiliateReferral]:
    return _scoped(
        user,
        AffiliateReferral.objects.select_related("affiliate", "client", "link"),
        AFFILIATE_VIEW,
        branch_path="client__branch_id",
    )


def commission_rules(user: Any) -> QuerySet[CommissionRule]:
    if permission_scope(user, AFFILIATE_VIEW) in (None, "own"):
        return CommissionRule.objects.none()
    return CommissionRule.objects.select_related("affiliate")


def commission_items(user: Any) -> QuerySet[CommissionItem]:
    return _scoped(
        user,
        CommissionItem.objects.select_related("affiliate", "client", "statement"),
        AFFILIATE_VIEW,
    )


def statements(user: Any) -> QuerySet[AffiliateStatement]:
    return _scoped(
        user,
        AffiliateStatement.objects.select_related("affiliate").annotate(item_count=Count("items")),
        AFFILIATE_VIEW,
    )


def affiliate_for(user: Any) -> Affiliate | None:
    """The affiliate record of a signed-in affiliate (portal)."""
    if not getattr(user, "is_authenticated", False):
        return None
    return Affiliate.objects.filter(user=user).exclude(status=Affiliate.Status.ARCHIVED).first()


def affiliate_summary(affiliate: Affiliate) -> dict[str, Any]:
    """Totals for the affiliate's dashboard (portal and staff record page)."""
    items = CommissionItem.objects.filter(affiliate=affiliate)
    totals: dict[str, dict[str, Decimal]] = {}
    for row in items.values("currency", "statement__status").annotate(t=Sum("amount_amount")):
        bucket = totals.setdefault(
            row["currency"], {"earned": Decimal(0), "unpaid": Decimal(0), "paid": Decimal(0)}
        )
        value = row["t"] or Decimal(0)
        bucket["earned"] += value
        bucket["paid" if row["statement__status"] == "paid" else "unpaid"] += value
    referrals_qs = AffiliateReferral.objects.filter(affiliate=affiliate)
    clicks = AffiliateLink.objects.filter(affiliate=affiliate).aggregate(c=Sum("clicks"))["c"]
    return {
        "clicks": int(clicks or 0),
        "referred": referrals_qs.count(),
        "converted": referrals_qs.filter(converted_at__isnull=False).count(),
        "totals": [
            {
                "currency": currency,
                "earned": Money(v["earned"], currency).round_to_minor().to_dict(),
                "unpaid": Money(v["unpaid"], currency).round_to_minor().to_dict(),
                "paid": Money(v["paid"], currency).round_to_minor().to_dict(),
            }
            for currency, v in sorted(totals.items())
        ],
    }


def portal_referred_clients(affiliate: Affiliate) -> list[dict[str, Any]]:
    """FR-25-3 privacy-limited list: initials-style names, dates and commission only."""
    rows = AffiliateReferral.objects.filter(affiliate=affiliate).select_related("client")
    earned = {
        str(r["referral_id"]): (r["t"], r["currency"])
        for r in CommissionItem.objects.filter(affiliate=affiliate, referral__isnull=False)
        .values("referral_id", "currency")
        .annotate(t=Sum("amount_amount"))
    }
    out = []
    for r in rows.order_by("-attributed_at")[:500]:
        total = earned.get(str(r.pk))
        out.append(
            {
                "id": r.pk,
                "name": _first_word(r.client.display_name),
                "attributed_at": r.attributed_at,
                "converted_at": r.converted_at,
                "commission": Money(total[0], total[1]).round_to_minor().to_dict()
                if total
                else None,
            }
        )
    return out


# --- tutor referrals ----------------------------------------------------------------------------


def tutor_referrals(user: Any) -> QuerySet[TutorReferral]:
    return _scoped(
        user,
        TutorReferral.objects.select_related("referrer", "referred_tutor", "client"),
        "growth.tutor_referral.view",
    )


# --- reads of other apps (attribution, commission, fraud checks) -------------------------------


def enquiry_ref(enquiry_id: Any) -> tuple[Any, str] | None:
    """The enquiry's client and the ``ref`` code it arrived with (E17 UTM data)."""
    from tutortrack.leads.models import Enquiry

    enquiry = Enquiry.objects.select_related("client").filter(pk=enquiry_id).first()
    if enquiry is None:
        return None
    ref = str((enquiry.utm or {}).get("ref") or "")
    return (enquiry.client, ref) if ref else None


def enquiry_people(enquiry_id: Any) -> tuple[Any, Any, Any] | None:
    """Client, trial tutor and student of an enquiry's trial lesson."""
    from tutortrack.leads.models import Enquiry

    enquiry = Enquiry.objects.select_related("client", "trial_lesson").filter(pk=enquiry_id).first()
    if enquiry is None:
        return None
    tutor = student = None
    if enquiry.trial_lesson is not None:
        link = enquiry.trial_lesson.tutors.select_related("tutor").first()
        tutor = link.tutor if link else None
        attendee = enquiry.trial_lesson.attendees.select_related("student").first()
        student = attendee.student if attendee else None
    return enquiry.client, tutor, student


def application_ref(application_id: Any) -> tuple[str, str] | None:
    """The applicant's name and the ``ref`` code the application came with (E18)."""
    from tutortrack.recruitment.models import TutorApplication

    application = (
        TutorApplication.objects.select_related("submission").filter(pk=application_id).first()
    )
    if application is None or application.submission is None:
        return None
    ref = str((application.submission.utm or {}).get("ref") or "")
    name = f"{application.first_name} {application.last_name}".strip()
    return (name, ref) if ref else None


def succeeded_payments(client_id: Any, *, since: datetime | None = None) -> QuerySet[Any]:
    from tutortrack.payments.models import Payment

    qs = Payment.objects.filter(
        client_id=client_id,
        status__in=[
            Payment.Status.SUCCEEDED,
            Payment.Status.PARTIALLY_REFUNDED,
            Payment.Status.REFUNDED,
        ],
    )
    return qs.filter(received_at__gte=since) if since is not None else qs


def payment_info(payment_id: Any) -> dict[str, Any] | None:
    from tutortrack.payments.models import Payment

    payment = Payment.objects.filter(pk=payment_id).first()
    if payment is None:
        return None
    return {
        "client_id": payment.client_id,
        "amount": payment.amount,
        "received_at": payment.received_at,
        "reference": payment.reference or str(payment.pk)[:8],
    }


def payment_fingerprints(client_id: Any) -> set[tuple[str, str, str, Any, Any]]:
    """Saved cards/mandates as (type, brand, last 4, expiry month, year): the same card on
    two families is a fraud signal."""
    from tutortrack.payments.models import PaymentMethod

    return {
        (m.type, m.brand, m.last4, m.exp_month, m.exp_year)
        for m in PaymentMethod.objects.filter(client_id=client_id).exclude(last4="")
    }


def open_review_requests(client_ids: list[Any]) -> QuerySet[ReviewRequest]:
    return ReviewRequest.objects.filter(
        client_id__in=client_ids, status__in=["pending", "reminded"]
    ).filter(Q(expires_at__isnull=True) | Q(expires_at__gt=_now()))


def _now() -> datetime:
    from tutortrack.core.time import now

    return now()
