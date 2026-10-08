from django.db import migrations

from tutortrack.core.migrations_utils import enable_rls


class Migration(migrations.Migration):
    dependencies = [("testapp", "0001_initial")]

    operations = [enable_rls("testapp_gadget"), enable_rls("testapp_widget")]
