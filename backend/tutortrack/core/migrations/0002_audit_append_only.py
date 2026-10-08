"""Make core_auditentry append-only at the database level.

UPDATE and DELETE raise unless the transaction has explicitly opted in with
``SET LOCAL tutortrack.audit_purge = 'on'`` (used only by E29 retention purges).
TRUNCATE is prevented by privileges instead: from E02 the application database role does
not own tables (Django's test-database flush relies on TRUNCATE as the owner).
"""

from django.db import migrations

FORWARD = """
CREATE OR REPLACE FUNCTION core_auditentry_block_mutation() RETURNS trigger AS $$
BEGIN
    IF current_setting('tutortrack.audit_purge', true) = 'on' AND TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RAISE EXCEPTION 'core_auditentry is append-only (% blocked)', TG_OP
        USING ERRCODE = 'insufficient_privilege';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER core_auditentry_append_only
    BEFORE UPDATE OR DELETE ON core_auditentry
    FOR EACH ROW EXECUTE FUNCTION core_auditentry_block_mutation();
"""

REVERSE = """
DROP TRIGGER IF EXISTS core_auditentry_append_only ON core_auditentry;
DROP FUNCTION IF EXISTS core_auditentry_block_mutation();
"""


class Migration(migrations.Migration):
    dependencies = [("core", "0001_initial")]

    operations = [migrations.RunSQL(FORWARD, REVERSE)]
