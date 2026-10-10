# E19 — Tutor Matching & Job Marketplace

| | |
|---|---|
| **Phase** | Agency (Phase 2) |
| **Depends on** | E05, E07, E08, E18 |
| **Parity** | TutorCruncher job board (tutors apply for jobs), tutor search/filters; Socket discovery |

## 1. Summary
Find the right tutor for a job quickly: a scored search across subject competency, availability overlap, location/travel distance, delivery mode, rate fit, ratings, workload and preferences; plus a **job board** where tutors apply for open jobs, **direct offers** to shortlisted tutors, and **cover requests** for one-off absences.

## 2. Functional requirements

### FR-19-1 Matching search
- Input: from a job (`seeking_tutor`) or ad hoc criteria: subject/level, exam board, delivery mode, student location (geocode), preferred days/times, duration, start date, required compliance, gender preference (if lawful and set by client; configurable/off by default), language, max pay rate / margin target, SEN experience tags.
- Hard filters: approved subject, active & compliant, delivery mode supported, within travel radius (in-person), not excluded by client, branch.
- Scoring (weights configurable per org): availability overlap %, distance, rating, experience/years, current workload vs max hours, previous success with similar students, margin at their pay tier, response rate to offers, recency of last assignment (fairness).
- Results: ranked list with score breakdown, map view, availability heatmap overlay, quick actions (view profile, shortlist, offer).
- **AC:** a tutor without the approved subject/level or with expired compliance never appears in results (even with zero filters), unless the "include restricted" toggle is set by a permitted user.

### FR-19-2 Direct offers
- Send an offer to one or many shortlisted tutors (simultaneous or sequential cascade with timeouts); offer contains anonymised job brief (student first name/initial, area not full address, schedule, pay rate, notes).
- Tutor accepts/declines (with reason) via portal/push/SMS link; first acceptance wins (configurable: admin confirms). Others auto-withdrawn with a notification.
- On confirmation: tutor assigned to job (E07), series created/updated, intro emails sent.

### FR-19-3 Job board
- Jobs can be published to the internal job board (all eligible tutors or filtered group) with an anonymised brief; tutors express interest/apply with a message and proposed availability; staff review applicants (sorted by match score) and select.
- Optional public job board (for recruiting new tutors, links to E18 applications).

### FR-19-4 Cover requests
- When a tutor has time off or cancels, staff/tutor creates a cover request for affected lesson(s); eligible tutors (matching subset) are notified; accept → lessons reassigned for those dates only.

### FR-19-5 Client-facing tutor selection (Phase 2b)
- Share a shortlist with the client (tutor profile cards: photo, bio, qualifications, ratings; no contact details) via a link; client picks preferred tutor; feeds into offer flow. Links into E17 proposals.

### FR-19-6 Matching analytics
- Time-to-match per job, offer acceptance rates per tutor, unmatched demand by subject/area (recruitment signal for E18).

## 3. Data model
`MatchQuery(criteria JSONB, job, created_by)`, `MatchResult(query, tutor, score, breakdown JSONB)`, `Shortlist`, `JobOffer(job, tutor, status, expires_at, cascade_order, decline_reason)`, `JobPosting(job, visibility, audience filter, status)`, `JobPostingApplication`, `CoverRequest(lessons, status, accepted_by)`, `MatchingSettings(weights)`.

## 4. API
`POST /api/v1/matching/search`, `/shortlists`, `/job-offers` (+ accept/decline/withdraw), `/job-postings` (+ apply), `/cover-requests` (+ accept), `/matching/settings`, `/public/shortlists/{token}`.

## 5. Events
`job_offer.sent/accepted/declined/expired/withdrawn`, `job_posting.published/application_received`, `cover_request.created/accepted/unfilled`.

## 6. Delivery plan
- [x] **E19-T01** Matching query service: hard filters (SQL + PostGIS-lite distance via haversine/earthdistance extension) and scoring with breakdown.
- [x] **E19-T02** Availability overlap calculation (reuse E08 slot engine, vectorised for many tutors).
- [x] **E19-T03** Shortlists and direct offers incl. cascade and expiry tasks.
- [x] **E19-T04** Offer acceptance → assignment + series + intro notifications.
- [x] **E19-T05** Internal job board and applications.
- [x] **E19-T06** Cover requests.
- [x] **E19-T07** Frontend: match search UI with map & heatmap, offer management, tutor job inbox.
- [ ] **E19-T08** (Phase 2b) Client shortlist sharing.
- [x] **E19-T09** Matching analytics widgets.

## Temporal workflows (E32)

Implement these processes as Temporal workflows following the rules in [E32](E32-workflow-orchestration-temporal.md) (deterministic workflow code, side effects in tenant-scoped activities that call services, tenant-prefixed workflow IDs, signals for human decisions). Where the requirements above mention sweeper tasks, `next_*_at` / `resume_at` columns or retry schedules, the workflow replaces them.

- [x] **E19-TW1** Job offer and cover workflows (requires E32).

