# Information security policy

**Owner:** CTO · **Approved:** 2026-10-14 · **Review:** yearly

## 1. Purpose and scope
This policy protects the confidentiality, integrity and availability of the data our
customers (tutoring businesses) entrust to TutorTrack, much of it about children. It applies
to all staff, contractors and systems that build, run or support TutorTrack in every region.

## 2. Principles
1. **Least privilege.** People and services get only the access they need, for as long as
   they need it (access-control.md).
2. **Defence in depth.** Tenancy is enforced in the application and by PostgreSQL row-level
   security; secrets and sensitive fields are encrypted with KMS-managed keys.
3. **Privacy by design.** Data minimisation, retention limits, safeguarding restrictions and
   high-privacy defaults for children are product requirements, not options.
4. **Evidence.** Controls produce records (audit log, CI logs, review tickets) that an
   auditor can sample.

## 3. Roles
- **CTO**: owns this policy, the risk register and the security roadmap.
- **Data Protection Officer (DPO)**: privacy, DSARs on our own data, breach notification.
- **Engineering lead**: secure development and change management.
- **Everyone**: completes security and safeguarding awareness training at joining and yearly,
  reports incidents immediately (incident-response.md).

## 4. Controls
- Accounts: SSO with MFA for all staff tools; no shared accounts; production access through
  short-lived, audited roles.
- Endpoints: managed, encrypted laptops with automatic updates and screen lock.
- Development: code review on every change, CI security checks (Semgrep, Bandit rules,
  gitleaks, pip-audit, pnpm audit), dependency updates (Dependabot).
- Data: encryption at rest (RDS, S3, KMS) and in transit (TLS 1.2+); `EncryptedField` for
  tokens, bank details, tax ids, safeguarding notes and medical/SEN notes; regional stacks
  (no cross-region replication).
- Logging: tenant audit log (append-only), sensitive-read logging, platform logs without PII.
- Suppliers: vendor-management.md.
- Continuity: business-continuity.md.

## 5. Risk management
The CTO keeps a risk register (likelihood × impact, owner, treatment) and reviews it every
quarter with the DPO and after any significant incident or architecture change.

## 6. Exceptions
Exceptions need written CTO approval with an expiry date and are listed in the risk register.
