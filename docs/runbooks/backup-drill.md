# Quarterly restore drill

1. Pick a random time in the last 30 days.
2. Restore RDS to that point into a scratch instance, and restore the latest AWS Backup
   recovery point **from the backup account's vault**.
3. Run `manage.py check --database default` and spot-check row counts for organisations,
   invoices and payments against production at that time.
4. Run `tenant_dump` for one organisation to prove the per-tenant tool works.
5. Record the time taken (target RTO ≤ 4 hours) and any problems in the drill log below,
   then delete the scratch resources.

| Date | Restore point | Time to usable | Notes |
|---|---|---|---|
