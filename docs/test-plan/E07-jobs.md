# E07 — Jobs and tutor assignment: manual tests

**Scope.** Jobs (the ongoing engagement for a student): references and auto-names, students and tutors on a job, rate overrides, the status machine, tutor assign/offer/replace/remove with a preview of affected lessons, bill-to client and hours caps, the financial summary (margin), quick setup from a student page, duplicate, the jobs list, the board and "needs attention". Spec: [E07](../epics/E07-jobs.md).

**Built differently from the spec:** there is no "New job" form in the admin app — jobs come from **Set up lessons** on a student page, from enquiries (E17), from `POST /api/v1/jobs` or by duplicating; the board moves cards with a **Move to…** select instead of drag and drop; "needs attention" means seeking a tutor for more than 7 days or an open tutor offer (E08–E10 add more reasons); policy overrides (cancellation, report template) are stored as JSON for E09; tutor notifications and the client intro email are E13 events; clients have no job API (portal shows lessons instead). Status machine: draft → seeking_tutor/active/cancelled; seeking_tutor → draft/active/cancelled; active → seeking_tutor/paused/completed/cancelled; paused → active/completed/cancelled; completed → active (reopen); cancelled is final.

**Common preconditions.** Seeded jobs: **GCSE Maths for Arjun Patel** with Nia Adeyemi, Active, weekly Tuesday 16:30, with a lesson series; **GCSE Maths for Ada Okafor**, Seeking tutor. Services from E06. Admin → **Jobs** (`/jobs`). Celery worker running (events drive lesson changes).

## Creating jobs

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E07-001 | Quick setup with a tutor | Coordinator | Maya Patel (no job) | 1. Students → Maya → **Set up lessons**.<br>2. Service GCSE Maths 1:1, tutor Nia Adeyemi, Day Thursday, Time 17:00, leave Rate empty → **Create job**. | Job "GCSE Maths – Maya Patel" (or level + subject) with reference `JOB-00000N`, status Active, Nia active; a weekly series from the next Thursday 17:00 appears in the calendar. | P1 | backend: `tutortrack/jobs/tests/test_jobs.py`; e2e: `e2e/jobs-scheduling.spec.ts` | |
| TP-E07-002 | Quick setup without a tutor | Coordinator | Grace Hughes | 1. **Set up lessons** → **Find a tutor later**, Piano lesson, Monday 18:00 → **Create job**. | Job in **Seeking tutor**; no lessons yet (or tutorless lessons per setting); it shows under **Needs attention** after 7 days. | P1 | backend: `tutortrack/jobs/tests/test_jobs.py` | |
| TP-E07-003 | Quick setup with an agreed rate | Coordinator | — | 1. **Set up lessons** with Rate (GBP) 40. | Job charge rate £40/h; lessons priced with "job rate £40.00/h" in the trace. | P2 | backend: `tutortrack/jobs/tests/test_jobs.py` | |
| TP-E07-004 | Create a job via the API | Coordinator | Swagger | 1. `POST /api/v1/jobs` for the Okafor client with Ada and a Maya ID. | Refused: students must belong to the client. With only Ada: created as Draft with an auto-name. | P2 | backend: `tutortrack/jobs/tests/test_jobs.py` | |
| TP-E07-005 | Group job respects service capacity | Coordinator | 11+ group class (max 8) | 1. Create a job with 9 students. | Refused (more than the service maximum). | P3 | backend: `tutortrack/jobs/tests/test_jobs.py` | |
| TP-E07-006 | Duplicate a job for a new year | Coordinator | Arjun's job | 1. `POST /api/v1/jobs/<id>/duplicate` with a new start date. | New job with the same students, service, rates and tutors; new reference; the original is unchanged. | P2 | backend: `tutortrack/jobs/tests/test_jobs.py` | |
| TP-E07-007 | Rate overrides use the job currency | Coordinator | — | 1. Set a student rate override in EUR on a GBP job. | Refused. | P3 | backend: `tutortrack/jobs/tests/test_jobs.py` | |

