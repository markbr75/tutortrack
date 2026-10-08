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
- The database master user (`tutortrack_owner`) owns the tables. E02 creates a separate
  non-owner application role so Postgres row-level security applies to the app.
- Task definitions and services ignore image changes: CI registers new revisions on deploy.
