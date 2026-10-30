# E34 — The TutorTrack Network: manual tests

**Scope.** E34 is being built ticket by ticket; this file grows with it. **T01 (pathway engine):**
- pathway templates (stages of steps, versions, switching off);
- runs about a record for a tutor: one stage open at a time, gates, completed, turned down or
  cancelled;
- the six first step types: questions, upload, sign, read and acknowledge, staff review and
  system check;
- who may do each step;
- the tutor's tasks API;
- reminders and overdue notices on `PathwayRunWorkflow`;
- the `pathway.completed` webhook, pathway runs as a workflow record type, and privacy.

T01 has no screens (the editor, run timelines and the tutor's Tasks page come in T02), so these
cases use the API. Spec: [E34](../epics/E34-network.md), ADR 0048.

**Built differently from the spec (Implementation notes win):**
- Starting and cancelling runs needs `pathway.run.manage`, which was added; templates need
  `pathway.manage`.
- Steps have a `review` status: a tutor's answer to a checked step waits for staff, and
  rejecting it sends it back with the reason. A staff review that says no ends the run as
  `rejected`.
- `GET /api/v1/pathway-schema` lists the step types, record types, questions and staff roles.

**Common preconditions.**
- **Stack:** Celery, the Temporal worker and Mailpit running; seed loaded. The dev Temporal
  server can't skip time, so test due dates with `due_days: 1` and
  `pathways.reminder_days: 0`, or check the run's wait in the Temporal UI.
- **Sign-ins:** admin@ (Owner), coordinator@ (Coordinator), finance@ (Finance) and tutor@
  (Tutor, linked to a tutor record).
- **Data:** "a job" means any job id from `GET /api/v1/jobs`.
- **The standard template** (POST it as Owner): stage `paperwork` ("Paperwork") with a `sign`
  step `agreement` (`due_days` 3) and an `acknowledge` step `safeguarding`; then stage `ready`
  ("Ready to teach", `gate` "ready") with a `staff_review` step `check` (assignee `staff`).

## Templates (FR-34-1, FR-34-2, T01)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E34-001 | Create a template | Owner (admin@) | — | 1. `POST /api/v1/pathway-templates` with the standard template, `kind` "join", `record_type` "job". | 201. `key` "join-a-job"-style, `version` 1, both stages returned with each step's cleaned `config`; audited `create`. | P1 | backend: `test_templates_are_created_and_versioned_through_the_api` | |
| TP-E34-002 | Bad templates are refused with a reason | Owner | — | 1. POST templates with, in turn: no stages; a step `type` "teleport"; two steps with the same key; a `sign` step with `assignee` "staff"; a `role` on a tutor step; `due_days` 0; a `system_check` question about tutors on a job template; a `select` question with no options; an `acknowledge` step with no text or link. | 422 each time, with a message saying what's wrong (for example "Unknown kind of step", "Step keys must be unique", "Due dates are 1 to 365 days after a step opens"). | P1 | backend: `test_templates_are_checked_when_saved` | |
| TP-E34-003 | Changing the stages adds a version; running pathways keep theirs | Owner | A run of the template (TP-E34-005) | 1. PATCH the template's `name` only.<br>2. PATCH its `stages` (drop the staff review).<br>3. GET the running pathway. | 1 keeps `version` 1. 2 gives `version` 2. The running pathway still has three steps on version 1. | P1 | backend: `test_changing_the_stages_adds_a_version_and_runs_keep_theirs` | |
| TP-E34-004 | Templates are for staff with permission | Tutor (tutor@), Finance | — | 1. As Tutor, GET `/api/v1/pathway-templates`, `/api/v1/pathway-runs` and `/api/v1/pathway-schema`.<br>2. As Finance, the same. | 403 for both roles (neither holds `pathway.view`). | P2 | backend: `test_tutors_cant_see_or_change_templates` | |

## Runs and steps (FR-34-1, T01)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E34-005 | Start a pathway | Coordinator (coordinator@) | The standard template; a job; the seeded tutor | 1. `POST /api/v1/pathway-runs` with `template`, `record_id` (the job) and `tutor`. | 201. `status` "running", `stage` "paperwork", `progress` 0 of 3. The tutor's two steps are `open` (the agreement due in 3 days); the staff review is `waiting`. The tutor gets "Join a job: 2 steps to do" in Mailpit, listing both steps. | P1 | backend: `test_starting_opens_the_first_stage_and_tells_the_tutor`, `test_coordinators_start_follow_and_cancel_runs` | |
| TP-E34-006 | The tutor sees and does their own steps | Tutor | TP-E34-005 | 1. `GET /api/v1/me/tasks`.<br>2. `POST /api/v1/me/tasks/<safeguarding id>/complete` with `{}`.<br>3. `POST …/<agreement id>/complete` with `{"full_name": "Sam Tutor"}`. | 1 lists the two steps with what to read and sign. 2 and 3 return `done`. The signed agreement appears on the tutor's record with a signed PDF. The staff review opens, and holders of `pathway.step.complete` get the in-app alert "Pathway step for staff: Coordinator check". | P1 | backend: `test_tutors_see_and_do_their_own_tasks`, `test_tutor_steps_then_staff_review_complete_the_run_through_its_gate` | |
| TP-E34-007 | Only the person a step names can do it | Owner, another tutor | TP-E34-005, before TP-E34-006 | 1. As Owner, `POST /api/v1/pathway-runs/<id>/steps/safeguarding/complete`.<br>2. As another tutor, `POST /api/v1/me/tasks/<safeguarding id>/complete`. | 1 is refused (403: only the tutor following the pathway). 2 is 404 (not their task). | P1 | backend: `test_only_the_person_a_step_names_can_finish_it`, `test_tutors_see_and_do_their_own_tasks` | |
| TP-E34-008 | The staff review completes the pathway through its gate | Coordinator | TP-E34-006 | 1. `POST /api/v1/pathway-runs/<id>/steps/check/complete` with `{"note": "All good"}`.<br>2. GET the run. | `status` "completed", `gates` ["ready"]. Webhook endpoints subscribed to `pathway.completed` receive it with `outcome` "completed". | P1 | backend: `test_tutor_steps_then_staff_review_complete_the_run_through_its_gate`, `test_finished_pathways_are_a_webhook_event_and_the_rest_stay_internal` | |
| TP-E34-009 | A staff review can name a role | Coordinator, Owner | A template whose `staff_review` has `role` "finance" | 1. As Coordinator, complete the review.<br>2. As Owner, complete it. | 1 is refused (403). 2 works: owners and admins can always act. | P2 | backend: `test_a_staff_step_can_name_a_role`, `test_staff_steps_through_the_api_follow_their_role` | |
| TP-E34-010 | A staff review that says no turns the pathway down | Coordinator | A run at its staff review | 1. `…/steps/check/reject` with no reason.<br>2. Again with `{"reason": "Not enough experience"}`. | 1: 422 "Say why." 2: the step is `rejected` and the run `rejected` with the reason; `pathway.completed` has `outcome` "rejected". | P1 | backend: `test_a_staff_review_that_says_no_turns_the_run_down` | |
| TP-E34-011 | Answers that staff check go to review and can be sent back | Tutor, Coordinator | A template with a `questions` step (`review: true`) | 1. As Tutor, complete it with a required answer missing.<br>2. Complete it properly.<br>3. As Coordinator, `…/reject` with a reason.<br>4. As Tutor, answer again; as Coordinator, `…/complete`. | 1: 422 with the field's error. 2: `review`. 3: back to `open` with the reason, and the tutor gets "Please do this step again". 4: `done`. The tutor can't accept their own answers. | P1 | backend: `test_answers_staff_check_go_to_review_and_can_be_sent_back` | |
| TP-E34-012 | Uploads use the tutor's own files | Tutor | A template with an `upload` step | 1. Upload a file with `POST /api/v1/files/uploads` and `…/complete`.<br>2. Complete the step with that file's id.<br>3. Try a file id someone else uploaded. | 2: `review` (uploads are checked by default); the file is attached to the step. 3: 422 "Upload the files again". | P1 | backend: `test_uploads_must_be_the_tutors_own_files_and_are_attached_to_the_step` | |
| TP-E34-013 | System steps finish when their question holds | Owner | A template with a `system_check` step "job.active", run on a job that is seeking a tutor | 1. Start it.<br>2. Make the job active.<br>3. Wait for the daily re-check, or move another step. | The step stays `open` until the job is active; then it's `done` and the run completes. | P2 | backend: `test_system_steps_finish_when_their_question_holds` | |
| TP-E34-014 | Reminders, then overdue | Tutor, Coordinator | A step with `due_days` 2 and `pathways.reminder_days` 1 | 1. Leave the step undone past its due date. | A day before it's due, the tutor gets "Reminder: <step>". When it's due, the tutor gets "Overdue: <step>" and staff get "Pathway step overdue". Each is sent once. | P1 | backend: `test_tick_reminds_before_the_due_date_then_says_overdue`, `test_timers_remind_then_say_overdue_and_cancelling_ends_it` | |
| TP-E34-015 | Skip, remind and cancel | Coordinator | A running pathway | 1. `…/steps/agreement/skip` with a reason.<br>2. `…/steps/safeguarding/remind`.<br>3. `POST /api/v1/pathway-runs/<id>/cancel`.<br>4. Try to complete a step. | 1: `skipped` (it counts as finished). 2: the tutor gets a reminder now. 3: `cancelled`; the Temporal run ends "cancelled". 4: 422 "This pathway has finished." | P2 | backend: `test_coordinators_start_follow_and_cancel_runs`, `test_cancelling_stops_the_run` | |
| TP-E34-016 | Another organisation's pathways can't be reached | Admin of Northside | A run in Bright Minds | 1. GET it, and POST a step action on it, signed in to Northside. | 404 both times; the list doesn't show it. | P1 | backend: `TestPathwayRunIsolation`, `TestPathwayTemplateIsolation`, `test_runs_are_not_shared_between_organisations` | |
| TP-E34-017 | Workflows can start on pathway events | Owner | — | 1. `/workflows` → new workflow; open the start list. | **Pathway started / step done / stage done / finished / cancelled** are offered under the record type **Pathway**, with the question "The pathway is still in progress" and the tutor as a recipient. | P3 | backend: `test_pathways_are_a_record_type_for_workflows` | |
| TP-E34-018 | A tutor's answers are in their DSAR and go on erasure | Owner | A tutor who answered a questions step | 1. Export the tutor's data (E29).<br>2. Erase the tutor. | 1 has a **Pathways** section with their answers. 2 replaces each step's result with "erased", removes uploaded files, and keeps the steps. | P2 | backend: `test_a_tutors_answers_are_exported_and_erased` | |
