# Compliance programme (E29-T12)

TutorTrack handles children's data for tutoring businesses, so we run a compliance programme
aimed at **SOC 2 Type II**, **Cyber Essentials Plus** (UK) and, later, **ISO 27001**. This
folder holds the policies and runbooks auditors ask for. Each document has an owner and a
review date; review each one at least once a year and after any major incident.

| Document | Covers | Owner | Next review |
|---|---|---|---|
| [Information security policy](information-security-policy.md) | Scope, principles, roles, the control set | CTO | 2027-10 |
| [Access control and access reviews](access-control.md) | Joiners/movers/leavers, least privilege, quarterly reviews | CTO | 2027-10 |
| [Change management](change-management.md) | How code reaches production; CI/CD evidence | Engineering lead | 2027-10 |
| [Vendor management](vendor-management.md) | Due diligence for sub-processors | CTO | 2027-10 |
| [Sub-processors](subprocessors.md) | The public list and change notices | DPO | On every change |
| [Data processing agreement](dpa.md) | What tenants accept in the app | DPO | 2027-10 |
| [Data retention policy](data-retention.md) | Retention periods, purge, legal holds, erasure | DPO | 2027-10 |
| [Incident response runbook](incident-response.md) | Detect, contain, eradicate, recover, learn | On-call lead | 2027-04 |
| [Personal data breach notification](breach-notification.md) | 72-hour regulator clock, tenant notices | DPO | 2027-04 |
| [Vulnerability disclosure policy](vulnerability-disclosure.md) | `security.txt`, safe harbour, response times | CTO | 2027-10 |
| [Penetration testing](penetration-testing.md) | Annual test scope and remediation SLAs | CTO | 2027-10 |
| [Business continuity](business-continuity.md) | Backups, restore drills, RTO/RPO | CTO | 2027-10 |

Related: the OWASP ASVS L2 checklist is [`docs/security/asvs.md`](../security/asvs.md);
operational runbooks are in [`docs/runbooks/`](../runbooks/README.md); the data residency
design is ADR 0028.

## SOC 2 control map (summary)

| Trust services criterion | Where the evidence comes from |
|---|---|
| CC1 Control environment | Information security policy; annual security training records |
| CC2 Communication | Privacy notices, the DPA, `security.txt`, sub-processor change notices |
| CC3 Risk assessment | Annual risk register review (information security policy §5) |
| CC5/CC8 Change management | GitHub pull requests with review, CI (`make check`, SAST, dependency audit), deploy logs |
| CC6 Logical access | SSO + MFA for staff, quarterly access reviews, audit log (FR-29-2) |
| CC7 System operations | Alerts (`docs/runbooks/alerts.md`), incident runbook, penetration test |
| CC9 Vendor risk | Vendor management, sub-processor list |
| A1 Availability | Backups (RDS PITR + logical dumps), quarterly restore drill |
| C1 Confidentiality | Encryption at rest (KMS) and in transit, field encryption (`EncryptedField`) |
| P (Privacy) | Consent records, DSAR workflow, erasure engine, retention policies |

## Cyber Essentials Plus

The five technical controls and where they live: boundary firewalls (AWS security groups,
Terraform), secure configuration (hardened container images, CIS benchmarks), user access
control (access-control.md), malware protection (ClamAV on uploads, managed laptops), and
patch management (Dependabot, monthly base image rebuilds, 14-day critical patch SLA).
