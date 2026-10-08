from django.apps import AppConfig
from django.utils.module_loading import autodiscover_modules


class CoreConfig(AppConfig):
    name = "tutortrack.core"
    label = "core"
    verbose_name = "Core"

    def ready(self) -> None:
        # Domain event subscribers live in each app's handlers.py.
        autodiscover_modules("handlers")
        from . import signals  # noqa: F401
