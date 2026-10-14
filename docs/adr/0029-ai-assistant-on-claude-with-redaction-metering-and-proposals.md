# ADR 0029: AI assistant on Claude with pseudonymisation, credit metering, permission-checked tools and confirm-to-run proposals

- **Status:** Accepted
- **Date:** 2026-10-14
- **Epic:** E31 (T01–T08, FR-31-6). Builds on E04 (AI credits), E09 (report templates), E13 Phase 2 (inbox seam), E17, E19, E21 (progress-report seam), E24, E26 (report engine) and E29 (sub-processors).

## Context
E31 adds AI drafting, inbox assistance, enquiry triage, a command bar, a business copilot,
content writing and matching explanations. The constraints:
- **Human in the loop.** Nothing is sent to clients and no data changes without a person.
- **Privacy.** Tenants opt in per feature. As little data as possible is sent, and names
  are pseudonymised where possible. Safeguarding notes and sensitive fields are never sent.
- **Metering.** Usage is metered against the E04 AI credits, with monthly caps.
- **Grounding.** Answers use only data the requesting person may see. The copilot never
  runs free SQL.
- **Testing.** CI has no API key and the test suite must never call the real API.

## Decision
1. **A new `ai` app with a provider abstraction.**
   - `LLMProvider.complete(LLMRequest) -> LLMResponse` (`providers/base.py`).
   - `AnthropicProvider` uses the official `anthropic` SDK (new dependency) through `client.beta.messages.create`.
   - `FakeLLMProvider` is the provider when `ANTHROPIC_API_KEY` is unset or `AI_PROVIDER=fake`, and always in tests. It gives deterministic, content-aware canned responses, including multi-turn tool use, and accepts scripted responses.
2. **Models and request shape** (`settings.AI`, overridable by env).
   - `claude-opus-5-5` (default tier) does drafting, the command bar, the copilot, content and explanations.
   - `claude-haiku-5-5` (fast tier) does intent classification, enquiry extraction and thread summaries.
   - Thinking is always `{"type": "adaptive"}`, because Opus 5.5 cannot turn it off. Cost and latency are set per prompt with an explicit `output_config.effort`: `low` for rewrites, replies, explanations and the Haiku prompts; `medium` for drafting, triage, the command bar and the copilot.
   - There is no temperature, no `budget_tokens` and no assistant prefill.
   - Forced `tool_choice` returns a 400 on Opus 5.5. So tools are `strict: true` with `tool_choice: auto` and prompt instructions. Extraction and other JSON answers use structured outputs (`output_config.format`).
3. **Refusal fallbacks.**
   - Opus requests send `betas=["server-side-fallback-2026-07-01"]` and `fallbacks="default"`. A request declined by a safety classifier is re-run server-side on Anthropic's recommended fallback model. The log records `fallback_used` from `usage.iterations`.
   - Haiku 5.5 has no server-side fallback.
   - `stop_reason` is checked before any content is read:
     - `refusal`: 422 `ai-refused`, logged as `refused`. A refused turn's tool calls never run.
     - `max_tokens`: 422 `ai-incomplete`.
     - `tool_use`: the tool loop continues.
   - `AI_REFUSAL_FALLBACKS=false` turns fallbacks off, e.g. for platforms without them.
