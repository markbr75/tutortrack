"""E25 Reviews, referrals and affiliates: review requests, the review page, moderation and
aggregates (T01), testimonials and the Google prompt (T02), the client referral programme
(T03), affiliates and attribution (T04), the commission engine with clawbacks, statements
and payouts (T05), tutor referral bonuses (T06), plus the API with tenant isolation."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest

from tutortrack.billing import ledger
from tutortrack.catalogue.models import DiscountRule
from tutortrack.catalogue.tests.factories import ServiceFactory
from tutortrack.core.context import tenant_context
from tutortrack.core.exceptions import BusinessRuleViolation
from tutortrack.core.models import OutboxEvent
from tutortrack.core.money import Money
from tutortrack.core.testing import TenantIsolationTestMixin, client_for
from tutortrack.core.time import now
from tutortrack.delivery import services as delivery
from tutortrack.growth import selectors, services
from tutortrack.growth.models import (
    AffiliateReferral,
    AffiliateStatement,
    CommissionItem,
    ImmutableRecord,
    Referral,
    Review,
    ReviewRequest,
    TutorReferral,
)
from tutortrack.identity.models import Invitation
from tutortrack.identity.tests.factories import MembershipFactory
from tutortrack.leads import services as leads
from tutortrack.payments import services as payments
from tutortrack.payroll.models import PayItem
from tutortrack.people.tests.factories import (
    ClientFactory,
    ContactFactory,
    TutorProfileFactory,
)
from tutortrack.portal.tests.test_portal import make_household
from tutortrack.scheduling import services as scheduling
from tutortrack.sites.models import Testimonial as SiteTestimonial
from tutortrack.tenancy import settings_service

from .factories import (
    AffiliateFactory,
    AffiliateLinkFactory,
    AffiliateReferralFactory,
    CommissionRuleFactory,
    ReferralFactory,
    ReferralProgramFactory,
    ReviewFactory,
    ReviewRequestFactory,
    TutorReferralFactory,
)

pytestmark = pytest.mark.django_db


def gbp(value: str) -> Money:
    return Money(Decimal(value), "GBP")


def settings(org, **values):
    with tenant_context(org):
        settings_service.update_settings("growth", {f"growth.{k}": v for k, v in values.items()})


def events_of(org, kind):
    with tenant_context(org):
        rows = OutboxEvent.objects.filter(event_type=kind).order_by("occurred_at")
        return [row.payload["data"] for row in rows]


def snap(moment):
    return moment.replace(minute=0, second=0, microsecond=0)


@pytest.fixture
def world(org):
    admin = MembershipFactory(organisation=org, role="admin")
    tutor_membership = MembershipFactory(organisation=org, role="tutor")
    tutor = TutorProfileFactory(
        organisation=org, status="active", first_name="Nia", membership=tutor_membership
    )
    family = make_household(org, "The Patels")
    return {
        "admin": admin.user,
        "api": client_for(org, admin.user),
        "tutor": tutor,
        "tutor_api": client_for(org, tutor_membership.user),
        "family": family,
        "client": family["client"],
        "student": family["students"][0],
        "service": ServiceFactory(organisation=org, name="Maths 1:1"),
    }


def done_lesson(org, world, *, days_ago=1):
    start = snap(now() - timedelta(days=days_ago, hours=3))
    with tenant_context(org):
        lesson = scheduling.create_lesson(
            start=start,
            end=start + timedelta(hours=1),
            service=world["service"],
            attendees=[{"student": world["student"]}],
            tutors=[{"tutor": world["tutor"]}],
            timezone="Europe/London",
            override_conflicts=True,
        ).lesson
        delivery.complete_lesson(lesson)
        return lesson


def ask(org, world, **kw):
    with tenant_context(org):
        return services.request_review(client=world["client"], tutor=world["tutor"], **kw)


# --- T01 review requests, the review page, moderation and aggregates ---------------------------


def test_a_review_is_requested_after_n_completed_lessons(org, world):
    settings(org, review_after_lessons=2)
    done_lesson(org, world, days_ago=3)
    with tenant_context(org):
        rows = [
            {
                "client_id": str(world["client"].pk),
                "student_id": str(world["student"].pk),
                "outcome": "present",
            }
        ]
        tutors = [{"tutor_id": str(world["tutor"].pk)}]
        assert services.lesson_completed(rows, tutors) == []  # one lesson so far
    done_lesson(org, world, days_ago=1)
    with tenant_context(org):
        made = services.lesson_completed(rows, tutors)
        assert len(made) == 1
        request = made[0]
        assert (request.trigger, request.lesson_count) == ("lessons", 2)
        assert services.lesson_completed(rows, tutors) == []  # asked once per tutor
    assert events_of(org, "review.requested")[0]["tutor_id"] == str(world["tutor"].pk)


def test_review_request_email_has_the_signed_link(org, world):
    from tutortrack.comms.models import Message

    request = ask(org, world)
    with tenant_context(org):
        assert services.send_review_request(request.pk)
        assert services.send_review_request(request.pk, reminder=True)
        assert not services.send_review_request(request.pk, reminder=True)  # once
        message = Message.objects.filter(type_key="review_request").first()
        assert message is not None
        assert "/review/" in message.body
        request.refresh_from_db()
        assert request.status == "reminded"
        assert request.sent_at is not None


def test_the_public_review_page_submits_into_moderation(org, world):
    settings(org, google_review_url="https://g.page/r/brightminds/review")
    request = ask(org, world)
    with tenant_context(org):
        token = services.review_token(request)
    public = client_for(org)
    page = public.get(f"/api/v1/public/review/{token}")
    assert page.status_code == 200, page.content
    assert page.json()["tutor"] == "Nia"
    assert page.json()["open"] is True
    assert "communication" in page.json()["criteria"]
    body = {
        "rating": 5,
        "criteria": {"communication": 5},
        "text": "Great!",
        "reviewer_name": "Priya",
        "publish_consent": True,
    }
    response = public.post(f"/api/v1/public/review/{token}", body, format="json")
    assert response.status_code == 201, response.content
    assert response.json()["google_review_url"] == "https://g.page/r/brightminds/review"
    with tenant_context(org):
        review = Review.objects.get(request=request)
        assert (review.status, review.rating, review.google_prompted) == ("pending", 5, True)
        assert ReviewRequest.objects.get(pk=request.pk).status == "submitted"
    again = public.post(f"/api/v1/public/review/{token}", body, format="json")
    assert again.status_code == 422
    assert public.get("/api/v1/public/review/not-a-token").status_code == 404
    assert events_of(org, "review.submitted")[0]["request_id"] == str(request.pk)


def test_low_ratings_get_no_google_prompt_and_bad_input_is_refused(org, world):
    settings(org, google_review_url="https://g.page/r/x/review")
    request = ask(org, world)
    with tenant_context(org):
        with pytest.raises(BusinessRuleViolation):
            services.submit_review(request, rating=6)
        with pytest.raises(BusinessRuleViolation):
            services.submit_review(request, rating=4, criteria={"unknown": 3})
        review = services.submit_review(request, rating=3, text="OK")
        assert services.google_prompt_url(review) == ""


def test_a_tokens_from_another_organisation_is_not_found(org, other_org, world):
    request = ask(org, world)
    with tenant_context(org):
        token = services.review_token(request)
    assert client_for(other_org).get(f"/api/v1/public/review/{token}").status_code == 404


def test_moderation_approve_hide_and_respond(org, world):
    review = ReviewFactory(organisation=org, client=world["client"], tutor=world["tutor"])
    api = world["api"]
    queue = api.get("/api/v1/reviews?status=pending")
    assert [r["id"] for r in queue.json()["results"]] == [str(review.pk)]
    approved = api.post(f"/api/v1/reviews/{review.pk}/approve")
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    assert events_of(org, "review.published")
    reply = api.post(f"/api/v1/reviews/{review.pk}/respond", {"response": "Thank you!"})
    assert reply.json()["response"] == "Thank you!"
    hidden = api.post(f"/api/v1/reviews/{review.pk}/hide")
    assert hidden.json()["status"] == "hidden"


def test_tutors_see_only_approved_reviews_about_them(org, world):
    mine = ReviewFactory(
        organisation=org, client=world["client"], tutor=world["tutor"], status="approved"
    )
    ReviewFactory(organisation=org, client=world["client"], tutor=world["tutor"])  # pending
    other = TutorProfileFactory(organisation=org)
    ReviewFactory(organisation=org, client=world["client"], tutor=other, status="approved")
    ids = [r["id"] for r in world["tutor_api"].get("/api/v1/reviews").json()["results"]]
    assert ids == [str(mine.pk)]
    assert world["tutor_api"].post(f"/api/v1/reviews/{mine.pk}/hide").status_code == 403
    settings(org, tutors_see_reviews=False)
    assert world["tutor_api"].get("/api/v1/reviews").json()["results"] == []


def test_ratings_feed_summaries_matching_and_the_directory(org, world):
    for rating in (5, 4, 3):
        ReviewFactory(
            organisation=org,
            client=world["client"],
            tutor=world["tutor"],
            rating=rating,
            status="approved",
        )
    ReviewFactory(organisation=org, client=world["client"], tutor=world["tutor"], rating=1)
    summary = world["api"].get(f"/api/v1/reviews/summary?tutor={world['tutor'].pk}").json()
    assert (summary["average"], summary["count"], summary["stars"]["5"]) == (4.0, 3, 1)
    with tenant_context(org):
        assert selectors.tutor_ratings([world["tutor"].pk])[str(world["tutor"].pk)] == (4.0, 3)
        assert selectors.public_rating(world["tutor"].pk) is None  # not shown by default
    settings(org, show_ratings_publicly=True)
    with tenant_context(org):
        from tutortrack.sites import selectors as sites
        from tutortrack.sites.models import PublicProfile

        profile = PublicProfile(tutor=world["tutor"], slug="nia", published={"display_name": "Nia"})
        card = sites.public_tutor_card(profile)
        assert (card["rating"], card["review_count"]) == (4.0, 3)


def test_staff_request_and_cancel_a_review(org, world):
    response = world["api"].post(
        "/api/v1/review-requests",
        {"client": str(world["client"].pk), "tutor": str(world["tutor"].pk)},
        format="json",
    )
    assert response.status_code == 201, response.content
    again = world["api"].post(
        "/api/v1/review-requests",
        {"client": str(world["client"].pk), "tutor": str(world["tutor"].pk)},
        format="json",
    )
    assert again.status_code == 422
    cancelled = world["api"].post(f"/api/v1/review-requests/{response.json()['id']}/cancel")
    assert cancelled.json()["status"] == "cancelled"


def test_trial_lessons_and_automations_can_ask_for_reviews(org, world):
    from tutortrack.automations import registry
    from tutortrack.automations.recipes import recipe

    with tenant_context(org):
        enquiry = leads.create_enquiry(contact={"first_name": "Sam", "email": "sam@example.com"})
        request = services.trial_completed(enquiry.pk)
        assert request is not None
        assert request.trigger == "trial"
        assert services.trial_completed(enquiry.pk) is None  # once
    assert registry.action("request_review") is not None
    assert recipe("trial_review") is not None


# --- T02 testimonials ---------------------------------------------------------------------------


def test_approved_reviews_become_testimonials(org, world):
    settings(org, auto_testimonial=True)
    review = ReviewFactory(
        organisation=org,
        client=world["client"],
        tutor=world["tutor"],
        publish_consent=True,
        text="Nia is wonderful.",
    )
    world["api"].post(f"/api/v1/reviews/{review.pk}/approve")
    with tenant_context(org):
        review.refresh_from_db()
        testimonial = SiteTestimonial.objects.get(pk=review.testimonial_id)
        assert (testimonial.quote, testimonial.rating, testimonial.published) == (
            "Nia is wonderful.",
            5,
            True,
        )
        from tutortrack.sites.selectors import public_testimonials

        assert public_testimonials(10)[0]["quote"] == "Nia is wonderful."
    world["api"].post(f"/api/v1/reviews/{review.pk}/hide")
    with tenant_context(org):
        assert not SiteTestimonial.objects.get(pk=review.testimonial_id).published


def test_publishing_needs_consent(org, world):
    review = ReviewFactory(
        organisation=org, client=world["client"], status="approved", publish_consent=False
    )
    response = world["api"].post(f"/api/v1/reviews/{review.pk}/publish")
    assert response.status_code == 422
    review2 = ReviewFactory(
        organisation=org, client=world["client"], status="approved", publish_consent=True
    )
    published = world["api"].post(f"/api/v1/reviews/{review2.pk}/publish")
    assert published.status_code == 200
    assert published.json()["published_as_testimonial"]


# --- T03 the client referral programme ----------------------------------------------------------


@pytest.fixture
def program(org):
    return ReferralProgramFactory(organisation=org, max_rewards_per_period=2)


def new_family(org, name="The Smiths", email="smith@example.com"):
    client = ClientFactory(organisation=org, display_name=name)
    ContactFactory(organisation=org, client=client, email=email, mobile="")
    return client


def test_an_enquiry_with_a_referral_code_is_attributed(org, world, program):
    with tenant_context(org):
        code = services.code_for_client(world["client"])
        assert services.code_for_client(world["client"]).pk == code.pk
    click = client_for(org).post("/api/v1/public/ref", {"code": code.code.lower()}, format="json")
    assert click.json()["valid"]
    assert click.json()["kind"] == "referral"
    assert click.json()["offer"] == "10%"
    with tenant_context(org):
        enquiry = leads.create_enquiry(
            contact={"first_name": "Jo", "email": "jo@example.com"}, utm={"ref": code.code}
        )
        referral = services.attribute_enquiry(enquiry.pk)
        assert isinstance(referral, Referral)
        assert (referral.referrer_id, referral.referee_id) == (
            world["client"].pk,
            enquiry.client_id,
        )
        code.refresh_from_db()
        assert code.clicks == 1
        assert services.attribute_enquiry(enquiry.pk) is None  # only once
    assert events_of(org, "referral.created")[0]["source"] == "link"


def test_a_converted_referral_rewards_both_families(org, world, program):
    referee = new_family(org)
    with tenant_context(org):
        referral = services.create_referral(referrer=world["client"], referee=referee)
        assert not services.milestone_reached(referral.pk)
        payments.record_manual_payment(client=referee, amount=gbp("40"), method="bank_transfer")
        assert services.milestone_reached(referral.pk)
        assert services.convert_referral(referral.pk) == "converted"
        assert services.reward_referral(referral.pk) == "rewarded"
        assert services.reward_referral(referral.pk) == "rewarded"  # idempotent
        assert ledger.ledger_balance(world["client"], "GBP") == gbp("-20.00")
        referral.refresh_from_db()
        assert referral.referrer_credit == gbp("20.00")
        discount = DiscountRule.objects.get(pk=referral.referee_discount_id)
        assert (discount.kind, discount.client_id, discount.percent) == (
            "client",
            referee.pk,
            Decimal("10.00"),
        )
    rewarded = events_of(org, "referral.rewarded")
    assert rewarded[0]["credit"] == {"amount": "20.00", "currency": "GBP"}


def test_fraud_checks_hold_the_reward_until_staff_approve(org, world, program):
    family_email = world["family"]["contact"].email
    referee = new_family(org, email=family_email.upper())
    with tenant_context(org):
        referral = services.create_referral(referrer=world["client"], referee=referee)
        services.convert_referral(referral.pk)
        assert services.reward_referral(referral.pk) == "blocked"
        referral.refresh_from_db()
        assert referral.fraud_flags == ["same_email"]
    response = world["api"].post(f"/api/v1/referrals/{referral.pk}/approve")
    assert response.status_code == 200, response.content
    assert response.json()["status"] == "rewarded"
    with tenant_context(org):
        assert ledger.ledger_balance(world["client"], "GBP") == gbp("-20.00")


def test_reward_limit_per_period(org, world, program):
    with tenant_context(org):
        for n in range(3):
            referee = new_family(org, name=f"F{n}", email=f"f{n}@example.com")
            referral = services.create_referral(referrer=world["client"], referee=referee)
            services.convert_referral(referral.pk)
            outcome = services.reward_referral(referral.pk)
        assert outcome == "blocked"
        referral.refresh_from_db()
        assert referral.fraud_flags == ["reward_limit"]


def test_referral_rules(org, world, program):
    paying = new_family(org, email="paid@example.com")
    with tenant_context(org):
        with pytest.raises(BusinessRuleViolation):
            services.create_referral(referrer=world["client"], referee=world["client"])
        payments.record_manual_payment(client=paying, amount=gbp("10"), method="cash")
        with pytest.raises(BusinessRuleViolation):  # only new families
            services.create_referral(referrer=world["client"], referee=paying)
        other = new_family(org, email="o@example.com")
        services.create_referral(referrer=world["client"], referee=other)
        with pytest.raises(BusinessRuleViolation):  # once
            services.create_referral(referrer=paying, referee=other)


def test_the_client_portal_shows_the_referral_page(org, world, program):
    family = world["family"]
    me = family["api"].get("/api/v1/portal/me").json()
    assert me["features"]["referrals"] is True
    referee = new_family(org)
    ReferralFactory(organisation=org, program=program, referrer=world["client"], referee=referee)
    page = family["api"].get("/api/v1/portal/referrals")
    assert page.status_code == 200, page.content
    body = page.json()
    assert body["link"].endswith(f"/?ref={body['code']}")
    assert body["referrals"][0]["name"] == "The S."  # no other family's details
    assert body["program"]["referrer_reward"] == {"amount": "20.00", "currency": "GBP"}
    settings(org, referrals_enabled=False)
    assert family["api"].get("/api/v1/portal/me").json()["features"]["referrals"] is False


def test_cancelling_a_referral(org, world, program):
    referral = ReferralFactory(organisation=org, program=program, referrer=world["client"])
    response = world["api"].post(f"/api/v1/referrals/{referral.pk}/cancel", {"reason": "dup"})
    assert response.json()["status"] == "cancelled"


# --- T04 affiliates, links, attribution and the partner portal ---------------------------------


def test_affiliates_with_bank_details_and_a_main_link(org, world):
    body = {
        "kind": "organisation",
        "name": "Hillside PTA",
        "email": "PTA@hillside.example",
        "payout_method": "bank_file",
        "bank_country": "GB",
        "bank": {"sort_code": "04-00-04", "account_number": "12345678"},
    }
    response = world["api"].post("/api/v1/affiliates", body, format="json")
    assert response.status_code == 201, response.content
    data = response.json()
    assert (data["email"], data["bank_hint"]) == ("pta@hillside.example", "••5678")
    assert "bank" not in data
    links = world["api"].get(f"/api/v1/affiliate-links?affiliate={data['id']}").json()["results"]
    assert len(links) == 1
    assert len(links[0]["code"]) == 8
    missing = world["api"].post(
        "/api/v1/affiliates", {**body, "bank": None, "email": "x@example.com"}, format="json"
    )
    assert missing.status_code in (400, 422)


def test_affiliate_invite_and_login_link(org, world):
    affiliate = AffiliateFactory(organisation=org, email="blogger@example.com")
    response = world["api"].post(f"/api/v1/affiliates/{affiliate.pk}/invite")
    assert response.status_code == 201, response.content
    with tenant_context(org):
        invitation = Invitation.objects.get(email="blogger@example.com")
        assert (invitation.role, invitation.target_type) == ("affiliate", "growth.affiliate")
        user = MembershipFactory(organisation=org, role="affiliate").user
        services.link_affiliate_user(invitation.target_id, user)
        affiliate.refresh_from_db()
        assert affiliate.user_id == user.pk


def test_an_enquiry_through_an_affiliate_link_is_attributed(org, world):
    link = AffiliateLinkFactory(organisation=org, code="SCHOOL1")
    with tenant_context(org):
        enquiry = leads.create_enquiry(
            contact={"first_name": "Al", "email": "al@example.com"}, utm={"ref": "school1"}
        )
        found = services.attribute_enquiry(enquiry.pk)
        assert isinstance(found, AffiliateReferral)
        assert (found.affiliate_id, found.link_id) == (link.affiliate_id, link.pk)
        other = AffiliateFactory(organisation=org)
        assert services.attribute_to_affiliate(other, client=enquiry.client) is None  # first wins


def test_codes_must_be_unique_across_referrals_and_affiliates(org, world):
    affiliate = AffiliateFactory(organisation=org)
    with tenant_context(org):
        code = services.code_for_client(world["client"])
        with pytest.raises(BusinessRuleViolation):
            services.save_link(None, affiliate=affiliate, code=code.code)


@pytest.fixture
def partner(org):
    membership = MembershipFactory(organisation=org, role="affiliate")
    affiliate = AffiliateFactory(organisation=org, name="Hillside PTA", user=membership.user)
    AffiliateLinkFactory(organisation=org, affiliate=affiliate, code="HILL0001", clicks=7)
    return {"affiliate": affiliate, "api": client_for(org, membership.user)}


def test_the_affiliate_portal_is_privacy_limited(org, world, partner):
    referred = ClientFactory(organisation=org, display_name="The Smith Family")
    AffiliateReferralFactory(organisation=org, affiliate=partner["affiliate"], client=referred)
    AffiliateReferralFactory(organisation=org)  # another affiliate's client
    home = partner["api"].get("/api/v1/portal/affiliate")
    assert home.status_code == 200, home.content
    assert home.json()["summary"]["clicks"] == 7
    assert home.json()["links"][0]["url"].endswith("/?ref=HILL0001")
    clients = partner["api"].get("/api/v1/portal/affiliate/clients").json()
    assert [c["name"] for c in clients] == ["The S."]
    assert partner["api"].get("/api/v1/affiliates").status_code == 403  # no staff API
    assert world["family"]["api"].get("/api/v1/portal/affiliate").status_code == 403


def test_affiliates_set_their_own_payout_details(org, partner):
    body = {
        "payee_name": "Hillside PTA",
        "country": "GB",
        "bank": {"sort_code": "040004", "account_number": "87654321"},
    }
    response = partner["api"].put("/api/v1/portal/affiliate/payout", body, format="json")
    assert response.status_code == 200, response.content
    assert response.json()["bank_hint"] == "••4321"
    with tenant_context(org):
        partner["affiliate"].refresh_from_db()
        assert partner["affiliate"].payout_method == "bank_file"
        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute(
                "select bank_details from growth_affiliate where id = %s",
                [partner["affiliate"].pk],
            )
            assert "87654321" not in cursor.fetchone()[0]  # encrypted at rest


# --- T05 the commission engine, statements and payouts ------------------------------------------


@pytest.fixture
def referred(org):
    affiliate = AffiliateFactory(organisation=org, name="Hillside PTA")
    CommissionRuleFactory(organisation=org, percent=Decimal("10"), duration_months=12)
    client = ClientFactory(organisation=org, display_name="The Smiths")
    referral = AffiliateReferralFactory(organisation=org, affiliate=affiliate, client=client)
    return {"affiliate": affiliate, "client": client, "referral": referral}


def pay(org, client, amount):
    with tenant_context(org):
        return payments.record_manual_payment(client=client, amount=gbp(amount), method="cash")


def test_acceptance_commission_and_clawback(org, referred):
    """AC: 10% for 12 months; a £200 payment earns £20; a £50 refund claws back £5."""
    payment = pay(org, referred["client"], "200")
    with tenant_context(org):
        items = services.record_payment_commission(payment.pk)
        assert [(i.kind, i.amount) for i in items] == [("commission", gbp("20.00"))]
        assert services.record_payment_commission(payment.pk) == []  # idempotent
        refund = payments.refund_payment(payment, amount=gbp("50"), reason="Lesson cancelled")
        clawed = services.record_refund_clawback(payment.pk, refund.pk, gbp("50"))
        assert [(i.kind, i.amount) for i in clawed] == [("clawback", gbp("-5.00"))]
        assert services.record_refund_clawback(payment.pk, refund.pk, gbp("50")) == []
    assert events_of(org, "commission.earned")[0]["amount"]["amount"] == "20.00"
    assert events_of(org, "commission.clawed_back")[0]["amount"]["amount"] == "-5.00"


def test_commission_handlers_follow_payment_events(org, referred):
    from tutortrack.core.events.base import EventEnvelope
    from tutortrack.growth import handlers

    pay(org, referred["client"], "100")
    with tenant_context(org):
        event = OutboxEvent.objects.get(event_type="payment.succeeded")
        handlers.payment_succeeded(EventEnvelope.from_payload(event.payload))
        handlers.payment_succeeded(EventEnvelope.from_payload(event.payload))  # redelivered
        assert CommissionItem.objects.filter(kind="commission").count() == 1
        referred["referral"].refresh_from_db()
        assert referred["referral"].converted_at is not None


def test_no_commission_after_the_window_or_for_paused_affiliates(org, referred):
    with tenant_context(org):
        AffiliateReferral.objects.filter(pk=referred["referral"].pk).update(
            attributed_at=now() - timedelta(days=400)
        )
    payment = pay(org, referred["client"], "100")
    with tenant_context(org):
        assert services.record_payment_commission(payment.pk) == []
        AffiliateReferral.objects.filter(pk=referred["referral"].pk).update(attributed_at=now())
        services.save_affiliate(referred["affiliate"], status="paused")
        assert services.record_payment_commission(payment.pk) == []


def test_bounty_tiers_and_affiliate_overrides(org, referred):
    affiliate = referred["affiliate"]
    with tenant_context(org):
        services.save_rule(None, name="Bounty", kind="bounty", bounty=gbp("30"))
        services.save_rule(
            None,
            affiliate=affiliate,
            name="VIP",
            kind="percent",
            percent=Decimal("12"),
            tiers=[{"from_clients": 1, "percent": "15"}],
        )
        kinds = sorted(r.name for r in services.rules_for(affiliate))
        assert kinds == ["Bounty", "VIP"]  # VIP replaces the default percent rule
    first = pay(org, referred["client"], "100")
    second = pay(org, referred["client"], "100")
    with tenant_context(org):
        made = services.record_payment_commission(first.pk)
        assert sorted((i.kind, str(i.amount.amount)) for i in made) == [
            ("bounty", "30.00"),
            ("commission", "15.00"),
        ]  # converted counts this client: the 15% tier applies
        again = services.record_payment_commission(second.pk)
        assert [(i.kind, str(i.amount.amount)) for i in again] == [("commission", "15.00")]


def test_refunds_outside_the_clawback_window_keep_commission(org, referred):
    settings(org, clawback_days=0)
    payment = pay(org, referred["client"], "100")
    with tenant_context(org):
        services.record_payment_commission(payment.pk)
        from tutortrack.payments.models import Payment

        Payment.objects.filter(pk=payment.pk).update(received_at=now() - timedelta(days=2))
        assert services.record_refund_clawback(payment.pk, "r1", gbp("100")) == []


def test_statements_carry_items_and_are_paid(org, referred):
    payment = pay(org, referred["client"], "200")
    with tenant_context(org):
        services.record_payment_commission(payment.pk)
        loser = AffiliateFactory(organisation=org)
        services.adjust_commission(loser, amount=gbp("-5"), description="Correction")
    response = client_for(org, MembershipFactory(organisation=org, role="finance").user).post(
        "/api/v1/affiliate-statements/issue",
        {"period_end": str((now() + timedelta(days=1)).date())},
        format="json",
        HTTP_IDEMPOTENCY_KEY="statements-1",
    )
    assert response.status_code == 201, response.content
    issued = response.json()
    assert len(issued) == 1  # the negative balance carries forward
    assert issued[0]["number"] == "AFS-000001"
    assert issued[0]["total"]["amount"] == "20.00"
    with tenant_context(org):
        statement = AffiliateStatement.objects.get(pk=issued[0]["id"])
        assert statement.items.count() == 1
        assert CommissionItem.objects.filter(statement__isnull=True).count() == 1
        paid = services.mark_statement_paid(statement, reference="BACS 14/10")
        assert paid.status == "paid"
    assert events_of(org, "affiliate_statement.issued")[0]["number"] == "AFS-000001"


def test_bank_file_for_affiliate_statements(org, referred, world):
    with tenant_context(org):
        services.save_affiliate(
            referred["affiliate"],
            payout_method="bank_file",
            bank_country="GB",
            bank={"sort_code": "040004", "account_number": "12345678"},
        )
    payment = pay(org, referred["client"], "300")
    with tenant_context(org):
        services.record_payment_commission(payment.pk)
        [statement] = services.issue_statements(now().date() + timedelta(days=1))
    response = world["api"].post(
        "/api/v1/affiliate-statements/bank-file",
        {"statements": [str(statement.pk)], "file_format": "csv"},
        format="json",
    )
    assert response.status_code == 200, response.content
    assert "12345678" in response.json()["content"]
    assert "30.00" in response.json()["content"]


def test_commission_items_are_immutable(org, referred):
    payment = pay(org, referred["client"], "100")
    with tenant_context(org):
        [item] = services.record_payment_commission(payment.pk)
        item.description = "changed"
        with pytest.raises(ImmutableRecord):
            item.save()


def test_monthly_statement_schedule_follows_the_setting(org, monkeypatch):
    from tutortrack.growth import schedules

    calls = []
    monkeypatch.setattr(schedules, "ensure_schedule", lambda **kw: calls.append(kw) or "sid")
    monkeypatch.setattr(schedules, "delete_schedule", lambda *a: calls.append(a) or True)
    with tenant_context(org):
        assert schedules.sync_statement_schedule() is None
        settings_service.update_settings("growth", {"growth.statement_schedule": "monthly"})
        assert schedules.sync_statement_schedule() == "sid"
    assert calls[-1]["cron"] == ["0 6 1 * *"]


# --- T06 tutor referral bonuses -----------------------------------------------------------------


def test_a_tutor_referral_pays_a_bonus_when_the_applicant_is_approved(org, world):
    settings(org, tutor_referral_bonus=50, tutor_referral_milestone_lessons=0)
    referral = TutorReferralFactory(
        organisation=org, referrer=world["tutor"], application_id="app-1"
    )
    hired = TutorProfileFactory(organisation=org)
    with tenant_context(org):
        paid = services.application_approved("app-1", hired.pk)
        assert paid is not None
        assert paid.status == "paid"
        item = PayItem.objects.get(pk=paid.pay_item_id)
        assert (item.kind, item.amount, item.tutor_id) == (
            "referral",
            gbp("50.00"),
            world["tutor"].pk,
        )
        assert services.pay_tutor_referral(referral).pay_item_id == paid.pay_item_id  # once


def test_tutor_referral_after_n_lessons_and_client_referrals(org, world):
    settings(
        org,
        tutor_referral_bonus=40,
        tutor_client_referral_bonus=25,
        tutor_referral_milestone_lessons=1,
    )
    hired = world["tutor"]
    referrer = TutorProfileFactory(organisation=org)
    TutorReferralFactory(organisation=org, referrer=referrer, referred_tutor=hired)
    done_lesson(org, world)
    with tenant_context(org):
        [paid] = services.tutor_lessons_completed([str(hired.pk)])
        assert paid.status == "paid"
        assert paid.bonus == gbp("40.00")
        code = services.code_for_tutor(referrer)
        enquiry = leads.create_enquiry(
            contact={"first_name": "Kim", "email": "kim@example.com"}, utm={"ref": code.code}
        )
        tutor_ref = services.attribute_enquiry(enquiry.pk)
        assert isinstance(tutor_ref, TutorReferral)
        assert tutor_ref.kind == "client"
        payments.record_manual_payment(client=enquiry.client, amount=gbp("30"), method="cash")
        assert services.client_paid(enquiry.client_id).status == "paid"


def test_staff_record_and_pay_tutor_referrals(org, world):
    other = TutorProfileFactory(organisation=org)
    response = world["api"].post(
        "/api/v1/tutor-referrals",
        {"referrer": str(world["tutor"].pk), "kind": "tutor", "referred_tutor": str(other.pk)},
        format="json",
    )
    assert response.status_code == 201, response.content
    rid = response.json()["id"]
    refused = world["api"].post(f"/api/v1/tutor-referrals/{rid}/pay", {}, format="json")
    assert refused.status_code == 422  # no bonus configured
    paid = world["api"].post(
        f"/api/v1/tutor-referrals/{rid}/pay",
        {"amount": {"amount": "35.00", "currency": "GBP"}},
        format="json",
    )
    assert paid.status_code == 200
    assert paid.json()["status"] == "paid"


def test_application_with_a_tutor_code_is_attributed(org, world, monkeypatch):
    with tenant_context(org):
        code = services.code_for_tutor(world["tutor"])
    monkeypatch.setattr(
        selectors, "application_ref", lambda application_id: ("Sam Taylor", code.code.lower())
    )
    with tenant_context(org):
        found = services.attribute_application("app-9")
        assert found is not None
        assert (found.kind, found.referred_name) == ("tutor", "Sam Taylor")
        assert services.attribute_application("app-9") is None


def test_tutors_see_their_referral_page(org, world):
    TutorReferralFactory(organisation=org, referrer=world["tutor"], referred_name="Sam Taylor")
    page = world["tutor_api"].get("/api/v1/portal/tutor/referrals")
    assert page.status_code == 200, page.content
    body = page.json()
    assert body["tutor_link"].endswith(f"/vacancies?ref={body['code']}")
    assert body["referrals"][0]["referred_name"] == "Sam T."
    others = world["tutor_api"].get("/api/v1/tutor-referrals").json()["results"]
    assert len(others) == 1  # own scope


# --- tenant isolation ---------------------------------------------------------------------------


class TestReviewIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/reviews"

    def make_object(self, organisation):
        return ReviewFactory(organisation=organisation)


class TestReviewRequestIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/review-requests"

    def make_object(self, organisation):
        return ReviewRequestFactory(organisation=organisation)


class TestProgramIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/referral-programs"

    def make_object(self, organisation):
        return ReferralProgramFactory(organisation=organisation)


class TestReferralIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/referrals"

    def make_object(self, organisation):
        return ReferralFactory(organisation=organisation)


class TestReferralCodeIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/referral-codes"

    def make_object(self, organisation):
        with tenant_context(organisation):
            return services.code_for_client(ClientFactory(organisation=organisation))


class TestAffiliateIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/affiliates"

    def make_object(self, organisation):
        return AffiliateFactory(organisation=organisation)


class TestAffiliateLinkIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/affiliate-links"

    def make_object(self, organisation):
        return AffiliateLinkFactory(organisation=organisation)


class TestAffiliateReferralIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/affiliate-referrals"

    def make_object(self, organisation):
        return AffiliateReferralFactory(organisation=organisation)


class TestCommissionRuleIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/commission-rules"

    def make_object(self, organisation):
        return CommissionRuleFactory(organisation=organisation)


class TestCommissionItemIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/commission-items"

    def make_object(self, organisation):
        with tenant_context(organisation):
            return services.adjust_commission(
                AffiliateFactory(organisation=organisation), amount=gbp("5"), description="x"
            )


class TestStatementIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/affiliate-statements"

    def make_object(self, organisation):
        with tenant_context(organisation):
            services.adjust_commission(
                AffiliateFactory(organisation=organisation), amount=gbp("5"), description="x"
            )
            return services.issue_statements(now().date() + timedelta(days=1))[0]


class TestTutorReferralIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/tutor-referrals"

    def make_object(self, organisation):
        return TutorReferralFactory(organisation=organisation)
