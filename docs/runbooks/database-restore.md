# Restore the database

Use for data loss across organisations (for one organisation, see
[restore-one-organisation.md](restore-one-organisation.md)).

1. Declare an incident ([incident-comms.md](incident-comms.md)) and post a platform notice
   from the console (Operations → Notices) with severity "outage".
2. Scale `worker`, `beat` and `temporal-worker` to 0 so nothing writes during the restore.
3. Restore to a point in time just before the problem:
   `aws rds restore-db-instance-to-point-in-time --source-db-instance-identifier <id>
   --target-db-instance-identifier <id>-restore --restore-time <UTC>`
   (or from an AWS Backup recovery point, including the copy in the backup account).
4. Check the restored instance (row counts, latest invoices and payments).
5. Swap: point `DATABASE_URL`, `DATABASE_OWNER_URL` and `DATABASE_PLATFORM_URL` secrets at
   the restored instance and redeploy, or rename the instances.
6. Scale services back up. Replay Stripe webhooks for the lost window from the Stripe
   dashboard (payments are idempotent by provider reference).
7. End the notice and write the post-incident review.
