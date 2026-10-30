# Release test run: 2026-10-28

| | |
|---|---|
| Date | 2026-10-28 |
| Tester | Claude Code, running scripted browser (Playwright, Chromium 1248 headless) and API checks, for MB |
| Commit | `7794f818` (main) |
| Environment | Host stack from `CLAUDE.md` on a separate, freshly seeded `tutortrack_release` database (own Redis databases, S3 bucket and Temporal namespace `tutortrack-release`); Django on :8010, Celery worker and beat, Temporal worker on every queue, admin and portal dev servers; a built portal (`vite build` + `vite preview` on :5176) for the service-worker cases; widgets playground on :5175. Fake providers throughout. |
| Scope | Every P1 case marked **Automated? = No** (56 cases) and the ten P1 journeys (J01–J06, J08, J10, J12, J17). The 887 automated P1 cases are covered by main CI run 40711612517 on the same commit (backend tests, frontend, e2e: all passed). |

## Result: release blocked

| | Pass | Pass with note | Fail | Partial | Blocked |
|---|---|---|---|---|---|
| Per-epic P1 cases (56) | 41 | 9 | 4 | 1 | 1 |
| P1 journeys (10) | 1 | 6 (two run in part) | 3 | | |

A P1 failure blocks the release (see the plan README). Seven P1 failures, four in per-epic cases and three found in journeys:

| # | Case | What fails | Where |
|---|---|---|---|
| 1 | TP-E02-012 (J01 step 2) | The setup wizard's **first service** and **first family and student** are never created. Only identity subscribes to `onboarding.step_completed` (tutor invitations); catalogue and people never consume the answers. The cited test checks only that the event is published. | `backend/tutortrack/tenancy/onboarding.py`; no handlers in catalogue/people |
| 2 | TP-E18-020 (J12 steps 4–5) | **A recruited tutor becomes active the moment they accept the invitation**, before the onboarding checklist or any compliance check, so they can be assigned while unvetted. `link_membership` (on `user.joined`) moves an ONBOARDING tutor to ACTIVE. Later compliance evaluation restricts them, and verifying documents re-activates them with mandatory checklist items still open. | `backend/tutortrack/people/services.py` `link_membership` |
| 3 | TP-E29-031 (J06 step 5) | After erasing a student the **job title keeps their real name** ("JOB-000004 GCSE Higher Maths – Eddie Test") and global search finds it. Lessons and invoice lines are anonymised. | erasure providers (jobs) |
| 4 | TP-E08-025 | Rescheduling works by keyboard, but the "Lesson moved" email has **no updated ICS** (the E08 spec says it does; nothing builds one). The email also prints "16:30:00 Greenwich Mean Time". | `backend/tutortrack/comms/defaults.py` (lesson_changed) |
| 5 | TP-E20-008 | **A course can't be created on a service that allows fewer than 10 students** from the admin app: the New course form has no class-size field and the model default is 10, so it's refused with "11+ group class takes at most 8 students; raise it in the catalogue first." | `frontend/apps/admin/src/courses/CoursesPages.tsx`, `backend/tutortrack/courses/models.py` (`default_capacity=10`) |
| 6 | TP-E24-003 | **The brand font isn't applied in the portal**: `applyBrandTheme` sets `font-family` on `<html>`, the body keeps "Source Sans 3". Colours are applied and meet AA. | `frontend/packages/ui/src/brandTheme.ts` |
| 7 | TP-E30-029 | Help panel: Escape closes it but **focus goes to the page body, not back to Help** (WCAG 2.4.3). Opened before the page has finished loading, Escape doesn't close it at all (reproduced three times). | `frontend/apps/admin/src/success/HelpPanel.tsx` |

### Follow-up: fixes (2026-10-30)

All seven are fixed on branch `fix/release-p1s`, each with a regression test. Re-run these cases (and J01, J06, J12) before release:

