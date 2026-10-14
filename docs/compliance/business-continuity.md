# Business continuity and disaster recovery

**Owner:** CTO · **Review:** yearly

| Objective | Target |
|---|---|
| Availability | 99.9% monthly |
| Recovery point objective (RPO) | 5 minutes (RDS point-in-time recovery) |
| Recovery time objective (RTO) | 4 hours for a full regional restore |

- **Backups:** RDS PITR (35 days) and daily logical dumps to a separate AWS account in the
  same region (data never leaves its region); S3 versioning with lifecycle rules.
- **Drills:** a quarterly restore drill (`docs/runbooks/backup-drill.md`) and a yearly
  single-organisation restore (`restore-one-organisation.md`); results recorded.
- **Dependencies:** Temporal Cloud namespaces per region (workflow state is recoverable from
  the database: every process can be restarted from its record), provider outages
  (`docs/runbooks/provider-outage.md`).
- **People:** two people can deploy, restore and rotate keys; their contact details are in
  the on-call rota.
