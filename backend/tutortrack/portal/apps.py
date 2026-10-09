from django.apps import AppConfig


class PortalConfig(AppConfig):
    name = "tutortrack.portal"
    label = "portal"
    verbose_name = "Client and student portal"

    def ready(self) -> None:
        from . import org_settings  # noqa: F401