4. **Prompt caching.**
   - Each prompt has a frozen, versioned system prompt (`prompts.py`) with a `cache_control` breakpoint. Tools render before system, so the same breakpoint caches the sorted tool list too.
   - Everything per organisation or per request (tone, spelling, today's date, data) goes in the user message.
   - Cache read and write tokens are recorded per request and priced at their own rates.
5. **Pseudonymisation and exclusion.**
   - Features register the people they load with a per-request `Redactor`. Names (full, first and last name), email addresses and long digit runs (phone and account numbers) become placeholders such as `[STUDENT_1_FIRST]` before sending. Tool results are redacted the same way. Placeholders in answers and tool inputs are restored.
   - The command bar and the copilot first pre-register any student or tutor (visible to the person) named in the free text.
   - Sensitive data is excluded at the source: prompts are built from explicit allow-lists of fields. Examples:
     - progress snapshots: family-visible facts only;
     - tutor facts: never pay rate, tax reference or private bio;
     - matching: the `margin` factor is hidden.
   - Safeguarding notes, `EncryptedField` values, bank details and tokens are never read into a prompt. Conversations flagged by safeguarding detection get no AI assistance.
   - **Limitation:** names in brand-new free text (a new enquiry email) cannot be known in advance and are sent as written. Contact details in it are still scrubbed.
6. **Logging without prompts.**
   - `AIRequestLog` stores the prompt key and version, model, status, token counts (input, output, cache read and write), credits, latency, tool rounds, fallback use, the provider request id and a sha256 of exactly what was sent (redacted). It never stores prompt or answer text.
   - `AIUsage` keeps monthly totals per person and feature.
   - `AIFeedback` keeps thumbs up/down plus edit statistics (similarity, characters added and removed) computed from the draft and final text. The texts themselves are discarded.
7. **Metering against E04 AI credits.**
   - Credits per request: list-price token cost (per-model table in `metering.py`) divided by $0.005, rounded up, minimum 1.
   - Before a request, `AICreditsExhausted` (402) is raised if either of these is true:
     - the organisation's `ai.monthly_credit_cap` is used up;
     - on a subscription, the AI credit balance is empty and overage is off.
   - After a request, credits are consumed from the E04 `CreditAccount` with the request log as the reference.
   - E04 gains an `ai_credits_monthly` plan limit, re-synced by `subscriptions/0003`: Agency 2,000, Enterprise 10,000, Solo/Team 0. AI features also need the existing `ai_assistant` plan feature. Organisations without a subscription are unmetered, as for SMS.
   - A per-person rate limit (`AI_USER_REQUESTS_PER_MINUTE`, default 20) returns 429 `ai-rate-limited`.
8. **Tools and proposals (human in the loop).**
   - The command bar and the copilot use whitelisted toolboxes (`tools.py`). Every read goes through the owning app's selectors with `scope_queryset`, or through the E26 report engine (`reports.run`), which applies the report permission and data scope. Tool failures return `is_error` results. All results of a turn go back in one user message.
   - **Write tools only propose.** `services.propose` validates the action against the person's permissions and stores an `AIProposal`. The whitelisted actions are `reschedule_lesson`, `create_task`, `update_enquiry` and `assign_thread`.
   - `POST /ai/proposals/{id}/confirm` runs the action through the owning app's services with the person's permissions. Only the person who asked can confirm, within an hour. It publishes `ai_proposal.executed`.
   - Tutor-search "filters" are returned to the UI, which runs the E19 search only when the person asks.
   - Copilot answers cite each report run, with its parameters and a link to `/analytics/<report>?<params>`. There is no SQL path.
9. **Drafts, not writes.**
   - Every feature returns drafts. Other apps' records change only when a person submits or saves them through the owning app's endpoints. Proposals are the exception, and they run only on confirm.
   - The "AI-assisted" flag is an `AIAssist` row (request, subject type and id) that the UI records when a person applies a draft. Delivery and learning models are not changed.
   - The E21 progress seam is kept. `learning.progress.register_drafter` gains an `available` callback so `ai_draft_available` reflects the opt-in.
10. **Synchronous requests, no streaming.**
    - Every generation is short and bounded: `max_tokens` of 1,500–10,000, a 90 s SDK timeout, 2 SDK retries and at most 6 tool rounds. So endpoints call the API synchronously, which keeps request handling simple. No Celery task or stream is involved.
    - The only background job is classifying new inbox messages. It runs as a short Celery task started from `message.received`, because it has no human waiting. It is not a Temporal workflow: it has no timers and no multi-step state.
11. **Voice notes.**
    - Claude does not transcribe audio, so a `Transcriber` interface (`AI_TRANSCRIBER`, dotted path) sits in front of the drafting prompt.
    - The fake provider uses a `FakeTranscriber`. Otherwise voice notes return a clear "not available yet" error.
    - **A speech-to-text provider (with its own DPA and sub-processor entry) is still needed.** None is added here.
12. **Evals.**
    - `ai/evals/cases.py` holds golden inputs with expected properties for every prompt: JSON fields, required and banned phrases, placeholders kept, tools called with given arguments.
    - CI runs them against the fake provider (`tests/test_evals.py`).
    - `AI_EVALS_LIVE=1 manage.py ai_evals --live` runs them against the real API, on request only.
13. **Sub-processor.** Anthropic is listed (as optional: only when an AI feature is on) in the E29 sub-processor list, `privacy/compliance.py` (FR-29-8).

## Consequences
- Turning AI on is a per-organisation, per-feature decision. The plan entitlement, the opt-in, `ai.use` and the data permission must all allow a request.
- Prompt changes need a version bump and must keep their eval cases passing. Real-model quality is checked with the live eval command before release.
- Metering prices drift with model prices. `metering.PRICES` must follow Anthropic's list prices.
- A real speech-to-text provider and the E29 sub-processor page are follow-ups.
