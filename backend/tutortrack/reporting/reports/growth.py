"""Referral, affiliate and review reports (gap G5, FR-26-2 "referral and affiliate
performance; review scores"). They belong to the sales family and also need the growth
app's view permission; the records come from ``growth.selectors`` (which apply the growth
permission's data scope), never from growth's models directly."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from zoneinfo import ZoneInfo

from django.db.models import Avg, Count, Q, Sum
from django.db.models.functions import TruncMonth
from django.utils.translation import gettext_lazy as _

from .. import dims, periods
from .base import (
    GROUP_LABELS,
    Column,
    Params,
    ReportDef,
    Result,
    money,
    percent,
    register,
)

CODENAME = "reporting.sales.view"
NONE = _("(none)")


def _in_period(qs: Any, params: Params, field: str) -> Any:
    start, end = params.period.utc_bounds(periods.org_timezone())
    return qs.filter(**{f"{field}__gte": start, f"{field}__lt": end})


def _month(field: str) -> Any:
    return TruncMonth(field, tzinfo=ZoneInfo(periods.org_timezone()))


def _month_label(value: Any) -> str:
    if value is None:
        return ""
    return (value.date() if hasattr(value, "date") else value).isoformat()


def _stars(value: Any) -> str:
    if value is None:
        return ""
    return str(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


# --- referrals ----------------------------------------------------------------------------------


def referral_performance(user: Any, params: Params) -> Result:
    """Referrals made in the period: how many reached the milestone, were rewarded, held by
    fraud checks or lapsed, and the referrer credit given (per programme currency)."""
    from tutortrack.growth import selectors as growth

    qs = _in_period(growth.referrals(user), params, "created_at")
    if params.branch:
        qs = qs.filter(referee__branch_id__in=params.branch)
    if params.client:
        qs = qs.filter(referrer_id__in=params.client)
    group = params.group_by
    field = {
        "program": "program_id",
        "status": "status",
        "source": "source",
        "referrer": "referrer_id",
        "month": "_month",
    }[group]
    if group == "month":
        qs = qs.annotate(_month=_month("created_at"))
    rewarded = Q(status="rewarded")
    data = (
        qs.order_by()
        .values(field, "program__currency")
        .annotate(
            referrals=Count("pk"),
            converted=Count("pk", filter=Q(converted_at__isnull=False)),
            rewarded=Count("pk", filter=rewarded),
            held=Count("pk", filter=Q(status="blocked")),
            lapsed=Count("pk", filter=Q(status__in=("expired", "cancelled"))),
            rewards=Sum("referrer_credit_amount", filter=rewarded),
        )
        .order_by(field)
    )
    model = qs.model
    if group == "program":
        names = dict(qs.order_by().values_list("program_id", "program__name").distinct())
        label = lambda raw: names.get(raw, "")  # noqa: E731
    elif group in ("status", "source"):
        choices = dict((model.Status if group == "status" else model.Source).choices)
        label = lambda raw: str(choices.get(raw, raw))  # noqa: E731
    elif group == "referrer":
        clients = dims.labels("client", (r[field] for r in data))
        label = lambda raw: clients.get(str(raw), "")  # noqa: E731
    else:
        label = _month_label
    rows = []
    for r in data:
        raw = r[field]
        currency = r["program__currency"] or ""
        rows.append(
            {
                "group": label(raw) if raw not in (None, "") else str(NONE),
                "group_id": str(raw) if raw is not None else "",
                "currency": currency,
                "referrals": r["referrals"],
                "converted": r["converted"],
                "rewarded": r["rewarded"],
                "held": r["held"],
                "lapsed": r["lapsed"],
                "conversion_rate": percent(r["converted"], r["referrals"]),
                "rewards": money(r["rewards"] or 0, currency),
            }
        )
    return Result(
        columns=[
            Column("group", GROUP_LABELS.get(group, _("Group"))),
            Column("currency", _("Currency")),
            Column("referrals", _("Referrals"), "count"),
            Column("converted", _("Reached the milestone"), "count"),
            Column("rewarded", _("Rewarded"), "count"),
            Column("held", _("Held by fraud checks"), "count"),
            Column("lapsed", _("Expired or cancelled"), "count"),
            Column("conversion_rate", _("Conversion %"), "percent"),
            Column("rewards", _("Referrer credit given"), "money"),
        ],
        rows=rows,
        chart={"type": "bar", "x": "group", "y": ["referrals", "converted"]},
    )


register(
    ReportDef(
        key="referral_performance",
        title=_("Referral performance"),
        category="sales",
        codename=CODENAME,
        requires=("growth.referral.view",),
        description=_(
            "Family referrals made in the period: conversions, rewards, fraud holds "
            "and credit given."
        ),
        run=referral_performance,
        filters=("branch", "client"),
        group_by=("program", "status", "source", "month", "referrer"),
        default_period="last_12_months",
    )
)


# --- affiliates ---------------------------------------------------------------------------------


def affiliate_performance(user: Any, params: Params) -> Result:
    """Per affiliate: clients referred and converted in the period, commission earned,
    clawed back and adjusted (net), and how much of it is already paid."""
    from tutortrack.growth import selectors as growth

    affiliates: dict[str, dict[str, Any]] = {
        str(a["pk"]): dict(a)
        for a in growth.affiliates(user).values("pk", "name", "currency", "status")
    }
    referrals = growth.affiliate_referrals(user)
    items = _in_period(growth.commission_items(user), params, "earned_at")
    if params.branch:
        referrals = referrals.filter(client__branch_id__in=params.branch)
        items = items.filter(client__branch_id__in=params.branch)
    referred = _per_affiliate(_in_period(referrals, params, "attributed_at"), Count("pk"))
    converted = _per_affiliate(_in_period(referrals, params, "converted_at"), Count("pk"))
    clicks = _per_affiliate(growth.affiliate_links(user), Sum("clicks"))
    earned = Q(kind__in=("commission", "bounty"))
    sums = (
        items.order_by()
        .values("affiliate_id", "currency")
        .annotate(
            earned=Sum("amount_amount", filter=earned),
            clawed_back=Sum("amount_amount", filter=Q(kind="clawback")),
            adjusted=Sum("amount_amount", filter=Q(kind="adjustment")),
            net=Sum("amount_amount"),
            paid=Sum("amount_amount", filter=Q(statement__status="paid")),
        )
    )
    by: dict[tuple[str, str], dict[str, Any]] = {}

    def row(affiliate_id: Any, currency: str) -> dict[str, Any]:
        key = (str(affiliate_id), currency)
        if key not in by:
            info = affiliates.get(str(affiliate_id), {})
            by[key] = {
                "group": info.get("name", ""),
                "group_id": str(affiliate_id),
                "currency": currency,
                "clicks": 0,
                "referred": 0,
                "converted": 0,
                "earned": Decimal(0),
                "clawed_back": Decimal(0),
                "adjusted": Decimal(0),
                "net": Decimal(0),
                "paid": Decimal(0),
            }
        return by[key]

    for affiliate_id, info in affiliates.items():
        counts = (
            clicks.get(affiliate_id, 0),
            referred.get(affiliate_id, 0),
            converted.get(affiliate_id, 0),
        )
        if not any(counts) and info["status"] == "archived":
            continue
        target = row(affiliate_id, info["currency"] or "")
        target["clicks"], target["referred"], target["converted"] = counts
    for s in sums:
        target = row(s["affiliate_id"], s["currency"])
        for name in ("earned", "clawed_back", "adjusted", "net", "paid"):
            target[name] += s[name] or Decimal(0)
    rows = sorted(by.values(), key=lambda r: (str(r["group"]).lower(), r["currency"]))
    for r in rows:
        r["conversion_rate"] = percent(r["converted"], r["referred"])
        r["unpaid"] = r["net"] - r["paid"]
        for name in ("earned", "clawed_back", "adjusted", "net", "paid", "unpaid"):
            r[name] = money(r[name], r["currency"])
    return Result(
        columns=[
            Column("group", _("Affiliate")),
            Column("currency", _("Currency")),
            Column("clicks", _("Link clicks (all time)"), "count"),
            Column("referred", _("Clients referred"), "count"),
            Column("converted", _("Clients converted"), "count"),
            Column("conversion_rate", _("Conversion %"), "percent"),
            Column("earned", _("Commission earned"), "money"),
            Column("clawed_back", _("Clawed back"), "money"),
            Column("adjusted", _("Adjustments"), "money"),
            Column("net", _("Net commission"), "money"),
            Column("paid", _("Paid"), "money"),
            Column("unpaid", _("Not yet paid"), "money"),
        ],
        rows=rows,
        chart={"type": "bar", "x": "group", "y": ["net"]},
        notes=[str(_("Link clicks are lifetime totals; the other figures follow the period."))],
    )


def _per_affiliate(qs: Any, measure: Any) -> dict[str, int]:
    rows = qs.order_by().values("affiliate_id").annotate(n=measure)
    return {str(r["affiliate_id"]): int(r["n"] or 0) for r in rows}


register(
    ReportDef(
        key="affiliate_performance",
        title=_("Affiliate performance"),
        category="sales",
        codename=CODENAME,
        requires=("growth.affiliate.view",),
        description=_(
            "Clients each affiliate referred and converted, and the commission earned, "
            "clawed back and paid."
        ),
        run=affiliate_performance,
        filters=("branch",),
        group_by=("affiliate",),
        default_period="last_12_months",
        ordering="-net",
    )
)


# --- reviews ------------------------------------------------------------------------------------


def review_scores(user: Any, params: Params) -> Result:
    """Reviews received in the period: count, average stars, five-star share, low scores,
    moderation and replies; by tutor or month also the review requests sent and answered."""
    from tutortrack.growth import selectors as growth

    reviews = _in_period(growth.reviews(user), params, "created_at")
    requests = _in_period(growth.review_requests(user), params, "sent_at")
    if params.branch:
        reviews = reviews.filter(client__branch_id__in=params.branch)
        requests = requests.filter(client__branch_id__in=params.branch)
    if params.tutor:
        reviews = reviews.filter(tutor_id__in=params.tutor)
        requests = requests.filter(tutor_id__in=params.tutor)
    group = params.group_by
    field = {"tutor": "tutor_id", "month": "_month", "source": "source"}[group]
    if group == "month":
        reviews = reviews.annotate(_month=_month("created_at"))
        requests = requests.annotate(_month=_month("sent_at"))
    low = Q(rating__lte=2)
    measures = {
        "reviews": Count("pk"),
        "average": Avg("rating"),
        "five": Count("pk", filter=Q(rating=5)),
        "low": Count("pk", filter=low),
        "approved": Count("pk", filter=Q(status="approved")),
        "pending": Count("pk", filter=Q(status="pending")),
        "replied": Count("pk", filter=~Q(response="")),
    }
    data = list(reviews.order_by().values(field).annotate(**measures).order_by(field))
    asked: dict[str, tuple[int, int]] = {}
    if group != "source":
        for r in (
            requests.order_by()
            .values(field)
            .annotate(n=Count("pk"), answered=Count("pk", filter=Q(status="submitted")))
        ):
            asked[str(r[field])] = (r["n"], r["answered"])
    if group == "tutor":
        keys = {str(r[field]) for r in data if r[field]} | {k for k in asked if k != "None"}
        names = dims.labels("tutor", keys)
        label = lambda raw: names.get(str(raw), "") if raw else str(_("The business"))  # noqa: E731
    elif group == "source":
        choices = dict(reviews.model.Source.choices)
        label = lambda raw: str(choices.get(raw, raw))  # noqa: E731
    else:
        label = _month_label
    rows: dict[str, dict[str, Any]] = {}
    for r in data:
        raw = r[field]
        rows[str(raw)] = {
            "group": label(raw),
            "group_id": str(raw or ""),
            "reviews": r["reviews"],
            "average": _stars(r["average"]),
            "five_star": percent(r["five"], r["reviews"]),
            "low": r["low"],
            "approved": r["approved"],
            "pending": r["pending"],
            "reply_rate": percent(r["replied"], r["reviews"]),
        }
    for key, (n, answered) in asked.items():
        raw = None if key == "None" else key
        target = rows.setdefault(
            key,
            {
                "group": label(raw) if group == "tutor" else _month_label_from(key),
                "group_id": raw or "",
                "reviews": 0,
                "average": "",
                "five_star": "0.0",
                "low": 0,
                "approved": 0,
                "pending": 0,
                "reply_rate": "0.0",
            },
        )
        target["requested"] = n
        target["request_answer_rate"] = percent(answered, n)
    columns = [
        Column("group", GROUP_LABELS.get(group, _("Group"))),
        Column("reviews", _("Reviews"), "count"),
        Column("average", _("Average stars"), "number"),
        Column("five_star", _("5 stars %"), "percent"),
        Column("low", _("1\N{EN DASH}2 stars"), "count"),
        Column("approved", _("Approved"), "count"),
        Column("pending", _("Waiting for moderation"), "count"),
        Column("reply_rate", _("Replied %"), "percent"),
    ]
    if group != "source":
        columns += [
            Column("requested", _("Requests sent"), "count"),
            Column("request_answer_rate", _("Requests answered %"), "percent"),
        ]
        for r in rows.values():
            r.setdefault("requested", 0)
            r.setdefault("request_answer_rate", "0.0")
    overall = reviews.aggregate(**measures)
    totals: dict[str, Any] = {
        "reviews": overall["reviews"],
        "average": _stars(overall["average"]),  # the overall average, not a sum
        "five_star": percent(overall["five"], overall["reviews"]),
        "low": overall["low"],
        "approved": overall["approved"],
        "pending": overall["pending"],
        "reply_rate": percent(overall["replied"], overall["reviews"]),
    }
    if group != "source":
        sent = requests.aggregate(n=Count("pk"), answered=Count("pk", filter=Q(status="submitted")))
        totals["requested"] = sent["n"]
        totals["request_answer_rate"] = percent(sent["answered"], sent["n"])
    ordered = sorted(rows.values(), key=lambda r: str(r["group"]).lower())
    if group == "month":
        ordered = sorted(rows.values(), key=lambda r: str(r["group"]))
    return Result(
        columns=columns,
        rows=ordered,
        totals=[totals],
        chart={"type": "bar", "x": "group", "y": ["average"]},
    )


def _month_label_from(key: str) -> str:
    return key[:10] if key and key != "None" else ""


register(
    ReportDef(
        key="review_scores",
        title=_("Review scores"),
        category="sales",
        codename=CODENAME,
        requires=("growth.review.view",),
        description=_(
            "Reviews received by tutor, month or source: average stars, low scores, "
            "moderation, replies and requests answered."
        ),
        run=review_scores,
        filters=("branch", "tutor"),
        group_by=("tutor", "month", "source"),
        default_period="last_12_months",
    )
)
