# E29 — Security, Privacy, Safeguarding & Compliance: manual tests

**Scope.** Feature-level security and privacy: security headers and SSRF guard (spot checks), encrypted fields and key rotation, audit search and sensitive-read logging, login history and alerts, consent types/records and the cookie banner (Part 1); data subject requests with the export compiler and redaction, erasure/anonymisation, legal holds, retention policies and purges, safeguarding concerns for Designated Safeguarding Leads (DSLs), messaging safeguards and flags, lone-working check-ins, COPPA/AADC children's defaults, regions, the DPA and sub-processor list, and `security.txt` (Part 2). Workflows: `DataSubjectRequestWorkflow`, `ErasureWorkflow`, `RetentionPurgeWorkflow` (Schedule), `LoneWorkingWorkflow` on the `privacy` queue. Spec: [E29](../epics/E29-security-privacy-compliance.md). Generic non-functional security checks (rate limits, uploads, auth hardening) are in [non-functional.md](non-functional.md); MFA, passkeys and sessions are covered in the E03 file.

**Built differently from the spec (Implementation notes win):**
- "DSL role" is the permission `safeguarding.dsl`: the owner has it by default; anyone else needs a custom role that grants it. Admins and branch managers are denied it.
- Erasure keeps the global login (`User`) and removes the membership in this organisation; owners are skipped.
- Financial records are never deleted: names on invoice lines become the "Erased Student #n" token; bill-payer details stay for `privacy.financial_retention_years` (6).
- Safeguarding cases are not included in DSAR exports (exemption; the DSL decides).
- Impossible-travel detection (G6) is country-based from the CDN header; no GeoIP database ships. COPPA verifiable consent is a recorded signed form or a parent's portal consent.
- Consent types and records have no admin screen: use the API (`/api/v1/consent-types`, `/api/v1/consents`, `/api/v1/me/consents`; the browsable API works in dev while signed in).
- Regions: one local stack serves every region; region routing is configured by `REGIONS`/`TT_REGION`.

**Common preconditions.**
- `make seed`: retention policies exist; one open DSAR (access request from Priya Patel by email, status "Awaiting identity check"). No safeguarding cases are seeded.
- Admin screens: **Privacy centre** `/privacy` (tabs Data requests, Erasures, Legal holds, Retention, Agreement & sub-processors, Settings), request page `/privacy/requests/<id>`; **Safeguarding** `/safeguarding` (Concerns, Flagged messages, Lone working, Settings), case page `/safeguarding/<id>`; student page panel "Privacy and safeguarding"; Audit log `/audit`; Account `/account` (sessions, logins).
- Portal: **Your data** `/portal/privacy`; tutor lesson page `/portal/tutor/lessons/<id>` (check-in/out, raise a concern).
- Temporal worker running (queue `privacy`); Mailpit http://localhost:8025.

## Security baseline and encryption (T01, T02) — spot checks

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E29-001 | Security headers on API and Django pages | Anyone | — | 1. `curl -I http://brightminds.localhost:8010/api/v1/status` and `/django-admin/login/`. | CSP (lock-down on API, nonce-based on HTML), `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, Permissions-Policy, COOP. | P1 | backend: `tutortrack/core/tests/test_security.py` | |
| TP-E29-002 | Widgets can be framed | Anyone | — | 1. `curl -I` a `/widgets/...` path. | No `X-Frame-Options: DENY` on widget paths. | P2 | backend: `tutortrack/core/tests/test_security.py` | |
| TP-E29-003 | SSRF guard on user URLs | Owner | — | 1. Use any URL field that fetches (webhook endpoint, calendar/CalDAV URL) with `https://127.0.0.1`, `https://169.254.169.254`, `http://example.com`. | All refused (https and public addresses only). | P1 | backend: `tutortrack/developer/tests/test_webhooks.py::test_ssrf_guard_refuses_unsafe_urls` | |
| TP-E29-004 | Encrypted fields at rest | Developer | DB access as owner role | 1. Save an organisation tax number and an affiliate's bank details.<br>2. `SELECT` the columns in psql. | Ciphertext (Fernet token), not plain text. | P1 | backend: `tutortrack/core/tests/test_crypto.py` | |
| TP-E29-005 | Key rotation | Developer | Two keys in `FIELD_ENCRYPTION_KEYS` | 1. Add a new key first; run `manage.py rotate_encryption_keys`.<br>2. Remove the old key; reload data in the app. | Every encrypted column re-encrypted; values still readable. | P2 | backend: `tutortrack/core/tests/test_crypto.py` | |
| TP-E29-006 | security.txt | Anyone | — | 1. Open http://localhost:8010/.well-known/security.txt. | Contact (`SECURITY_CONTACT_EMAIL`), policy URL and expiry. | P2 | backend: `tutortrack/privacy/tests/test_compliance.py::test_security_txt_is_served` | |

