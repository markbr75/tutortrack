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
- [x] **E29-T05** DSAR workflow and export compiler.
- [x] **E29-T06** Erasure/anonymisation engine respecting financial retention and legal holds.
- [x] **E29-T07** Retention policies and purge job.
- [x] **E29-T08** Safeguarding concerns and DSL role.
- [x] **E29-T09** Messaging safeguards (detection, restrictions) and lone-working check-ins.
- [x] **E29-T10** COPPA/AADC age-aware defaults.
- [x] **E29-T11** Regional stacks and region-aware signup routing; DPA acceptance and sub-processor page.
- [x] **E29-T12** Compliance programme artefacts (policies, runbooks, security.txt).

## Temporal workflows (E32)

Implement these processes as Temporal workflows following the rules in [E32](E32-workflow-orchestration-temporal.md) (deterministic workflow code, side effects in tenant-scoped activities that call services, tenant-prefixed workflow IDs, signals for human decisions). Where the requirements above mention sweeper tasks, `next_*_at` / `resume_at` columns or retry schedules, the workflow replaces them.

- [x] **E29-TW1** Privacy workflows (requires E32).

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
| Scanning (T01) | CI `security` job: gitleaks (full history; `.gitleaks.toml` allows tests and the two public dev keys), Semgrep (`p/django`, `p/python`, `p/secrets`), pip-audit, `pnpm audit --prod`; Bandit rules already run via ruff `S`; Dependabot security updates only (repository setting: a PR only when a dependency has a known vulnerability; the weekly version-update config was removed on 2026-10-21 at the owner's request) | |
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

## Part 2 implementation notes (as built 2026-10-14)

Part 2 = T05–T12 and E29-TW1, all built. Design: ADR 0028. Everything lives in the `privacy`
app except the per-app providers (`<app>/privacy.py`), the comms pre-send hook seam
(`comms/hooks.py`) and region routing (`tenancy/regions.py`).

| Area | As built | Why / deviation |
|---|---|---|
| Provider registry (T05/T06/T07) | `privacy/registry.py`: each app registers a `Provider` (expand, export, files, erase, revoke) and `RetentionCategory`s in its own `privacy.py`, autodiscovered. Providers: people, crm, identity, comms, billing, payments, payroll, scheduling, delivery, learning, courses, leads, recruitment, growth, calendar_sync, migration, sites, developer, privacy | Apps only touch their own tables; new apps plug in without changing privacy |
| Data subjects | `privacy.subjects` now also registers `people.tutor`, `recruitment.application`, `growth.affiliate` and display labels. A person is resolved by repeated expansion (client → contacts/students → logins; login → its records); a student's household is *context* (its holds apply, it isn't erased) | |
| DSAR (T05) | `DataSubjectRequest` (`DSAR-00001`): staff intake (`/data-requests`) or portal (`/me/data-requests`, a parent may ask for their child); deadline `privacy.dsar_deadline_days` (30) with extension up to 60 more days; identity checklist (identity, matches records, authority when a parent/representative asks; a signed-in portal request counts as the identity check); reject/cancel with a reason told to the requester | "30 days" per the spec (UK GDPR says one month) |
| Export compiler (T05) | Every provider's sections → private JSON draft (S3) → staff review in `/export-preview` (a sensitive read) → redactions (a record, one field, or a file) → package zip: redacted `data.json`, `summary.pdf` (WeasyPrint) and `files/` → secure link `/api/v1/data-export/{token}` (hashed token, `privacy.dsar_link_days` = 7, redirect to a 5-minute presigned URL, every download audited) → on expiry the package and draft are deleted | Safeguarding cases are not exported (exemption; the DSL decides) |
| Erasure (T06) | `erasure.py`: plan (labels "Erased Student #n" from a per-org sequence, encrypted scrub terms) → legal-hold check → provider steps → delete files (object removed, `StoredFile` blanked, status `rejected`) → revoke logins → finish (audit summary, `data_subject.erased`). Names are replaced, DOB/notes/school/learning needs/custom fields/addresses cleared, records archived (out of search and lists); notes, documents, tasks, tags, learning records, references, preferences, in-app notifications and push devices deleted | A `StoredFile` "deleted" state would need a core migration; the blanked `rejected` row keeps foreign keys valid |
| Financial records (T06) | Never deleted, amounts never change: student/tutor names on invoice lines become the token and are scrubbed from descriptions (the AC); the bill payer's details on `billing_snapshot` stay for `privacy.financial_retention_years` (6) unless the invoice is already older; the `erased_financial` category anonymises them afterwards. Payments, statements and pay items keep amounts/references; notes and bank narratives are scrubbed; bank details removed | The only sanctioned edit of issued financial records (ADR 0028 §3) |
| Logins (T06) | Erasure removes the membership in this organisation (owners are skipped), revokes iCal feeds, API keys and app grants; the global `User` is kept | A login may belong to other organisations; account deletion is E30 |
| Legal holds (T06/T07) | `LegalHold` on any subject; blocks DSAR erasure approval (`legal_hold` 422), `ErasureWorkflow` (→ `blocked`) and every retention category | |
| Retention (T07) | `RetentionPolicy` per category (created on `organisation.created` and lazily): archived students/clients (6y, erased), rejected applications (183 days, erased), lesson report notes (6y), recordings (1y), message log (2y), unconverted form submissions (1y), erased people's financial details, audit log (7y minimum). `RetentionRun` keeps the dry-run report and what was done; admins are notified | |
| Audit retention (T07) | Deleted on the platform (BYPASSRLS) connection with `SET LOCAL tutortrack.audit_purge='on'`, filtered to the organisation; `privacy/retention.py` added to the platform-alias allowlist test | The app role has no DELETE on the append-only table |
| Safeguarding (T08) | `SafeguardingConcern` (`SG-00001`, encrypted description/outcome, immediate-risk flag, attachments), `SafeguardingAction` timeline (encrypted notes; a referral sets status *referred*; closing needs an outcome). Raise from the student page (admin) or the lesson page (tutor portal); raisers get the reference only (`/safeguarding/raised`). `safeguarding.dsl`: owner by default, others via a custom role; admins and branch managers are denied it. Every case opening is `audit.record_read`; `/history` shows the case's own trail; `core.audit.RESTRICTED_OBJECT_TYPES` hides it from the general audit search. DSL alerts (`safeguarding_alert`, immediate for urgent cases) carry the reference and category only | Spec's "DSL role" = a permission granted through custom roles (built-in role list unchanged) |
| Messaging safeguards (T09) | `comms/hooks.py` pre-send registry, called once in `comms.services._create` (blocked email/SMS → `suppressed` with the reason; in-app/push not created). `privacy.safeguards.check_outgoing`: marketing to under-18s blocked; for messages people write (`sender_user_id`): tutor → child direct blocked, parent required on child threads, contact details (phone ≥ 10 digits, email, social handles) block/flag per setting, keywords flag. `SafeguardingFlag` review queue (dismiss / escalate to a concern). Lesson report comments are screened from `lesson_report.commented` (flag only) | E13 has no tutor–family inbox yet (a parallel agent is adding it): it should call `comms.hooks.run_pre_send` with `sender_user_id` and `participants` |
| Lone working (T09) | `safeguarding.lone_working` (off / client homes / all in person); tutor "I've arrived"/"I've left" on the lesson page (`/lone-working/visits/check-in|check-out`); `LoneWorkingWorkflow` alerts monitors and the tutor `lone_working_grace_minutes` after the lesson, escalates to DSLs after `lone_working_escalate_minutes`, ends on check-out or "confirm safe" | Timers on Temporal (rule 4a); not listed in TW1's table |
| Children (T10) | COPPA (`privacy.coppa`: auto = US organisations): `invite_to_portal` needs a `parental-consent` record (new consent type + data migration) for under-13s; unknown DOB = child. AADC (`privacy.child_defaults`): no marketing consent for under-18 students, marketing messages to them blocked; student page shows the defaults (`/students/{id}/privacy`) | Verifiable consent method = a recorded signed form or a parent's portal consent; card/ID-based VPC not built |
| Regions (T11) | Settings `REGIONS` and `TT_REGION`; signup on the wrong stack → 409 `wrong-region` with the regional signup URL; `GET /signup/region?country=` and a notice + link on the signup page. Deployment per region documented in ADR 0028 | No infrastructure changes (as instructed) |
| DPA and sub-processors (T11) | Versioned in `privacy/compliance.py`; `DPAAcceptance` (owner-only `privacy.dpa.manage`, records signer, company, IP, browser); public `/api/v1/subprocessors` (`?region=`); change notices once per version per organisation (`manage.py notify_subprocessor_changes`, Celery fan-out) | |
| Compliance (T12) | `docs/compliance/`: index with SOC 2 and Cyber Essentials maps, information security, access control and reviews, change management, vendor management, sub-processors, DPA, retention, incident response, breach notification (72h clock, tenant notice template), vulnerability disclosure, penetration testing, business continuity. `/.well-known/security.txt` served by the backend (`SECURITY_CONTACT_EMAIL`, `SECURITY_POLICY_URL`) | Tenant notification tooling is the template + E30's platform notify tool |
| Workflows (TW1) | Queue `privacy`: `DataSubjectRequestWorkflow` (reminders by workflow clock, sent once; stale stages skipped), `ErasureWorkflow` (child of the DSAR workflow; one activity per provider), `RetentionPurgeWorkflow` (Schedule 02:00 org time while `privacy.retention_purge` ≠ off; manual runs from the UI), `LoneWorkingWorkflow`. Replay histories in `backend/tests/workflow_histories/` | |
| Frontend | Admin: Privacy centre `/privacy` (requests, erasures, legal holds, retention, agreement & sub-processors, settings) and request page; Safeguarding `/safeguarding` (cases, flagged messages, lone working, settings) and case page; student page privacy & "raise a concern" panel; signup region notice. Portal: "Your data" page; tutor lesson page check-in/out and "raise a concern". i18n namespaces `privacyCentre`, `safeguarding` | |

