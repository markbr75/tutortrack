import factory

from tutortrack.core.context import tenant_context
from tutortrack.core.tests.factories import TenantFactory
from tutortrack.tenancy.models import Branch, Organisation


class OrganisationFactory(factory.django.DjangoModelFactory):
    """Creates the organisation row only. Use ``tenancy.services.create_organisation`` when a
    test needs the full signup result (default branch, owner membership, events)."""

    class Meta:
        model = Organisation
        django_get_or_create = ("slug",)
        skip_postgeneration_save = True

    name = factory.Sequence(lambda n: f"Tutoring Co {n}")
    slug = factory.Sequence(lambda n: f"tutoring-co-{n}")
    status = Organisation.Status.ACTIVE

    @factory.post_generation
    def default_branch(self, create: bool, extracted: object, **kwargs: object) -> None:
        if not create:
            return
        with tenant_context(self):
            if not Branch.objects.filter(is_default=True).exists():
                BranchFactory(organisation=self, is_default=True, code="MAIN", name=self.name)


class BranchFactory(TenantFactory):
    class Meta:
        model = Branch

    name = factory.Sequence(lambda n: f"Branch {n}")
    code = factory.Sequence(lambda n: f"B{n}")
    timezone = "Europe/London"
    currency = "GBP"
    locale = "en-GB"