## Audit and access transparency (T03)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E29-007 | Audit search | Owner | Some edits done | 1. Audit log → filter by actor office@, action update, object client, date range; free text "Patel". | Matching entries only, newest first. | P1 | backend: `tutortrack/core/tests/test_audit_search.py` | |
| TP-E29-008 | Audit CSV export is itself audited | Owner | — | 1. Export the audit log. | CSV downloads (formula-safe); a new `export` entry appears. | P1 | backend: same | |
| TP-E29-009 | Mass-export alert | Owner | — | 1. Export 5 times within an hour. | Owners get one `security.alert` email for the window. | P2 | backend: same | |
| TP-E29-010 | Sensitive read logged | Owner | Org tax id set | 1. Open Settings and reveal the tax id.<br>2. Open a member's login history.<br>3. Check the audit log. | `read` entries for both. | P1 | backend: same | |
| TP-E29-011 | Login history | Owner; any staff | — | 1. Sign in with a wrong password once, then correctly.<br>2. Account → logins; Team → member → logins. | Failed and successful logins with time, IP and device. | P2 | No | |
| TP-E29-012 | New-device alert | Owner | — | 1. Sign in from a new browser. | New-device email (E03). | P3 | No | |

## Consent (T04)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E29-013 | Default consent types exist | Owner | Seed | 1. `GET /api/v1/consent-types`. | Data processing, photo/video, marketing email, marketing SMS, lesson recording, terms, privacy policy, parental consent. | P1 | backend: `tutortrack/privacy/tests/test_consent.py::test_new_organisations_get_default_consent_types` | |
| TP-E29-014 | Staff record consent on behalf of a child | Coordinator | Arjun Patel | 1. `POST /api/v1/consents` for Arjun, photo/video, method "paper form", given by Priya (guardian). | Record stored with version, method, IP, user agent, staff member and "on behalf of". | P1 | backend: `tutortrack/privacy/tests/test_consent.py::test_staff_record_consent_on_behalf_with_evidence` | |
| TP-E29-015 | Self-service consent and withdrawal | Parent | Portal sign-in | 1. `GET/POST /api/v1/me/consents`: give then withdraw marketing email. | Append-only history: current state is the latest record; `consent.withdrawn` published; marketing to Priya suppressed. | P1 | backend: `tutortrack/privacy/tests/test_consent.py::test_people_give_and_withdraw_their_own_consent` | |
| TP-E29-016 | New version needs re-consent | Owner | — | 1. `POST /api/v1/consent-types/<id>/new-version` for the privacy policy. | People who agreed to the old version show `needs_reconsent`. | P2 | backend: `tutortrack/privacy/tests/test_consent.py::test_new_versions_require_reconsent` | |
| TP-E29-017 | Cookie banner on public pages | Anonymous | Website http://brightminds.site.localhost:8010/ and admin `/signup` | 1. Open in a fresh private window.<br>2. Check "Reject non-essential" is as prominent as "Accept all".<br>3. Customise → Analytics on, Marketing off → Save choices. | Banner shows; `tt_consent` cookie (180 days) stores the choice; banner doesn't return. | P1 | e2e: `e2e/leads.spec.ts` | |

