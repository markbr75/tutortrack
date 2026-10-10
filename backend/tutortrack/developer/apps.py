from django.apps import AppConfig


class DeveloperConfig(AppConfig):
    name = "tutortrack.developer"
    label = "developer"
    verbose_name = "Developer platform (API keys, OAuth apps, webhooks)"

    def ready(self) -> None:
        from django.utils.module_loading import autodiscover_modules

        # Every app's events must be registered before webhooks subscribe to them.
        autodiscover_modules("events")
        from . import handlers, notifications, org_settings, schema  # noqa: F401

        handlers.connect()
