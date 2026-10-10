from django.apps import AppConfig


class MatchingConfig(AppConfig):
    name = "tutortrack.matching"
    label = "matching"
    verbose_name = "Matching and job marketplace"

    def ready(self) -> None:
        from . import handlers, org_settings  # noqa: F401
