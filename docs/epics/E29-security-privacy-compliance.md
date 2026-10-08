# E29 — Security, Privacy, Safeguarding & Compliance

| | |
|---|---|
| **Phase** | MVP (part 1) → Scale (part 2) |
| **Depends on** | E01–E03; cross-cutting for all epics |
| **Parity** | TutorCruncher GDPR export/erasure, encryption, EU/UK data residency, 2FA; **beyond** with safeguarding tooling (critical when working with children) |

## 1. Summary
Platform-wide controls that make TutorTrack trustworthy for businesses handling children's data: security hardening, privacy and GDPR tooling (consent, DSARs, erasure, retention), safeguarding features, data residency and compliance readiness (SOC 2, Cyber Essentials, ISO 27001 path).

## 2. Functional requirements

### Part 1 (MVP)

#### FR-29-1 Security baseline
- OWASP ASVS L2 checklist tracked in `docs/security/asvs.md`; CSP (nonce-based), HSTS, X-Frame-Options (except widget endpoints), secure cookies; SSRF protections for outbound fetches (webhooks, URL imports); dependency scanning (pip-audit, npm audit, Dependabot); SAST (Bandit, Semgrep) in CI; secret scanning.
- Encryption: TLS everywhere; RDS/S3 encryption at rest; application-level encryption (`EncryptedField`, envelope encryption with AWS KMS data keys, key rotation support) for: OAuth tokens, bank details, tax IDs, safeguarding notes, SEN/medical notes, DBS numbers.
- Brute-force and abuse protection: rate limits, Turnstile on public forms, account lockout (E03).

#### FR-29-2 Audit and access transparency
- Global audit search (E01 audit log) for admins: by user, record, action, date; export.
- Sensitive-data access logging: viewing safeguarding notes, full bank details, DOB/medical fields, and exports are logged as `read` audit entries.
- Login history per user; admin alerts on suspicious activity (impossible travel, mass export).

#### FR-29-3 Consent management
- Consent types configurable per org (data processing, photo/video, marketing email/SMS, lesson recording, terms of service, privacy policy versions); captured on forms, portal and imports with timestamp, version, method, IP and who gave consent (guardian on behalf of a child).
- Consent withdrawal in the portal; downstream effects (marketing suppression, recording disabled).
- Cookie consent banner for public pages/widgets (necessary/analytics/marketing categories; decline as easy as accept).

### Part 2 (Phase 2–3)

#### FR-29-4 Data subject requests (DSAR)
- Request intake (portal or staff-logged), identity verification checklist, statutory deadline tracker (30 days), compile export of all personal data for a person (JSON + PDF summary + files), redaction step, delivery via secure link.
- **Erasure/anonymisation:** replace PII with tokens while preserving financial records required by law (invoices retained for 6 years UK / 7 years per setting with minimal identifying data), delete files, revoke logins; blocked if legal hold applies; full audit.
- **AC:** erasing a student removes name/DOB/notes/files, replaces with "Erased Student #1234", keeps invoice lines with anonymised description, and the student no longer appears in search or exports.

#### FR-29-5 Retention policies
- Per-org retention settings per data category (archived students after N years, lesson reports, messages, recordings, applications of rejected tutors (default 6 months), audit logs (7 years)); nightly purge/anonymise job with dry-run report and admin notification.
- Legal hold flag on records.

#### FR-29-6 Safeguarding
- Safeguarding concern logging (tutors/staff can raise concerns about a student from the lesson or student page): category, description, immediate risk flag, attachments; routed **only** to Designated Safeguarding Leads (DSL role permission) with urgent notifications; case record with actions/timeline; restricted, encrypted, separately audited; not visible on the general timeline.
- Communication safeguards: all tutor–student/parent messaging within the platform is logged (E13); settings to forbid tutor–student direct messaging for under-18s, require a parent on threads, block sharing of personal contact details (pattern detection) and flag keywords for DSL review.
- Online lesson safeguards: recording consent, session logs (E22).
- Lone working: optional check-in/out for in-person lessons at client homes (tutor taps "arrived"/"left"; alert if not checked out N minutes after end).
- Compliance gating of tutors (E18) is part of safeguarding.

#### FR-29-7 Children's privacy
- Age-aware settings: COPPA (US under 13) verifiable parental consent for student logins; UK Age Appropriate Design Code defaults (high privacy defaults for child accounts, no profiling, no marketing to children).

#### FR-29-8 Data residency and DPA
- Region per org (`uk`, `eu`, `us`, `au`): stacks deployed per region with separate DB/storage; org created in its region (signup routes by country). Cross-region data never replicated.
- Tenant-facing Data Processing Agreement (accept in-app, versioned), sub-processor list page with change notifications.

#### FR-29-9 Compliance programme
- SOC 2 Type II readiness (policies, access reviews, change management evidence from CI/CD, vendor management), Cyber Essentials Plus (UK), annual penetration test, vulnerability disclosure policy (`security.txt`), incident response runbook and breach notification workflow (72h ICO/regulator timelines; tenant notification tooling).

## 3. Data model
`ConsentType`, `ConsentRecord`, `DataSubjectRequest`, `RetentionPolicy`, `LegalHold`, `SafeguardingConcern`, `SafeguardingAction`, `CheckIn`, `SensitiveAccessLog` (or AuditEntry with action=read), `DPAAcceptance`.

## 4. Permissions
`privacy.dsar.manage`, `privacy.retention.manage`, `safeguarding.raise` (all staff/tutors), `safeguarding.dsl` (view/manage cases), `audit.view`, `security.settings.manage`.

## 5. Delivery plan
- [ ] **E29-T01** (MVP) Security headers/CSP, SAST/dependency scanning in CI, ASVS checklist doc.
- [ ] **E29-T02** (MVP) EncryptedField with KMS envelope encryption and rotation; apply to sensitive fields.
- [ ] **E29-T03** (MVP) Sensitive-read audit logging and global audit search UI.
- [ ] **E29-T04** (MVP) Consent types/records, capture in forms/portal, cookie banner.
- [ ] **E29-T05** DSAR workflow and export compiler.
- [ ] **E29-T06** Erasure/anonymisation engine respecting financial retention and legal holds.
- [ ] **E29-T07** Retention policies and purge job.
- [ ] **E29-T08** Safeguarding concerns and DSL role.
- [ ] **E29-T09** Messaging safeguards (detection, restrictions) and lone-working check-ins.
- [ ] **E29-T10** COPPA/AADC age-aware defaults.
- [ ] **E29-T11** Regional stacks and region-aware signup routing; DPA acceptance and sub-processor page.
- [ ] **E29-T12** Compliance programme artefacts (policies, runbooks, security.txt).
