from typing import Any

from django.apps import AppConfig
from django.db.models.signals import post_migrate
from django.utils.module_loading import autodiscover_modules


def _grant_after_migrate(sender: AppConfig, using: str, **_: Any) -> None:
    """New tables need privileges for the app/platform roles (no-op if roles are absent)."""
    from django.db import connections

    if connections[using].vendor != "postgresql":
        return
    from .dbroles import grant_privileges

    grant_privileges(using)


class CoreConfig(AppConfig):
    name = "tutortrack.core"
    label = "core"
    verbose_name = "Core"

    def ready(self) -> None:
        # Domain event subscribers live in each app's handlers.py.
        autodiscover_modules("handlers")
        from . import signals  # noqa: F401
        from .db import connect_signals

        connect_signals()
        post_migrate.connect(_grant_after_migrate, sender=self, dispatch_uid="core.grant")
