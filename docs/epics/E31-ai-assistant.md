# E31 — AI Assistant Features

| | |
|---|---|
| **Phase** | Scale (Phase 3); report drafting can be pulled into Phase 2 as a differentiator |
| **Depends on** | E04 (AI credits), E05, E08, E09, E13, E19, E21 |
| **Differentiator** | None of TutorCruncher, TutorBird or Teachworks offer AI assistance |

## 1. Summary
Practical AI features that save tutors and admins time while respecting privacy: lesson report drafting, parent-friendly summaries and progress reports, smart replies in the inbox, natural-language scheduling and search, matching explanations, and an admin copilot that answers questions about the business. Built on the Anthropic Claude API behind a provider abstraction.

## 2. Principles
- **Human in the loop:** AI produces drafts and suggestions; a person approves anything sent to clients or changing data.
- **Privacy:** tenants opt in per feature; minimal data sent (pseudonymise names where possible); no training on customer data (zero data retention API settings where available); disclosed in the sub-processor list (E29); safeguarding notes and sensitive fields are never sent.
- **Metered:** usage consumes AI credits (E04 FR-04-8); per-org monthly caps.
- **Grounded:** responses only use data the requesting user is permitted to see (permission-scoped retrieval).

## 3. Functional requirements

### FR-31-1 Lesson report drafting
- Tutor enters rough notes or voice dictation → AI produces a structured report matching the template fields (E09), in the org's tone settings (formal/friendly, UK/US spelling), suggests topics covered (E21 curriculum mapping) and homework.
- Tutor edits and submits; the AI-assisted flag is stored.

### FR-31-2 Parent summaries and progress reports
- Draft termly progress report comments from reports, attendance, goals and assessments (E21 FR-21-6).
- "Explain to parent" rewrite: simplify jargon, translate into the contact's preferred language.

### FR-31-3 Inbox assistance
- Suggested replies for client messages using context (upcoming lessons, balance, policies); classify intent (reschedule, billing question, complaint, new enquiry) and route/assign; summarise long threads.

### FR-31-4 Enquiry triage
- Extract structured data from free-text enquiries and emails (students, subjects, levels, availability, location) into the enquiry record; propose next steps and a draft response.

