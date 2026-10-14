# E05 — People and CRM core: manual tests

**Scope.** Clients (households, individual learners, organisations), contacts, students and tutor profiles, plus the shared CRM features: custom fields, tags, notes, tasks, documents, the activity timeline, list filters and exports, saved views, global search (⌘K), bulk actions, duplicate detection, archive/restore, geocoding and the Phase 2b **map view**. Spec: [E05](../epics/E05-people-crm.md).

**Built differently from the spec:** CRM items reference records by `target_type` + `target_id`, and a note on a record you can't see is 404; search is trigram similarity (no full-text ranking yet); exports are CSV only (XLSX deferred); the **merge tool is not built** (duplicates are only detected); custom fields, tags, documents, saved views and bulk actions have APIs but little or no admin UI yet, so several cases use Swagger (`/api/v1/docs/`); safeguarding notes are E29; the map view is an accessible schematic SVG with a list view, not map tiles, and points are rounded to about 100 m and labelled by postcode district.

**Common preconditions.** Seeded brightminds: Patel family (Priya Patel, priya.patel@example.com; Arjun, Year 10, GCSE Maths; Maya, Year 7, English; tag **VIP**, pinned note "Prefers lessons after 4pm on weekdays.", task "Call The Patel Family about GCSE mock results"), Okafor family (Tom; Ada, Year 12, Physics A level), Grace Hughes (adult learner), tutors Nia Adeyemi (active, Maths GCSE) and Sam Clarke (Physics A level). Tags **VIP** and **Exam year** (students only). Geocoder = `FakeGeocoder` (no network). Northside's family Olivia / Noah Northside for isolation.

## Clients, contacts and quick-add

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E05-001 | Quick-add a family in one step | Coordinator | — | 1. Clients → **Add a family**.<br>2. Parent "Hannah Reid", hannah.reid@example.com, phone; Student 1 "Ella", Year 8, Maths; **Add another student** "Finn", Year 5.<br>3. **Create family**. | One client "The Reid Family" (household), primary contact Hannah (bill payer), two students; you land on the family page. | P1 | backend: `tutortrack/people/tests/test_people.py`; e2e: `e2e/people.spec.ts` | |
| TP-E05-002 | Quick-add is all or nothing | Coordinator | — | 1. Add a family with an invalid email for the parent. | "We couldn't create the family. Check the…" with the field highlighted; no client, contact or student created. | P1 | backend: `tutortrack/people/tests/test_people.py` | |
| TP-E05-003 | Adult learner | Coordinator | — | 1. Quick-add with relationship **Self** and no separate student (as Grace Hughes). | Client type Individual learner; the contact is linked to the student record. | P2 | backend: `tutortrack/people/tests/test_people.py` | |
| TP-E05-004 | Family page content | Coordinator | Patel family | 1. Open Clients → The Patel Family. | Header with name and status; Contacts (Primary, Bill payer badges, **Invite to portal**), Students (Arjun, Maya), Billing (currency GBP, payment terms, PO number, billing address), notes/tasks/timeline. | P1 | e2e: `e2e/people.spec.ts` | |
| TP-E05-005 | Add a second contact and change primary | Coordinator | Patel family | 1. Add contact "Raj Patel" (Parent) via API `POST /api/v1/clients/<id>/contacts`.<br>2. Make Raj primary. | Both contacts listed; only one primary at a time; Priya keeps her own notification preferences. | P2 | backend: `tutortrack/people/tests/test_people.py` | |
| TP-E05-006 | Client list search and filters | Coordinator | — | 1. Clients → search "Oka".<br>2. Filter status Active, then **Apply**. | Okafor family found; filters narrow the list; "Load more" pages. | P1 | backend: `tutortrack/people/tests/test_people.py` | |
| TP-E05-007 | Organisation client with PO number | Coordinator | — | 1. Create a client of type Organisation "Hillside Academy" with PO number "PO-7781" (API or form). | Saved; PO number shows on the client and is available to jobs/invoices. | P3 | No | |
| TP-E05-008 | Client tax ID is encrypted and permissioned | Finance, Coordinator | Set a tax ID on a client | 1. View the client as finance@ and as coordinator@. | Finance sees it (read logged in audit); coordinator does not. | P2 | backend: `tutortrack/people/tests/test_people.py` | |
| TP-E05-009 | Invite a contact to the portal | Coordinator | Okafor family, Tom has an email | 1. Family page → Tom → **Invite to portal**.<br>2. Open the email in Mailpit and accept. | "Invitation sent."; Tom gets the Client role and sees the Okafor household in the portal. Inviting again says they already have a login. | P1 | backend: `tutortrack/people/tests/test_people.py` | |

