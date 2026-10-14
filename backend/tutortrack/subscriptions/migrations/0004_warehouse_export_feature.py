"""E26-T09: re-sync the plan catalogue for the new ``warehouse_export`` feature (Enterprise)."""

from django.db import migrations


def sync(apps, schema_editor):
    from tutortrack.subscriptions.catalogue import sync_plans

    sync_plans(
        (
            apps.get_model("subscriptions", "Plan"),
            apps.get_model("subscriptions", "PlanPrice"),
            apps.get_model("subscriptions", "PlanEntitlement"),
        )
    )


class Migration(migrations.Migration):
    dependencies = [("subscriptions", "0003_ai_credit_allowance")]

    operations = [migrations.RunPython(sync, migrations.RunPython.noop)]
