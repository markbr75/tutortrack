# E31 — AI Assistant Features: manual tests

**Scope.** The AI pipeline (plan entitlement, per-feature opt-in, rate limit, monthly cap and credits, pseudonymisation, tool loop, logging and metering), lesson report drafting (incl. voice notes), progress report comments and "Explain to parent", enquiry extraction and triage, inbox suggested replies/summaries/intent and routing, the command bar, the business copilot, content writing (broadcasts, bios, page copy, job adverts), matching explanations, feedback, and AI settings. Spec: [E31](../epics/E31-ai-assistant.md).

**Built differently from the spec (Implementation notes win):**
- The "AI-assisted" flag is stored as `AIAssist` rows (recorded when a draft is applied), shown as a badge on lesson and progress reports.
- The job advert writer sits on the recruitment applications page and offers Copy (no job-opening editor).
- Names in brand-new free text (a new enquiry email) can't be pseudonymised; contact details are always scrubbed.
- Voice notes need `AI_TRANSCRIBER`; none ships. With the fake provider a voice note returns a canned transcript; with the real provider and no transcriber it returns 422 "not available yet".
- No separate output-moderation model; nothing client-facing is sent without a person.
- No Temporal workflow in this epic. Auto-classification of new inbox messages is a Celery task.

**Common preconditions.**
- `ANTHROPIC_API_KEY` empty → the deterministic **fake provider** answers (no network). Its answers are canned but derived from the input, e.g. a suggested reply reads "Hi Priya, thanks for your message. … We'll confirm the details shortly."; "move … 5pm" is classified as Reschedule; the copilot answers "According to <report> [1], there are n rows for …".
- Seed turns on every AI feature for Bright Minds. The org is on the trial (Agency features incl. `ai_assistant`; trial gets the Agency AI credits). If a page says "Your plan doesn't include the AI assistant.", grant an `ai_assistant` override from `/platform`.
- Screens: AI assistant settings `/settings/ai`; copilot `/copilot` ("Ask the copilot"); command bar Ctrl+J / ⌘J or "Ask AI"; Inbox `/inbox`; Enquiries `/leads/<id>`; Learning `/learning/students/<id>` (progress reports); Broadcasts `/broadcasts`; Website `/website`; Recruitment `/recruitment`; Matching `/jobs/<id>/match`. Tutor portal: lesson report page `/portal/tutor/lessons/<id>/report`, profile `/portal/tutor/profile`.
- Live API check (optional, needs a real key): `AI_EVALS_LIVE=1 uv run python manage.py ai_evals --live`.