### Verified
- Backend: `tutortrack/privacy` 112 tests (103 new; erasure AC, DSAR export/redaction/delivery, retention, holds, safeguarding, messaging, lone working, COPPA/AADC, DPA, regions, workflows + replay) and the touched apps' suites (core, identity, tenancy, comms, people, crm, scheduling, delivery, growth, learning, billing, recruitment, leads) pass; ruff, mypy, `makemigrations --check`, `spectacular --fail-on-warn` clean.
- Frontend: admin (142) and portal (46) vitest, tsc and eslint pass.

### Carried forward
- **E13 inbox/broadcasts:** call `comms.hooks.run_pre_send` with `sender_user_id`/`participants`; use category `marketing` for broadcasts so the children's block applies.
- **E30:** platform "notify customers" tool for breaches; global account deletion; login history retention (the tables are global).
- **E27/E01:** retention for webhook delivery payloads and dispatched outbox events.
- **Infra:** regional Terraform workspaces and DNS per ADR 0028.


**Integration with E13 Phase 2 (merged in parallel, 2026-10-14).** The inbox and broadcasts were built at the same time, so they were wired to the pre-send hooks on merge:
- `comms.queue_message` (inbox replies by email/SMS/WhatsApp, broadcasts) runs `hooks.run_pre_send` with the message's `category`; broadcasts pass `marketing` or `service` from their purpose, so marketing broadcasts skip children (`skip_reason="safeguarding"`).
- Messages people write in the inbox (staff replies, portal chat from families, students and tutors) are screened with the sender and the thread's participants *before* they are stored, and a hard block is refused with a 422. The block rolls the message back but the safeguarding flag is recorded outside that rollback, so the DSL still sees it.
- With `safeguarding.require_parent_on_threads` on (the default), a student under 18 can only start a portal conversation when a parent is on it.

