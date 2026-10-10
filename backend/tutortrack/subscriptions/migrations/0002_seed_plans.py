"""Seed the plan catalogue (FR-04-1). Later catalogue changes: ``manage.py sync_plans``."""

from django.db import migrations


def seed(apps, schema_editor):
    from tutortrack.subscriptions.catalogue import sync_plans

    sync_plans(
        (
            apps.get_model("subscriptions", "Plan"),
            apps.get_model("subscriptions", "PlanPrice"),
            apps.get_model("subscriptions", "PlanEntitlement"),
        )
    )


class Migration(migrations.Migration):
    dependencies = [("subscriptions", "0001_initial")]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