### FR-31-5 Natural-language scheduling and search
- Command bar: "Move Sam's Thursday maths to 5pm from next week", "Find a GCSE chemistry tutor free Tuesday evenings near LS6": parsed into proposed actions or filters (via tool calling against our API with the user's permissions), shown for confirmation before execution.

### FR-31-6 Matching explanations
- Plain-language explanation of why tutors are ranked (E19 score breakdown) and a suggested intro message.

### FR-31-7 Business copilot
- Q&A over the tenant's own data: "Which tutors had the most late cancellations last term?", "What's our outstanding balance over 30 days?". Implemented as tool calls to reporting selectors (E26 semantic layer), never free SQL; answers cite the report/filters used, with a link to open the report.

### FR-31-8 Content generation
- Draft marketing emails/broadcasts (E13), tutor bios for public profiles (E24, requiring approval), website page copy (E24), job opening descriptions (E18).

## 4. Architecture
- `ai` app with `LLMProvider` interface (default: Anthropic Claude via the official Python SDK; model ids configured in settings, defaulting to the latest Claude models; cheaper/faster model for classification, more capable model for copilot reasoning).
- Prompt templates versioned in code with eval sets (golden inputs/outputs) run in CI on prompt changes.
- Tool-calling layer exposing a whitelisted subset of services/selectors with permission checks.
- Redaction/pseudonymisation middleware; output moderation for client-facing text.
- Usage metering (`AIUsage(org, user, feature, input_tokens, output_tokens, credits)`), rate limits, per-feature org toggles.
- Feedback capture (thumbs up/down + edits diff) for quality monitoring.

## 5. Data model
`AIFeatureSetting(org, feature, enabled, tone, language)`, `AIRequestLog(feature, user, prompt_version, tokens, latency, status, redacted_input_hash)`, `AIUsage`, `AIFeedback`.

## 6. Delivery plan
- [x] **E31-T01** AI app: provider abstraction (Anthropic SDK), settings, metering against credits, redaction middleware, request logging, eval harness.
- [x] **E31-T02** Lesson report drafting (incl. voice notes) in tutor portal.
- [x] **E31-T03** Progress report comment drafting and parent-friendly rewrite/translation.
- [x] **E31-T04** Enquiry extraction and triage.
- [x] **E31-T05** Inbox suggested replies, intent classification, thread summaries.
- [x] **E31-T06** Command bar: NL → proposed actions/filters via permission-checked tools.
- [x] **E31-T07** Business copilot over the reporting semantic layer.
- [x] **E31-T08** Content generation helpers (broadcasts, bios, pages, job ads).

## Implementation notes (as built 2026-10-14)
All of T01–T08 and FR-31-6 (matching explanations) are built. The epic defines no Temporal workflow (TW1), so none was added. Design decisions are in ADR 0029.

**Backend: `tutortrack.ai`**
- **Provider.**
  - `LLMProvider` with `AnthropicProvider` (official `anthropic` SDK, **new dependency**) and the deterministic `FakeLLMProvider`.
  - The fake is used when `ANTHROPIC_API_KEY` is unset, and always in tests and CI.
  - Models: `claude-opus-5-5` (drafting, command bar, copilot, content, explanations) and `claude-haiku-5-5` (classification, extraction, summaries). Both can be changed with env vars.
  - Request shape: adaptive thinking with an explicit `output_config.effort`; strict tools with `tool_choice: auto`; structured outputs for JSON. Opus requests opt into server-side refusal fallbacks (`fallbacks="default"`, beta `server-side-fallback-2026-07-01`).
  - The stable system prompt carries a cache breakpoint.
- **Pipeline (`engine.run`).** For every request:
  - checks the plan entitlement `ai_assistant`, the feature opt-in, the per-person rate limit, the monthly cap and the credits;
  - pseudonymises the content;
  - runs the tool loop, with all results returned in one message and `is_error` for failures;
  - checks `stop_reason` (refusal, max_tokens);
  - restores placeholders;
  - logs `AIRequestLog` (hash of the redacted input, tokens incl. cache, credits, latency, rounds, fallback), adds to `AIUsage` and consumes E04 AI credits.
  - SDK exceptions map to RFC 7807: 429 `ai-rate-limited`, 503 `ai-unavailable`, 502 `ai-provider-error`, 422 `ai-refused`/`ai-incomplete`, 402 `ai-credits-exhausted`.
- **Models (all with RLS):** `AIFeatureSetting` (per-feature opt-in, tone, spelling), `AIRequestLog`, `AIUsage` (monthly per person and feature), `AIFeedback` (rating and edit statistics, no texts), `AIAssist` (the AI-assisted flag), `AIProposal` (proposed actions) and `ThreadInsight` (inbox intent).
- **Org settings (`ai.*`):** `tone`, `spelling`, `monthly_credit_cap`, `inbox_auto_classify` and `inbox_routing` (intent → team member).
- **Permissions:** `ai.use`, `ai.copilot`, `ai.settings.manage` and `ai.usage.view`. Roles:
  - Coordinator: use and copilot.
  - Finance: use, copilot and usage.
  - Tutor: use.
  - Branch managers: everything except settings.
  - Owner and Admin get them through `*`.
- **Events:** `ai_feature.updated`, `ai_proposal.executed` and `thread.intent_classified`.
- **Features:**
  - **T02 lesson reports.** Answers come back in the report template's own field types (enums for options, 1–5 ratings), with candidate curriculum topics from E21 and homework. Answers are validated with `delivery.templates.clean_answers`. Voice notes go through the `Transcriber` interface.
  - **T03 progress.** Comments come from the report snapshot, through the E21 seam and `/ai/progress-reports/{id}/draft`. "Explain to parent" uses the contact's preferred language.
  - **T04 enquiries.** Extraction runs on Haiku with structured output. Triage gives next steps, a priority and a draft reply. Field changes come back as an `update_enquiry` proposal.
  - **T05 inbox.** Suggested replies use upcoming lessons, the cancellation policy and the balance, each included only if the person may see it. Summaries and intent; routing is a proposal. Optional auto-classification on `message.received` runs as a Celery task, which assigns only unassigned conversations.
  - **T06 command bar.** Tools `find_students`, `find_lessons`, `propose_reschedule`, `propose_task` and `search_tutors`. Proposals run only through `/ai/proposals/{id}/confirm`.
  - **T07 copilot.** Tools `list_reports` and `run_report` over the E26 engine. Answers cite `[n]` with the report, its parameters and an `/analytics/...` link.
  - **T08 content.** Broadcasts (merge fields are checked with the E13 renderer), tutor bios (approval still applies), page copy and job adverts.
  - **FR-31-6 matching.** Explanations are computed from a recomputed E19 breakdown, plus an intro message.
- **Evals.** Golden cases for every prompt live in `ai/evals/cases.py`. They run in CI against the fake (`test_evals.py`). `AI_EVALS_LIVE=1 manage.py ai_evals --live` runs them against the real API.

**Frontend**
- Admin:
  - Command bar (⌘J/Ctrl+J, a modal dialog, confirm and discard per proposal, optional tutor search).
  - Copilot page at `/copilot`, with a log region and linked sources.
  - AI settings at `/settings/ai` (feature toggles, tone and spelling, organisation defaults, cap, auto-classify, usage and credits).
  - "Draft with AI", "Suggest reply" and "Summarise" are wired into the inbox, enquiries (fill from text and triage), progress reports (draft with feedback and explain to parent), the broadcast editor, the website page editor, the recruitment page (job advert) and job matching (explain ranking).
  - An "AI-assisted" badge shows on lesson and progress reports.
- Tutor portal: report drafting from notes or a voice note on the report page (AI-assisted flag on submit), and "Draft my bio" on the public profile.
- Thumbs up/down feedback on every draft. i18n namespace `ai` (en-GB, with en-US spelling overrides).

**Deviations**
- **AI-assisted flag.** It is stored as `AIAssist` rows in the AI app, recorded when a draft is applied (on submit or save), not as a column on `LessonReport` or `ProgressReport`. This keeps E31 from writing other apps' schemas. The UI reads it with `/ai/assists`.
- **Job advert writer.** There is no admin job-opening editor yet (E18 only has the API). The writer sits on the recruitment applications page and offers "copy", instead of filling an editor.
- **Unknown names.** Names in brand-new free text (a new enquiry email) can't be pseudonymised, because they aren't known yet. Contact details are always scrubbed.
- **Voice notes.** Without a configured `AI_TRANSCRIBER` and with the real provider, voice notes return 422 "not available yet". **A speech-to-text provider is still to be chosen.**
- **Sub-processor list.** Anthropic is in the E29 sub-processor list (`privacy/compliance.py`, optional: only when an AI feature is on); E29 part 2 was merged alongside E31.
- **Output moderation.** Client-facing text is never sent without a person. Refusals come from Claude's classifiers. No separate moderation model was added.
- **Credit pricing.** AI credits are priced from list token costs (1 credit ≈ $0.005, minimum 1 per request). E04 plans gain `ai_credits_monthly` (Agency 2,000, Enterprise 10,000); `subscriptions/0003` re-syncs the catalogue.
