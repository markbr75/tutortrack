from django.apps import AppConfig


class AutomationsConfig(AppConfig):
    name = "tutortrack.automations"
    label = "automations"
    verbose_name = "Automations"

    def ready(self) -> None:
        from . import builtin_workflows, builtins, catalogue, g4, handlers, org_settings  # noqa: F401

        # (the catalogue and g4 register before handlers)
        builtin_workflows.discover()
