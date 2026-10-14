"""Demo growth data (E25): a referral programme, approved and pending reviews of the first
tutor, and a school affiliate with a tracking link and the default commission rule."""

from decimal import Decimal

from tutortrack.core.context import tenant_context
from tutortrack.core.money import Money
from tutortrack.core.seeding import SeedContext, seed_step


@seed_step(order=80)
def growth_demo(ctx: SeedContext) -> None:
    from tutortrack.growth import services
    from tutortrack.growth.models import Affiliate, ReferralProgram, Review
    from tutortrack.people.models import Client, TutorProfile

    with tenant_context(ctx.organisation):
        if ReferralProgram.objects.exists():
            return
        currency = str(ctx.organisation.default_currency or "GBP")
        services.save_program(
            None,
            name="Refer a friend",
            referrer_reward=Money(Decimal("20.00"), currency),
            referee_discount_percent=Decimal("10.00"),
            max_rewards_per_period=5,
        )
        tutor = TutorProfile.objects.filter(status=TutorProfile.Status.ACTIVE).first()
        clients = list(Client.objects.filter(archived_at__isnull=True).order_by("display_name")[:3])
        quotes = [
            (5, "Our daughter's confidence in maths has grown so much this term.", "Priya P."),
            (4, "Patient, well prepared and always on time.", "James W."),
            (5, "Exam results went up two grades. Thank you!", "Sofia M."),
        ]
        for n, client in enumerate(clients):
            rating, text, name = quotes[n]
            review = services.create_review(
                client=client,
                tutor=tutor,
                rating=rating,
                text=text,
                reviewer_name=name,
                publish_consent=True,
                source=Review.Source.STAFF,
            )
            if n < 2:
                services.moderate(review, action="approve")
        if not Affiliate.objects.exists():
            services.save_affiliate(
                None,
                kind=Affiliate.Kind.ORGANISATION,
                name="Hillside Primary PTA",
                email="pta@hillside.example",
                currency=currency,
            )
            services.save_rule(
                None,
                name="Standard partner rate",
                kind="percent",
                percent=Decimal("10.00"),
                duration_months=12,
            )
        ctx.log("    created a referral programme, reviews and an affiliate")