## Pipeline, settings and metering (T01)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E31-001 | AI settings page | Owner | Seed | 1. Open AI assistant settings. | Features listed (lesson report, progress report, explain to parent, enquiry, inbox, command bar, copilot, content, matching) all On; tone and spelling per feature with "Organisation default"; cap; auto-classify; usage this month; "n AI credits left". | P1 | backend: `tutortrack/ai/tests/test_features.py::test_status_settings_and_permissions` | |
| TP-E31-002 | Feature off → buttons hidden and API 403 | Owner | — | 1. Turn off Inbox.<br>2. Open the inbox; call `POST /api/v1/ai/threads/<id>/reply` (or use the old tab). | "Suggest reply" not shown; API 403. | P1 | backend: `tutortrack/ai/tests/test_features.py::test_disabled_feature_is_403`; `tutortrack/ai/tests/test_engine.py::test_features_are_off_until_the_organisation_opts_in` | |
| TP-E31-003 | Plan without the AI assistant | Owner (Northside) | Northside on a plan without `ai_assistant` (set via `/platform`) | 1. Open `/settings/ai`. | "Your plan doesn't include the AI assistant."; no AI buttons anywhere. | P1 | backend: `tutortrack/ai/tests/test_engine.py::test_the_plan_must_include_the_ai_assistant` | |
| TP-E31-004 | Tone and spelling | Owner | — | 1. Set organisation tone Formal, spelling US English; Inbox tone Friendly.<br>2. Draft a reply and a broadcast. | Request uses Friendly for inbox, Formal for others; en-US spelling (visible in the request log metadata; the fake echoes the setting). | P2 | backend: `tutortrack/ai/tests/test_engine.py::test_tone_and_spelling_follow_the_feature_then_the_organisation` | |
| TP-E31-005 | Credits consumed; exhaustion | Owner | Credits balance | 1. Note credits left; run a draft; reload.<br>2. Exhaust credits (platform override `ai_credits_monthly` = 1, then two requests). | Credits decrease (min 1 per request); when exhausted, a clear 402 "AI credits used up" message. | P1 | backend: `tutortrack/ai/tests/test_engine.py::test_credits_are_consumed_and_exhaustion_blocks_with_a_clear_error` | |
| TP-E31-006 | Monthly cap | Owner | Cap = 1 credit | 1. Run two AI requests. | Second refused with a cap message. | P2 | backend: `tutortrack/ai/tests/test_engine.py::test_monthly_cap` | |
| TP-E31-007 | Per-person rate limit | Coordinator | `AI_USER_REQUESTS_PER_MINUTE=20` (set 2 to test) | 1. Run 3 requests within a minute. | Third: 429 "ai-rate-limited" message, retry later. | P2 | backend: `tutortrack/ai/tests/test_engine.py::test_per_user_rate_limit` | |
| TP-E31-008 | Request log and usage | Finance | Some requests | 1. AI settings → usage; `GET /api/v1/ai/requests` and `/api/v1/ai/usage`. | Requests and credits per feature and person; no prompt text stored (hash only). | P1 | backend: `tutortrack/ai/tests/test_engine.py::test_requests_are_redacted_logged_and_metered_without_storing_prompts`; `tutortrack/ai/tests/test_features.py::test_usage_and_request_log` | |
| TP-E31-009 | Pseudonymisation | Developer | Fake provider | 1. In a Django shell, run an inbox suggestion for the "Thursday's lesson" conversation and inspect `FakeLLMProvider().requests` (or the eval harness). | Names and contact details replaced by placeholders (`[CONTACT_1]` …) in what is sent; restored in the answer shown. | P1 | backend: `tutortrack/ai/tests/test_engine.py::test_redactor_pseudonymises_people_and_contact_details_and_restores_them` | |
| TP-E31-010 | Safeguarding-flagged conversations get no AI | Coordinator | A conversation with a safeguarding flag | 1. Try Suggest reply. | Not offered / refused. | P1 | backend: `tutortrack/ai/tests/test_features.py::test_flagged_conversations_get_no_ai` | |
| TP-E31-011 | Feedback thumbs | Coordinator | A draft | 1. Select Helpful / Not helpful; edit the draft and use it. | "Thanks for the feedback."; feedback stores rating and edit statistics only, not text. | P2 | backend: `tutortrack/ai/tests/test_features.py::test_feedback_keeps_edit_statistics_not_text` | |
| TP-E31-012 | Provider errors are clear | Owner | Real provider with an invalid key (optional) | 1. Set `ANTHROPIC_API_KEY=bad`, restart, run a draft. | Friendly error (502/503 problem), no stack trace; request logged as failed. | P3 | backend: `tutortrack/ai/tests/test_engine.py::test_sdk_errors_map_to_problems` | |
| TP-E31-013 | Refusals and truncation | Owner | — | 1. (Covered by tests) | Refused/incomplete answers stop with 422 `ai-refused` / `ai-incomplete` and are logged. | P3 | backend: `tutortrack/ai/tests/test_engine.py::test_refusals_and_truncation_stop_the_request_and_are_logged` | |

## Lesson report drafting (T02)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E31-014 | Draft a lesson report from notes | Tutor | Nia's completed lesson with Arjun | 1. Portal → lesson → write report → Draft with AI.<br>2. Rough notes: "fractions, equivalent fractions ok, struggled with mixed numbers, set worksheet".<br>3. Draft the report. | Template fields filled (enums/ratings valid); "Suggested topics: …" from GCSE Maths curriculum; "Suggested homework: …". | P1 | backend: `tutortrack/ai/tests/test_features.py::test_lesson_report_draft_fills_the_template_and_marks_ai_assisted` | |
| TP-E31-015 | Edit and submit marks AI-assisted | Tutor; Coordinator | TP-E31-014 | 1. Edit a field, submit.<br>2. As coordinator open Lesson reports. | Report shows the "AI-assisted" badge. | P1 | backend: same | |
| TP-E31-016 | Voice note | Tutor | Fake provider | 1. Record or attach a short voice note; Draft the report. | Fake transcription is used and the report is drafted. With the real provider and no `AI_TRANSCRIBER`: 422 "not available yet". | P2 | backend: `tutortrack/ai/tests/test_features.py::test_lesson_report_voice_note` | |
| TP-E31-017 | Tutors only draft their own reports | Tutor | Sam Clarke's lesson id | 1. Call the draft API for Sam's lesson as tutor@. | 403/404. | P1 | backend: `tutortrack/ai/tests/test_features.py::test_tutors_only_draft_their_own_reports` | |

