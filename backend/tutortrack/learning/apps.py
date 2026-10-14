from django.apps import AppConfig


class LearningConfig(AppConfig):
    name = "tutortrack.learning"
    label = "learning"
    verbose_name = "Learning tools"

    def ready(self) -> None:
        from . import files, handlers, notifications, org_settings  # noqa: F401