## Tutors on a job

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E07-008 | Assign a tutor activates a seeking job | Coordinator | Ada's job (Seeking tutor); Sam Clarke active | 1. Open the job → **Add a tutor** → Choose a tutor Sam Clarke → **Assign**. | Sam listed Active; job moves to **Active**; tutorless future lessons get Sam; Sam is notified (E13). | P1 | backend: `tutortrack/jobs/tests/test_jobs.py`; e2e: `e2e/jobs-scheduling.spec.ts` | |
| TP-E07-009 | Offer first, tutor accepts | Coordinator, Tutor | A seeking job; tutor@ (Nia) | 1. **Add a tutor** → Nia → tick **Offer first (tutor accepts)** → **Assign**.<br>2. As tutor@ open portal **Jobs** (`/portal/tutor/jobs`) and accept. | Status **Offered** until accepted, then Active and the job Active. Declining sets **Declined**. | P1 | backend: `tutortrack/jobs/tests/test_jobs.py` | |
| TP-E07-010 | Unavailable tutor is refused | Coordinator | Restricted or inactive tutor | 1. Try to assign them. | Refused with a reason. | P2 | backend: `tutortrack/jobs/tests/test_jobs.py` | |
| TP-E07-011 | Replace a tutor with a preview | Coordinator | Arjun's job with future lessons; Sam Clarke | 1. **Replace Nia Adeyemi** → Replace with Sam, From next week → **Preview**.<br>2. **Replace tutor**. | Preview: "N future lessons will move", clash count if any. After confirming, future unlocked lessons move to Sam and pay is re-resolved; past and locked lessons keep Nia; Nia shows "Previously". | P1 | backend: `tutortrack/jobs/tests/test_jobs.py` | |
| TP-E07-012 | Remove the last tutor returns the job to seeking | Coordinator | Job with one tutor | 1. **Remove** the tutor. | Job goes back to **Seeking tutor**. | P2 | backend: `tutortrack/jobs/tests/test_jobs.py` | |
| TP-E07-013 | Lead and assistant tutors | Coordinator | Group job | 1. Add a second tutor as Assistant via API (`role: assistant`). | Both listed with role; pay lines for both on lessons. | P3 | No | |

## Status lifecycle

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E07-014 | Pause and keep lessons | Coordinator | Maya's job (TP-E07-001) | 1. **Change status** → Paused, reason "Exams", untick **Cancel future lessons** → **Apply**. | Paused; future lessons kept; status history records the reason. | P1 | backend: `tutortrack/jobs/tests/test_jobs.py` | |
| TP-E07-015 | Pause and cancel future lessons | Coordinator | Maya's job active again | 1. Paused with **Cancel future lessons** ticked. | Future lessons cancelled as not chargeable; past lessons untouched. | P1 | backend: `tutortrack/jobs/tests/test_jobs.py` | |
| TP-E07-016 | Complete a job | Coordinator | Job with an open offer | 1. Change status → Completed. | Future lessons cancelled, series ended, open offers declined. Reopen (Completed → Active) is possible. | P1 | backend: `tutortrack/jobs/tests/test_jobs.py` | |
| TP-E07-017 | Cancelled is final | Coordinator | Cancelled job | 1. Try any status change. | Not allowed: "That move isn't allowed…". | P2 | backend: `tutortrack/jobs/tests/test_jobs.py` | |
| TP-E07-018 | Activating needs an active tutor | Coordinator | Draft job without tutor | 1. Change status → Active. | Refused. | P2 | backend: `tutortrack/jobs/tests/test_jobs.py` | |
| TP-E07-019 | Status history | Coordinator | After the above | 1. Job page → activity / `GET /api/v1/jobs/<id>/status-history`. | Every change with who, when, from → to and reason. | P3 | No | |

## Rules: bill-to and hours cap

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E07-020 | Bill a different client | Coordinator | Organisation client "Hillside Academy" | 1. PATCH Ada's job `bill_to` = Hillside Academy.<br>2. Create a lesson and look at its attendee charge. | Charges go to Hillside Academy (E10 invoices it), not the Okafor family. | P2 | backend: `tutortrack/jobs/tests/test_jobs.py` | |
| TP-E07-021 | Hours cap warning and block | Coordinator | Job hours cap 10 hours a month | 1. Schedule lessons up to 8 hours, then 10, then 11 in one month. | At 80% a warning; above 100% the lesson is blocked (hard conflict) unless `jobs.block_at_hours_cap` is off (warning only). Job page shows "10 hours a month". | P1 | backend: `tutortrack/jobs/tests/test_jobs.py` | |
| TP-E07-022 | Hours cap event once per period | Coordinator | As above | 1. Cross 80% and 100%. | `job.hours_cap_reached` emitted once per level per period (automations/notifications fire once). | P3 | backend: `tutortrack/jobs/tests/test_jobs.py` | |
| TP-E07-023 | PO number and billing method | Finance | Organisation client job | 1. Set PO number "PO-7781" and billing method Prepaid credit. | Shown under Billing on the job; E10 carries the PO onto invoices. | P3 | No | |

