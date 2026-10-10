"""Write the plan catalogue to the database and, with ``--stripe``, create the matching
Stripe products, prices and the revenue-share meter on the platform account."""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError

from tutortrack.subscriptions.catalogue import sync_plans


class Command(BaseCommand):
    help = "Sync the plan catalogue (and optionally Stripe prices)."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--stripe", action="store_true", help="Create missing Stripe prices")

    def handle(self, *args: Any, **options: Any) -> None:
        count = sync_plans()
        self.stdout.write(f"{count} plans synced.")
        if options["stripe"]:
            from django.conf import settings

            if not settings.STRIPE["SECRET_KEY"]:
                raise CommandError("STRIPE_SECRET_KEY is not set.")
            created = _sync_stripe()
            self.stdout.write(f"{created} Stripe prices created.")


def _sync_stripe() -> int:
    import stripe
    from django.conf import settings

    from tutortrack.subscriptions.models import PlanPrice
    from tutortrack.subscriptions.services import REVENUE_METER

    client = stripe.StripeClient(settings.STRIPE["SECRET_KEY"])
    meters: Any = client.billing.meters.list(params={"limit": 100})
    meter: Any = next((m for m in meters["data"] if m["event_name"] == REVENUE_METER), None)
    if meter is None:
        meter = client.billing.meters.create(
            params={
                "display_name": "Payments processed (minor units)",
                "event_name": REVENUE_METER,
                "default_aggregation": {"formula": "sum"},
                "customer_mapping": {"type": "by_id", "event_payload_key": "stripe_customer_id"},
                "value_settings": {"event_payload_key": "value"},
            }
        )
    created = 0
    products: dict[str, str] = {}
    for price in PlanPrice.objects.select_related("plan").filter(stripe_price_id=""):
        lookup = f"tt:{price.plan.key}:{price.currency}:{price.interval}:{price.component}"
        product_key = f"{price.plan.key}:{price.component}"
        if product_key not in products:
            product = client.products.create(
                params={"name": f"TutorTrack {price.plan.name}: {price.get_component_display()}"}
            )
            products[product_key] = product["id"]
        params: Any = {
            "product": products[product_key],
            "currency": price.currency.lower(),
            "lookup_key": lookup,
            "transfer_lookup_key": True,
            "tax_behavior": "exclusive",
            "recurring": {"interval": price.interval},
        }
        if price.component == PlanPrice.Component.REVENUE_SHARE:
            # Value reported in minor units; the price per unit is the percentage of one.
            params["unit_amount_decimal"] = str(price.unit_amount / 100)
            params["recurring"].update({"usage_type": "metered", "meter": meter["id"]})
        else:
            params["unit_amount_decimal"] = str(price.unit_amount * 100)
        stripe_price = client.prices.create(params=params)
        PlanPrice.objects.filter(pk=price.pk).update(stripe_price_id=stripe_price["id"])
        created += 1
    return created
