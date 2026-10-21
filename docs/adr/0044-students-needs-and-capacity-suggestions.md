# ADR 0044: Students' needs in matching, capacity suggestions, and gap batch G5c

- **Status:** Accepted
- **Date:** 2026-10-21
- **Scope:** people (matching profile fields), matching (engine criteria and factors),
  leads (`WaitlistSuggestion`), learning (scheduled progress reports, classroom resources),
  calendar_sync (classroom resource links), portal (tutor shell).

## Context

Gap batch G5c closes four deferred items: waitlist suggestions when tutor capacity appears
(FR-17-6), matching on exam board, SEN experience and a gender preference (FR-19-1),
progress reports drafted on a schedule (FR-21-6) and resources in the video room (FR-21-8).
Three of them raised design questions worth recording:

- SEN tags are special-category data about children, and acting on a family's preference
  for a tutor's gender is only lawful in some places and situations. The spec already says
  gender preference is "configurable, off by default".
- Adding factors to the match score would change every existing score (the weights are
  normalised), which staff compare over time and which tests pin.
- "Capacity appears" has no single event: availability, time off, jobs ending, tutors
  becoming active. CLAUDE.md forbids a `next_*_at` column with a sweeper.

## Decision

1. **Needs live on the people records, guarded like learning needs.** Tutors get
   `exam_boards`, `sen_tags` (experience) and `gender`; students get `sen_tags` and
   `tutor_gender_preference` (`exam_boards` already existed). A student's SEN tags and
   preference use `people.student.view_sensitive`; a tutor's gender a new permission,
   `people.tutor.view_sensitive`. All are audit-redacted and covered by the DSAR export,
   erasure and the merge screen. SEN tags are short labels (JSON list) rather than
   encrypted text, so the engine can read them; free-text detail stays in the encrypted
   `learning_needs`. Searches store only the number of SEN tags and whether a gender
   preference applied (`MatchQuery.criteria`), never the values.
2. **Exam board and SEN experience are optional factors.** `exam_board` and `sen` join the
   weights (10 each) but count only when a search asks for them, so searches without needs
   score exactly as before. Missing tutor data scores 0.5, as for every other factor.
3. **Gender preference is a hard filter behind an organisation switch.**
   `matching.gender_preference` is off by default; with it off the preference is stored but
   ignored everywhere. With it on, only tutors of that gender match. A preference is only a
   preference if every student on the job who states one agrees.
4. **Capacity suggestions are event-driven records.** An idempotent handler on
   `availability.updated`, `job.status_changed` (ended), `job.tutor_removed`,
   `tutor.status_changed` (to active) and `tutor.unrestricted` checks whether the tutor has
   room (hours limit; a free hour in the next two weeks when availability is set) and runs
   the matching engine limited to that tutor for each waiting student. A match is a
   `leads.WaitlistSuggestion`, one per entry and tutor, so replays never duplicate and a
   dismissed suggestion is never raised again. Staff offer the place from it (the existing
   E17 offer link) or dismiss it.
5. **Scheduled progress reports are a Temporal Schedule.** `learning.progress_schedule`
   (none, monthly, termly) keeps a per-organisation schedule in step. Monthly runs on the
   1st for last month. Termly runs daily and drafts for E20 terms that ended in the last
   week, because terms are irregular and a daily cron that usually finds nothing is
   simpler and sturdier than one schedule entry per term. Runs only create missing reports
   (never refresh drafts), so the look-back and reruns are idempotent.
6. **Resources reach the room through our classroom, not the provider.** The classroom
   endpoint opens anything shared into the lesson for anyone in the room, the page polls
   while the room is open, and the tutor shares into it from the page. No provider API is
   called: Lessonspace documents no resource field, Zoom, Teams and Meet have no in-meeting
   file API we can use, and provider code is outside this batch.

## Consequences

- Organisations that want gender preferences must turn them on deliberately; the setting's
  help text says to do so only where it is lawful.
- Coordinators (via `people.*`) see SEN tags and tutors' gender; custom roles can remove
  either permission. Tutors don't see tutors' gender.
- Staff get at most one notice per tutor and capacity event; dismissing is permanent for
  that student and tutor, so a tutor freeing up again later won't re-raise a dismissed pair.
- A job ending counts as room for its tutors without the slot check, because another
  handler may still be cancelling the job's lessons in the same dispatch.
- Termly drafting depends on terms being set up under Classes.
- If a provider later supports pushing files into its own room, a provider method can be
  added behind the same classroom share without changing the API.
- The tutor app's shell redirected every path outside `/tutor` to Today, which hid the
  E22-T10 classroom from tutors; the shell now lets `/classroom/<lesson>` through.
