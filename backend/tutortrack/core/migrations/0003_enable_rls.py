"""Row-level security for the E01 tenant tables (FR-02-4, applied retro-actively)."""

from django.db import migrations

from tutortrack.core.migrations_utils import enable_rls


class Migration(migrations.Migration):
    dependencies = [("core", "0002_audit_append_only")]

    operations = [
        enable_rls("core_storedfile"),
        enable_rls("core_sequence"),
        # Platform-level actions (e.g. signups) are audited without an organisation.
        enable_rls("core_auditentry", allow_null_org_writes=True),
    ]
