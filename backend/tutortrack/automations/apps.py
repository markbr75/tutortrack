from django.apps import AppConfig


class AutomationsConfig(AppConfig):
    name = "tutortrack.automations"
    label = "automations"
    verbose_name = "Automations"

    def ready(self) -> None:
        from . import builtins, handlers, org_settings  # noqa: F401
