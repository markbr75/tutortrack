"""Dev seed (E24): brand kit, a published website, widgets, testimonials and public tutor
profiles for the demo organisation. Visit http://brightminds.site.localhost:8010/."""

from django.db import transaction

from tutortrack.core.context import tenant_context
from tutortrack.core.seeding import SeedContext, seed_step


@seed_step(order=990)
def website(ctx: SeedContext) -> None:
    from tutortrack.people.models import TutorProfile

    from . import services
    from .models import PublicProfile, Site, Testimonial, WidgetConfig

    with tenant_context(ctx.organisation), transaction.atomic():
        services.save_brand_kit(
            primary_colour="#1d4ed8",
            secondary_colour="#0f172a",
            font="Inter",
            email_footer="Bright Minds Tutoring · Learning that sticks",
            social_links={"instagram": "https://www.instagram.com/brightminds"},
        )
        if not Testimonial.objects.exists():
            for quote, author, role in (
                ("Our daughter's confidence in maths has soared.", "Sarah", "Parent, Year 9"),
                ("Brilliant tutors who really get to know you.", "James", "A-level student"),
                ("Organised, friendly and great value.", "Priya", "Parent, Year 6"),
            ):
                services.save_testimonial(quote=quote, author=author, role=role, rating=5)
        admin = getattr(ctx, "admin", None)
        for tutor in TutorProfile.objects.filter(status="active")[:6]:
            if PublicProfile.objects.filter(tutor=tutor).exists():
                continue
            profile = services.ensure_profile(tutor)
            services.approve_profile(profile, admin)
        if not WidgetConfig.objects.exists():
            services.create_widget(
                kind="tutor_directory",
                name="Tutor directory",
                allowed_origins=["http://localhost:5175"],
            )
            services.create_widget(kind="reviews", name="Reviews")
        site = Site.objects.first() or services.create_site()
        for page in site.pages.all():
            if page.live_version_id is None:
                services.publish_page(page, admin)
        if not site.published:
            services.update_site(site, published=True)
        if not site.posts.exists():  # G6: a news post for /blog
            post = services.create_post(
                site,
                title="Summer exam results",
                excerpt="Our students' best results yet.",
                body="Congratulations to everyone who sat exams this summer.\n\n"
                "Enrolment for the new term is open now.",
                author_name="Bright Minds team",
            )
            services.publish_post(post)
    ctx.log("    website: http://brightminds.site.localhost:8010/ (blog: /blog)")
