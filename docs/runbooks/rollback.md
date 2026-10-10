# Roll back a release

1. Find the previous task definition revision for each service (`aws ecs describe-services`).
2. `aws ecs update-service --service <name> --task-definition <family>:<previous>` for
   `web`, `worker`, `beat` and `temporal-worker`.
3. Do **not** roll back migrations: they are backward compatible by design. If a migration
   itself is the problem, write a forward fix.
4. Workflows: if a workflow change caused non-determinism errors, roll back the
   `temporal-worker` first; the replay tests (`tests/workflow_histories`) should have caught
   it, so add the missing history.
5. Confirm on the dashboard that errors are back to normal and note the incident.