## Progress reports and explain to parent (T03)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E31-018 | Draft progress comments | Coordinator | Arjun: reports, goal "Grade 7 in GCSE Maths", mock result 54/80 | 1. Learning → Arjun → progress report → Draft with AI. | Comment drafted from reports, attendance, goals and assessments; AI-assisted badge after saving. | P1 | backend: `tutortrack/ai/tests/test_features.py::test_progress_comments_via_ai_endpoint_and_the_e21_seam` | |
| TP-E31-019 | Explain to parent in their language | Coordinator | Priya's preferred language set to Polish | 1. Explain to parent; Language = Same language. | Simplified text in Polish (fake marks the language); choosing another language overrides. | P2 | backend: `tutortrack/ai/tests/test_features.py::test_explain_to_parent_in_the_contacts_language` | |

## Enquiry extraction and triage (T04)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E31-020 | Fill in an enquiry from text | Coordinator | New enquiry with message "Looking for a GCSE chemistry tutor for my son Leo, Year 10, Tuesday evenings, LS6 2AB. Call 07700 900123." | 1. Enquiry page → Fill in with AI. | Proposed fields: student Leo, subject chemistry, level GCSE/Year 10, weekday Tuesday evening, postcode LS6 2AB; applied only on confirm; the phone number never reaches the model. | P1 | backend: `tutortrack/ai/tests/test_features.py::test_extraction_prefills_and_contact_details_never_reach_the_model` | |
| TP-E31-021 | Triage | Coordinator | TP-E31-020 | 1. Triage with AI. | Suggested next steps, priority and a draft reply; field changes come as a proposal that applies only on Confirm. | P1 | backend: `tutortrack/ai/tests/test_features.py::test_triage_proposes_changes_that_apply_only_when_confirmed` | |

## Inbox assistance (T05)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E31-022 | Suggest reply uses account context | Coordinator | Seed conversation "Thursday's lesson" | 1. Inbox → open it → Suggest reply. | Draft greets Priya and mentions the next lesson (if permitted); "Use this draft" puts it in the reply box; nothing is sent until you press Send. | P1 | backend: `tutortrack/ai/tests/test_features.py::test_suggested_reply_uses_account_context`; e2e: `e2e/inbox.spec.ts` | |
| TP-E31-023 | Context limited by permission | Tutor | Tutor portal message thread | 1. Suggest reply as tutor (if available). | Balance/invoice context not included for roles without billing view. | P2 | backend: same | |
| TP-E31-024 | Summarise and classify | Coordinator | Seed conversation | 1. Summarise; Classify. | Summary shown; "Intent: Reschedule (n%)"; a routing proposal to the configured team member, applied only on confirm. | P1 | backend: `tutortrack/ai/tests/test_features.py::test_summary_and_classification_with_routing_proposal` | |
| TP-E31-025 | Auto-classification of new messages | Owner | Settings: auto-classify on; routing Billing → finance@ | 1. As parent@, send a portal message "Question about my invoice".<br>2. Check the inbox. | Conversation classified Billing and assigned to finance (only if unassigned). | P2 | backend: `tutortrack/ai/tests/test_features.py::test_new_messages_are_classified_and_routed_automatically` | |

## Command bar (T06)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E31-026 | Open with keyboard | Coordinator | — | 1. Press Ctrl+J (⌘J on Mac).<br>2. Press Escape. | Modal "Ask AI" with focus in "What would you like to do?"; Escape closes and returns focus. | P1 | No | |
| TP-E31-027 | Propose a reschedule; confirm | Coordinator | Arjun's Tuesday 16:30 lessons | 1. Type "Move Arjun's Tuesday maths to 5pm from next week" → Go.<br>2. Review "Proposed changes" → Confirm. | A reschedule proposal listing the lessons and new time; nothing changes until Confirm; then "Done." and the lessons move to 17:00. | P1 | backend: `tutortrack/ai/tests/test_features.py::test_command_bar_proposes_a_reschedule_and_runs_it_only_on_confirm` | |
| TP-E31-028 | Discard a proposal | Coordinator | — | 1. Repeat; Discard. | "Discarded."; nothing changes. | P2 | backend: same | |
| TP-E31-029 | Tasks and tutor search | Coordinator | — | 1. "Remind me to call Tom Okafor tomorrow" → Confirm.<br>2. "Find a GCSE physics tutor free Tuesday evenings near LS6" → Run this search. | Task created for tomorrow; Matching tutors list (Sam Clarke if available) or "No tutors match." | P2 | backend: `tutortrack/ai/tests/test_features.py::test_command_bar_tasks_and_tutor_search` | |
| TP-E31-030 | Respects permissions | Finance | — | 1. As finance (no scheduling edit) ask to move a lesson. | No reschedule proposal or confirm refused ("That didn't work: …"). | P1 | backend: `tutortrack/ai/tests/test_features.py::test_command_bar_respects_the_users_permissions`; `test_proposals_cannot_run_actions_the_user_lacks` | |

