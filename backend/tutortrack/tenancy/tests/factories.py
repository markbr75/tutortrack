import factory

from tutortrack.tenancy.models import Organisation


class OrganisationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Organisation
        django_get_or_create = ("slug",)

    name = factory.Sequence(lambda n: f"Tutoring Co {n}")
    slug = factory.Sequence(lambda n: f"tutoring-co-{n}")
    status = Organisation.Status.ACTIVE