## Economics and lists

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E07-024 | Margin on the job page | Owner | Arjun's job (£45/h charge, £28/h pay, 60 min) | 1. Open the job → **Economics**. | Charge per lesson £45.00, pay per lesson £28.00, margin £17.00 (37.8%); "N of M lessons" delivered. | P1 | backend: `tutortrack/jobs/tests/test_jobs.py` | |
| TP-E07-025 | Jobs list filters | Coordinator | — | 1. Jobs → search "JOB-", filter status Seeking tutor, tick **Needs attention**. | Filters combine; "No jobs yet." when empty. | P1 | backend: `tutortrack/jobs/tests/test_jobs.py` | |
| TP-E07-026 | Board view | Coordinator | — | 1. View **Board**.<br>2. On Ada's card use **Move Ada…** → Active (no tutor) then Cancelled. | Columns per status; disallowed moves show "That move isn't allowed…"; allowed moves update the card. Fully keyboard operable. | P2 | No | |
| TP-E07-027 | Student page lists jobs | Coordinator | Arjun | 1. Open Arjun's page. | His GCSE Maths job with status and tutor; link to the job. | P2 | No | |

## Permissions

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E07-028 | Tutors see own jobs without charge rates or internal notes | Tutor | tutor@ (Nia) | 1. `GET /api/v1/jobs`.<br>2. `GET /api/v1/jobs/<Ada's job>`. | Only Arjun's job (and offers); no charge rate, margin, bill-to, PO or internal notes. Ada's job 404. | P1 | backend: `tutortrack/jobs/tests/test_jobs.py` | |
| TP-E07-029 | Coordinator sees charge but not pay or margin | Coordinator | — | 1. Open Arjun's job. | Job rate and charge per lesson shown; pay per lesson and margin hidden (`view_pay` missing). | P1 | backend: `tutortrack/jobs/tests/test_jobs.py` | |
| TP-E07-030 | Finance sees economics but can't edit jobs | Finance | finance@ | 1. Open `/jobs` and a job summary via API. | Finance has no `jobs.*`: Jobs nav absent; the API 403. (Margins are in reports, E26.) | P2 | No | |
| TP-E07-031 | Parent has no job API | Parent | parent@ | 1. `GET /api/v1/jobs`. | 403; the portal shows lessons, never pay rates. | P2 | No | |

## Tenant isolation

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E07-032 | Jobs list is per organisation | Owner | Create a job in northside for Noah | 1. On brightminds list jobs and search "Noah". | Not found; northside numbers its own `JOB-` sequence from 1. | P1 | backend: `tutortrack/jobs/tests/test_jobs.py` | |
| TP-E07-033 | Can't assign another organisation's tutor | Coordinator | Northside tutor ID | 1. `POST /api/v1/jobs/<id>/tutors` with it. | 404/400; nothing assigned. | P1 | No | |

## i18n and edge cases

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E07-034 | Quick setup time is in the organisation's timezone | Coordinator | Account timezone America/New_York | 1. **Set up lessons** Thursday 17:00. | Lessons at 17:00 Europe/London (the org/lesson timezone), shown as 12:00 in the viewer's New York time. | P2 | No | |
| TP-E07-035 | Weekday names and pluralisation | Coordinator | — | 1. Check the "Weekly" schedule and "1 future lesson will move" vs "3 future lessons will move". | Correct day names and plural forms. | P3 | No | |

## Gap batch G3 (as built 2026-10-14)

Built by gap batch G3 ([ADR 0037](../adr/0037-gap-batch-g3-scheduling-billing-payments-payroll.md)); see the epic's *Gap backlog* notes.

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E07-036 | Active job without upcoming lessons | Coordinator | Active job, no future lessons | 1. Jobs → tick **Needs attention**. | The job is listed with the badge "No upcoming lessons"; adding a future lesson removes it. | P1 | backend: `jobs/tests/test_g3_attention.py::test_active_job_without_upcoming_lessons` | |
| TP-E07-037 | Low prepaid balance or package units | Coordinator | Prepaid job with little credit; package job with no package | 1. Filter by reason **Low balance**. | Both jobs listed; selling a package removes the package job. | P1 | backend: `test_low_prepaid_balance_and_package_units` | |
| TP-E07-038 | Overdue reports | Coordinator | Job with an overdue lesson report | 1. Filter by reason **Overdue reports**. | The job is listed. | P2 | backend: `test_overdue_reports`, `test_list_filters_and_shows_reasons` | |
