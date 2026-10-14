# E20 — Group classes, courses and term enrolment: manual tests

**Scope.** Academic years and terms with breaks, courses and classes (cohorts) run on E08 lesson series, enrolment with capacity locks and eligibility, class billing and proration, transfers and withdrawals, class waitlists with auto-offers, registers and makeups, term rollover with family confirmation, the public catalogue with online enrolment and payment, and the admin and portal screens. Spec: [E20](../epics/E20-classes-courses.md); decisions in [ADR 0024](../adr/0024-group-classes-on-lesson-series-with-roster-sync.md).

**Built differently from the spec (Implementation notes win):**
- "Running" classes still accept mid-term enrolment (status is informational).
- Instalments are fixed monthly charges from enrolment, not E11 auto-pay schedules.
- Absence reasons are free text.
- `class.below_minimum` is only checked on withdrawal or transfer, not on a timer.
- Pay-as-you-go courses need a service where each student pays the rate (not split).
- The rollover workflow id is per rollover, so a cancelled rollover can be run again.

**Common preconditions.**
- Stack running and seeded (see [README](README.md)); admin http://brightminds.localhost:5173, portal http://brightminds.localhost:5174/portal/. Password: `SEED_ADMIN_PASSWORD` (default `tutortrack`).
- The trial carries the Agency plan, so the `courses` feature is on (**Courses** in the admin navigation; **Classes** in the family portal when the portal's classes feature is on).
- Seed: academic year (e.g. 2026/27), term "This term" (started two weeks ago, 12 weeks, with a one-week "Half term" six weeks in), course "Year 6 11+ Prep" (£180.00 per term, years 5–6, on the website), class "Saturday 10am" (open, 8 places, taught by Nia Adeyemi, service "11+ group class").
- **No seeded student is in Year 5 or 6.** Create one first: on the Patel family add student "Riya Patel", Year 6, date of birth 10 years ago. Reuse her below. Also add "Theo Okafor", Year 5, to the Okafor family for sibling/second-student cases.
- Fake Stripe for online payment (no keys). Temporal worker running for payment holds and rollover (http://localhost:8233). Emails in Mailpit.

## Terms and academic calendar (FR-20-1, T01)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E20-001 | View seeded year and term | Coordinator | Seed | 1. Open **Courses → Terms**. | The academic year and "This term" with dates and the "Half term" break show. | P1 | No | |
| TP-E20-002 | Add a term with a break | Admin | None | 1. Click **New term**: "Spring term", the 12 weeks after "This term", enrolment open/close dates.<br>2. Add break "Half term" (one week in the middle).<br>3. **Add term**. | Saved and listed. | P1 | backend: `tutortrack/courses/tests/test_courses.py::test_staff_set_up_a_term_course_and_class_and_enrol_through_the_api` | |
| TP-E20-003 | Term rules | Admin | Terms exist | 1. Add a term overlapping "This term".<br>2. Add a term outside the academic year. | Both refused with clear errors. | P2 | backend: `tutortrack/courses/tests/test_courses.py::test_term_rules` | |
| TP-E20-004 | Class sessions skip breaks | Coordinator | Seeded class | 1. Open the class "Saturday 10am" → **Sessions**. | No session falls in the half-term week. | P1 | backend: `tutortrack/courses/tests/test_courses.py::test_breaks_are_skipped_by_class_sessions` | |
| TP-E20-005 | Adding a break re-plans future sessions | Admin | Seeded class | 1. Add a break "Inset day" on a future Saturday. | That Saturday's session is removed; sessions are re-planned; past sessions untouched. | P2 | backend: `tutortrack/courses/tests/test_courses.py::test_new_breaks_replan_the_sessions` | |
| TP-E20-006 | Breaks pause 1:1 lessons only with the setting | Admin | Arjun's weekly Tuesday lessons; a break over a Tuesday | 1. With `courses.breaks_skip_all_lessons` off, check Arjun's lesson in the break.<br>2. Turn it on and check again. | Off: Arjun's lesson stays. On: it is skipped. | P2 | backend: `tutortrack/courses/tests/test_courses.py::test_breaks_pause_other_lessons_only_with_the_setting` | |
| TP-E20-007 | Termly billing plans follow term dates | Finance | A termly E10 billing plan on a family | 1. Check the plan's periods. | Each term is a period; holidays between terms are not billed. Past the last known term, the plan waits until a new term is saved. | P2 | backend: `tutortrack/courses/tests/test_courses.py::test_termly_billing_plans_follow_term_dates` | |

## Courses and classes (FR-20-2, FR-20-3, T02)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E20-008 | Create a course | Admin | Service "11+ group class" | 1. **Courses → Courses → New course**: "GCSE Maths Booster", scheduled as 11+ group class, pricing **Per term**, price £150.00, registration fee £20.00, description, **Show on the website and portal**.<br>2. **Create course**. | Listed with price "£150.00" and **On the website: Yes**. | P1 | No | |
| TP-E20-009 | Course validation | Admin | None | 1. Create an **instalments** course without the number of instalments.<br>2. Negative price. | Both refused with field errors. | P2 | backend: `tutortrack/courses/tests/test_courses.py::test_course_validation` | |
| TP-E20-010 | Create a class with sessions | Admin | Course from TP-E20-008; "This term" | 1. **Classes → New class**: course GCSE Maths Booster, term This term, name "Wednesday 5pm", day Wednesday, start 17:00, length 60, places 6, teacher Nia, location Leeds Centre.<br>2. **Create class and sessions**. | The class is created with a weekly session every Wednesday 17:00 (UK time) to the term end, skipping half term. If the teacher or room is busy, a message lists skipped dates. | P1 | backend: `tutortrack/courses/tests/test_courses.py::test_a_class_runs_on_lessons_with_its_teachers` | |
| TP-E20-011 | Capacity limited by service and room | Admin | Service max 8 | 1. Create a class with 12 places.<br>2. In a room with capacity 4, create a class with 6 places. | Refused in both cases with the limit named. | P2 | backend: `tutortrack/courses/tests/test_courses.py::test_capacity_is_limited_by_the_service_and_the_room` | |
| TP-E20-012 | Class status changes | Admin | Draft class | 1. Click **Open for enrolment**.<br>2. Fill all places.<br>3. Withdraw one student. | Draft → Open → Full → Open; staff are alerted when it becomes full. | P1 | backend: `tutortrack/courses/tests/test_courses.py::test_capacity_is_enforced_and_the_class_fills` | |
| TP-E20-013 | Teacher pay options | Admin | Class | 1. Set teacher pay: fixed £40 per session; then headcount tiers; then a fixed total £400 split over sessions; add an assistant at £15 per session. | Lesson tutors' pay overrides follow each option; the fixed total splits exactly across sessions (pennies add up). | P2 | backend: `tutortrack/courses/tests/test_courses.py::test_teacher_pay_by_session_headcount_and_fixed_total`, `tutortrack/courses/tests/test_pricing.py::test_a_fixed_class_fee_for_teachers_splits_exactly` | |
| TP-E20-014 | Class lifecycle to completed | Coordinator | Class with sessions | 1. Complete the first session's register.<br>2. Complete the last session. | Status Running after the first; Completed (with enrolments completed) after the last. | P3 | No | |
| TP-E20-015 | Cancel a class | Admin | Class with enrolments and paid fees | 1. Click **Cancel class**. | Everyone withdrawn with unused sessions credited; future sessions cancelled; status Cancelled. | P2 | backend: `tutortrack/courses/tests/test_courses.py::test_cancelling_a_class_withdraws_everyone_and_cancels_sessions` | |

## Enrolment and billing (FR-20-4, FR-20-7, T03, T04)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E20-016 | Staff enrol a student | Coordinator | Riya Patel (Year 6); class "Saturday 10am" | 1. Open the class → **Enrol a student**, choose Riya.<br>2. Read the live quote, **Enrol**. | Quote shows "Fee: £180.00" (or "Joining late: N of M" with the prorated amount). Riya is **Enrolled**; places taken goes up by one; an invoice (fees at enrolment) or dated charge is created. | P1 | backend: `tutortrack/courses/tests/test_courses.py::test_staff_set_up_a_term_course_and_class_and_enrol_through_the_api`; e2e: `e2e/courses.spec.ts` | |
| TP-E20-017 | Mid-term join attends future sessions only and is prorated | Coordinator | Class started two weeks ago | 1. Enrol Theo Okafor today.<br>2. Open the sessions and the invoice. | Theo is an attendee on future sessions only, not past ones; the fee is prorated by remaining sessions (or teaching weeks per setting). (AC FR-20-3) | P1 | backend: `tutortrack/courses/tests/test_courses.py::test_a_mid_term_join_attends_future_sessions_only_and_is_prorated` | |
| TP-E20-018 | Eligibility by year group and age | Coordinator | Maya Patel (Year 7) | 1. Enrol Maya in "Saturday 10am".<br>2. Repeat with the skip-eligibility option. | 1: refused (year group/age). 2: allowed for staff. | P1 | backend: `tutortrack/courses/tests/test_courses.py::test_eligibility_by_age_and_year_group` | |
| TP-E20-019 | Capacity is enforced | Coordinator | Full class | 1. Enrol another student.<br>2. Tick **Enrol even though the class is full**. | 1: refused, offers **Add to the waitlist**. 2: allowed (override). | P1 | backend: `tutortrack/courses/tests/test_courses.py::test_capacity_is_enforced_and_the_class_fills` | |
| TP-E20-020 | Last place can't be taken twice | Coordinator ×2 | Class with one place left | 1. In two browsers enrol two different students at the same moment. | One succeeds; the other is told the class is full. | P2 | backend: `tutortrack/courses/tests/test_courses.py::test_capacity_is_enforced_and_the_class_fills` | |
| TP-E20-021 | Trial enrolment | Coordinator | Class | 1. Enrol with **Trial (no fee until converted)**.<br>2. Convert to enrolled. | No fee while trial; billed from conversion. | P2 | backend: `tutortrack/courses/tests/test_courses.py::test_trials_are_free_until_converted` | |
| TP-E20-022 | Registration fee once a year, materials each class | Finance | Course with registration and materials fees | 1. Enrol Riya in two classes of courses with fees in the same academic year. | One registration fee for Riya this year; a materials fee per enrolment. | P2 | backend: `tutortrack/courses/tests/test_courses.py::test_registration_fee_once_a_year_and_materials_each_class` | |
| TP-E20-023 | Sibling and multi-class discounts | Admin | Discounts: sibling 10% and multi-class (min 2 classes) 5% in **Catalogue** | 1. Enrol Riya, then her sibling, then Riya in a second class. | Second child gets the sibling discount (order of first enrolment this term); Riya's second class gets the multi-class discount; stacking follows E06 rules; never below zero. | P2 | backend: `tutortrack/courses/tests/test_courses.py::test_sibling_and_multi_class_discounts`, `tutortrack/courses/tests/test_pricing.py::test_discounts_never_go_below_zero_or_above_the_list_price` | |
| TP-E20-024 | Pay-as-you-go course | Finance | Course **Per session**; service priced per lesson | 1. Enrol a student; complete two sessions. | Each delivered session is charged at the per-session price; nothing up front. | P2 | backend: `tutortrack/courses/tests/test_courses.py::test_pay_as_you_go_charges_each_delivered_session` | |
| TP-E20-025 | Monthly course uses a billing plan | Finance | Course **Per month** | 1. Enrol mid-month. | An E10 monthly plan from the start date to the class end; the part month is prorated. | P2 | backend: `tutortrack/courses/tests/test_courses.py::test_monthly_courses_use_a_billing_plan` | |
| TP-E20-026 | Instalments add up exactly | Finance | Course in 3 instalments, £100.00 | 1. Enrol. | Three monthly charges totalling exactly £100.00 (e.g. £33.34 + £33.33 + £33.33); the first billed now. | P2 | backend: `tutortrack/courses/tests/test_courses.py::test_instalments_add_up_to_the_fee`, `tutortrack/courses/tests/test_pricing.py::test_instalments_add_up_exactly_month_by_month` | |
| TP-E20-027 | Fees from term start wait for the invoice run | Finance | Fee timing setting = charge from term start | 1. Enrol.<br>2. Run the next invoice run (E10). | No invoice at enrolment; the charge appears in the run. | P3 | backend: `tutortrack/courses/tests/test_courses.py::test_fees_from_term_start_wait_for_the_invoice_run` | |
| TP-E20-028 | Proration by teaching weeks leaves out breaks | Finance | Setting = teaching weeks | 1. Enrol in the week before half term. | Prorated by remaining teaching weeks; the half-term week doesn't count. | P2 | backend: `tutortrack/courses/tests/test_courses.py::test_proration_by_teaching_weeks_leaves_out_breaks` | |

## Transfers and withdrawals (T05)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E20-029 | Withdraw with credit for unused sessions | Coordinator | Riya enrolled and invoice paid; refund setting = credit | 1. On the roster click **Withdraw Riya Patel** from next week. | Riya removed from sessions from then on; a credit note for unused sessions becomes client credit; the place is freed. | P1 | backend: `tutortrack/courses/tests/test_courses.py::test_withdrawing_credits_unused_sessions_and_frees_the_place` | |
| TP-E20-030 | Withdraw with an unpaid invoice | Coordinator | Unpaid invoice | 1. Withdraw. | The unpaid invoice owes less (adjusted). | P2 | backend: `tutortrack/courses/tests/test_courses.py::test_withdrawing_credits_unused_sessions_and_frees_the_place` | |
| TP-E20-031 | No-refund setting keeps the fee | Coordinator | Refund setting = none | 1. Withdraw. | Fee unchanged. | P3 | backend: `tutortrack/courses/tests/test_courses.py::test_no_refund_setting_keeps_the_fee` | |
| TP-E20-032 | Withdraw from a monthly course ends its plan | Coordinator | Monthly enrolment | 1. Withdraw. | The billing plan ends the day before. | P3 | backend: `tutortrack/courses/tests/test_courses.py::test_withdrawing_from_a_monthly_course_ends_its_plan` | |
| TP-E20-033 | Transfer to another class | Coordinator | Two classes of the same course | 1. **Transfer**, **Move to** the other class, **Move**. | Enrolled in the new class (prorated, no repeat one-off fees); the old fee's unused share is credited; status Transferred on the old enrolment. | P1 | backend: `tutortrack/courses/tests/test_courses.py::test_transfers_move_the_student_and_settle_the_difference` | |
| TP-E20-034 | Below minimum alert | Coordinator | Class with minimum 3 and 3 enrolled | 1. Withdraw one. | Staff alert: the class is below its minimum. | P3 | No | |

## Class waitlist (FR-20-5, T06)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E20-035 | Join the waitlist when full | Coordinator | Full class | 1. **Add to the waitlist** for Theo. | Theo listed under **Waitlist** with position 1, **Waiting**. | P1 | backend: `tutortrack/courses/tests/test_courses.py::test_the_waitlist_offers_a_free_place_and_accepting_enrols`; e2e: `e2e/courses.spec.ts` | |
| TP-E20-036 | Freed place is offered and accepted | Coordinator, Family | TP-E20-035; waitlist auto-offer on | 1. Withdraw a student.<br>2. Open the offer email (`/offers/<token>`) and **Accept the place**. | Theo shows **Offered a place until <date>**, then **Accepted** and is enrolled (or held for payment). | P1 | backend: `tutortrack/courses/tests/test_courses.py::test_the_waitlist_offers_a_free_place_and_accepting_enrols` | |
| TP-E20-037 | Expired or declined offer moves on | Family | Two waiting | 1. Decline (or let expire). | Next family offered; the declined entry shows **Declined**/**Offer expired**. | P2 | No | |
| TP-E20-038 | Class waitlists don't cascade by subject | Coordinator | A subject waitlist entry (E17) and a class waitlist | 1. Free a place in the class. | Only the class waitlist is offered. | P3 | backend: `tutortrack/courses/tests/test_courses.py::test_class_waitlists_dont_cascade_by_subject` | |

## Registers and makeups (FR-20-6, T07)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E20-039 | Take a register | Tutor | Nia teaches "Saturday 10am"; a session today or past | 1. Open the session's **Register** (`/class-sessions/<id>/register`).<br>2. **Mark everyone present**, then set one student **Absent (told us)** with reason "Ill".<br>3. **Save register**. | "Register saved." The lesson is completed through E09: attendance, charges and pay follow; the absence reason is kept. | P1 | backend: `tutortrack/courses/tests/test_courses.py::test_register_marks_everyone_with_absence_reasons` | |
| TP-E20-040 | Correct a saved register | Coordinator | Saved register | 1. Change a student from Present to No-show; save. | Attendance updated via `record_attendance`; charges follow policy. | P2 | No | |
| TP-E20-041 | Book a makeup in another class | Coordinator | Two classes of the same course; a student with an absence | 1. Click **Makeup** for the absent student and choose a future session of the other class with room. | Student added to that session, not charged; a makeup credit is used or issued. | P2 | backend: `tutortrack/courses/tests/test_courses.py::test_makeups_go_to_another_class_of_the_same_course` | |
| TP-E20-042 | Tutor sees only own classes | Tutor | Nia and another teacher's class | 1. As tutor@ open **Courses** / the other class's register. | Only Nia's classes; the other register is refused. | P1 | backend: `tutortrack/courses/tests/test_courses.py::test_tutors_see_and_mark_only_their_own_classes` | |

## Term rollover (FR-20-4, T08)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E20-043 | Start re-enrolment (families confirm) | Admin | Spring term with a "Saturday 10am" class (or `next_class` set); enrolments this term | 1. **Courses → Next term**.<br>2. **From term** This term, **To term** Spring, deadline in 7 days, mode **Families confirm to keep their place**.<br>3. **Start re-enrolment**. | Rollover **Waiting for families**; each family gets `term_rollover_invite` with `/re-enrol/<token>`. | P1 | backend: `tutortrack/courses/tests/test_courses.py::test_rollover_enrols_confirmed_students_and_releases_the_rest` | |
| TP-E20-044 | Family answers by email link | Family | TP-E20-043 | 1. Open the link: "<student>'s place next term", deadline shown.<br>2. Click **Keep the place**. | Answer recorded (**Keeping the place**). | P1 | backend: `tutortrack/courses/tests/test_courses.py::test_families_answer_from_the_email_link_and_the_portal` | |
| TP-E20-045 | Family answers in the portal | Parent | parent@ (Patel) | 1. Portal **Classes → Next term**, **Not continuing**. | Recorded as **Not continuing**. | P1 | backend: `tutortrack/courses/tests/test_courses.py::test_families_answer_from_the_email_link_and_the_portal` | |
| TP-E20-046 | Reminder and finish at deadline | Admin | Temporal worker; `TermRolloverWorkflow` | 1. Follow the workflow in the Temporal UI, or click **Finish now**. | Halfway reminder to families who haven't answered. At finish: confirmed students enrolled and billed; others released to waitlists. Status **Finished**. | P1 | backend: `tutortrack/courses/tests/test_workflows.py::test_rollover_reminds_and_finishes_at_the_deadline`, `::test_staff_can_finish_a_rollover_early` | |
| TP-E20-047 | Opt-out mode | Admin | Mode **Places roll over unless families opt out** | 1. Start; one family declines; finish. | Everyone who didn't decline is enrolled. | P2 | backend: `tutortrack/courses/tests/test_courses.py::test_opt_out_rollover_keeps_everyone_who_didnt_decline` | |
| TP-E20-048 | Finishes early when all have answered | Admin | Every family answers | 1. Watch the rollover. | It finishes without waiting for the deadline. | P3 | backend: `tutortrack/courses/tests/test_workflows.py::test_rollover_finishes_once_every_family_has_answered` | |
| TP-E20-049 | Cancel and re-run | Admin | Running rollover | 1. **Cancel**, then start again. | Cancelled; a new rollover can start (new workflow id). | P3 | No | |

## Public catalogue and online enrolment (FR-20-8, T09)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E20-050 | Catalogue lists open public classes | Anonymous | Class catalogue widget created on **Website → Widgets** (or website Classes block) | 1. Open the widget preview / the widgets playground, or `GET /api/v1/public/catalogue`. | Open, public classes with "N places left"; filters for subject, age, weekday, location, course. Draft or private classes are not listed. | P1 | backend: `tutortrack/courses/tests/test_courses.py::test_public_catalogue_shows_open_public_classes_with_places` | |
| TP-E20-051 | Online enrolment holds the place until paid | Anonymous | Online payment setting = full; fake Stripe | 1. In the catalogue, enrol a new family "Zara Ahmed" with child "Isla", Year 6.<br>2. Pay on the fake Stripe page. | Place held (**Waiting for payment**) for the hold minutes; after payment the enrolment is confirmed, sessions and fees added, the payment settles the invoice. Confirmation email `class_enrolment_confirmed`. | P1 | backend: `tutortrack/courses/tests/test_courses.py::test_online_enrolment_holds_the_place_until_paid`, `tutortrack/courses/tests/test_workflows.py::test_a_paid_place_becomes_an_enrolment` | |
| TP-E20-052 | Unpaid place is released | Anonymous | Hold set to a few minutes | 1. Start an online enrolment and don't pay. | At the hold timeout the place is released to the waitlist (`EnrolmentPaymentWorkflow`). | P2 | backend: `tutortrack/courses/tests/test_workflows.py::test_an_unpaid_place_is_released_when_the_hold_runs_out` | |
| TP-E20-053 | Eligibility checked before creating a family | Anonymous | Year 6 class | 1. Try to enrol a Year 9 child online. | Refused; no client or student is created. | P2 | backend: `tutortrack/courses/tests/test_courses.py::test_online_enrolment_checks_eligibility_before_creating_a_family` | |
| TP-E20-054 | Full class takes waitlist sign-ups | Anonymous | Full public class | 1. Sign up online. | Added to the waitlist, not enrolled. | P2 | backend: `tutortrack/courses/tests/test_courses.py::test_a_full_class_takes_website_waitlist_signups` | |
| TP-E20-055 | Portal enrolment | Parent | parent@; Riya in the Patel family | 1. Portal **Classes → Classes you can join**.<br>2. **Enrol Riya**, tick **I accept the terms**.<br>3. **Pay to confirm** if payment is required. | "Riya is enrolled." (or "The place is held until <date>"); the class shows under **Your classes**. **Give up this place** releases a held place. | P1 | backend: `tutortrack/courses/tests/test_courses.py::test_portal_families_enrol_their_children` | |
| TP-E20-056 | Portal waitlist position | Parent | Child on a class waitlist | 1. Portal **Classes**. | "Number N in the queue"; when offered: "A place is offered: check your email to accept it." | P2 | No | |

## Permissions

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E20-057 | Finance views courses read-only | Finance | finance@ | 1. Open **Courses**; try **New class**. | Can view (`courses.view`); create/enrol actions hidden or refused. | P2 | No | |
| TP-E20-058 | Coordinator manages classes and enrolments | Coordinator | coordinator@ | 1. Create a class, enrol, run a register, start a rollover. | All allowed (`courses.*`). | P1 | No | |
| TP-E20-059 | Student can't enrol | Student | student@ (Arjun) | 1. Portal: look for enrol actions. | No enrol (needs `portal.client.enrol`). | P2 | No | |

## Tenant isolation

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E20-060 | Catalogue and classes per organisation | Anonymous, Owner (Northside) | owner@northside.localhost | 1. `GET http://northside.localhost:8010/api/v1/public/catalogue`.<br>2. In Northside open `/classes/<brightminds class id>`. | No brightminds classes; detail 404. Re-enrol tokens of brightminds don't open on northside. | P1 | backend: `tutortrack/courses/tests/test_courses.py::TestClassIsolation`, `::TestEnrolmentIsolation`, `::TestSessionIsolation`, `::TestRolloverIsolation` | |

## i18n, time zones and currency

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E20-061 | Sessions keep local time across the clock change | Coordinator | Class running over the last Sunday of October | 1. Check sessions before and after the change. | Always 10:00 UK local time (UTC offset changes). | P1 | No | |
| TP-E20-062 | Money and plurals | Parent | Portal catalogue | 1. Check "1 place left" vs "2 places left", prices, "Ages 9 to 11". | Correct plurals and £ formatting. | P3 | No | |

## Errors and edge cases

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E20-063 | Payment arrives after the hold timed out | Anonymous | Pay just after the timeout | 1. Pay late. | The workflow finds the payment and confirms the place instead of releasing it (or the payment becomes credit if the place has gone). | P2 | backend: `tutortrack/courses/tests/test_workflows.py::test_confirming_is_retried_after_a_failure` | |
| TP-E20-064 | Invalid re-enrol link | Anonymous | Tampered token | 1. Open `/re-enrol/<bad>`. | "We couldn't find this re-enrolment link." | P3 | No | |
