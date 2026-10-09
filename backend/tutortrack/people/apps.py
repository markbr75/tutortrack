from django.apps import AppConfig


class PeopleConfig(AppConfig):
    name = "tutortrack.people"
    label = "people"
    verbose_name = "People"

    def ready(self) -> None:
        from tutortrack.crm import targets

        from . import consent_subjects  # noqa: F401
        from .models import Client, Contact, Student, TutorProfile

        targets.register("people.client", Client, "people.client.view", "Client")
        targets.register("people.contact", Contact, "people.contact.view", "Contact")
        targets.register("people.student", Student, "people.student.view", "Student")
        targets.register("people.tutor", TutorProfile, "people.tutor.view", "Tutor")
