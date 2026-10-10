from django.apps import AppConfig


class ReportingConfig(AppConfig):
    name = "tutortrack.reporting"
    label = "reporting"
    verbose_name = "Reporting and dashboards"

    def ready(self) -> None:
        from . import handlers, notifications, org_settings  # noqa: F401
        from .reports import load_all

        load_all()
