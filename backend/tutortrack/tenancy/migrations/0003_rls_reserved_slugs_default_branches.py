from django.db import migrations

from tutortrack.core.ids import new_id
from tutortrack.core.migrations_utils import enable_rls

RESERVED = [
    "about", "account", "accounts", "admin", "affiliate", "affiliates", "api", "app", "apps",
    "assets", "auth", "billing", "blog", "cdn", "dashboard", "demo", "dev", "developer",
    "developers", "docs", "email", "files", "ftp", "help", "home", "imap", "info", "login",
    "logout", "mail", "marketing", "media", "news", "pop", "portal", "pricing", "privacy",
    "sales", "security", "signin", "signup", "smtp", "sso", "staging", "static", "status",
    "support", "terms", "test", "tutortrack", "webhooks", "widgets", "www",
]  # fmt: skip


def seed_reserved(apps, schema_editor):
    db = schema_editor.connection.alias  # the owner connection running the migration
    ReservedSlug = apps.get_model("tenancy", "ReservedSlug")
    ReservedSlug.objects.using(db).bulk_create(
        [ReservedSlug(slug=s, reason="platform") for s in RESERVED], ignore_conflicts=True
    )


def default_branches(apps, schema_editor):
    """Every organisation has a default branch (FR-02-2); backfill existing ones."""
    db = schema_editor.connection.alias
    Organisation = apps.get_model("tenancy", "Organisation")
    Branch = apps.get_model("tenancy", "Branch")
    for org in Organisation.objects.using(db).all():
        if not Branch.objects.using(db).filter(organisation=org, is_default=True).exists():
            Branch.objects.using(db).create(
                id=new_id(),
                organisation=org,
                name=org.name,
                code="MAIN",
                timezone=org.timezone,
                currency=org.default_currency,
                locale=org.locale,
                is_default=True,
            )


class Migration(migrations.Migration):
    dependencies = [("tenancy", "0002_branch_organisationdomain_reservedslug_and_more")]

    operations = [
        enable_rls("tenancy_branch"),
        migrations.RunPython(seed_reserved, migrations.RunPython.noop),
        migrations.RunPython(default_branches, migrations.RunPython.noop),
    ]