## Students

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E05-010 | Student page | Coordinator | Arjun Patel | 1. Students → Arjun. | Year group, school, subjects (Maths GCSE), goals, status, family link, jobs, learning tabs and activity. | P1 | e2e: `e2e/people.spec.ts` | |
| TP-E05-011 | Change student status | Coordinator | Maya Patel | 1. **Change status** → Waiting list. | Status saved with a timestamp; `student.status_changed` event (shows in the timeline); Maya appears in waitlist views. | P1 | backend: `tutortrack/people/tests/test_people.py`; e2e: `e2e/people.spec.ts` | |
| TP-E05-012 | Sensitive data is permissioned and read-logged | Owner, Tutor | Add DOB and learning needs to Arjun | 1. View Arjun as admin@ (has `people.student.view_sensitive`).<br>2. View as tutor@ (API). | Owner sees DOB and learning needs; the read is logged in the audit; tutor sees neither. Values are encrypted at rest. | P1 | backend: `tutortrack/people/tests/test_people.py` | |
| TP-E05-013 | Student subject filter | Coordinator | — | 1. `GET /api/v1/students?subject=Physics`. | Ada Okafor only. | P3 | backend: `tutortrack/people/tests/test_people.py` | |
| TP-E05-014 | Invite a student to the portal | Coordinator | Ada (17) with an email | 1. Student page → **Invite to portal** with ada@example.com. | Invitation sent; under-13s need verifiable parental consent first (E29), so the same action on a Year 5 student without consent is refused. | P2 | No | |

## Tutors

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E05-015 | Tutor list and profile | Coordinator | — | 1. Tutors → Nia Adeyemi. | Status Active, headline, subjects with Approved / Awaiting approval, teaches online/in person, activity. Pay rate hidden for coordinators. | P1 | No | |
| TP-E05-016 | Add a tutor and invite them | Owner | Unused email | 1. `POST /api/v1/tutors` with invite (or Team invite with role Tutor).<br>2. Accept the invitation. | Tutor profile created as Applicant/Onboarding; on accepting it links to the membership and becomes Active. | P1 | backend: `tutortrack/people/tests/test_people.py` | |
| TP-E05-017 | Approve a tutor subject | Owner | Sam Clarke, Physics A level unapproved | 1. Tutor page → **Approve Physics**. | Subject shows Approved, approved by you; matching (E19) can use it. | P2 | backend: `tutortrack/people/tests/test_people.py` | |
| TP-E05-018 | Change tutor status | Owner | Sam Clarke | 1. **Change status** → Restricted, then back to Active. | Saved and audited; restricted tutors are excluded from new assignments. | P2 | backend: `tutortrack/people/tests/test_people.py` | |
| TP-E05-019 | Tutor pay and tax hidden from coordinators | Coordinator, Finance | Nia with a pay rate override and a tax number | 1. View Nia as coordinator@ and finance@. | Coordinator: no pay rate, no tax info (`people.tutor.view_financial` denied). Finance/Owner: visible; tax shown masked. | P1 | backend: `tutortrack/people/tests/test_people.py` | |
| TP-E05-020 | Tutor sees only their own profile | Tutor | tutor@ | 1. `GET /api/v1/tutors`.<br>2. `GET /api/v1/tutors/<Sam's id>`. | Only Nia; Sam is 404. | P1 | backend: `tutortrack/people/tests/test_people.py` | |