| Workflow | Started by | Steps, timers and signals | Replaces |
|---|---|---|---|
| `JobOfferCascadeWorkflow` `job-offer:{org}:{job}` | Coordinator sends offers (simultaneous or sequential) | Send offer(s) → wait `accepted`/`declined` per tutor with expiry timers → sequential cascade to the next tutor → first acceptance wins (or admin confirm signal) → withdraw the rest → assign tutor + create series + intro notifications | Offer expiry tasks |
| `CoverRequestWorkflow` | Cover request created | Notify eligible tutors → wait for first `accept` until lesson start minus N hours → reassign lessons, or escalate as unfilled | Manual chasing |

## Implementation notes (as built 2026-10-10)
- **App:** `matching`, with RLS on every table: `MatchQuery` and `MatchResult` (each search and its ranked results, for analytics and audit), `Shortlist`, `OfferBatch` and `JobOffer`, `JobPosting` and `JobPostingApplication`, `CoverRequest` and `CoverLesson`. See ADR 0013.
  - Deviation: weights are the org setting `matching.weights` (per organisation, editable at `/api/v1/matching/settings`) rather than a `MatchingSettings` table. Other settings: default travel radius, target margin, offer expiry hours, admin confirmation, cover cut-off and how many tutors to ask for cover.
- **Search (T01):** `matching.engine`. Criteria come from the job (subject, level, mode, place, weekly slots, start, branch, charge rate, the students' excluded tutors and the tutors already on the job) or are given ad hoc (a postcode is geocoded with the E05 geocoder, plus languages, maximum pay rate and required checks).
  - Hard filters: active, approved subject at the level (or level-less approval), mode, branch, not excluded, travel radius for in-person (great-circle distance, as payroll uses), required checks, and no lapsed blocking check.
  - AC: tutors without an approved subject, restricted tutors and tutors with a lapsed check never appear, even with no criteria. "Include restricted" (`matching.include_restricted`, which coordinators don't hold) relaxes this to claimed subjects; those tutors are flagged with reasons, audited, and can't be offered the job from the UI.
  - Scoring: nine factors, each 0-1, combined by weight into a score from 0 to 100: availability overlap, distance, rating, experience, spare capacity, similar lessons taught, margin, offer acceptance, and time since last job (fairness). Unknown inputs score 0.5 and are marked unknown in the breakdown.
  - Deviations: rating uses referee ratings from E18 until client feedback exists. Gender preference and SEN tags are not built (gender is off by default in the spec).
- **Availability (T02):** `scheduling.availability.interval_fit` scores many tutors in a fixed number of queries: templates, approved extra and time-off exceptions, lessons with the travel buffer, events and closures. A job's weekly slots are checked over the next four weeks; cover checks the exact lessons.
- **Offers (T03/T04):** offers go to the tutors in the order chosen, one after another or all at once, each with an expiry.
  - The brief is anonymised: students' first names and initials, postcode district, schedule, optional pay rate, notes for the tutor.
  - Tutors accept or decline (with a reason) in the portal. With `matching.admin_confirms`, a coordinator confirms the accepted tutor.
  - The first acceptance wins: the tutor is assigned (E07 `add_tutor`), the job's series is created from its weekly schedule if it has none (E08), the tutor and family get introduction notifications, and the other offers are withdrawn with a notice.
  - An unanswered cascade ends "exhausted" with a staff alert. Shortlists keep a tutor's score per job.
- **Job board (T05):** publishing a job fixes the eligible tutors (those passing the hard filters, optionally above a minimum score) and tells them. Tutors apply with a message and proposed slots. Staff see applicants sorted by match score and choose one, who is assigned like an accepted offer; the others are told.
  - Deviation: the optional public job board is the E18 vacancies page.
- **Cover (T06):** a coordinator or the tutor (for their own lessons) asks for cover for planned future lessons. The best tutors free for every lesson are asked, up to `matching.cover_notify_limit`. The first to accept gets those lessons only (E08 `update_lesson`, re-priced; the job keeps its tutor). Staff can also assign cover directly from the free tutors.
- **Frontend (T07):** admin `/jobs/$id/match`: ranked results with an expandable score breakdown, distance, a per-slot availability heatmap, a map of rounded tutor locations relative to the lessons, shortlist, offers (order, mode, expiry; confirm, reject or withdraw), and the job board with applicants.
  - Admin `/matching` has tabs for cover requests (who's free, assign, cancel), analytics and weights.
  - Tutor portal `/portal/tutor/jobs` holds offers (accept or decline with a reason), the job board (apply) and cover (take it); today's offer count includes these. This also delivers E16-T10.
  - Deviation: the map is a schematic plot rather than map tiles; tile providers come with E22 integrations.
- **Analytics (T09):** `/api/v1/matching/analytics` reports time to match (from seeking-tutor to filled), offer answers per tutor, unmatched demand by subject and area, and searches with no results by subject.
- **Workflows (TW1):**
  - `JobOfferCascadeWorkflow` `job-offer:{org}:{batch}`: waves, expiry timers, signals `responded`, `decided` and `cancelled`, first acceptance wins. The id is per batch rather than per job because a job can be offered again after a cascade ends.
  - `CoverRequestWorkflow` `cover:{org}:{request}`: asks the eligible tutors, waits for `accepted` or `cancelled` until the cut-off, then escalates as unfilled.
  - Replay histories are in `backend/tests/workflow_histories/`.
- **Not built:** T08 client shortlist sharing (Phase 2b).