| # | Case | Fix | Regression test |
|---|---|---|---|
| 1 | TP-E02-012 | Catalogue and people handle the wizard's service and student steps. | `tenancy/tests/test_onboarding.py::test_service_and_student_steps_create_the_records` |
| 2 | TP-E18-020 | Joining leaves a tutor with an unfinished checklist in onboarding. | `recruitment/tests/test_recruitment.py::test_a_recruited_tutor_stays_onboarding_after_accepting_the_invitation` |
| 3 | TP-E29-031 | New jobs privacy provider scrubs job names and notes. | `privacy/tests/test_erasure.py::test_erasing_a_student_scrubs_their_name_from_job_names_and_search` |
| 4 | TP-E08-025 | Booked, moved and cancelled emails attach `lesson.ics`. | `comms/tests/test_comms.py::test_the_lesson_moved_email_carries_the_updated_ics` |
| 5 | TP-E20-008 | *Usual class size* on New course; default capped at the service's limit. | `courses/tests/test_courses.py::test_a_new_course_fits_a_small_group_service_by_default`, `Courses.test.tsx` |
| 6 | TP-E24-003 | Brand font set through `--font-sans`. | `packages/ui/src/brandTheme.test.ts` |
| 7 | TP-E30-029 | Help closes natively and refocuses *Help*; no welcome tour over the open panel. | `success/Success.test.tsx` |

The "16:30:00 Greenwich Mean Time" wording in lesson emails (note on TP-E08-025) is unchanged; it affects every email using `datetime("full")`.

## Other findings (not blocking)

**P2: should be fixed with an agreed date**

- **Wizard-invited tutors have no tutor profile** (J01 step 4). A tutor invited from the setup wizard (or Team) gets a tutor login but no tutor record, so the portal refuses them and they aren't under Tutors until staff add a tutor with the same email (which then links).
- **Migration steps validate dependent batches before their parents are imported** (J08). In a TutorCruncher migration, students fail "No client with this id; import clients first." and lessons fail likewise, until each batch is re-checked by re-saving its mapping (submitting again gives 409 "already submitted").
- **Public proposal shows quantity 10 as "1E+1"** (J02): Decimal formatting on a customer-facing page.
- **Cookie banner hides the focused button** on the public reference page (TP-E18-012): "Send reference" sits under the banner when focused (WCAG 2.4.11).
- **Compliance restriction can't be overridden in the app** (TP-E18-028): the override exists only as `?compliance_override=` on the API.
- **The admin calendar ignores the account time zone setting** (TP-E08-067): it follows the device's time zone.
- **Nia has no compliance records in the seed**, so the first compliance sweep (nightly) restricts her and demo flows that assign her fail with `tutor_not_compliant`.
- **Two "Thanks for getting in touch" emails** when the New enquiry template is switched on (TP-E14-025): the template repeats the leads module's own acknowledgement.

**P3: when convenient**

- Help and command bar: with nothing focused, Ctrl+J then Escape leaves focus on the hidden input (TP-E31-026).
- The portal Home "Next lesson" only looks 7 days ahead, then says "No lessons coming up." even when a lesson is 8 days away.
- Other-organisation portal message reads "This area is for families and students." for a parent or tutor of another organisation (TP-E15-044, TP-E16-044): not a clear "no access here".
- No staff notification when a tutor accepts an offer that needs no confirmation; Accept has no message field (TP-E16-020).
- Workflow wait step refuses 1 minute ("between an hour and a year") but accepts `hours: 0.02`.
- Group-class calendar events are titled "11+ group class –" (trailing dash) (TP-E22-056).
- Applicant subjects ("Maths GCSE") are stored as a subject with no level after approval (J12).
- Staff can enrol into a draft class, but transferring into it is refused (J05).
- Application page shows "I have read the privacy notice: true" (raw boolean).
- The seeded Christmas closure doesn't cancel lessons (no `cancel_lessons`), so Arjun's 29 Dec lesson stays planned; it ends at the start of 2 Jan.
- In the dev server only, the portal favicon URL is doubled (`/portal/portal/icons/…`); the production build is correct.

