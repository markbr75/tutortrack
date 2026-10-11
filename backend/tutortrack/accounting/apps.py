from django.apps import AppConfig


class AccountingConfig(AppConfig):
    name = "tutortrack.accounting"
    label = "accounting"
    verbose_name = "Accounting integrations"

    def ready(self) -> None:
        from . import handlers, notifications, org_settings, providers  # noqa: F401
