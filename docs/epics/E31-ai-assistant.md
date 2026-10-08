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
- [ ] **E31-T01** AI app: provider abstraction (Anthropic SDK), settings, metering against credits, redaction middleware, request logging, eval harness.
- [ ] **E31-T02** Lesson report drafting (incl. voice notes) in tutor portal.
- [ ] **E31-T03** Progress report comment drafting and parent-friendly rewrite/translation.
- [ ] **E31-T04** Enquiry extraction and triage.
- [ ] **E31-T05** Inbox suggested replies, intent classification, thread summaries.
- [ ] **E31-T06** Command bar: NL → proposed actions/filters via permission-checked tools.
- [ ] **E31-T07** Business copilot over the reporting semantic layer.
- [ ] **E31-T08** Content generation helpers (broadcasts, bios, pages, job ads).