## Data subject requests (T05)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E29-018 | Seeded request is visible with its deadline | Owner | Seed | 1. Privacy centre → Data requests. | `DSAR-00001`, Access, Priya Patel, Received by Email, "Awaiting identity check", "due in 30 days". | P1 | backend: `tutortrack/privacy/tests/test_dsar.py::test_staff_log_a_request_and_the_deadline_starts` | |
| TP-E29-019 | Log a request | Admin | — | 1. Log a request → Find the person "Tom Okafor" → Access → Phone → requester name/email.<br>2. Log request and start the deadline. | New `DSAR-00002`; deadline 30 days; Temporal `dsar:<org>:<id>` running. | P1 | backend: same; `tutortrack/privacy/tests/test_workflows.py::test_an_access_request_is_compiled_reviewed_delivered_and_expires` | |
| TP-E29-020 | Unknown person refused | Admin | — | 1. Try to log a request without choosing a person. | Field error. | P3 | backend: `tutortrack/privacy/tests/test_dsar.py::test_unknown_people_are_refused` | |
| TP-E29-021 | Identity verification checklist | Admin | TP-E29-018 | 1. Tick only "identity"; try to continue.<br>2. Tick all required checks. | Incomplete checklist refused; then "Verified on <date>" and compile starts. | P1 | backend: `tutortrack/privacy/tests/test_dsar.py::test_verification_needs_every_required_check` | |
| TP-E29-022 | Review the export and redact | Admin | Verified request | 1. Review the export: sections from every app (people, billing, scheduling, comms, learning…).<br>2. Leave one record out and one document out.<br>3. Approve and send. | "Approve and send (2 items left out)". Opening the preview is logged as a sensitive read. | P1 | backend: `tutortrack/privacy/tests/test_dsar.py::test_the_export_covers_every_app_and_is_reviewed_before_delivery`; `test_documents_are_included_unless_redacted` | |
| TP-E29-023 | Secure link delivery | Requester | TP-E29-022 | 1. Open the email in Mailpit; follow the link `/api/v1/data-export/<token>`. | ZIP with `data.json` (without the redacted items), `summary.pdf` and `files/`; each download audited. Link expires after 7 days. | P1 | backend: `tutortrack/privacy/tests/test_dsar.py::test_delivery_sends_an_expiring_link_and_downloads_are_audited` | |
| TP-E29-024 | Expiry deletes the package | Admin | `privacy.dsar_link_days` = 1 | 1. Wait past expiry. | Link stops working; request Completed; package and draft deleted. | P2 | backend: `tutortrack/privacy/tests/test_dsar.py::test_expiry_deletes_the_package_and_completes_the_request` | |
| TP-E29-025 | Extend the deadline | Admin | Open request | 1. Extend or reject → Extra days 60 with a reason.<br>2. Try 61. | 60 accepted (max 60 more); 61 refused. | P2 | backend: `tutortrack/privacy/tests/test_dsar.py::test_the_deadline_can_be_extended_by_two_months_at_most` | |
| TP-E29-026 | Reject a request | Admin | Open request | 1. Reject the request with a reason. | Status Rejected; the requester is emailed the reason. | P2 | backend: `tutortrack/privacy/tests/test_dsar.py::test_reject_tells_the_requester` | |
| TP-E29-027 | Reminders before the deadline | Admin | Unverified request | 1. Check the Temporal workflow timers. | Escalating reminder timers before the deadline; each reminder sent once. | P2 | backend: `tutortrack/privacy/tests/test_workflows.py::test_unverified_requests_get_escalating_reminders_until_closed` | |
| TP-E29-028 | Parent asks in the portal for self or child | Parent | Portal | 1. Your data → Make a request → A copy of my data → About = Arjun.<br>2. Try a student not in the household (API). | Request logged with channel Portal and identity treated as checked; another family's child refused. | P1 | backend: `tutortrack/privacy/tests/test_dsar.py::test_the_portal_asks_for_their_own_or_their_childs_data`; `test_parents_cannot_ask_for_other_childrens_data` | |
| TP-E29-029 | Safeguarding cases are not exported | Admin | A concern about Arjun exists | 1. Compile Arjun's access export. | No safeguarding section. | P1 | No | |

