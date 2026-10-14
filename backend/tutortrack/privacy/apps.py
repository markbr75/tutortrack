from django.apps import AppConfig


class PrivacyConfig(AppConfig):
    name = "tutortrack.privacy"
    label = "privacy"
    verbose_name = "Privacy"

    def ready(self) -> None:
        from django.utils.module_loading import autodiscover_modules

        from . import (  # noqa: F401 - registrations
            handlers,
            notifications,
            org_settings,
            own_data,
            retention,
            safeguarding,
            safeguards,
            subjects,
        )

        # Every app's privacy provider (``<app>/privacy.py``, ADR 0028).
        autodiscover_modules("privacy")
