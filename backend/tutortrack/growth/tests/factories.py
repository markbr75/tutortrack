from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import factory
from django.utils import timezone

from tutortrack.core.tests.factories import TenantFactory
from tutortrack.growth.models import (
    Affiliate,
    AffiliateLink,
    AffiliateReferral,
    CommissionRule,
    Referral,
    ReferralProgram,
    Review,
    ReviewRequest,
    TutorReferral,
)
from tutortrack.people.tests.factories import ClientFactory, TutorProfileFactory


class ReviewRequestFactory(TenantFactory):
    class Meta:
        model = ReviewRequest

    client = factory.SubFactory(ClientFactory, organisation=factory.SelfAttribute("..organisation"))
    expires_at = factory.LazyFunction(lambda: timezone.now() + timedelta(days=14))


class ReviewFactory(TenantFactory):
    class Meta:
        model = Review

    client = factory.SubFactory(ClientFactory, organisation=factory.SelfAttribute("..organisation"))
    rating = 5
    text = "Brilliant tutor."
    reviewer_name = "Priya"


class ReferralProgramFactory(TenantFactory):
    class Meta:
        model = ReferralProgram

    name = "Refer a friend"
    currency = "GBP"
    referrer_reward_amount = Decimal("20.00")
    referee_discount_percent = Decimal("10.00")


class ReferralFactory(TenantFactory):
    class Meta:
        model = Referral

    program = factory.SubFactory(
        ReferralProgramFactory, organisation=factory.SelfAttribute("..organisation")
    )
    referrer = factory.SubFactory(
        ClientFactory, organisation=factory.SelfAttribute("..organisation")
    )
    referee = factory.SubFactory(
        ClientFactory, organisation=factory.SelfAttribute("..organisation")
    )
    deadline = factory.LazyFunction(lambda: timezone.now() + timedelta(days=90))


class AffiliateFactory(TenantFactory):
    class Meta:
        model = Affiliate

    name = factory.Sequence(lambda n: f"Partner {n}")
    email = factory.Sequence(lambda n: f"partner{n}@example.com")
    currency = "GBP"


class AffiliateLinkFactory(TenantFactory):
    class Meta:
        model = AffiliateLink

    affiliate = factory.SubFactory(
        AffiliateFactory, organisation=factory.SelfAttribute("..organisation")
    )
    code = factory.Sequence(lambda n: f"LINK{n:04d}")


class AffiliateReferralFactory(TenantFactory):
    class Meta:
        model = AffiliateReferral

    affiliate = factory.SubFactory(
        AffiliateFactory, organisation=factory.SelfAttribute("..organisation")
    )
    client = factory.SubFactory(ClientFactory, organisation=factory.SelfAttribute("..organisation"))
    attributed_at = factory.LazyFunction(timezone.now)


class CommissionRuleFactory(TenantFactory):
    class Meta:
        model = CommissionRule

    name = "Standard"
    kind = CommissionRule.Kind.PERCENT
    percent = Decimal("10.00")


class TutorReferralFactory(TenantFactory):
    class Meta:
        model = TutorReferral

    referrer = factory.SubFactory(
        TutorProfileFactory, organisation=factory.SelfAttribute("..organisation")
    )
    kind = TutorReferral.Kind.TUTOR
    referred_name = "Sam Taylor"