## Erasure and legal holds (T06)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E29-030 | Erasure request preview and approval | Owner | Create a test family "Erin Test" with student "Eddie Test", a lesson, an invoice, a note and an uploaded file | 1. Log an Erasure request for Eddie Test; verify identity.<br>2. Review "Erasing covers: …".<br>3. Approve the erasure. | Status Erasing → Completed; erasure report lists areas anonymised, deleted and kept. | P1 | backend: `tutortrack/privacy/tests/test_dsar.py::test_erasure_requests_are_previewed_and_need_approval`; `test_erasure_runs_across_the_apps` | |
| TP-E29-031 | AC: erased student | Owner | TP-E29-030 | 1. Search for "Eddie".<br>2. Open the invoice.<br>3. Export students (grid CSV). | No search result; invoice line reads "Erased Student #1" with the same amount; not in exports; DOB, notes, files gone. | P1 | backend: `tutortrack/privacy/tests/test_erasure.py::test_erasing_a_student_meets_the_acceptance_criteria` | |
| TP-E29-032 | Erasing a client keeps recent invoice details | Owner | Family with a recent invoice | 1. Erase the client. | Bill-payer details on recent invoices kept until the financial retention period; amounts unchanged. | P1 | backend: `tutortrack/privacy/tests/test_erasure.py::test_erasing_a_client_keeps_recent_invoice_details_until_the_retention_period` | |
| TP-E29-033 | Erasure ends the portal login here | Owner | Family with a portal login | 1. Erase the contact. | Membership removed; iCal feeds, API keys and app grants revoked; the global user remains. | P1 | backend: `tutortrack/privacy/tests/test_erasure.py::test_erasure_ends_the_portal_login_here` | |
| TP-E29-034 | Place a legal hold | Owner | A client | 1. Legal holds → Place a legal hold on the client with a reason.<br>2. Try to approve an erasure for them. | Approval refused (`legal_hold`); request "Blocked by a legal hold". | P1 | backend: `tutortrack/privacy/tests/test_erasure.py::test_a_legal_hold_blocks_erasure`; `tutortrack/privacy/tests/test_workflows.py::test_a_legal_hold_blocks_the_erasure_workflow` | |
| TP-E29-035 | Release a hold | Owner | TP-E29-034 | 1. Release with a reason; approve the erasure again. | Erasure proceeds. | P2 | backend: `tutortrack/privacy/tests/test_erasure.py::test_released_holds_no_longer_block` | |
| TP-E29-036 | Erasure numbering per organisation | Owner | Two erasures | 1. Erase two students. | "Erased Student #1" and "#2" in this org; Northside starts from #1. | P3 | backend: `tutortrack/privacy/tests/test_erasure.py::test_the_erasure_number_is_a_per_organisation_sequence` | |
| TP-E29-037 | AI proposals scrubbed | Owner | An AI proposal naming the student | 1. Erase the student. | Their name no longer appears in AI proposals. | P3 | backend: `tutortrack/privacy/tests/test_erasure.py::test_erasure_scrubs_the_person_from_ai_proposals` | |

## Retention (T07)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E29-038 | Retention policies listed with defaults | Owner | Seed | 1. Privacy centre → Retention. | Categories with defaults: archived students/clients 6 years, rejected applications 183 days, lesson report notes 6 years, recordings 1 year, message log 2 years, form submissions 1 year, audit 7 years, product usage 395 days. | P1 | backend: `tutortrack/privacy/tests/test_retention.py::test_every_category_gets_a_policy_with_its_default` | |
| TP-E29-039 | Change periods but not below the minimum | Owner | — | 1. Set audit log to 1 year. | Refused (7-year minimum). Other categories can be changed. | P2 | backend: `tutortrack/privacy/tests/test_retention.py::test_staff_change_periods_but_not_below_the_minimum` | |
| TP-E29-040 | Dry run then purge | Owner | An archived student older than the period (set **Archived students** to the 30-day minimum and archive a test student; backdate `archived_at` in the database, or wait) | 1. Report what's due (dry run).<br>2. Purge now. | Dry-run run lists the student; purge run erases them; admins notified. | P1 | backend: `tutortrack/privacy/tests/test_retention.py::test_dry_run_reports_and_the_purge_erases_old_archived_students`; `tutortrack/privacy/tests/test_workflows.py::test_the_retention_purge_reports_then_purges` | |
| TP-E29-041 | Legal holds and disabled policies are skipped | Owner | Held record; a disabled category | 1. Purge now. | Held record and disabled category untouched. | P1 | backend: `tutortrack/privacy/tests/test_retention.py::test_legal_holds_are_skipped_by_the_purge`; `test_disabled_policies_are_not_purged` | |
| TP-E29-042 | Nightly schedule follows the setting | Owner | Settings: retention purge on/off | 1. Turn on; check Temporal UI Schedules (02:00 org time).<br>2. Turn off. | Schedule created; when off, scheduled runs do nothing. | P2 | backend: `tutortrack/privacy/tests/test_workflows.py::test_the_scheduled_purge_does_nothing_while_switched_off` | |

