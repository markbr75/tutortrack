# Deploy

1. Merge to `main`; CI must be green (`make check` equivalent).
2. The deploy workflow builds the image, pushes it to ECR and runs the `migrate` task
   (`ensure_db_roles` then `migrate`). Migrations are expand/contract: the old code must
   keep working against the new schema.
3. New task definitions roll out to `web`, `worker`, `beat` and `temporal-worker`. Old
   Temporal workers keep polling until they drain.
4. Watch the CloudWatch dashboard for 15 minutes: 5xx rate, p95 latency, outbox lag.
5. Check Sentry for new issues tagged with the release.

If any alarm fires during the rollout, follow [rollback.md](rollback.md).
