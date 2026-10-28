# E14 — Automation: manual tests

> **Since E33 (2026-10-28) Automations is Workflows.** The engine, actions, guardrails and loop detection tested here are unchanged; the screens are E33's. Automations are custom workflows under **Your workflows**, recipes are **Templates** (**Use template**), the builder is the sequence editor, **Test with a record** is **Preview for a record**, and `/automations` redirects to `/workflows`. The steps below use the new screens; the built-in workflows, preview, Coming up and the Runs list are in [E33](E33-workflow-designer.md).

**Scope.** No-code automations: event, schedule, date-field and manual triggers; conditions (safe evaluator); actions (message, task, field, tag, stage, signed webhook, finance actions, job offers); wait and if/else steps; guardrails and loop detection; versioning; dry run; recipe library; run log with retry; all executed by Temporal (`AutomationRunWorkflow`, `AutomationScheduleWorkflow`). Spec: [E14](../epics/E14-automation.md).

**Built differently from the spec (Implementation notes win):**
- Recipes are a code catalogue; installing one creates a **disabled** automation to review.
- The builder is a structured vertical form (no drag-and-drop canvas). Messages are inline text (not E13 templates).
- No feedback survey, broadcast list, Mailchimp or WhatsApp actions. "Package < 2 hours" recipe is "Prepaid balance low".
- Waits and schedules are Temporal timers and Schedules (no `resume_at` sweeper). Schedule triggers process up to 2,000 records a day.
- Automations never react to `automation.*` events. The kill switch is the org setting `automations.enabled`.

