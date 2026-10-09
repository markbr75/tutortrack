from django.apps import AppConfig


class PaymentsConfig(AppConfig):
    name = "tutortrack.payments"
    label = "payments"
    verbose_name = "Payments"

    def ready(self) -> None:
        from . import handlers, org_settings  # noqa: F401
