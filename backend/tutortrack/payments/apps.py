from django.apps import AppConfig


class PaymentsConfig(AppConfig):
    name = "tutortrack.payments"
    label = "payments"
    verbose_name = "Payments"

    def ready(self) -> None:
        from tutortrack.crm import selectors as crm

        from . import bank_feeds, handlers, org_settings  # noqa: F401
        from .selectors import payment_timeline

        crm.register_timeline_provider("payment", payment_timeline)  # E05 FR-05-10