## Safeguarding (T08, T09)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E29-043 | Staff raise a concern from the student page | Coordinator | Arjun Patel | 1. Students → Arjun → Privacy and safeguarding → Raise a safeguarding concern.<br>2. Category Bullying, What happened, not immediate risk.<br>3. Send to the safeguarding lead. | Coordinator sees only the reference (e.g. `SG-00001`), not the case. The DSL (owner admin@) gets a `safeguarding_alert` email with reference and category only (no names). | P1 | backend: `tutortrack/privacy/tests/test_safeguarding.py::test_staff_raise_a_concern_and_get_only_the_reference`; `test_dsls_are_alerted_without_personal_details` | |
| TP-E29-044 | Tutor raises a concern from the lesson page | Tutor | Nia's lesson with Arjun | 1. Portal → lesson → Raise a safeguarding concern, immediate risk ticked. | Reference shown; DSL alerted immediately; tutor can't raise about students they don't teach. | P1 | backend: `tutortrack/privacy/tests/test_safeguarding.py::test_tutors_raise_concerns_only_about_their_own_students` | |
| TP-E29-045 | Only DSLs see cases | Admin; Branch Manager; Owner | TP-E29-043 | 1. As office@ and manager@ open `/safeguarding/<id>`.<br>2. As admin@ (owner) open it. | Admin and branch manager: no access. Owner: full case. | P1 | backend: `tutortrack/privacy/tests/test_safeguarding.py::test_cases_are_restricted_to_safeguarding_leads`; e2e: `e2e/roles.spec.ts` | |
| TP-E29-046 | Custom role makes someone a DSL | Owner | Team → Roles | 1. Clone Coordinator as "Coordinator + DSL", grant `safeguarding.dsl`; assign to coordinator@. | coordinator@ now sees cases. | P1 | backend: `tutortrack/privacy/tests/test_safeguarding.py::test_a_custom_role_makes_someone_a_dsl` | |
| TP-E29-047 | Case management | Owner (DSL) | TP-E29-043 | 1. Record an action "Contacted the family" with a note.<br>2. Mark referred ("Referred to children's social care").<br>3. Close the case without an outcome; then with an outcome. | Timeline grows; status Referred externally; closing needs an outcome. | P1 | backend: `tutortrack/privacy/tests/test_safeguarding.py::test_case_management` | |
| TP-E29-048 | Case access is audited and hidden from the general audit | Owner (DSL) | TP-E29-047 | 1. Open "Who has opened or changed this case".<br>2. Search the general Audit log for the case. | Case history lists each opening (read) and change; the general audit log doesn't show the case. | P1 | backend: `tutortrack/privacy/tests/test_safeguarding.py::test_opening_a_case_is_audited_and_hidden_from_the_general_audit_log` | |
| TP-E29-049 | Case description encrypted | Developer | TP-E29-043 | 1. `SELECT` description in psql. | Ciphertext. | P2 | No | |
| TP-E29-050 | Contact details blocked and flagged | Tutor | Inbox thread with Priya | 1. Tutor writes "Call me on 07700 900123" in portal messages. | Message refused (422) with a clear reason; a flag appears in Safeguarding → Flagged messages ("Personal contact details", blocked). | P1 | backend: `tutortrack/privacy/tests/test_comms_safeguards.py::test_a_tutor_portal_message_with_contact_details_is_blocked` | |
| TP-E29-051 | Staff inbox reply with contact details | Coordinator | Inbox conversation "Thursday's lesson" | 1. Reply including an email address. | Blocked or flagged per setting; flag recorded even though the message rolled back. | P1 | backend: `tutortrack/privacy/tests/test_comms_safeguards.py::test_a_staff_inbox_reply_with_contact_details_is_blocked_and_flagged` | |
| TP-E29-052 | Tutor → child direct messages blocked | Tutor | Arjun (under 18) | 1. Tutor tries to message Arjun without a parent on the thread. | Refused (parent required). Adult learner Grace Hughes can be messaged directly. | P1 | backend: `tutortrack/privacy/tests/test_safeguarding.py::test_tutors_cannot_message_children_directly`; `test_adult_learners_can_be_messaged_directly` | |
| TP-E29-053 | Flag keywords | Owner | Settings: flagged words include "secret" | 1. A message containing "secret" is sent. | Delivered but flagged ("Flagged words"). | P2 | backend: `tutortrack/privacy/tests/test_safeguarding.py::test_screening_finds_contact_details_and_flagged_words` | |
| TP-E29-054 | Review flags | Owner (DSL) | Flags exist | 1. Dismiss one; Raise a concern from another. | Dismissed disappears; escalation creates a new case linked to the message. | P1 | backend: `tutortrack/privacy/tests/test_safeguarding.py::test_dsls_review_flags` | |
| TP-E29-055 | Lesson report comments are screened | Tutor | — | 1. Submit a report comment with a phone number. | Flag only (never blocked). | P3 | backend: `tutortrack/privacy/tests/test_safeguarding.py::test_shared_text_is_flagged_but_never_blocked` | |
| TP-E29-056 | Lone working off by default | Tutor | Seed | 1. Open an in-person lesson in the portal. | No check-in buttons. | P2 | backend: `tutortrack/privacy/tests/test_lone_working_children.py::test_check_in_is_off_by_default` | |
| TP-E29-057 | Check in and out | Tutor | Settings: lone working = client homes; a lesson at the family's home today | 1. Select I've arrived; later I've left. | "Checked in at …", "Checked out at …"; visit status On site → Left in Safeguarding → Lone working. Online lessons need no check-in. | P1 | backend: `tutortrack/privacy/tests/test_lone_working_children.py::test_tutors_check_in_and_out_of_home_visits`; `test_online_lessons_need_no_check_in` | |
| TP-E29-058 | Missed check-out alerts then escalates | Owner | Grace minutes 1, escalate minutes 2; lesson ending now | 1. Check in and don't check out. | After grace: monitors and tutor alerted, visit "Overdue". After escalation: DSLs alerted. "Confirm safe" with a note ends it. | P1 | backend: `tutortrack/privacy/tests/test_workflows.py::test_a_missed_check_out_alerts_then_escalates_until_resolved`; `tutortrack/privacy/tests/test_lone_working_children.py::test_monitors_resolve_overdue_visits` | |

