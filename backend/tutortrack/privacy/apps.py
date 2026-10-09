from django.apps import AppConfig


class PrivacyConfig(AppConfig):
    name = "tutortrack.privacy"
    label = "privacy"
    verbose_name = "Privacy"

    def ready(self) -> None:
        from . import subjects  # noqa: F401 - registers built-in consent subjects
