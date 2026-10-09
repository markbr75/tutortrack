# Infrastructure (Terraform)

Baseline AWS stack for one environment in one region (docs/02-architecture.md §11):
VPC (3 AZs) · RDS PostgreSQL 16 (encrypted, 35-day PITR) · ElastiCache Redis 7 (TLS) ·
S3 uploads bucket (KMS, versioned, private) · ECS Fargate services `web`, `worker`, `beat`
plus a one-off `migrate` task · ALB (TLS 1.3 policy) · CloudFront + private S3 for the SPAs
· Secrets Manager · ECR.

```bash
cd infra/terraform
terraform init -backend-config=env/staging.s3.tfbackend
terraform plan -var-file=env/staging.tfvars
```

Still to add (tracked in later epics): ClamAV sidecar/service (E29), WAF and rate limiting,
per-region stacks for data residency (E29), tenant custom domains (E24), alarms and
dashboards (E30), the OIDC deploy role used by `.github/workflows/deploy.yml`.

Notes:
- Database roles (FR-02-4): the RDS master user owns the tables and is only given to the
  `migrate` task (`DATABASE_OWNER_URL`), which runs `manage.py ensure_db_roles` before
  migrating. `web`, `worker` and `beat` connect as `tutortrack_app` (non-owner,
  `NOBYPASSRLS`, so row-level security applies); platform-admin code uses
  `tutortrack_platform` (`BYPASSRLS`). Not yet verified against RDS: creating a `BYPASSRLS`
  role needs a superuser-equivalent, so check on the first apply that the master user is
  allowed to; if not, create `tutortrack_platform` once by hand.
- Temporal (E32): Temporal Cloud is used in every hosted environment (one namespace per
  environment; set `temporal_address`/`temporal_namespace` and the `TEMPORAL_API_KEY` and
  `TEMPORAL_PAYLOAD_KEYS` secrets). The `temporal-worker` ECS service polls every task
  queue. Self-hosting Temporal (server on ECS with its own RDS) is possible but not built.
  Alarms on workflow task failures, retry storms and schedule backlog arrive with E30.
- Task definitions and services ignore image changes: CI registers new revisions on deploy.