## Gap backlog (as built 2026-10-14)

Batch G6 of `docs/05-gap-backlog.md`; design in ADR 0034.


- **Consent capture (FR-29-3; E29:106):** `privacy.capture.record_ticked` writes E29 consent
  records for public enquiry/registration forms (each `consent` field names a `consent_key`,
  default `data-processing`; chosen in the form builder), class enrolment and waitlist
  (`accept_terms` → `terms`, plus `consents`), the review page (`review-publication`), the
  lesson-feedback page ("don't ask me again" withdraws `lesson-feedback`) and imports.
  `ConsentRecord.source` records where; types that apply to students are recorded for the
  children "on behalf of a child"; unknown keys and refused consents (AADC) never block a
  submission. Referral links land on the enquiry form, so referees' consent is captured there.
  New default types `review-publication` and `lesson-feedback` (created on first use).
- **Platform terms (FR-29-3; E29:108):** `TermsAcceptance` (global) with user, terms and
  privacy-notice versions (`compliance.TERMS_VERSION`), time, IP, browser and the
  organisation created; `/signup` requires `accept_terms`, `/signup/config` returns the
  versions and URLs, and the signup page has the checkbox.
- **Account deletion (FR-03-9, FR-29-4; E29:135):** `/api/v1/me/account-deletion` (preview,
  then delete with the password or the email typed). Last owners of open organisations and
  platform staff are refused with reasons. Per organisation the membership ends and the E29
  erasure runs (`privacy.account_deletion`: `erase` default, or `review` to log an erasure
  request; a legal hold always logs a request). The login is anonymised (sessions, MFA,
  passkeys, SSO links, sign-in links and login history deleted); `AccountDeletion` keeps an
  email hash; platform event `user.account_deleted`. Account page: "Delete your account".
- **Retention (FR-29-5; E29:155-156):** category `dispatched_events` (90 days, dispatched
  outbox rows of the organisation; pending and dead letters kept); platform task
  `purge_platform_records` (beat 04:40) for login history (`LOGIN_HISTORY_RETENTION_DAYS`
  400) and organisation-less events (`OUTBOX_RETENTION_DAYS` 90). Deviation: login history is
  one global table, so its period is a platform setting rather than a per-organisation one.
- **Notify customers (FR-29-9; E29:145):** platform console "Customer notices": breach (72-hour
  notice), security, service and legal templates, preview, a required reason and a once-only
  send to each organisation's owners and admins through comms (hidden transactional type
  `platform_customer_notice`), audited in each organisation's log.
- **Impossible travel (FR-29-2; E29:104):** the sign-in country comes from
  `GEOIP_COUNTRY_HEADER` (`CF-IPCountry`) or an optional `GEOIP_LOOKUP` class and is stored on
  `LoginEvent.country` (shown in login history). Another country within
  `IMPOSSIBLE_TRAVEL_HOURS` (2) emails the person and raises `security.alert`
  (`impossible_travel`) in each organisation where they are staff. Deviation: no GeoIP
  database ships; the rule is country-based, not distance-based.
- **Release test fix (2026-10-30, TP-E29-031).** New `jobs` privacy provider (`jobs/privacy.py`, order 29): erasure scrubs the person's name from job names, goals, notes and status reasons (jobs stay; they underpin lessons, charges and pay), so search no longer finds an erased student through their job; DSAR exports list the person's jobs.