**Common preconditions.** Stack with Celery, Temporal worker and Temporal UI (http://localhost:8233); seed loaded. Screens: `/workflows` (tabs **Built-in**, **Your workflows**, **Templates**, **Runs**), `/workflows/<id>` (the editor). Owner, Admin and Branch Manager hold `automation.*`; Finance holds `automation.view` and `automation.builtin.manage` only (E33); Coordinator holds none. Custom workflows need a plan that allows them (Team or above).

## Builder, conditions and versioning (FR-14-1, FR-14-2, FR-14-4, T01, T02, T09)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E14-001 | Create an event automation | Owner (admin@) | — | 1. `/workflows` → **New workflow**.<br>2. **Name** "Welcome new client"; **Start**: When something happens, "Client created".<br>3. **Add a step** → **Do**: send a message to Family by Email, subject "Welcome {{ recipient.first_name }}".<br>4. **Save and switch on**. | Saved as version 1 and switched on. | P1 | backend: `test_create_validates_and_versions` | |
| TP-E14-002 | Event triggers a run | Coordinator, Owner | TP-E14-001 on | 1. Quick-add a new family with an email (E05).<br>2. Owner: **Runs**. | One run Completed; Mailpit has the welcome email with the first name filled. | P1 | backend: `test_on_event_starts_matching_automations`, `test_send_message_renders_for_each_recipient` | |
| TP-E14-003 | Conditions with all/any | Owner | — | 1. Start on lesson completed; on the **Start** card add the **Only if** questions for a Maths lesson and the student's first lesson (an E14 field condition on the service subject shows in words and can be replaced with a plain question).<br>2. **Save**. | Only first Maths lessons start runs. Invalid conditions are refused on save with a clear error. | P1 | backend: `test_condition_operators`, `test_create_validates_and_versions` | |
| TP-E14-004 | Changed-from/to and date operators | Owner | Trigger student status changed | 1. Condition: status changed to "inactive".<br>2. Change Maya's status to inactive, then to active. | Runs only for the change to inactive. | P2 | backend: `test_condition_operators` | |
| TP-E14-005 | Preview with a record | Owner | Automation with conditions | 1. **Preview for a record** → find the Patel family → **Preview**. | The steps with their dates and what each would do (nothing is sent), or "This wouldn't start for this record: it fails “…”." See TP-E33-027–031. `POST /api/v1/automations/<id>/test` (the E14 dry run) still answers for one release. | P1 | backend: `test_dry_run_describes_without_doing`, `test_a_preview_for_a_record_that_wouldnt_start_says_which_check_fails` | |
| TP-E14-006 | Editing creates a new version; in-flight runs continue | Owner | A run waiting on a 2-day wait | 1. Change the steps → **Save**. | "Saved. New runs use these steps; the run already under way finishes on the old ones." A new version is stored (versions aren't shown as a screen). Renaming, pausing or switching on alone doesn't create a version. | P1 | backend: `test_create_validates_and_versions` | |
| TP-E14-007 | Schema lists triggers, subjects and actions | Owner | — | 1. Open the **Start** card's event list and a step's **Do** list. | The curated events and actions for the workflow's kind of record (E33 added invoice runs, payment requests, packages, review requests and branches). | P3 | backend: `test_schema_lists_triggers_subjects_and_actions` | |

## Actions (FR-14-3, T04, T07)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E14-008 | Create task, add tag, change field | Owner | — | 1. Automation on lesson report overdue: create a task for the owner; add tag "Report chased" to the tutor; change a whitelisted field.<br>2. Make a report overdue (E09). | Task in `/tasks`; tag created and applied; field changed (audited). | P1 | backend: `test_task_tag_and_field_actions` | |
| TP-E14-009 | Round-robin task assignment | Owner | Two coordinators; one has more open tasks | 1. Action create task, assignee round-robin among Coordinator. | Goes to the coordinator with fewer open tasks. | P2 | backend: `test_round_robin_assigns_the_least_busy` | |
| TP-E14-010 | Signed outbound webhook | Owner | A request bin reachable from the backend (e.g. a local `python -m http.server` won't verify; use a small echo service) | 1. Action call webhook to the URL.<br>2. Trigger it. | Request has `X-TutorTrack-Signature: t=..,v1=...` (HMAC-SHA256 with the automation's secret). A URL to 127.0.0.1/169.254.169.254 is refused by the SSRF guard. | P1 | backend: `test_signed_webhook` | |
| TP-E14-011 | Move an enquiry stage | Owner | Pipeline on (E17) | 1. Automation on enquiry received → move stage to "Contacted". | New enquiry moves stage. | P2 | backend: `test_task_tag_and_field_actions` | |
| TP-E14-012 | Finance actions need the author's permission | Coordinator-like custom role, Owner | A member with `automation.manage` but no billing permission | 1. That member adds "add a one-off charge".<br>2. Owner creates one, then loses the permission. | Save refused ("needs permission"). A run of an automation whose author lost permission fails that step. | P1 | backend: `test_finance_actions_need_the_authors_permission`, `test_late_fee_and_revoked_permission` | |
| TP-E14-013 | Apply a late fee action | Owner | Invoice overdue trigger | 1. Action apply late fee 5% min £5. | Charge rounded half-up; at least £5. | P2 | backend: `test_late_fee_and_revoked_permission` | |
| TP-E14-014 | Offer a job to top matches | Owner | Ada's job seeking a tutor | 1. Automation on job created → offer to top matches.<br>2. Create a job. | Offers sent to the top matching tutors (E19). | P3 | No | |

## Wait, branch and execution (FR-14-5, T03, T05, TW1)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E14-015 | Wait then branch | Owner | Workflow: lesson completed → a step **After 1 hour** → **Add a Yes / No split** (the family pays automatically) → Yes: message; No: task | 1. Complete a lesson.<br>2. **Runs**, and the Temporal UI: `automation:<org>:<automation>:<subject>:<key>`. | Runs says "Waiting until <time>"; after it, the split asks again and takes the right path. | P1 | backend: `test_event_run_waits_branches_and_completes` | |
| TP-E14-016 | Max runs per record per day | Owner | Default max 1 | 1. Trigger the same automation twice for the same record in a day. | Second run recorded as Skipped. Manual runs are exempt. | P1 | backend: `test_guardrails` | |
| TP-E14-017 | Loop detection | Owner | A: on tag added → add tag; B: on tag added → add another tag (chain) | 1. Trigger A. | Depth beyond 3 is recorded as Skipped; no infinite loop. | P1 | backend: `test_automations_triggering_each_other_are_stopped` | |
| TP-E14-018 | Org kill switch and rate limit | Owner | `automations.enabled` off (API settings) | 1. Trigger an automation. | No run starts. With `automations.max_runs_per_hour` reached, further runs are skipped. | P2 | backend: `test_guardrails` | |
| TP-E14-019 | Retry from the failed step | Owner | Webhook action to a URL that returns 500 | 1. Trigger; run fails after retries.<br>2. Fix the URL; **Runs** → **Retry from the failed step**. | Completed steps aren't repeated; run completes. `automation.run_failed` (internal) and `workflow.run_failed` (webhook, TP-E33-060) published. | P1 | backend: `test_a_failed_step_can_be_retried` | |

## Schedule, date and manual triggers (FR-14-1, T06)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E14-020 | Schedule trigger uses conditions as the query | Owner | — | 1. **Start**: On a schedule, **How often** Daily, 08:00, for each student; Only if last lesson more than 30 days ago.<br>2. **Coming up** lists the next five days; Temporal UI → Schedules: `automation-schedule`; trigger it now. | One run per matching student, deduplicated per day. | P1 | backend: `test_schedule_trigger_uses_conditions_as_the_query`, `test_schedule_fans_out_to_due_records` | |
| TP-E14-021 | Date trigger with anniversary | Owner | A student with a birthday today | 1. **Start**: Before or after a date, "Date of birth", on the day, every year (anniversary). | That student gets a run today. | P2 | backend: `test_date_trigger_picks_anniversaries_and_fans_out` | |
| TP-E14-022 | Manual run on chosen records | Owner | Automation with manual trigger | 1. Run it on Arjun and Maya. | Two runs, regardless of the per-record daily limit. | P2 | backend: `test_manual_run` | |
| TP-E14-023 | Disabling deletes the schedule | Owner | Scheduled automation | 1. Switch **Off** (or delete). | Its Temporal Schedule is removed/paused. | P3 | No | |

## Templates (recipes) (FR-14-6, T08)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E14-024 | Use every template | Owner | — | 1. **Templates** → **Use template** on each (new enquiry, trial follow-up, dormant students, overdue report, prepaid balance low, overdue invoice, expiring check, birthdays, tutor approved). | Each becomes a switched-off workflow under **Your workflows** ("Added"), valid and editable. Templates count towards the plan's custom workflow limit. | P1 | backend: `test_every_recipe_installs` | |
| TP-E14-025 | New enquiry template end to end | Owner | Template used and switched on; pipeline on | 1. Submit an enquiry form (E17).<br>2. Check Mailpit and `/tasks`. | Auto-reply to the enquirer; a coordinator task due within 1 hour. | P1 | No | |
| TP-E14-026 | Trial follow-up template waits and branches | Owner | Template used and switched on | 1. Complete a trial lesson; inspect the workflow in Temporal UI. | Waits 1 day, sends follow-up, then branches on a booking within 5 days. | P3 | No | |

## Permissions

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E14-027 | Coordinator can't see workflows; Finance only the built-ins | Coordinator, Finance | — | 1. As each, check the sidebar and the Settings menu; open `/workflows`. | Coordinator: no **Workflows** item and 403 from the API. Finance (since E33): **Workflows** is in the Settings menu, with no **New workflow**; see TP-E33-062. | P1 | e2e: `e2e/roles.spec.ts` | |
| TP-E14-028 | Admin manages automations | Admin (office@) | — | 1. Create, edit and switch on a custom workflow. | Allowed. | P2 | No | |

## Tenant isolation

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E14-029 | Automations and runs are per org | Owner of Northside | Bright Minds automation id | 1. Open `/workflows` → **Your workflows** and `/workflows/<Bright Minds id>` on northside.localhost. | No Bright Minds workflows; not found. A Bright Minds event never starts a Northside automation. | P1 | backend: `tutortrack/automations/tests/test_automations.py` (TenantIsolationTestMixin) | |
| TP-E14-030 | Preview can't load another org's record | Owner | Northside client id | 1. `POST /api/v1/workflows/<id>/preview` in Bright Minds with that id. | "not found"; nothing leaks. | P2 | No | |

## Time zones and edge cases

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E14-031 | Daily schedule at 08:00 local across DST | Owner | Daily 08:00 schedule | 1. **Coming up** and the Temporal Schedule spec around the last Sunday of October. | Fires at 08:00 Europe/London both before and after the change. | P2 | No | |
| TP-E14-032 | Condition with a deleted tag | Owner | Automation conditioned on tag "VIP"; delete the tag | 1. Trigger. | Condition evaluates false (no crash); run Skipped. | P3 | No | |
| TP-E14-033 | Message to a recipient without an address | Owner | Client without email | 1. Trigger an email action. | Step completes with that recipient skipped; no failure loop. | P3 | No | |

## Gap batch G4 (2026-10-14): new actions, package triggers and recipe

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E14-034 | Send the lesson feedback survey | Admin | A workflow "Lesson completed → Send the lesson feedback survey" (the **Lesson feedback request** built-in does this too, TP-E33-046) | 1. Complete a lesson. | The family gets the E09 feedback request (once per student and lesson). | P2 | backend: `test_feedback_survey_action` | |
| TP-E14-035 | Add to a mailing list | Admin | Mailchimp connected | 1. Workflow "Student status changed → Add to a mailing list: Summer school". | The client is tagged "Summer school" (usable in segments); consented contacts are synced to the audience with the tag. | P2 | backend: `test_mailing_list_action_tags_and_syncs`; frontend: `automations/G4.test.tsx` | |
| TP-E14-036 | WhatsApp from an approved template | Admin | Approved utility WhatsApp template; contact opted in to WhatsApp | 1. Add "Send a WhatsApp message", choose the template, trigger. | Opted-in contacts get the template; others are skipped; a marketing template is refused. | P2 | backend: `test_whatsapp_action_needs_an_approved_utility_template_and_opt_in` | |
| TP-E14-037 | Message from a saved template | Admin | A saved reply in Settings → Messaging | 1. Add "Send a saved message", pick it; **Preview**; trigger. | The preview shows the saved text; the message uses its title as subject and fills variables. | P2 | backend: `test_saved_reply_action`; frontend: `automations/G4.test.tsx` | |
| TP-E14-038 | Package under 2 hours recipe | Admin | Settings → Billing low level 2; template used and switched on | 1. Use an hours package down to 1.5 hours. | The family gets the email with the buy link; lessons packages and packages with more left don't match. | P1 | backend: `test_package_under_two_hours_recipe`, `test_package_subject_and_triggers_are_registered` | |
