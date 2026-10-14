from django.db import migrations

from tutortrack.core.ids import new_id


def backfill(apps, schema_editor):
    """The COPPA parental-consent type (E29-T10) for organisations created before it."""
    db = schema_editor.connection.alias  # owner connection (bypasses RLS)
    Organisation = apps.get_model("tenancy", "Organisation")
    ConsentType = apps.get_model("privacy", "ConsentType")
    for org in Organisation.objects.using(db).all():
        if not ConsentType.objects.using(db).filter(organisation=org, key="parental-consent").exists():
            ConsentType.objects.using(db).create(
                id=new_id(),
                organisation=org,
                key="parental-consent",
                name="Parental consent for a child's login",
                category="parental_consent",
                required=False,
                applies_to=["people.student"],
            )


class Migration(migrations.Migration):
    dependencies = [("privacy", "0003_e29_part2")]

    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
