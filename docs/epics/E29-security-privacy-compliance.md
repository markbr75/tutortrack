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
- [x] **E29-T01** (MVP) Security headers/CSP, SAST/dependency scanning in CI, ASVS checklist doc.
- [x] **E29-T02** (MVP) EncryptedField with KMS envelope encryption and rotation; apply to sensitive fields.
- [x] **E29-T03** (MVP) Sensitive-read audit logging and global audit search UI.
- [x] **E29-T04** (MVP) Consent types/records, capture in forms/portal, cookie banner.
- [ ] **E29-T05** DSAR workflow and export compiler.
- [ ] **E29-T06** Erasure/anonymisation engine respecting financial retention and legal holds.
- [ ] **E29-T07** Retention policies and purge job.
- [ ] **E29-T08** Safeguarding concerns and DSL role.
- [ ] **E29-T09** Messaging safeguards (detection, restrictions) and lone-working check-ins.
- [ ] **E29-T10** COPPA/AADC age-aware defaults.
- [ ] **E29-T11** Regional stacks and region-aware signup routing; DPA acceptance and sub-processor page.
- [ ] **E29-T12** Compliance programme artefacts (policies, runbooks, security.txt).

## Temporal workflows (E32)

Implement these processes as Temporal workflows following the rules in [E32](E32-workflow-orchestration-temporal.md) (deterministic workflow code, side effects in tenant-scoped activities that call services, tenant-prefixed workflow IDs, signals for human decisions). Where the requirements above mention sweeper tasks, `next_*_at` / `resume_at` columns or retry schedules, the workflow replaces them.

- [ ] **E29-TW1** Privacy workflows (requires E32).

| Workflow | Started by | Steps, timers and signals | Replaces |
|---|---|---|---|
| `DataSubjectRequestWorkflow` `dsar:{org}:{id}` | DSAR logged | Statutory deadline timer (30 days) with escalating reminders → wait for `identity_verified` → compile export (activities) → wait for `redaction_approved` → deliver secure link → link expiry | Deadline tracker polling |
| `ErasureWorkflow` | Approved erasure request | Legal-hold check → anonymise records across apps (activities, idempotent) → delete files → revoke logins → audit summary | Ad hoc scripts |
| `RetentionPurgeWorkflow` (**Temporal Schedule** per organisation) | Nightly schedule | Dry-run report → purge/anonymise per policy in batches → notify admins | Nightly purge beat job |

## Implementation notes (Part 1, as built 2026-10-09)

Part 1 (MVP) = T01–T04, per the roadmap. T05–T12 and E29-TW1 remain for Part 2.

| Area | As built | Why |
|---|---|---|
| Headers (T01) | `core.security.SecurityHeadersMiddleware`: nonce CSP for Django HTML (`request.csp_nonce`), lock-down CSP for API responses, Permissions-Policy, COOP, nosniff; `X_FRAME_OPTIONS=DENY` except `FRAMEABLE_PATH_PREFIXES` (`/widgets/`, E24). SPA headers via a CloudFront response headers policy | SPAs are static files on CloudFront |
| SSRF (T01) | `core.net.safe_url` / `safe_urlopen`: https only, no credentials or non-standard ports, every resolved address must be public (private, loopback, link-local incl. metadata, CGNAT, multicast, reserved, IPv4-mapped IPv6), no auto-redirects, re-resolve check before connecting. **Every user-influenced outbound fetch must use it** (E22, E27, E28) | |
| Scanning (T01) | CI `security` job: gitleaks (full history; `.gitleaks.toml` allows tests and the two public dev keys), Semgrep (`p/django`, `p/python`, `p/secrets`), pip-audit, `pnpm audit --prod`; Bandit rules already run via ruff `S`; Dependabot (uv, npm, docker, actions) | |
| PEP 695 | `def f[T]()` generics are not used: Semgrep cannot parse them (ruff UP046/UP047 disabled) | Keep SAST coverage |
| Encryption (T02) | `EncryptedField` (Fernet) with **KMS envelope keys**: `FIELD_ENCRYPTION_KMS_KEY_ID` set → `FIELD_ENCRYPTION_KEYS` hold KMS-wrapped data keys (`manage.py generate_encryption_key`), unwrapped once per process; Temporal payload keys accept `id:kms:...`. `manage.py rotate_encryption_keys` re-encrypts every encrypted column on the platform connection. Empty strings are stored as empty. Terraform: KMS key (rotation on) + task-role permission | |
| Encrypted fields so far | MFA secrets (E03), `Organisation.tax_number` (data migration encrypted existing values). Bank details, DBS numbers, SEN/medical and safeguarding notes use it when their epics add them | Fields don't exist yet |
| Audit (T03) | Search by actor email, free text, action, object and dates; CSV export (`audit.export`, ≤ 50k rows, spreadsheet-formula safe) that is itself audited; ≥ 5 exports per person per hour → `security.alert` → owners emailed (once per window). Sensitive reads: organisation tax id (visible only with `org.settings.manage`) and member login history are logged as `read`. Login history: `/me/logins`, `/memberships/{id}/logins` | |
| Suspicious activity | Mass export and new-device alerts (E03). **Impossible travel not built** (needs GeoIP): E30 | |
| Consent (T04) | New `privacy` app: `ConsentType` (per org, versioned, `applies_to` subject types, required flag) and append-only `ConsentRecord` (method, version, IP, user agent, who, on behalf of a child); current state = latest record; new version → `needs_reconsent`. Defaults created on `organisation.created` and backfilled. Events `consent.granted` / `consent.withdrawn` (category in the payload) for E13/E22 to act on. Subjects are registered by apps (`privacy.subjects.register`); `identity.user` now, E05 adds people. API: `/consent-types` (+ `new-version`), `/consents` (+ `status`), `/me/consents` | Append-only is the evidence regulators ask for |
| Consent capture points | Staff recording (paper/phone) and self-service via the API now; portal (E15), public forms (E24) and imports (E28) call the same service | Those surfaces don't exist yet |
| Cookie banner (T04) | `ui` `CookieBanner` on the apps' public pages and `<tt-cookie-consent>` widget for tenant sites: necessary/analytics/marketing, reject as prominent as accept, `tt_consent` cookie (180 days), `tt-cookie-consent` window event | |
| Signup terms acceptance | Not recorded yet (platform ToS acceptance for new owners) | Needs the platform legal copy; tracked for E30 |

### Verified
- Backend: 436 tests (3 skipped); Semgrep, gitleaks, pip-audit and pnpm audit clean locally and in CI.
- Frontend: lint, typecheck, unit tests (admin 22, ui 6, widgets 2).
- e2e (Playwright on the production build) passing in CI.

### Carried forward
- **Part 2:** T05–T12, E29-TW1 (DSAR, erasure, retention workflows, safeguarding, COPPA/AADC, regional stacks, compliance artefacts).
- **E05:** register `people.client/contact/student` consent subjects; encrypt SEN/medical notes.
- **E13:** suppress marketing on `consent.withdrawn` (`marketing_email`/`marketing_sms`).
- **E30:** impossible-travel detection; platform ToS acceptance at signup.

