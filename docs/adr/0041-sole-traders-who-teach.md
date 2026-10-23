# ADR 0041: Sole traders who teach (solo mode)

- **Status:** Accepted (menu and tutor rules extended by ADR 0045)
- **Date:** 2026-10-20
- **Scope:** people (tutor records), tenancy (onboarding, organisation mode), identity (`/me`),
  the admin app (menu, Home, settings) and the portal (tutor shell). Product principle 1,
  "sole-trader simple, agency deep".

## Context

A walk-through as a new **sole trader** showed that the core flow worked (book, mark, charge,
invoice), but the product treated one tutor like an agency:

- the owner was not a tutor, so no lesson could be booked until they found **Tutors** and
  added themselves by email; nothing said so;
- the menu showed agency tools (matching, payroll, recruitment, compliance) and Home showed
  "Next pay run";
- the phone tutor app opened only for logins with the Tutor role, so an owner who teaches
  could not use it;
- `Organisation.mode` ("solo" or "multi", set from the business type) existed but nothing
  read it, and the type of business could not be changed after the wizard.

## Decision

1. **"Add yourself as a tutor"** (`people.services.add_self_as_tutor`, `POST /api/v1/tutors/add-me`,
   `people.tutor.create`): an active tutor record on the signed-in person's own membership,
   with no invitation; idempotent, and it links a tutor record already made with their email.
2. **The wizard asks** "I teach lessons myself" on the business step (`owner_teaches`), ticked
   by default for sole traders and small teams. The step calls the service directly with the
   current membership; onboarding events carry no actor. The step starts from the type of
   business chosen at sign-up; it used to default to "Sole trader", which would put an agency
   that clicked straight through into solo mode.
3. **`/me` says whether you teach** (`membership.teaches`). The portal opens the tutor shell for
   the Tutor role **or** any login that teaches; the admin account menu offers
   "Open the tutor app". The tutor API already accepted any login with a linked tutor record.
4. **Solo mode trims the admin app** from `organisation.mode`: nav items marked `team`
   (matching, payroll, recruitment, compliance) are left out of the menu, and Home's third
   money figure is "Not yet invoiced" instead of "Next pay run". Pages stay reachable; this
   is presentation, not permission.
5. **Type of business is editable** in Settings › Organisation; changing it already updates
   the mode, so a sole trader who takes on tutors gets the team menus back.

## Consequences

- The user guide gains "Working on your own"; the admin guide documents the wizard option
  and the type of business setting.
- Plan limits are unchanged (Solo: one tutor), so a sole trader's own tutor record fits.
- Completed lessons did not become charges locally. The cause (found 2026-10-21) was not beat:
  the local worker command consumed only the `default` queue, so outbox, notification, billing
  and other routed tasks never ran. `config/celery.py` now declares every queue, and the README
  adds beat for timed jobs.
