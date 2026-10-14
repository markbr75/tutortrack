"""Reviews, referrals and affiliate attribution follow a merged client, contact or
student (FR-05-13).

* Review requests and reviews move to the survivor.
* Referrals: the survivor becomes referrer/referee. Two referred families, or a family
  that referred its own duplicate, block the merge (a reward would be paid twice or to
  themselves). A personal referral code moves when the survivor has none; otherwise the
  merged client's referrals point at the survivor's code and the old code stops working.
* Affiliate and tutor-referral attribution is once per client, so both clients being
  attributed blocks the merge. Commission items never change (E25), so they stay on the
  merged record as history.
"""

from __future__ import annotations

from typing import Any

from django.db.models import Q
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy as _l

from tutortrack.people.merging import (
    MergeContext,
    MergeProvider,
    Move,
    count,
    moves,
    register,
    repoint,
)

from .models import (
    AffiliateReferral,
    Referral,
    ReferralCode,
    Review,
    ReviewRequest,
    TutorReferral,
)


def _field(ctx: MergeContext) -> str:
    return ctx.kind


def _both(model: Any, name: str, ctx: MergeContext) -> bool:
    qs = model._base_manager
    return qs.filter(**{name: ctx.source}).exists() and qs.filter(**{name: ctx.target}).exists()


def _check(ctx: MergeContext) -> list[str]:
    if ctx.subject_type != "people.client":
        return []
    out = []
    if _both(Referral, "referee", ctx):
        out.append(_("Both families came through a referral. Only one referral can be kept."))
    if Referral.objects.filter(
        Q(referrer=ctx.source, referee=ctx.target) | Q(referrer=ctx.target, referee=ctx.source)
    ).exists():
        out.append(_("One family referred the other, so they can't be merged."))
    if _both(AffiliateReferral, "client", ctx):
        out.append(_("Both families are attributed to an affiliate."))
    if _both(TutorReferral, "client", ctx):
        out.append(_("Both families were referred by a tutor."))
    return out


def _count(ctx: MergeContext) -> list[Move]:
    name = _field(ctx)
    reviews = count(Review, name, ctx) + count(ReviewRequest, name, ctx)
    found = [("growth.reviews", _l("Reviews and review requests"), reviews)]
    if ctx.subject_type == "people.client":
        referrals = count(Referral, "referrer", ctx) + count(Referral, "referee", ctx)
        affiliate = count(AffiliateReferral, "client", ctx)
        found += [
            ("growth.referrals", _l("Referrals"), referrals),
            ("growth.referral_code", _l("Referral code"), count(ReferralCode, "client", ctx)),
            ("growth.affiliate", _l("Affiliate attribution"), affiliate),
            ("growth.tutor_referral", _l("Tutor referral"), count(TutorReferral, "client", ctx)),
        ]
    return moves(*found)


def _merge(ctx: MergeContext) -> list[Move]:
    name = _field(ctx)
    reviews = repoint(Review, name, ctx) + repoint(ReviewRequest, name, ctx)
    if ctx.subject_type != "people.client":
        return moves(("growth.reviews", _l("Reviews and review requests"), reviews))
    referrals = repoint(Referral, "referrer", ctx) + repoint(Referral, "referee", ctx)
    theirs = ReferralCode.objects.filter(client=ctx.source).first()
    ours = ReferralCode.objects.filter(client=ctx.target).first()
    codes = 0
    if theirs is not None and ours is None:
        codes = repoint(ReferralCode, "client", ctx)
    elif theirs is not None and ours is not None:
        Referral.objects.filter(code=theirs).update(code=ours)
        theirs.delete()
        ctx.note(
            _("The merged client's referral code %(code)s no longer works.") % {"code": theirs.code}
        )
    return moves(
        ("growth.reviews", _l("Reviews and review requests"), reviews),
        ("growth.referrals", _l("Referrals"), referrals),
        ("growth.referral_code", _l("Referral code"), codes),
        (
            "growth.affiliate",
            _l("Affiliate attribution"),
            repoint(AffiliateReferral, "client", ctx),
        ),
        ("growth.tutor_referral", _l("Tutor referral"), repoint(TutorReferral, "client", ctx)),
    )


register(
    MergeProvider(
        key="growth",
        label="Reviews and referrals",
        subject_types=frozenset({"people.client", "people.contact", "people.student"}),
        count=_count,
        merge=_merge,
        check=_check,
        history=("growth.CommissionItem.client",),
        order=90,
    )
)
