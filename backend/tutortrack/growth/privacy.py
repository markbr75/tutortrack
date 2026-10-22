"""Reviews, referrals and affiliates in DSARs and erasure (E25 data, E29 Part 2).

Affiliates are data subjects (``growth.affiliate``). Their statements and commission are
financial records and stay; their contact and bank details are removed. Reviews written by
an erased person lose their text and name (the rating stays in the averages)."""

from __future__ import annotations

from typing import Any

from django.db.models import Q
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from tutortrack.privacy import subjects
from tutortrack.privacy.registry import (
    ErasureContext,
    ErasureOutcome,
    Person,
    Provider,
    Section,
    register,
)

from .models import (
    Affiliate,
    AffiliateStatement,
    CommissionItem,
    Referral,
    ReferralCode,
    Review,
    TutorReferral,
)


def _exists(subject_id: str) -> bool:
    return Affiliate.objects.filter(pk=subject_id).exists()


def _label(subject_id: str) -> str:
    affiliate = Affiliate.objects.filter(pk=subject_id).first()
    return affiliate.name if affiliate else ""


subjects.register("growth.affiliate", _exists, _label)


def expand(person: Person) -> None:
    users = person.of("identity.user")
    if users:
        person.add(
            "growth.affiliate",
            *Affiliate.objects.filter(user_id__in=users).values_list("pk", flat=True),
        )
    for affiliate in Affiliate.objects.filter(pk__in=person.of("growth.affiliate")):
        person.add("identity.user", affiliate.user_id)
        person.add_terms(names=[affiliate.name], emails=[affiliate.email], phones=[affiliate.phone])


def _reviews_by(person: Person) -> Q:
    return (
        Q(contact_id__in=person.of("people.contact"))
        | Q(client_id__in=person.of("people.client"))
        | Q(student_id__in=person.of("people.student"))
    )


def export(person: Person) -> list[Section]:
    reviews = [
        {
            "id": str(r.pk),
            "rating": r.rating,
            "text": r.text,
            "name": r.reviewer_name,
            "status": r.status,
            "created_at": r.created_at,
        }
        for r in Review.objects.filter(_reviews_by(person))
    ]
    clients = person.of("people.client")
    referrals = [
        {"id": str(r.pk), "status": r.status, "created_at": r.created_at}
        for r in Referral.objects.filter(Q(referrer_id__in=clients) | Q(referee_id__in=clients))
    ]
    codes = [
        {"id": str(c.pk), "code": c.code, "active": c.active}
        for c in ReferralCode.objects.filter(
            Q(client_id__in=clients) | Q(tutor_id__in=person.of("people.tutor"))
        )
    ]
    affiliates = [
        {
            "id": str(a.pk),
            "name": a.name,
            "email": a.email,
            "phone": a.phone,
            "status": a.status,
            "payee_name": a.payee_name,
            "bank": a.bank_hint,
        }
        for a in Affiliate.objects.filter(pk__in=person.of("growth.affiliate"))
    ]
    statements = [
        {
            "id": str(s.pk),
            "number": s.number,
            "period_start": s.period_start,
            "period_end": s.period_end,
            "total": str(s.total),
            "status": s.status,
        }
        for s in AffiliateStatement.objects.filter(affiliate_id__in=person.of("growth.affiliate"))
    ]
    return [
        Section("growth.reviews", _("Reviews"), reviews),
        Section("growth.referrals", _("Referrals"), referrals),
        Section("growth.referral_codes", _("Referral codes"), codes),
        Section("growth.affiliate", _("Affiliate account"), affiliates),
        Section("growth.statements", _("Affiliate statements"), statements),
    ]


def _scrub(model: Any, qs: Any, field: str, ctx: ErasureContext) -> int:
    count = 0
    for pk, value in qs.values_list("pk", field):
        if ctx.scrub(value) != value:
            model.objects.filter(pk=pk).update(**{field: ctx.scrub(value)})
            count += 1
    return count


def erase(person: Person, ctx: ErasureContext) -> ErasureOutcome:
    out = ErasureOutcome()
    for review in Review.objects.filter(_reviews_by(person)):
        Review.objects.filter(pk=review.pk).update(
            text="", reviewer_name=_("Former client"), criteria={}, publish_consent=False
        )
        out.anonymised += 1
    out.anonymised += _scrub(
        Review, Review.objects.filter(tutor_id__in=person.of("people.tutor")), "text", ctx
    )
    clients = person.of("people.client")
    out.anonymised += ReferralCode.objects.filter(
        Q(client_id__in=clients) | Q(tutor_id__in=person.of("people.tutor"))
    ).update(active=False)
    out.anonymised += _scrub(
        Referral,
        Referral.objects.filter(Q(referrer_id__in=clients) | Q(referee_id__in=clients)),
        "note",
        ctx,
    )
    out.anonymised += _scrub(
        TutorReferral,
        TutorReferral.objects.filter(referrer_id__in=person.of("people.tutor")),
        "referred_name",
        ctx,
    )
    affiliates = Affiliate.objects.filter(pk__in=person.of("growth.affiliate"))
    for affiliate in affiliates:
        Affiliate.objects.filter(pk=affiliate.pk).update(
            name=ctx.label("growth.affiliate", affiliate.pk, _("Erased affiliate")),
            email="",
            phone="",
            payee_name="",
            bank_details="",
            bank_hint="",
            notes="",
            user=None,
            status=Affiliate.Status.ARCHIVED,
        )
        out.anonymised += 1
    out.anonymised += _scrub(
        CommissionItem, CommissionItem.objects.filter(client_id__in=clients), "description", ctx
    )
    out.retained += AffiliateStatement.objects.filter(affiliate__in=affiliates).count()
    return out


register(
    Provider(
        key="growth",
        label=gettext_lazy("Reviews and referrals"),
        expand=expand,
        export=export,
        erase=erase,
        order=36,
    )
)
