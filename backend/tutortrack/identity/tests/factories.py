import factory

from tutortrack.core.tests.factories import TenantFactory
from tutortrack.identity.models import Membership, User

TEST_PASSWORD = "correct-horse-battery"


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = User

    email = factory.Sequence(lambda n: f"user{n}@example.com")
    first_name = factory.Faker("first_name")
    last_name = factory.Faker("last_name")
    password = factory.django.Password(TEST_PASSWORD)


class MembershipFactory(TenantFactory):
    class Meta:
        model = Membership

    user = factory.SubFactory(UserFactory)
    role = Membership.Role.ADMIN
    status = Membership.Status.ACTIVE
