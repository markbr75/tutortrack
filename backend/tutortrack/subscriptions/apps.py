from django.apps import AppConfig


class SubscriptionsConfig(AppConfig):
    name = "tutortrack.subscriptions"
    label = "subscriptions"
    verbose_name = "Subscriptions"

    def ready(self) -> None:
        from tutortrack.comms.channels import set_credit_meter
        from tutortrack.core import entitlements, flags

        from . import handlers  # noqa: F401
        from .credits import SmsCreditMeter
        from .entitlements import PlanResolver

        entitlements.set_resolver(PlanResolver())
        flags.PLAN_RESOLVER = "tutortrack.subscriptions.entitlements.plan_key_for"
        set_credit_meter(SmsCreditMeter())
