from django.apps import AppConfig


class BillingConfig(AppConfig):
    name = "tutortrack.billing"
    label = "billing"
    verbose_name = "Client billing"

    def ready(self) -> None:
        from tutortrack.crm import selectors as crm
        from tutortrack.crm import targets
        from tutortrack.delivery import balance

        from . import handlers, org_settings  # noqa: F401
        from .guard import PrepaidBalanceGuard
        from .models import Invoice

        targets.register("billing.invoice", Invoice, "billing.invoice.view", "Invoice")
        balance.set_guard(PrepaidBalanceGuard())

        from .selectors import invoice_timeline

        crm.register_timeline_provider("invoice", invoice_timeline)  # E05 FR-05-10
