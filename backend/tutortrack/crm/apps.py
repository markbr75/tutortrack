from django.apps import AppConfig


class CrmConfig(AppConfig):
    name = "tutortrack.crm"
    label = "crm"
    verbose_name = "CRM"

    def ready(self) -> None:
        from . import notifications  # noqa: F401 - the note_mention type (FR-05-7)