## Custom fields and tags

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E05-021 | Define a custom field | Owner | Swagger | 1. `POST /api/v1/custom-fields` for `people.student`: key `exam_board`, type single select, options AQA/Edexcel/OCR, visibility staff. | Created; appears on student serialisers under `custom_fields`. Single select without options is refused. | P2 | backend: `tutortrack/crm/tests/test_crm.py` | |
| TP-E05-022 | Custom field values are validated | Coordinator | `exam_board` exists | 1. PATCH Arjun with `custom_fields: {"exam_board": "WJEC"}`. | 400 with `errors.custom_fields.exam_board`. AQA saves. | P2 | backend: `tutortrack/crm/tests/test_crm.py` | |
| TP-E05-023 | Required field added later is soft-required | Coordinator | Make a new required field on clients | 1. Edit an existing client's other fields and save.<br>2. Filter `missing_required=true`. | Saving still works; the client appears under "missing required data". | P2 | backend: `tutortrack/crm/tests/test_crm.py` | |
| TP-E05-024 | Custom fields need manage permission | Finance, Coordinator | — | 1. `POST /api/v1/custom-fields` as finance@.<br>2. Repeat as coordinator@. | Finance: 403 (no `crm.customfield.manage`). Coordinator: allowed (Coordinator holds `crm.*`). | P3 | backend: `tutortrack/crm/tests/test_crm.py` | |
| TP-E05-025 | Apply and filter by tag | Coordinator | Tag **Exam year** (students only) | 1. Tag Ada with **Exam year** (API `POST /api/v1/tags/<id>/apply` or bulk).<br>2. Filter students by the tag.<br>3. Try to tag a client with **Exam year**. | Ada is found by the filter; tagging a client is refused (wrong entity type). | P2 | backend: `tutortrack/crm/tests/test_crm.py` | |

## Notes, tasks, documents and timeline

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E05-026 | Add a note with visibility | Coordinator | Patel family | 1. Notes → **Add a note** "Mum asked about Easter revision", Who can see this: **Staff and tutors** → **Save note**.<br>2. Add another as **Staff only**. | Both listed newest first; pinned note "Prefers lessons after 4pm on weekdays." stays on top. | P1 | backend: `tutortrack/crm/tests/test_crm.py`; e2e: `e2e/people.spec.ts` | |
| TP-E05-027 | Note HTML is sanitised | Coordinator | — | 1. Save a note containing `<script>alert(1)</script><a href="javascript:x">x</a><b>bold</b>`. | Script and javascript link removed; bold kept; no alert. | P1 | backend: `tutortrack/crm/tests/test_crm.py` | |
| TP-E05-028 | Mention a colleague | Coordinator | — | 1. In a note type @ and choose admin (Platform Admin). | Mention saved; admin gets a notification (E13). Inactive members can't be mentioned. | P3 | backend: `tutortrack/crm/tests/test_crm.py` | |
| TP-E05-029 | Staff-only notes are hidden from tutors | Tutor | Staff-only note on Arjun | 1. As tutor@ view Arjun's notes (portal or API). | Staff-and-tutors note visible; staff-only note hidden. A tutor's new "staff only" note is saved as staff-and-tutors. | P1 | backend: `tutortrack/crm/tests/test_crm.py` | |
| TP-E05-030 | Tasks and My tasks | Coordinator | — | 1. Tasks → **Add task** "Send GCSE timetable", due tomorrow, on the Patel family, assignee coordinator@.<br>2. Open **My tasks**; tick **Only overdue tasks**.<br>3. **Mark "Send GCSE timetable" done**. | Task listed with "Due …"; overdue filter hides it; marking done removes it ("Nothing to do. Nice." when empty) and records completion. | P1 | backend: `tutortrack/crm/tests/test_crm.py` | |
| TP-E05-031 | Overdue badge | Coordinator | Task due yesterday | 1. Open My tasks. | Task shows **Overdue**. | P2 | backend: `tutortrack/crm/tests/test_crm.py` | |
| TP-E05-032 | Tutor sees only their own tasks | Tutor | A task assigned to tutor@ and one to coordinator@ | 1. As tutor@ open tasks. | Only their own task. | P2 | backend: `tutortrack/crm/tests/test_crm.py` | |
| TP-E05-033 | Attach a document | Coordinator | Uploaded file (E01 flow) | 1. `POST /api/v1/documents` linking the file to the Patel family, category Consent form, expiry date. | Document listed on the record and in the timeline; a file that wasn't uploaded is refused. | P2 | backend: `tutortrack/crm/tests/test_crm.py` | |
| TP-E05-034 | Activity timeline | Coordinator | Patel family after the steps above | 1. Open the **Timeline** tab. | Notes, tasks, documents, status changes and messages in time order, filterable by type. | P2 | backend: `tutortrack/crm/tests/test_crm.py` | |

