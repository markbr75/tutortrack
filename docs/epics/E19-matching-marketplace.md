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
- [ ] **E19-T01** Matching query service: hard filters (SQL + PostGIS-lite distance via haversine/earthdistance extension) and scoring with breakdown.
- [ ] **E19-T02** Availability overlap calculation (reuse E08 slot engine, vectorised for many tutors).
- [ ] **E19-T03** Shortlists and direct offers incl. cascade and expiry tasks.
- [ ] **E19-T04** Offer acceptance → assignment + series + intro notifications.
- [ ] **E19-T05** Internal job board and applications.
- [ ] **E19-T06** Cover requests.
- [ ] **E19-T07** Frontend: match search UI with map & heatmap, offer management, tutor job inbox.
- [ ] **E19-T08** (Phase 2b) Client shortlist sharing.
- [ ] **E19-T09** Matching analytics widgets.

## Temporal workflows (E32)

Implement these processes as Temporal workflows following the rules in [E32](E32-workflow-orchestration-temporal.md) (deterministic workflow code, side effects in tenant-scoped activities that call services, tenant-prefixed workflow IDs, signals for human decisions). Where the requirements above mention sweeper tasks, `next_*_at` / `resume_at` columns or retry schedules, the workflow replaces them.

- [ ] **E19-TW1** Job offer and cover workflows (requires E32).

| Workflow | Started by | Steps, timers and signals | Replaces |
|---|---|---|---|
| `JobOfferCascadeWorkflow` `job-offer:{org}:{job}` | Coordinator sends offers (simultaneous or sequential) | Send offer(s) → wait `accepted`/`declined` per tutor with expiry timers → sequential cascade to the next tutor → first acceptance wins (or admin confirm signal) → withdraw the rest → assign tutor + create series + intro notifications | Offer expiry tasks |
| `CoverRequestWorkflow` | Cover request created | Notify eligible tutors → wait for first `accept` until lesson start minus N hours → reassign lessons, or escalate as unfilled | Manual chasing |