## Test plan corrections made in this change

- TP-E12-039: a tutor's `GET /api/v1/pay-runs` returns an empty list (200), not 403; a run's detail is 404.
- TP-E31-026: the dialog is named "Ask AI", not "Command bar".
- TP-E29-040: the retention period can't go below 30 days; the precondition now says so.

## Harness notes

- Native date inputs in headless Chromium use mm/dd/yyyy whatever the locale; one keyboard test first typed the date in UK order and moved a lesson to 11 May (put back).
- Playwright's offline mode doesn't take a service worker offline, so queued changes sync at once (TP-E16-045).
- No clock change falls inside the calendar-push window (1 day back, 120 days ahead) on 2026-10-28 (TP-E22-056); repeat after 28 Nov 2026.

## Per-epic results

| Case | Result | Notes |
|---|---|---|
| TP-E05-015 | Pass | Active; Maths · GCSE with Approve (coordinator can approve, so "Awaiting approval" shows only for those who can't); Teaches Online, In person; Activity tabs; no pay card. No headline seeded. |
| TP-E07-033 | Pass | 400 "object does not exist"; nothing assigned. |
| TP-E08-025 | **Fail** | Keyboard only: focus lesson → Enter → Tab to Reschedule → Date/From/To/Reason → Enter. Lesson moved, rescheduled_from and reason recorded, Priya and Nia emailed "Lesson moved". **No updated ICS attached** (E08 spec: "including updated ICS"; never built, no code or test). Also the email shows "16:30:00 Greenwich Mean Time" (seconds, long zone name). |
| TP-E08-065 | Pass | Brightminds week of 2 Nov shows only Arjun and the 11+ class, not Northside's 3 Nov lesson; API 404. |
| TP-E08-067 | Pass with note | With the device in Australia/Sydney: "4 Nov 2026, 03:30" and quick view "(3 Nov 2026, 16:30 Europe/London)". The admin calendar follows the device time zone, not the account time zone setting (setting the account to Sydney with a London device still shows London times). |
| TP-E10-018 | Pass | Email to client: Mailpit "Invoice INV-000001 from Bright Minds Tutoring" to priya.patel@ with INV-000001.pdf and /pay/<token> link. |
| TP-E10-074 | Pass | /billing redirects a tutor to /portal/tutor, no Billing nav; GET /api/v1/invoices 403. |
| TP-E11-047 | Pass | Tutor 403; parent portal Payments shows only The Patel Family. |
| TP-E12-037 | Pass | Finance: New pay run → PR-000001 Ready for review (Nia's 27 Oct lesson) → Approve → Approved; bank file and Mark all paid offered. Tutor: list empty, detail 404. |
| TP-E12-039 | Pass with note | GET /api/v1/pay-runs returns 200 with an empty list (own scope; PayRun has no own rows), not 403. No data exposed. Plan expectation corrected. |
| TP-E14-025 | Pass with note | "New enquiry" template installed and switched on; public enquiry → "Thanks for getting in touch" to the enquirer and task "Call The Release Family about their enquiry" due in 1 hour. The family also gets the leads module's own "Thanks for getting in touch" (two near-identical emails); the task is unassigned when the enquiry has no owner. |
| TP-E15-002 | Pass | "Check your email: we sent a sign-in link to parent@tutortrack.localhost."; "Your sign-in link" email; link signs in to /portal/ (Home, "Next lesson"). |
| TP-E15-034 | Pass | Booking on, GCSE Maths 1:1 bookable: Nia, 9 Nov 15:00 → "We're holding this time for you until 28 Oct 2026, 17:44." → "You're booked. We've added it to your schedule." |
| TP-E15-044 | Pass with note | parent@ on northside: no household or Bright Minds data; portal/me 403. Message "This area is for families and students." with "Go to the main app": not a clear "no access here" for a parent. |
| TP-E15-045 | Pass | Olivia Northside invited and signed in: own lesson only; Bright Minds lesson ICS/cancel/absence and Patel statement 404. |
| TP-E15-048 | Pass | 375 px: no horizontal scroll on 14 portal pages; bottom "Portal menu" (Home, Lessons, Payments, Messages, More) works. Only sub-24 px targets are inline text links and native checkboxes with labels. |
| TP-E16-013 | Pass | Saturday 09:00–12:00 saved ("Saved."); admin availability shows weekday 5 09:00–12:00; booking slots use it (around the Saturday class with the 15-minute buffer). |
| TP-E16-020 | Pass with note | E19 offer batch to Nia → portal "Waiting for your answer · answer by …" → Accept → "You accepted"; job assigns Nia; family gets "Meet your tutor". No staff notification (only sent when an admin must confirm) and Accept has no message field. |
| TP-E16-030 | Pass | Built portal with service worker: 10–12 API responses cached; after Sign out the outbox is empty, localStorage cleared and tt-api holds only public branding. |
| TP-E16-044 | Pass with note | tutor@ on northside /portal/tutor: no Bright Minds data; same generic "This area is for families and students." message. |
| TP-E16-045 | Partial | Offline banner is a polite live region (role=status), state in text ("You're offline. …"), dark text on a light tint (AA). The register completed offline was queued and synced by the service worker straight away (Playwright's offline mode doesn't take the service worker offline), so the "N changes waiting" text and **Sync now** button were never on screen. Check on a real phone. |
| TP-E17-020 | Pass | Tab reached select "Move Dee Release to"; chose Trial booked; card moved (Trial booked 1). |
| TP-E17-061 | Pass | Northside /f/website-enquiry: "This form isn't available"; public GET/POST on northside host 404; brightminds enquiries unchanged. |
| TP-E18-012 | Pass | Referee ticked concern; application References panel shows "Concerns raised" in red. Finding: cookie banner hides the focused "Send reference" button (WCAG 2.4.11). |
| TP-E18-028 | Pass with note | Admin assign with ?compliance_override=Supervised session: 201, audit "Compliance overridden" reason recorded. No override control exists in the admin app (API only), so no role gets a UI option. |
| TP-E18-035 | Pass | Verified / To check / Rejected / Missing / Expired with dates, text plus colour; Restricted flagged under the name. |
| TP-E18-048 | Pass | Coordinator with ?compliance_override: 403. |
| TP-E18-049 | Pass | Northside /vacancies: "There are no vacancies"; slug: "This vacancy isn't available". |
| TP-E18-050 | Pass | Northside Recruitment and Compliance show only Northside data; brightminds application id on northside host 404. |
| TP-E19-042 | Pass | Coordinator: Find a tutor, Send offers, Post to the job board, Send to the family, Cover requests; no "Include restricted and unapproved tutors" (owner has it); matching settings PUT/PATCH 403. |
| TP-E19-043 | Pass | Tutor /matching redirects to the portal; portal Jobs shows only offers sent to Nia. |
| TP-E20-001 | Pass | Courses → Terms: "This term", 2026/27, 14 Oct 2026 – 5 Jan 2027, "Half term (25 Nov 2026 – 1 Dec 2026)". |
| TP-E20-008 | **Fail** | New course "GCSE Maths Booster" on 11+ group class, Per term £150.00, fee £20.00: refused "11+ group class takes at most 8 students; raise it in the catalogue first." The form has no class-size field and the model default is 10 (courses/models.py default_capacity=10), so no course can be created on a service with max_students < 10 from the admin app. |
| TP-E20-058 | Pass | As coordinator (API): class created 201, enrolment 201, register 200, rollover to a new "Spring term" 201. |
| TP-E20-061 | Pass | Saturday 10am class: 24 Oct 10:00 BST (09:00Z), 31 Oct 10:00 GMT (10:00Z). |
| TP-E21-050 | Pass | Added a goal and homework for Maya: student (Arjun) sees neither; parent sees both. |
| TP-E22-054 | Pass with note | Built-in video provider: portal lesson has meeting_url and a per-student join_url, no host/start link fields. (Built-in has no separate host link; a provider with host links wasn't the org default.) |
| TP-E22-056 | Blocked | Calendar push covers 1 day back to 120 days ahead, so no clock change is in the window on 2026-10-28 (next: 28 Mar 2027, in the window from 28 Nov 2026). Pushed GMT events carry the right instants (Arjun 16:30Z, class 10:00Z). Also: group-class events are titled "11+ group class –" (trailing dash). |
| TP-E24-003 | **Fail** | Brand colour applied (Pay button #1d4fd7 on white text, AA) and Inter font CSS loaded, but **the brand font isn't used**: applyBrandTheme sets font-family on <html>, the body keeps "Source Sans 3". Logo and favicon not seeded, so not checked. |
| TP-E24-033 | Pass | Keyboard walk: directory search, Subject, Lessons, Search, View profile, login link, enquiry First name (Required), Last name, Email (Required), Anything else?, Send; all named, 2 px focus outline. Empty submit: role=alert "Please check the highlighted answers.", aria-invalid with aria-describedby on each field. |
| TP-E25-068 | Pass | Coordinator: Reviews (Approve, Reply, Hide), Review requests (Send request), Referrals (Save programme); Affiliates and Statements read-only (no Add or Issue). No tutor referrals seeded, so their actions weren't exercised. |
| TP-E25-069 | Pass | Finance: Affiliates (Add affiliate, Add link, Add rule), Statements (Issue); Referrals read-only; no Reviews tab. |
| TP-E26-018 | Pass | "Open the Lessons delivered report" → /analytics/lessons?period=this_month, Period "This month". One branch only and no branch filter on Home, so branch carry-over not exercised. |
| TP-E27-008 | Pass | Same Idempotency-Key twice with an API key: both 201, same payment id, one payment. |
| TP-E27-056 | Pass | Completed two brightminds lessons: brightminds endpoint got lesson.completed; Northside endpoint got nothing. |
| TP-E28-022 | Pass | CSV import of two tutors: created (active), no emails to either. |
| TP-E28-053 | Pass | Full export ZIP (121 files): no "Northside"/Northside tutor; Patel in 13 files. |
| TP-E29-029 | Pass | Concern about Arjun raised; Arjun's access export compiled: no safeguarding section or text. |
| TP-E30-016 | Pass | Operations: Events waiting, Outbox lag (s), Dead letters, Payment and Billing webhooks waiting, queue depths. |
| TP-E30-029 | **Fail** | Help opens as dialog "Help" with focus inside (Close) and tabs Articles, What's new, Tours, Chat with support, Usage data. Escape closes it but **focus goes to the page body, not back to Help** (WCAG 2.4.3). Also, opened before the page finished loading, Escape didn't close it (reproduced 3 times). |
| TP-E30-058 | Pass | Brightminds audit (148 rows) has none of Northside's actions; Northside's audit has them. |
| TP-E31-026 | Pass with note | Ctrl+J opens the modal, focus in "What would you like to do?", Escape closes; opened from the button, focus returns to it. The dialog is named "Ask AI", not "Command bar" (plan wording outdated). Opened with Ctrl+J from nothing focused, focus stays on the hidden input after Escape. |
| TP-E31-044 | Pass | Northside "Move Arjun's Tuesday lesson to 5pm": "I couldn't find that student."; same in brightminds finds Arjun. (Needed command_bar turned on for Northside.) |
| TP-E32-001 | Pass | "Temporal workers polling: default, billing, payroll, comms, integrations, imports, privacy"; every queue shows pollers. |
| TP-E32-064 | Pass | Northside GET brightminds process id: 404; list only Northside's. |
| TP-E32-065 | Pass | Northside export workflow (tenant-export:<northside id>:…) wrote only Northside data (12 files mention Northside, none Bright Minds); Bright Minds exports unchanged. |

## Journey results

| Journey | Result | Notes |
|---|---|---|
| J01 | **Fail (step 2)** | New org "Riverside Tutors": signup, email verify, Agency 30-day trial, wizard steps all 200, tutor invitation sent. **TP-E02-012 fails: no service and no family/student are created from the wizard answers** (only identity subscribes to onboarding.step_completed; catalogue and people never consume it; the cited test only checks the event). Step 4: a wizard-invited tutor gets a tutor login with no tutor profile, so they can't use the portal or set availability until staff add a tutor record with the same email (then it links). Steps 3, 5–10 pass: service £40/£25 per hour, weekly Tuesday job (26 lessons), parent invite + magic link, tutor completes lesson and submits report (one charge), invoice INV-000001 issued and emailed with PDF and pay link, fake PayPal connected, parent pays (invoice Paid, balance £0.00, portal shows it), pay run PR-000001 approved and paid, tutor Earnings shows the £25 payout. Audit has the changes. |
| J02 | Pass with notes | Public enquiry (Jo Journey, student Kit) → family and enquiry created, acknowledgement sent (twice: the leads email plus the New enquiry template switched on in TP-E14-025). Pipeline "Move to" by keyboard (TP-E17-020). Trial booked, outcome continuing. Proposal PRO-000002 sent; public page has no internal fields; **quantity 10 shows as "1E+1"** on the public proposal. Accepted with Nia → enquiry Won, job created; deposit £45 paid (Stripe webhook on the payment request) → credit. Nia accepted the offer → job Active. One "Journey" client only; enquiry funnel counts it. (Proposal schedule is free text, so no weekly lessons were created.) |
| J03 | Pass with notes | Nia completed Arjun's lessons and submitted reports (parent sees "Notes for parent", not private notes). Lesson feedback request switched on: sends only on the first and every Nth lesson (by design); with every 1: "How was Arjun's lesson?" → 1 star → "Low lesson rating: 1/5 for Arjun" to coordinator and owner; the link is 404 on the Northside host. Finance invoice run Oct: 4 charges £146.25 (rounded lines) → INV-000003 issued; re-running the period creates nothing. Stripe connected (fake); payment_intent.succeeded paid INV-000003, replay recorded once. £100 bank transfer: £32.66 to INV-000001, £67.34 credit shown in the portal. Payment chasing runs for paid invoices stopped. Also: the workflow editor refuses a 1-minute wait but accepts `hours: 0.02`. |
| J04 | Pass (partial) | Riverside: Tom's expense (receipt uploaded) approved as rebillable; PR-000002 (£12 expense) approved and marked paid (no bank file: tutor is paid by "manual", so "No bank transfers are waiting"). Fake Xero connected (organisation level), accounts and tax codes mapped, sync on with backfill: contacts, INV-000001 £40 PAID, payment £40 to Stripe Clearing, bills RA-000001 £25 and RA-000002 £12 PAID with bill payments; amounts match to the penny; 0 errors. Payment recorded in the ledger for INV-000002 → read-back imported 1, invoice Paid; ledger still has one payment (not pushed back). Not run: dual approval threshold, lock date, archived account error (backend tests cover them). |
| J05 | Pass (partial) | Seeded year/term and half term (TP-E20-001); new term "Spring term" added. Year 6 student Pip added to the Patel family; Arjun (Year 10) refused `not_eligible` "This class is for Year 5, Year 6."; Pip enrolled in Saturday 10am, prorated £144 for 8 of 10 sessions (INV-000005). Sessions skip half term (28 Nov) and keep 10:00 local across the clock change. Coordinator created a class, enrolled, ran a register and started a rollover (TP-E20-058). Transfer to Tuesday 5pm (after opening the class): new invoice £126 and credit note CN-000001 £126 for the old class. Withdrawal with refund as credit: family balance £144 → £36. Rollover with no next-term classes mapped finished at once with 0 offers. Not run: public catalogue enrolment with payment and release of an unpaid place, waitlist offer, families answering re-enrolment. Note: staff could enrol into a *draft* class (TP-E20-058) but transferring into it is refused "This class isn't taking enrolments." |
| J06 | **Fail (step 5)** | Tutor raised an immediate-risk concern from the lesson (SG-00002, "URGENT …" to the DSL); a student Nia doesn't teach 404. Case: admin/manager/coordinator 403, owner (DSL) 200, Northside 404; custom role "Coordinator + DSL" (safeguarding.dsl) gives the coordinator access, removing it takes it away; audit entries for the case are visible only to the DSL. Tutor message "Call me on 07700 900123" refused 422 and flagged (contact_details, blocked). Priya's access request: redaction saved, export approved, "Your data is ready (DSAR-00002)" emailed; no safeguarding section. Portal erasure request by Erin for Eddie (channel portal), another family's child 404; approved → Completed; student "Erased Student #1", DOB gone, invoice line "GCSE Higher Maths – Erased Student #1" amount kept. **The job title still reads "JOB-000004 GCSE Higher Maths – Eddie Test" and search for "Eddie" finds it (TP-E29-031).** Legal hold on Grace Hughes: erasure approval refused `legal_hold`. Retention: minimum period is 30 days (plan says 1 day); with 30 days and a student archived 40 days ago, dry run due 1, purge done 1 → "Erased Student #2". |
| J08 | Pass with note | New org "Moveover": TutorCruncher migration (fake, any key) steps people → services → jobs → balances → growth → payment methods → invite users → reminders. Steps refuse to complete while imports are open ("Finish or cancel this step's imports"; "Finish the current step first"). **Within a step, dependent batches are validated before their parent batch is imported**: students "No client with this id; import clients first." (2 of 3) and lessons (6 invalid) until the batch is re-checked by re-saving its mapping (submit again gives 409 "already submitted"). After that: clients 2, students 3, tutors 2 (no invitations, TP-E28-022), services 1, jobs 1, lessons, invoices 2, charges, payment requests. Reconciliation ok on every line (balances £60.00 = £60.00, future lessons 4 = 4). Rolling back the invoices batch voids them (not deleted). Full export: ready; download refused without the password (400) and with a wrong one (403); ZIP of 122 files. Admin (office@) can import but full export 403. |
| J10 | Pass with notes | Riverside: Agency trial; checkout on Solo adds the card. Limits don't apply during the trial (effective plan stays Agency); after `invoice.paid` → active Solo: 4th tutor refused "Your plan allows 1. Upgrade to add more." (required_plan team); preview "amount_due_now £20.00", upgrade, tutor then allowed. `invoice.payment_failed` → past due, one "We couldn't take your TutorTrack payment" email, `sub-dunning:<org>:in_rel_1` running; replay processed once; `invoice.paid` → active, dunning completed. Platform extended Northside's trial 27 Nov → 11 Dec (Riverside untouched). Cancel (cancel_at_period_end) and reactivate. Bright Minds admin can view the plan, change-plan 403. (Paying during a trial is artificial; after the upgrade the fake Stripe subscription reported trialing again.) |
| J12 | **Fail (steps 4–5)** | Opening published, applied, stages moved, interview times offered and booked by the applicant, reference with a concern received, approved → onboarding tutor + invitation. **On accepting the invitation the tutor became active at once** (people/services.py link_membership sets ONBOARDING → ACTIVE on user.joined), before the checklist, documents or any compliance check: assignable while unvetted. Compliance evaluation then restricted her and verification re-activated her, with mandatory checklist items (documents, payout) still not done (TP-E18-020). Tutor can't verify own records (403). Subject approved (applicant text "Maths GCSE" stored as subject "Maths GCSE", level blank). DBS expiry today + sweep → restricted, assignment refused tutor_not_compliant; renewal verified → active. |
| J17 | Pass | Lists (clients, students, tutors, jobs, invoices, enquiries, reports, threads, lessons, payments, search) show nothing of the other org either way; record ids of the other org 404 both ways; parent/tutor on the other host get no access; demo API key 404 on Northside; Bright Minds widget 404 on Northside; AI command bar, exports, webhooks, audit as in the per-epic cases. |