## Business copilot (T07)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E31-031 | Ask a question | Finance | Some invoices | 1. Ask the copilot: "What's our outstanding balance over 30 days?" → Ask. | "Looking at your reports…" then an answer citing [1] with Sources "Open <report>" linking to `/analytics/...` with the same parameters. | P1 | backend: `tutortrack/ai/tests/test_features.py::test_copilot_answers_from_reports_and_cites_them` | |
| TP-E31-032 | Copilot sees only permitted reports | Coordinator | — | 1. Ask "What was our revenue last month?". | Answer uses a report the coordinator may see, or says they don't have access; finance-only data never appears. | P1 | backend: `tutortrack/ai/tests/test_features.py::test_copilot_needs_its_permission_and_only_sees_permitted_reports` | |
| TP-E31-033 | Copilot not available to tutors | Tutor | — | 1. Open `/copilot` in the admin app as tutor@. | "The copilot isn't available to you." | P2 | backend: same | |
| TP-E31-034 | Conversation log is accessible | Finance | — | 1. Ask two questions with a screen reader. | New answers are announced (log region); sources are links with clear names. | P2 | No | |

## Content and matching (T08, FR-31-6)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E31-035 | Draft a broadcast | Coordinator | Draft broadcast "Half-term timetable" | 1. Broadcast editor → Draft with AI → brief "Remind families about half term" → Write draft → Use this draft. | Subject and body filled with valid merge fields (`{{ recipient.first_name }}`); invalid merge fields are refused. | P1 | backend: `tutortrack/ai/tests/test_features.py::test_content_drafts` | |
| TP-E31-036 | Tutor bio needs approval | Tutor; Coordinator | — | 1. Portal → profile → Draft my bio → save.<br>2. Coordinator checks profile moderation. | Bio saved as pending approval; not public until approved. | P1 | backend: same | |
| TP-E31-037 | Website page copy | Owner | — | 1. Website → page editor → Draft with AI. | Copy drafted into the editor; publishing still manual. | P2 | backend: same | |
| TP-E31-038 | Job advert | Owner | — | 1. Recruitment → Write a job advert → Copy. | Advert text drafted with a Copy button. | P3 | backend: same | |
| TP-E31-039 | Explain matching ranking | Coordinator | Ada Okafor's job seeking a tutor | 1. Jobs → Ada's job → Match → Explain this ranking. | Plain-language explanation consistent with the score breakdown, and a Suggested introduction. | P2 | backend: `tutortrack/ai/tests/test_features.py::test_matching_explanation` | |

## Permissions

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E31-040 | Settings only for owners/admins | Branch Manager; Coordinator | — | 1. Open `/settings/ai`. | Branch manager: can use AI and view usage but not change settings. Coordinator: no settings. | P1 | backend: `tutortrack/ai/tests/test_features.py::test_status_settings_and_permissions` | |
| TP-E31-041 | Usage view | Finance | — | 1. Open AI usage. | Finance sees usage (`ai.usage.view`); coordinator doesn't. | P2 | backend: same | |
| TP-E31-042 | Portal families and students have no AI | Parent; Student | — | 1. Look for AI buttons in the portal. | None. | P2 | No | |

## Tenant isolation

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E31-043 | Logs, proposals, insights per organisation | Owner (Northside) | Bright Minds AI activity | 1. Open AI usage in Northside; request a Bright Minds proposal id. | Only Northside usage; 404 for other ids. | P1 | backend: `tutortrack/ai/tests/test_isolation.py` | |
| TP-E31-044 | Copilot and command bar never return another org's data | Owner (Northside) | — | 1. Ask "find Arjun" in the command bar. | No Bright Minds students. | P1 | No | |

## i18n

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E31-045 | en-US spelling overrides in AI UI | Owner | Account language English (US) | 1. Open AI settings and the command bar. | UI strings in en-US spelling; no missing keys. | P3 | No | |
