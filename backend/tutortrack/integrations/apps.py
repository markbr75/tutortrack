from django.apps import AppConfig


class IntegrationsConfig(AppConfig):
    name = "tutortrack.integrations"
    label = "integrations"
    verbose_name = "Integrations"

    def ready(self) -> None:
        from . import notifications, org_settings, providers  # noqa: F401
