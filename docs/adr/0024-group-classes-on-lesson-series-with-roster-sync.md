# ADR 0024: Group classes run on E08 lesson series with roster sync; fees through E10; enrolment payment and rollover on Temporal

- **Status:** Accepted
- **Date:** 2026-10-13
- **Epic:** E20. Builds on ADR 0002 (Temporal), ADR 0007 (ledger and charge sync), ADR 0019 (sites registries), ADR 0021 (scheduling Phase 2) and ADR 0022 (billing Phase 2).

## Context
Learning centres sell courses taught in termly classes. A class has a fixed schedule, a capacity and a changing roster. Families join part way through, move between classes, miss sessions and catch up elsewhere, and roll over to the next term.

Most of what a class needs already existed:
- lessons, series, rooms and holds (E08);
- attendance, policies and makeup credits (E09);
- charges, invoices, plans and credit notes (E10);
- payment at booking (E11);
- waitlist offers (E17);
- widget and block registries (E24).

The rules that had to hold:
- Apps write other apps' data only through services.
- Money is `Decimal`, rounded half-up per line, and is never edited after issue.
- Timers live in Temporal.
- Two families must never take the last place at once.
- Enrolling mid-term changes future sessions only.

## Decision
1. **A class is a lesson series; each session is a `Lesson` linked by `ClassSession`.**
   - Scheduling gains three small, generic hooks:
     - `allow_empty_roster` (and `title`, `extra_template`) on series;
     - tutor-only pricing for lessons with no students;
     - `sync_group_roster(lesson, attendees, tutors)`.
   - `sync_group_roster` changes only future, planned, unlocked lessons and touches only the people who change.
   - The class roster (enrolments covering the session date, plus makeup bookings) is the source of truth. `courses.services.sync_class_roster` applies it after every enrolment, withdrawal, transfer, makeup and schedule change.
   - So the calendar, conflicts, rooms, attendance, E09 policies, E10 charge sync, E12 pay items and E22 calendar sync work for classes without class-specific code.
2. **Billing never learns about classes.** Two charging paths cover every pricing model:
   - Fee-based models (per term, whole course, instalments, registration, materials) use new E10 helpers. `charge_fee` makes idempotent charges by source key, split by payers. `adjust_fee` voids what isn't invoiced and credits what was over-billed (credit notes; unpaid invoices simply owe less). These charges use a new `course` charge kind.
   - Monthly courses are ordinary E10 billing plans. Pay-as-you-go courses set the session attendee's rate override, so E10 charges each delivered session. Every other model zero-rates sessions, so nothing is charged twice.
   - Discounts and proration live in a pure `courses.pricing` module, tested with Hypothesis.
3. **Term dates are provided to E10 and E08 through registration hooks, not imports.**
   - `billing.plans.register_term_calendar`: termly plans follow the branch's terms. An open-ended plan waits for the next term (`paused` from the activity; no workflow change, so recorded histories still replay).
   - `scheduling.services.register_skip_dates`: series skip term breaks.
   - `sites.selectors.register_public_assets`: course images are public assets.
   - Without terms, E10's four-monthly behaviour is unchanged.
4. **Places are counted under a row lock on the class.** Every enrolment does `select_for_update` on the class. Places taken = active enrolments + waitlist offers that are out or accepted but not yet enrolled. So an offered place is held while the family decides.
5. **Class waitlists are E17 entries tagged with `group_class_id`.** Offers, expiry and acceptance stay E17's (`WaitlistOfferWorkflow`, the token page, the `waitlist_offer` message). The class decides when to offer: on a freed place, an expired offer or a declined offer. E17's subject cascade skips class entries.
6. **Two workflows own the timers:**
   - `EnrolmentPaymentWorkflow` holds a place until the E11 payment request is paid or the hold expires. It replaces a pending-payment sweeper.
   - `TermRolloverWorkflow` sends requests, reminds half way, and finishes at the deadline, when everyone has answered, or on staff request.
   - Rollover answers come from the portal or an HMAC email token (no secret stored).
   - The rollover workflow id uses the rollover record rather than the term, so a cancelled rollover can be run again.

## Consequences
- Scheduling, billing, leads, sites, catalogue and portal changed in small, generic ways:
  - scheduling: an empty-roster series, roster sync and a skip-dates hook;
  - billing: the `course` charge kind, `charge_fee`/`adjust_fee`, the term calendar and the termly label;
  - leads: `WaitlistEntry.group_class_id` and per-class positions;
  - sites: a public assets hook;
  - catalogue: the `multi_class` discount kind with `min_classes`;
  - portal: the `classes` feature flag.

  Each has a migration where needed.
- A class's sessions are materialised up to the class end when it is created, ignoring the rolling horizon, so long terms create all their lessons at once.
- Editing a class series' place resets the people on future sessions; the roster sync re-adds them, but an absence notice given in advance for those sessions is lost.
- Pay-as-you-go prices are lesson overrides, which the rate engine treats as final: their discounts are applied when enrolling, not per session, and they need a per-lesson or per-hour service whose rate isn't split.
- A rollover answered late (after the deadline) is refused; staff enrol such families directly.
