# Restore one organisation's data

Use when a customer deleted or overwrote their own data by mistake.

1. Get the owner's written request with what was lost and roughly when (UTC).
2. Restore a point-in-time copy of the database into a scratch instance (see
   [database-restore.md](database-restore.md) step 3; don't touch production).
3. From a one-off task with `DATABASE_PLATFORM_URL` pointing at the scratch instance:
   `python manage.py tenant_dump <slug> --output /tmp/<slug>.json [--app people --app billing]`
   (every row of that organisation, read through the BYPASSRLS role).
4. Load the dump into a staging database with `python manage.py loaddata`, find the records,
   and recreate them in production **through the app's services or API** (so audit, events
   and invoices stay consistent). Financial records are never edited: use credit notes.
5. Confirm with the owner, and delete the dump and the scratch instance.