## Children's privacy (T10)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E29-059 | COPPA: under-13 login needs parental consent | Owner | Setting `privacy.coppa` = on (auto is US only); Maya Patel with DOB making her 11 | 1. Invite Maya to the portal.<br>2. Record a `parental-consent` consent for Maya (API).<br>3. Invite again. | First invite refused with a message; after consent it succeeds. | P1 | backend: `tutortrack/privacy/tests/test_lone_working_children.py::test_coppa_needs_parental_consent_before_an_under_13_gets_a_login` | |
| TP-E29-060 | COPPA off outside the US by default | Owner | GB org, auto | 1. Invite an under-13 student. | Allowed (COPPA doesn't apply). | P2 | backend: `tutortrack/privacy/tests/test_lone_working_children.py::test_coppa_does_not_apply_outside_the_us_by_default` | |
| TP-E29-061 | Unknown DOB gets the safe default | Owner | Student without DOB | 1. Open the student's privacy panel. | Treated as a child. | P2 | backend: `tutortrack/privacy/tests/test_lone_working_children.py::test_unknown_dates_of_birth_get_the_safe_default` | |
| TP-E29-062 | No marketing to children | Owner | Arjun (15) | 1. Try to record marketing consent for Arjun.<br>2. Send a marketing broadcast to a segment containing students. | Consent refused; Arjun skipped (`skip_reason` safeguarding). | P1 | backend: `tutortrack/privacy/tests/test_lone_working_children.py::test_marketing_consent_cannot_be_recorded_for_children`; `tutortrack/privacy/tests/test_comms_safeguards.py::test_marketing_queued_to_a_child_is_suppressed` | |
| TP-E29-063 | Student privacy panel | Coordinator | Arjun | 1. Open Arjun → Privacy and safeguarding. | Shows child defaults (no marketing, no profiling) and the raise-a-concern button. | P2 | backend: `tutortrack/privacy/tests/test_lone_working_children.py::test_the_student_privacy_panel` | |

## Regions, DPA and sub-processors (T11, T12)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E29-064 | Owner accepts the DPA | Owner | — | 1. Agreement & sub-processors → Read the agreement → Accept (name, role, legal name) → I accept on behalf of the organisation. | Acceptance recorded with signer, company, IP and browser; version shown. | P1 | backend: `tutortrack/privacy/tests/test_compliance.py::test_owners_accept_the_current_dpa` | |
| TP-E29-065 | Admins can't sign the DPA | Admin | — | 1. As office@ open the tab. | Accept is not available (owner-only). | P2 | backend: `tutortrack/privacy/tests/test_compliance.py::test_admins_cannot_sign_the_dpa` | |
| TP-E29-066 | Public sub-processor list | Anonymous | — | 1. `GET /api/v1/subprocessors` and `?region=us`. | List with purpose, data and location; Anthropic marked optional (only if AI is on). | P2 | backend: `tutortrack/privacy/tests/test_compliance.py::test_the_subprocessor_list_is_public_and_filterable_by_region` | |
| TP-E29-067 | Sub-processor change notices | Owner | — | 1. Run `manage.py notify_subprocessor_changes` twice. | One notice per organisation per version. | P3 | backend: `tutortrack/privacy/tests/test_compliance.py::test_subprocessor_changes_are_announced_once` | |
| TP-E29-068 | Signup on the wrong regional stack | Anonymous | Set `TT_REGION=uk` and `REGIONS` with a US URL | 1. On `/signup` choose country United States. | Notice "Continue to sign up in the US region" with the regional link; API returns 409 `wrong-region`. | P3 | backend: `tutortrack/privacy/tests/test_compliance.py::test_signup_on_the_wrong_stack_is_refused_with_the_right_address` | |
| TP-E29-069 | Compliance artefacts present | Reviewer | — | 1. Open `docs/compliance/`. | Index with SOC 2 and Cyber Essentials maps, policies, incident response and breach notification (72 h), vulnerability disclosure, pen-testing, business continuity. | P3 | No | |

## Permissions

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E29-070 | Privacy centre access | Coordinator; Finance; Branch Manager; Tutor | — | 1. Open `/privacy` as each. | Coordinator: consent view/record only, no DSAR management. Branch manager: no DSAR, retention or legal holds. Tutor/Finance: "You don't have access to the privacy centre." | P1 | backend: `tutortrack/privacy/tests/test_dsar.py::test_only_privacy_staff_handle_requests`; `tutortrack/privacy/tests/test_retention.py::test_only_privacy_admins_manage_retention`; e2e: `e2e/roles.spec.ts` | |
| TP-E29-071 | Everyone can raise; only DSLs read | All staff | — | 1. Check "Raise a safeguarding concern" for coordinator, tutor, finance. | Coordinator and tutor can raise; nobody but DSLs opens cases. | P1 | backend: `tutortrack/privacy/tests/test_safeguarding.py::test_cases_are_restricted_to_safeguarding_leads` | |

## Tenant isolation

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E29-072 | DSARs, holds, cases are per organisation | Owner (Northside) | Bright Minds data exists | 1. Open `/privacy` and `/safeguarding` on northside.localhost.<br>2. Request a Bright Minds DSAR/case id via API. | Lists contain only Northside records; ids give 404. | P1 | backend: `tutortrack/privacy/tests/test_consent.py::test_detail_of_other_organisation_is_404` and isolation classes in `test_dsar.py`, `test_retention.py`, `test_safeguarding.py` | |
| TP-E29-073 | Export link from another organisation | Requester | Bright Minds DSAR link | 1. Open it on northside.localhost. | Not found. | P2 | No | |

## Errors and edge cases

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E29-074 | Overdue request shows clearly | Admin | Request past deadline (set deadline days small) | 1. Open Data requests. | "overdue by n days" in red text with an accessible label. | P2 | No | |
| TP-E29-075 | Worker restart during erasure | Owner | Large erasure | 1. Stop the worker mid-erasure; restart. | Erasure completes; steps are idempotent (no double processing). | P2 | backend: `tutortrack/privacy/tests/test_erasure.py::test_steps_are_idempotent` | |

## Gap batch G6 (as built 2026-10-14)

Built by gap batch G6 ([ADR 0034](../adr/0034-gap-batch-g6-consent-capture-account-deletion-and-platform-tools.md)); see the epic's *Gap backlog* notes. Signup now requires `accept_terms: true` (the terms checkbox).

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E29-076 | Ticked consent on a public form is recorded | Anonymous | Enquiry form with a consent field (key `marketing-email`) | 1. Submit the form with the box ticked. | A consent record for the new contact (source `form:<slug>`); photo consent is recorded for the children. | P1 | backend: `test_ticked_consent_fields_are_recorded_as_consent_records`, `test_photo_consent_on_a_form_is_recorded_for_the_children` | |
| TP-E29-077 | Enrolment, review and feedback consents | Family | — | 1. Enrol online accepting terms.<br>2. Leave a review agreeing to publication.<br>3. On a feedback survey tick "don't ask me again". | Records for `terms`, `review-publication`, and a withdrawal of `lesson-feedback`. | P2 | backend: `test_online_enrolment_records_terms_and_ticked_consents`, `test_review_publication_consent_is_recorded`, `test_dont_ask_again_withdraws_the_feedback_consent` | |
| TP-E29-078 | Signup requires the terms | Anonymous | — | 1. On `/signup` leave the terms box unticked → submit.<br>2. Tick it → submit. | First refused (`accept_terms`); then the account is created and a `TermsAcceptance` with the versions, IP and browser is stored. | P1 | backend: `test_signup_records_terms_acceptance` | |
| TP-E29-079 | Delete your account | Tutor in two organisations | — | 1. Account → **Delete your account** → preview.<br>2. Enter the password → delete. | Membership ended and erasure run in each organisation; sessions, MFA, passkeys and login history gone; `user.account_deleted`. | P1 | backend: `test_deleting_an_account_erases_it_in_every_organisation`; vitest: `G6.test.tsx` deletes the account | |
| TP-E29-080 | Last owner can't delete their account | Owner (only owner) | — | 1. Preview account deletion. | Blocked with the reason; nothing deleted; a wrong password deletes nothing. | P1 | backend: `test_preview_lists_organisations_and_blocks_the_last_owner`, `test_a_wrong_password_deletes_nothing` | |
| TP-E29-081 | Impossible travel alert | Any staff | `CF-IPCountry` header set | 1. Sign in from GB, then within 2 hours from US. | Email to the person and `security.alert` (`impossible_travel`) for the owners; login history shows the country. | P2 | backend: `test_another_country_too_soon_alerts_the_person_and_the_owners` | |
| TP-E29-082 | Platform retention | Platform | Old login events and dispatched events | 1. Run `purge_platform_records`. | Login history over 400 days and organisation-less events over 90 days removed; pending events kept. | P3 | backend: `test_platform_purge_removes_old_login_history_and_platform_events` | |
