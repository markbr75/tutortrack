from django.db import migrations

from tutortrack.core.migrations_utils import enable_rls


class Migration(migrations.Migration):
    dependencies = [("identity", "0003_membershipbranch_branch_membershipbranch_created_by_and_more")]

    operations = [
        # Members can also see their own memberships in other organisations (org switcher).
        enable_rls("identity_membership", user_column="user_id"),
        enable_rls("identity_membershipbranch"),
    ]
