# Incident response runbook

**Owner:** On-call lead · **Review:** every 6 months, and after every SEV1/SEV2

## Severity
| Level | Examples | Response |
|---|---|---|
| SEV1 | Confirmed breach of customer data; cross-tenant data exposure; full outage | Page on-call, CTO and DPO now; war room |
| SEV2 | Suspected breach; partial outage; compromised staff account | Page on-call; CTO within 1 hour |
| SEV3 | Vulnerability report needing a fix; degraded feature | Ticket, next working day |

## Steps
1. **Detect and declare.** Anyone can declare an incident in `#incidents`. The on-call lead
   becomes incident commander (IC), opens the incident doc (timeline, decisions, owners) and
   sets the severity. Start the 72-hour clock if personal data may be involved: note the time
   we became aware (breach-notification.md).
2. **Contain.** Revoke credentials or sessions, disable the affected feature flag or
   integration, block IPs, pause affected organisations' schedules
   (`core.workflows.schedules`), snapshot evidence before changing it (logs, RDS snapshot,
   S3 object versions). Never delete evidence.
3. **Assess.** Which organisations, people (children?), data categories and time range. Use
   the audit log (`/api/v1/audit`, sensitive `read` entries), CloudTrail and access logs.
4. **Eradicate and recover.** Fix the cause, rotate keys (`manage.py rotate_encryption_keys`
   for field keys), restore from backup if needed (`docs/runbooks/database-restore.md`,
   `restore-one-organisation.md`), verify.
5. **Communicate.** Status page and customer messages: `docs/runbooks/incident-comms.md`.
   Personal data breaches follow breach-notification.md.
6. **Learn.** Blameless post-incident review within 5 working days: timeline, root cause,
   actions with owners and dates, tracked to completion. SEV1/2 reviews are shared with the
   leadership team and feed the risk register.
