# ADR 0013: Matching filters in SQL and scores in Python; offers cascade per batch

- **Status:** Accepted
- **Date:** 2026-10-10
- **Epic:** E19

## Context
Coordinators need a ranked list of tutors for a job, with reasons for each score. Unsafe
tutors (unapproved subject, restricted, lapsed checks) must never be offered work by
accident. Offers go to several tutors (one after another or all at once) with expiry and
"first acceptance wins", and cover for one-off absences has a hard deadline.

## Decision
1. **Hard filters first, then score.** `matching.engine.search` narrows candidates in SQL:
   - tutor status;
   - approved `TutorSubject` at the level (or with no level);
   - delivery mode and branch;
   - not excluded by a student, not already on the job;
   - maximum pay rate and languages.

   It then drops, in Python, tutors with a lapsed blocking check (a recruitment selector,
   so a sweep that hasn't yet run can't let them through) and tutors outside their travel
   radius (great-circle distance). Only the survivors are scored.

   "Include restricted" is a separate permission (`matching.include_restricted`). It
   relaxes the filters to claimed subjects, flags the tutors with reasons and is audited.
2. **Scores are explainable.** There are nine factors, each scored 0-1, combined by
   per-organisation weights (`matching.weights`) into a score from 0 to 100. Every result
   carries the breakdown.

   Missing inputs score a neutral 0.5 and are marked unknown, so tutors with sparse
   profiles are neither favoured nor buried.

   Inputs from other apps come from their selectors in a fixed number of batched queries
   per search:
   - scheduling: `interval_fit`, scheduled minutes, completed lessons;
   - jobs: last assignment;
   - recruitment: referee ratings and lapsed checks.
3. **Searches are recorded.** `MatchQuery`/`MatchResult` keep the criteria and ranking for
   analytics (unmet demand, empty searches) and for audit of restricted searches.
4. **One cascade workflow per offer batch.** `JobOfferCascadeWorkflow` runs
   `job-offer:{org}:{batch}`, not per job: Temporal ids can't be reused after completion,
   and a job may be offered again.

   Tutors' answers are written by services and signal the workflow. The workflow reads
   the state through activities and decides the next step:
   - next wave;
   - expire the wave;
   - ask for confirmation;
   - fill.

   Filling is idempotent and re-checks that the tutor is still assignable. A tutor who
   became restricted is skipped and the cascade continues.
5. **Cover is assigned on acceptance.** The first tutor to accept a cover request gets the
   lessons in the same transaction (via `scheduling.update_lesson`, so conflicts and pricing
   apply). `CoverRequestWorkflow` only asks tutors and escalates at the deadline, so a
   Temporal outage never strands an accepted cover.

## Consequences
- Scoring is O(candidates) in Python after SQL filtering. That is fine for organisations
  with hundreds of tutors; a SQL or vector scorer can replace `engine.search` behind the
  same interface if needed.
- Weights live in org settings, so they are audited and reset like other settings. There
  is no separate `MatchingSettings` table.
- The workflows hold no business state: replaying a history only re-runs decisions over
  the recorded activity results.
