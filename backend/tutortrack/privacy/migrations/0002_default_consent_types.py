from django.db import migrations

from tutortrack.core.ids import new_id

# Snapshot of privacy.services.DEFAULT_TYPES at the time of this migration.
DEFAULTS = [
    ("terms", "Terms of service", "terms_of_service", True, ["people.contact", "identity.user"]),
    ("privacy-policy", "Privacy policy", "privacy_policy", True, ["people.contact", "identity.user"]),
    ("data-processing", "Processing of personal data", "data_processing", True,
     ["people.contact", "people.student", "identity.user"]),
    ("marketing-email", "News and offers by email", "marketing_email", False,
     ["people.contact", "identity.user"]),
    ("marketing-sms", "News and offers by SMS", "marketing_sms", False,
     ["people.contact", "identity.user"]),
    ("photo-video", "Photos and video", "photo_video", False, ["people.student"]),
    ("lesson-recording", "Recording online lessons", "lesson_recording", False,
     ["people.student", "people.contact"]),
]  # fmt: skip


def backfill(apps, schema_editor):
    db = schema_editor.connection.alias  # owner connection (bypasses RLS)
    Organisation = apps.get_model("tenancy", "Organisation")
    ConsentType = apps.get_model("privacy", "ConsentType")
    for org in Organisation.objects.using(db).all():
        for key, name, category, required, applies_to in DEFAULTS:
            if not ConsentType.objects.using(db).filter(organisation=org, key=key).exists():
                ConsentType.objects.using(db).create(
                    id=new_id(), organisation=org, key=key, name=name, category=category,
                    required=required, applies_to=applies_to,
                )  # fmt: skip


class Migration(migrations.Migration):
    dependencies = [("privacy", "0001_initial"), ("tenancy", "0007_encrypt_tax_number")]

    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
