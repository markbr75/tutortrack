import factory

from tutortrack.core.tests.factories import TenantFactory
from tutortrack.people.tests.factories import TutorProfileFactory
from tutortrack.sites.models import (
    BrandKit,
    PublicProfile,
    Site,
    SitePage,
    Testimonial,
    WidgetConfig,
)


class BrandKitFactory(TenantFactory):
    class Meta:
        model = BrandKit

    primary_colour = "#1d4ed8"


class WidgetFactory(TenantFactory):
    class Meta:
        model = WidgetConfig

    key = factory.Sequence(lambda n: f"w-test{n}")
    kind = "reviews"
    name = factory.Sequence(lambda n: f"Widget {n}")


class QuoteFactory(TenantFactory):
    class Meta:
        model = Testimonial

    quote = "Fantastic tutoring."
    author = "Sam"
    rating = 5


class PublicProfileFactory(TenantFactory):
    class Meta:
        model = PublicProfile

    tutor = factory.SubFactory(
        TutorProfileFactory,
        organisation=factory.SelfAttribute("..organisation"),
        status="active",
        public_profile=True,
    )
    slug = factory.Sequence(lambda n: f"tutor-{n}")
    listed = True
    status = PublicProfile.Status.APPROVED
    published = factory.LazyFunction(
        lambda: {"display_name": "Ada L.", "headline": "Maths whizz", "bio": "Hello", "show": []}
    )
    draft = factory.SelfAttribute("published")


class SiteFactory(TenantFactory):
    class Meta:
        model = Site

    name = "Bright Minds"


class SitePageFactory(TenantFactory):
    class Meta:
        model = SitePage

    site = factory.SubFactory(SiteFactory, organisation=factory.SelfAttribute("..organisation"))
    path = factory.Sequence(lambda n: f"page-{n}")
    title = "A page"
