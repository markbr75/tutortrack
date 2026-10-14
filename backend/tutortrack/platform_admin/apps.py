from django.apps import AppConfig


class PlatformAdminConfig(AppConfig):
    name = "tutortrack.platform_admin"
    label = "platform_admin"
    verbose_name = "Platform administration"

    def ready(self) -> None:
        from . import notifications  # noqa: F401 - the comms type for customer notices
