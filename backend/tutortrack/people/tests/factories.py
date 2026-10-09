import factory

from tutortrack.core.tests.factories import TenantFactory
from tutortrack.people.models import Client, Contact, Student, TutorProfile


class ClientFactory(TenantFactory):
    class Meta:
        model = Client

    display_name = factory.Sequence(lambda n: f"Family {n}")
    currency = "GBP"


class ContactFactory(TenantFactory):
    class Meta:
        model = Contact

    client = factory.SubFactory(ClientFactory, organisation=factory.SelfAttribute("..organisation"))
    first_name = factory.Faker("first_name")
    last_name = factory.Faker("last_name")
    email = factory.Sequence(lambda n: f"contact{n}@example.com")


class StudentFactory(TenantFactory):
    class Meta:
        model = Student

    client = factory.SubFactory(ClientFactory, organisation=factory.SelfAttribute("..organisation"))
    first_name = factory.Faker("first_name")
    last_name = factory.Faker("last_name")


class TutorProfileFactory(TenantFactory):
    class Meta:
        model = TutorProfile

    email = factory.Sequence(lambda n: f"tutor{n}@example.com")
    first_name = factory.Faker("first_name")
    last_name = factory.Faker("last_name")
