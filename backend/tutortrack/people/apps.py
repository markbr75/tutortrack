from django.apps import AppConfig


class PeopleConfig(AppConfig):
    name = "tutortrack.people"
    label = "people"
    verbose_name = "People"

    def ready(self) -> None:
        from . import consent_subjects  # noqa: F401
