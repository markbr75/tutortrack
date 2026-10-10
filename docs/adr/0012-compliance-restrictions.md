# ADR 0012: Compliance restricts through the tutor's status; expiry runs per expiry date

- **Status:** Accepted
- **Date:** 2026-10-10
- **Epic:** E18

## Context
Tutors must not be given new work while a mandatory check (DBS, right to work, WWCC...) is
missing, rejected or expired. Restrictions must be enforced wherever tutors are assigned,
lift automatically on renewal, never override a restriction a person made, and optionally
hold pay. Expiry reminders and the expiry itself are timed processes.

## Decision
1. **One status, one guard.** Compliance sets the existing `TutorProfile.status` to
   `restricted` (and back to `active`). `TutorComplianceState.restricted_by_compliance`
   remembers that it was compliance, so manual restrictions are left alone.
   `people.assignability.check_assignable` is the single guard used by jobs and
   scheduling. It raises `tutor_not_compliant` for restricted tutors unless the request
   carries `?compliance_override=<reason>` from someone holding
   `compliance.override_restriction`; overrides are audited.
2. **Validity:** a verified record is valid until (not including) its expiry date.
   Requirement types come per organisation, seeded from its country (UK, IE, US, CA, AU, NZ
   plus common types) and editable. Renewal intervals fill in the expiry from the issue
   date.
3. **Expiry on Temporal:** each verified record with an expiry gets a
   `ComplianceRecordWorkflow` whose id includes the expiry date
   (`compliance:{org}:{record}:{yyyymmdd}`). A renewal signals `renewed` to the old run
   and starts a new one, instead of `continue_as_new`: workflow ids can't be reused after
   completion, and each date stays traceable. A nightly sweep re-checks everything as a
   safety net (records whose workflow never ran, new requirement types). It reads the
   domain data, not a schedule column.
4. **Pay hold** is a payroll hold rule (`compliance`) registered by recruitment; payroll
   doesn't know about compliance.
5. **Documents** are private files attached to the record. A storage access-rule hook
   lets holders of `compliance.view` open them; everyone else can't, apart from the
   uploader.

## Consequences
- Any future assignment path (marketplace offers in E19, self-booking) must call
  `check_assignable`.
- Background-check provider integrations (Phase 3) will submit records through the same
  services.