## Lists, exports, saved views and search

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E05-035 | Export clients to CSV | Coordinator | — | 1. Clients → **Export CSV**. | CSV with the visible columns; formula-like cells escaped; the export is audited; repeated exports alert owners. | P2 | backend: `tutortrack/people/tests/test_people.py` | |
| TP-E05-036 | Saved views are private unless shared | Coordinator, Admin | Swagger | 1. As coordinator@ `POST /api/v1/saved-views` (students, filter status active) private.<br>2. As office@ list saved views.<br>3. Share it and list again. | Private view invisible to office@ until shared. | P3 | backend: `tutortrack/crm/tests/test_crm.py` | |
| TP-E05-037 | Global search | Coordinator | — | 1. Press ⌘K / Ctrl+K (or **Search**).<br>2. Type "patl" (typo), then a phone number, then "priya.patel@". | Fuzzy matches: The Patel Family (Client), Priya Patel (Contact), Arjun and Maya (Students); results labelled by type and open the record. "No matches." for nonsense. | P1 | backend: `tutortrack/crm/tests/test_crm.py` | |
| TP-E05-038 | Search respects permissions | Tutor | tutor@ | 1. Search "Okafor". | No Okafor results (not on Nia's jobs); "Arjun" is found. | P1 | backend: `tutortrack/crm/tests/test_crm.py` | |

## Bulk actions and duplicates

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E05-039 | Bulk tag students | Coordinator | Swagger | 1. `POST /api/v1/bulk/students/tag` with Arjun and Ada IDs and tag **Exam year**.<br>2. Poll `GET /api/v1/bulk-jobs/<id>`. | Job runs in the background (worker), reports progress and success count; both students tagged and audited. | P2 | backend: `tutortrack/crm/tests/test_crm.py` | |
| TP-E05-040 | Bulk errors are reported per record | Coordinator | Include an ID you can't see | 1. Run a bulk archive with one foreign or invalid ID. | Only visible IDs are processed; failures listed per record in `errors`. Unknown action is 400. | P3 | backend: `tutortrack/crm/tests/test_crm.py` | |
| TP-E05-041 | Duplicate warning | Coordinator | — | 1. `GET /api/v1/people/duplicates?email=priya.patel@example.com` (or quick-add a family with that email). | Possible duplicate (Priya Patel) returned/warned; creation is still allowed. | P2 | backend: `tutortrack/people/tests/test_people.py` | |

## Archive and restore

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E05-042 | Archive a family | Coordinator | The Reid Family from TP-E05-001 | 1. Archive the client (API `DELETE /api/v1/clients/<id>` or record action). | Hidden from default lists ("Archived …" when included); its students are archived; new lessons can't be booked for them. | P1 | backend: `tutortrack/people/tests/test_people.py` | |
| TP-E05-043 | Restore a family | Coordinator | Archived Reid family | 1. `POST /api/v1/clients/<id>/restore` (or include archived and restore). | Back in lists; students restorable. | P2 | No | |

## Geocoding and map view (Phase 2b)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E05-044 | Addresses geocode in the background | Coordinator | Worker running; `GEOCODER=…FakeGeocoder` | 1. Give Arjun's family a billing address with postcode LS6 2AA.<br>2. Reload after a few seconds. | `lat`/`lng` filled (stable fake point); no network call. | P2 | backend: `tutortrack/people/tests/test_people.py` | |
| TP-E05-045 | Map shows students and tutors | Coordinator | Some geocoded addresses | 1. Open **Map** (`/people/map`).<br>2. Switch **Show** between Students and tutors / Students / Tutors; filter Status and Subject. | Students as circles, tutors as squares; each marker "Student: Arjun Patel, LS6"; no street addresses; counts match. | P2 | backend: `tutortrack/people/tests/test_map.py` | |
| TP-E05-046 | List view carries the same information | Coordinator | — | 1. Press **List**. | Table "Students and tutors by area" with name, type, area, subjects and travel radius. | P2 | No | |
| TP-E05-047 | Find map positions for missing addresses | Coordinator | People without coordinates | 1. Read "N people can't be placed yet…".<br>2. Press **Find their map positions**. | "Looking up N addresses. Refresh in…"; after refresh they appear. | P3 | backend: `tutortrack/people/tests/test_map.py` | |
| TP-E05-048 | Tutor's travel radius rings | Coordinator | Nia with an address and travel radius | 1. Tick **Show tutors' travel radius**. | A ring around Nia's marker; "Travels up to N km" in the list. | P3 | No | |
| TP-E05-049 | Map respects permissions | Tutor | tutor@ via API | 1. `GET /api/v1/people/map`. | Only Nia and the students on her jobs. | P2 | backend: `tutortrack/people/tests/test_map.py` | |
| TP-E05-050 | Map is keyboard accessible | Coordinator | — | 1. Tab through the map markers; press Enter on one. | Each marker receives visible focus with its label; Enter opens the record. | P2 | No | |

## Permissions

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E05-051 | Tutors see no students until they have jobs | Tutor | A new tutor with no jobs | 1. Sign in as that tutor and list students. | Empty. After assigning them to a job, that job's students appear. | P1 | backend: `tutortrack/people/tests/test_people.py` | |
| TP-E05-052 | Finance sees clients but not students | Finance | finance@ | 1. Open nav and `/students`. | Clients visible (`people.client.view`); Students nav absent and the API 403. | P2 | e2e: `e2e/roles.spec.ts` | |
| TP-E05-053 | Branch-restricted staff see their branch only | Branch Manager | manager@ MAIN-only; a family in another branch | 1. List clients and students. | Only MAIN-branch records. | P1 | backend: `tutortrack/people/tests/test_people.py` | |
| TP-E05-054 | Nested contact details follow field permissions | Tutor | `tutor_access.client_contact_details` = phone | 1. As tutor@ fetch Arjun's client with contacts. | Phone visible, email hidden, in nested contacts too. | P1 | backend: `tutortrack/people/tests/test_people.py` | |

## Tenant isolation

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E05-055 | Lists never show the other organisation | Owner | — | 1. On brightminds list clients, students, tutors, tasks, tags. | No Northside records (Olivia / Noah Northside). | P1 | backend: `tutortrack/crm/tests/test_crm.py`; e2e: `e2e/roles.spec.ts` | |
| TP-E05-056 | Timeline/notes of another tenant's record are 404 | Owner | Noah Northside's ID | 1. `GET /api/v1/timeline?target_type=people.student&target_id=<Noah>` on brightminds. | 404. | P1 | backend: `tutortrack/crm/tests/test_crm.py` | |
| TP-E05-057 | Map lists only own organisation | Owner | — | 1. `GET /api/v1/people/map` on brightminds. | No Northside points. | P2 | backend: `tutortrack/people/tests/test_map.py` | |

## i18n and edge cases

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E05-058 | Terminology applies to people pages | Owner | Terminology Client → Family, Student → Learner | 1. Open Clients and Students. | Labels use Family / Learner where terminology is wired. | P3 | No | |
| TP-E05-059 | Names with accents and apostrophes | Coordinator | — | 1. Quick-add "Siân O'Connor-Łukasik" with student "Zoë". | Saved and displayed correctly; search for "sian" finds her. | P2 | No | |
| TP-E05-060 | Due dates show in the viewer's timezone | Coordinator | Account timezone America/New_York | 1. View a task due 09:00 London. | Shows 04:00 (or 05:00) New York time with the date adjusted. | P3 | No | |
