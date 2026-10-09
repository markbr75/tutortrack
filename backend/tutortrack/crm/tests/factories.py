import factory

from tutortrack.core.tests.factories import TenantFactory
from tutortrack.crm.models import Note, SavedView, Tag, Task


class TagFactory(TenantFactory):
    class Meta:
        model = Tag

    name = factory.Sequence(lambda n: f"Tag {n}")


class NoteFactory(TenantFactory):
    class Meta:
        model = Note

    target_type = "people.client"
    target_id = ""
    body = "<p>Called about Year 10 maths.</p>"


class TaskFactory(TenantFactory):
    class Meta:
        model = Task

    title = factory.Sequence(lambda n: f"Follow up {n}")


class SavedViewFactory(TenantFactory):
    class Meta:
        model = SavedView

    entity_type = "people.client"
    name = factory.Sequence(lambda n: f"View {n}")
    owner = factory.SubFactory("tutortrack.identity.tests.factories.UserFactory")
