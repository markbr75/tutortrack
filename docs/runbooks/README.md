# Runbooks

Operational procedures for TutorTrack (E30 FR-30-3/4). Each runbook says when to use it,
the steps, and how to confirm the fix. Keep them short and current: update a runbook in the
same pull request as the change that makes it wrong.

| Runbook | Use when |
|---|---|
| [deploy.md](deploy.md) | Releasing a new version |
| [rollback.md](rollback.md) | A release is misbehaving |
| [database-restore.md](database-restore.md) | Data loss or corruption across the database |
| [restore-one-organisation.md](restore-one-organisation.md) | One customer deleted data by mistake |
| [alerts.md](alerts.md) | An alarm fired (what each one means and first steps) |
| [provider-outage.md](provider-outage.md) | Stripe, Twilio, Postmark or Temporal Cloud is down |
| [incident-comms.md](incident-comms.md) | Telling customers about an incident |
| [backup-drill.md](backup-drill.md) | The quarterly restore drill |

Targets: RPO ≤ 5 minutes (RDS point-in-time recovery), RTO ≤ 4 hours.
