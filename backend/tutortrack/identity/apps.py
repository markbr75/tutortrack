from django.apps import AppConfig


class IdentityConfig(AppConfig):
    name = "tutortrack.identity"
    label = "identity"
    verbose_name = "Identity"

    def ready(self) -> None:
        from . import signals  # noqa: F401
