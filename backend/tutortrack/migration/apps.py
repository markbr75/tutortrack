from django.apps import AppConfig


class MigrationConfig(AppConfig):
    name = "tutortrack.migration"
    label = "migration"
    verbose_name = "Import, export and migration"

    def ready(self) -> None:
        from . import connectors, files, handlers, notifications, org_settings  # noqa: F401
