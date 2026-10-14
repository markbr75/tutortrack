# E27 — Public API, Webhooks & Integration Platform: manual tests

**Scope.** The public `/api/v1/` surface and scope enforcement, API keys (scopes, branch scope, IP allowlist, expiry, rotation), rate limits, signed webhooks with the `WebhookDeliveryWorkflow` retry schedule, auto-disable and the delivery log, our own OAuth2 provider (authorisation code + PKCE, consent, connected apps), the developer docs portal, Zapier/Make connector manifests, the integrations marketplace and sandbox organisations. Spec: [E27](../epics/E27-public-api-webhooks.md).

**Built differently from the spec (Implementation notes win):**
- Our own OAuth2 provider (not django-oauth-toolkit). Tokens: API keys `ttk_<prefix>_<secret>`, OAuth `tta_` / `ttr_` / `ttc_`.
- Since G6, reviews (scope `reviews`) and form submissions (read-only, `enquiries` scope) are in the public API.
- Zapier/Make platform packages are not in this repo; they are generated from manifests at `/api/v1/developer/connectors/{zapier|make}`.
- Sandboxes don't copy provider connections (that is how "test mode" is met). Maximum 3 per organisation.
- Webhook endpoints subscribe to explicit types or `<aggregate>.*`, never `*`.

**Common preconditions.**
- `make seed` run. The seed prints a read-only demo API key (`clients:read`, `students:read`, `lessons:read`, `webhooks:read`) once — copy it from the seed output, or create a new key.
- Developer area: `/developer` (tabs Overview, API keys, Webhooks, Apps, Sandboxes). Docs: `/developer/docs`. Marketplace: `/settings/marketplace` ("Integrations" in the nav). Consent page: `/oauth/authorize`.
- API calls: `curl -H "Authorization: Bearer <key>" http://brightminds.localhost:8010/api/v1/clients`.
- **Webhook receivers in dev:** the SSRF guard only allows `https` URLs that resolve to public addresses (`ALLOW_HTTP_OUTBOUND` is off and has no env switch). Use a public HTTPS request bin (for example webhook.site) or an HTTPS tunnel to a local receiver; this needs internet access. For failure tests use a bin that can return 500 (or `https://httpstat.us/500`).
- Temporal worker running (`webhook-delivery:<org>:<delivery>` workflows); Temporal UI http://localhost:8233.

## Public API surface and scopes (T01)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E27-001 | Read clients with the demo key | API client | Demo key | 1. `GET /api/v1/clients` with the key. | 200 with Patel, Okafor and Hughes; cursor pagination (`next`). | P1 | backend: `tutortrack/developer/tests/test_auth.py::test_key_reads_public_endpoint_in_its_organisation` | |
| TP-E27-002 | Missing scope is refused | API client | Demo key (no invoices scope) | 1. `GET /api/v1/invoices`. | 403 problem response naming the missing scope. | P1 | backend: `tutortrack/developer/tests/test_auth.py::test_missing_scope_and_read_only_scope` | |
| TP-E27-003 | Read-only scope can't write | API client | Demo key | 1. `POST /api/v1/clients` with a body. | 403. | P1 | backend: same | |
| TP-E27-004 | Write scope creates and implies read | API client | New key with `clients:write` | 1. `POST /api/v1/clients` (new family).<br>2. `GET /api/v1/clients`. | 201 then 200; the new client is in the list; audit actor is the key's creator. | P1 | backend: `tutortrack/developer/tests/test_auth.py::test_write_scope_allows_creating`; `test_audit_actor_is_the_keys_user` | |
| TP-E27-005 | Internal endpoints refuse tokens | API client | Any key | 1. Call an internal endpoint, e.g. `GET /api/v1/settings` or `/api/v1/team`. | 403 `endpoint-not-public`. | P1 | backend: `tutortrack/developer/tests/test_auth.py::test_internal_endpoints_refuse_tokens` | |
| TP-E27-006 | Scopes never widen the creator's role | Coordinator → API client | Coordinator creates a key with `invoices:write` | 1. Coordinator creates the key (if allowed) and tries `POST /api/v1/invoices/<id>/issue`. | Refused: the coordinator's role can only view invoices. | P1 | backend: `tutortrack/developer/tests/test_auth.py::test_scopes_narrow_but_never_widen_role_permissions` | |
| TP-E27-007 | Lesson actions | API client | Key with `lessons:write` | 1. `POST /api/v1/lessons/<id>/complete` and `/cancel` on test lessons; record attendance. | Actions work as in the UI; events published. | P2 | No | |
| TP-E27-008 | Idempotency-Key on financial POSTs | API client | Key with `payments:write` | 1. `POST /api/v1/payments` (manual payment) twice with the same `Idempotency-Key`. | One payment; the second call returns the same result. | P1 | No | |
| TP-E27-009 | RFC 7807 errors | API client | Any key | 1. Send invalid JSON to a write endpoint. | `application/problem+json` with `type`, `title`, `status` and field errors. | P2 | No | |

## API keys and rate limits (T02)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E27-010 | Create a key; secret shown once | Owner | — | 1. API keys → New API key: name "Zap test", scopes clients:read, lessons:read.<br>2. Create key; copy; Done.<br>3. Reload. | "Copy this secret now" shows the full `ttk_…` key once. After reload only the prefix shows. | P1 | backend: `tutortrack/developer/tests/test_auth.py::test_create_key_shows_the_secret_once_and_stores_a_hash` | |
| TP-E27-011 | Unknown scope refused | Owner | API | 1. Create a key with scope `foo:read`. | 400 with a field error. | P3 | backend: `tutortrack/developer/tests/test_auth.py::test_unknown_scope_is_rejected` | |
| TP-E27-012 | Revoke, expiry and malformed keys | Owner | A key | 1. Revoke it and call the API.<br>2. Create a key that expires today; call after expiry.<br>3. Call with `ttk_bad`. | All 401. Key list shows "revoked or expired". | P1 | backend: `tutortrack/developer/tests/test_auth.py::test_revoked_expired_and_malformed_tokens_are_401` | |
| TP-E27-013 | Key stops when its creator leaves | Owner | Key created by office@ | 1. Deactivate office@ in Team.<br>2. Call the API with that key. | 401. | P1 | backend: `tutortrack/developer/tests/test_auth.py::test_key_stops_when_its_user_leaves` | |
| TP-E27-014 | IP allowlist | Owner | Key with allowlist `203.0.113.0/24` | 1. Call from localhost. | 403/401 (address not allowed). Changing the list to include 127.0.0.1 allows it. | P2 | backend: `tutortrack/developer/tests/test_auth.py::test_ip_allowlist` | |
| TP-E27-015 | Branch-scoped key | Owner | Two branches; key scoped to branch 2 | 1. `GET /api/v1/students`. | Only students in branch 2. | P2 | backend: `tutortrack/developer/tests/test_auth.py::test_branch_scoped_key_sees_only_its_branch` | |
| TP-E27-016 | Rotation with overlap | Owner | A key | 1. Rotate → copy the new secret.<br>2. Call with old and new keys. | Both work during the overlap (default 24 h); the old one shows its expiry; after it, only the new key works. | P1 | backend: `tutortrack/developer/tests/test_auth.py::test_rotation_overlaps_then_old_key_expires` | |
| TP-E27-017 | Rate-limit headers | API client | Any key | 1. Call any endpoint; read headers. | `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`. | P1 | backend: `tutortrack/developer/tests/test_auth.py::test_rate_limit_returns_429_with_retry_after` | |
| TP-E27-018 | 429 with Retry-After | API client | Key with `rate_limit_per_minute` = 5 (API) | 1. Call 6 times in a minute. | 6th call: 429 problem with `Retry-After`. Burst limit (100/s) likewise. | P1 | backend: `tutortrack/developer/tests/test_auth.py::test_rate_limit_returns_429_with_retry_after`; `test_burst_limit_per_second` | |
| TP-E27-019 | Session use of the admin app is unchanged | Owner | — | 1. Use the admin app normally while keys exist. | No CSRF or auth regressions. | P2 | backend: `tutortrack/developer/tests/test_auth.py::test_session_auth_is_unchanged`; e2e: `e2e/smoke.spec.ts` | |
| TP-E27-020 | Overview usage | Owner | Some API calls | 1. Developer → Overview. | Active API keys, connected apps, endpoints, deliveries (24 h), failing/retrying counts. | P3 | No | |

## Webhooks (T03, TW1)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E27-021 | Create an endpoint; secret shown once | Owner | Public HTTPS bin URL | 1. Webhooks → New webhook endpoint; URL; Event `lesson.completed`, Add; Add endpoint. | Endpoint Active; secret shown once. | P1 | backend: `tutortrack/developer/tests/test_webhooks.py::test_create_endpoint_returns_secret_once` | |
| TP-E27-022 | SSRF guard | Owner | — | 1. Try `http://example.com/hook`, `https://localhost/hook`, `https://10.0.0.5/hook`, `https://169.254.169.254/`, `https://user:pass@example.com/`. | All refused with a clear field error. | P1 | backend: `tutortrack/developer/tests/test_webhooks.py::test_ssrf_guard_refuses_unsafe_urls` | |
| TP-E27-023 | Event picker | Owner | — | 1. Open the event picker. | Business events and `<aggregate>.*` wildcards only; no `*`; internal events (`api_key.created`) not offered. | P2 | backend: `tutortrack/developer/tests/test_webhooks.py::test_unknown_or_internal_event_types_are_refused`; `test_event_types_endpoint` | |
| TP-E27-024 | Send test event | Owner | TP-E27-021 | 1. Send test event.<br>2. Open Delivery log and the bin. | A `webhook.test` delivery "Delivered"; the bin shows headers `Webhook-Id`, `Webhook-Event`, `Webhook-Attempt`, `Webhook-Signature: t=…,v1=…`. | P1 | backend: `tutortrack/developer/tests/test_webhooks.py::test_delivery_log_redeliver_and_test_event` | |
| TP-E27-025 | AC: lesson.completed signature verifies | Owner | TP-E27-021 | 1. Complete a lesson.<br>2. In the bin, copy the raw body and headers.<br>3. Verify `HMAC-SHA256(secret, t + "." + body)` with the Python sample in `/developer/docs` → Webhooks. | Signature matches `v1`; timestamp within 5 minutes; `data` is the public lesson representation plus `api_version`. | P1 | backend: `tutortrack/developer/tests/test_webhooks.py::test_delivered_lesson_completed_verifies_with_the_documented_algorithm` | |
| TP-E27-026 | AC: a 500 is retried at increasing intervals | Owner | Endpoint returning 500 | 1. Trigger an event.<br>2. Watch the Delivery log and the Temporal UI (`webhook-delivery:…`). | Status "Retrying"; attempts at about 30 s, 2 m, 5 m, 15 m…; each attempt is logged with status code, latency and response snippet. | P1 | backend: `tutortrack/developer/tests/test_workflows.py::test_a_500_is_retried_at_increasing_intervals` | |
| TP-E27-027 | Retry now | Owner | A retrying delivery | 1. Select Retry now. | The next attempt runs immediately (signal `retry_now`), not after the remaining wait. | P2 | backend: `tutortrack/developer/tests/test_workflows.py::test_retry_now_signal_cuts_the_wait_short` | |
| TP-E27-028 | Redeliver | Owner | A delivered delivery | 1. Select Redeliver. | A new delivery with the same `Webhook-Id` and the same frozen body. | P2 | backend: `tutortrack/developer/tests/test_webhooks.py::test_delivery_log_redeliver_and_test_event` | |
| TP-E27-029 | Pause cancels in-flight retries | Owner | A retrying delivery | 1. Pause the endpoint. | Delivery becomes "Cancelled"; Temporal workflow completes. Enable resumes future deliveries. | P2 | backend: `tutortrack/developer/tests/test_workflows.py::test_paused_endpoint_cancels_the_delivery` | |
| TP-E27-030 | Auto-disable after 3 days of failure | Owner | Hard to wait: check in Temporal UI | 1. Leave an always-failing endpoint and an event.<br>2. In the Temporal UI, check the pending timers (15 attempts ≈ 72 h). | After the last attempt the endpoint is "Disabled after failures"; staff with `developer.webhook.manage` get the `webhook_endpoint_disabled` email. | P2 | backend: `tutortrack/developer/tests/test_workflows.py::test_always_failing_gives_up_after_72_hours_and_disables`; `tutortrack/developer/tests/test_webhooks.py::test_three_days_of_failures_disable_the_endpoint_and_email_admins` | |
| TP-E27-031 | A success clears "failing since" | Owner | Endpoint failing | 1. Make the bin return 200; Retry now. | "failing since …" disappears. | P2 | backend: `tutortrack/developer/tests/test_webhooks.py::test_a_success_clears_the_failure_clock` | |
| TP-E27-032 | Secret rotation signs with both secrets | Owner | Endpoint | 1. Rotate secret.<br>2. Trigger an event. | Header carries two `v1` values for 24 h; both verify. | P2 | backend: `tutortrack/developer/tests/test_webhooks.py::test_rotated_secret_signs_with_both_for_the_overlap` | |
| TP-E27-033 | Branch filter | Owner | Endpoint with branch filter | 1. Complete lessons in two branches. | Only the filtered branch's event is delivered. | P3 | backend: `tutortrack/developer/tests/test_webhooks.py::test_branch_filter` | |
| TP-E27-034 | Two matching endpoints get one delivery each | Owner | Two endpoints on `lesson.*` | 1. Complete a lesson. | Exactly one delivery per endpoint. | P2 | backend: `tutortrack/developer/tests/test_webhooks.py::test_matching_endpoints_get_one_delivery_each` | |
| TP-E27-035 | Delivery log keeps 30 days | Owner | — | 1. Check the purge task in Celery Beat logs. | Deliveries older than 30 days are purged; ones still retrying are kept. | P3 | backend: `tutortrack/developer/tests/test_webhooks.py::test_purge_keeps_thirty_days` | |
| TP-E27-036 | Worker restart during retries | Owner | A retrying delivery | 1. Stop the Temporal worker for a few minutes; start it. | Retries continue from where they were; no duplicate attempts logged. | P2 | No | |

## OAuth2 provider (T04)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E27-037 | Register a tenant OAuth app | Owner | — | 1. Apps → Your OAuth apps: name "Test app", redirect `https://oauth.pstmn.io/v1/callback`, scopes clients:read.<br>2. Register app. | Client id and secret (shown once). | P1 | backend: `tutortrack/developer/tests/test_oauth.py::test_rotate_secret_and_delete_app` | |
| TP-E27-038 | Authorisation code + PKCE flow | Owner | TP-E27-037; Postman OAuth 2.0 with PKCE S256 | 1. Start the flow; sign in; the consent page `/oauth/authorize` lists the requested scopes.<br>2. Approve.<br>3. Exchange the code at `/api/v1/oauth/token`.<br>4. Call `/api/v1/clients` with the `tta_` token. | Consent page shows app name and scopes; token response has access (1 h) and refresh tokens; API call 200. | P1 | backend: `tutortrack/developer/tests/test_oauth.py::test_authorization_code_flow_with_pkce` | |
| TP-E27-039 | Deny consent | Owner | — | 1. Select deny on the consent page. | Redirect to the app with `error=access_denied`. | P2 | backend: `tutortrack/developer/tests/test_oauth.py::test_denied_consent_redirects_with_error` | |
| TP-E27-040 | Code reuse and refresh rotation | API client | TP-E27-038 | 1. Exchange the same code again.<br>2. Refresh twice, then reuse the first refresh token. | Reused code → `invalid_grant` and all grant tokens revoked. Each refresh rotates; reusing an old refresh token revokes everything. | P1 | backend: `tutortrack/developer/tests/test_oauth.py::test_code_is_single_use_and_needs_the_verifier`; `test_refresh_rotates_and_reuse_revokes_everything` | |
| TP-E27-041 | Unregistered redirect or extra scope | API client | — | 1. Start the flow with another redirect URI or a scope the app may not request. | Error page (no redirect to the unknown URI). | P1 | backend: `tutortrack/developer/tests/test_oauth.py::test_unregistered_redirect_and_scope_are_refused` | |
| TP-E27-042 | Connected apps: disconnect | Owner | TP-E27-038 | 1. Apps → Connected apps → Disconnect Test app. | Tokens stop working (401). | P1 | backend: `tutortrack/developer/tests/test_oauth.py::test_admin_disconnects_an_app` | |
| TP-E27-043 | Revocation endpoint | API client | A token | 1. `POST /api/v1/oauth/revoke`. | 200; token no longer works. | P3 | backend: `tutortrack/developer/tests/test_oauth.py::test_revocation_endpoint` | |

## Developer portal, connectors and marketplace (T05–T08)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E27-044 | Docs page | Owner | — | 1. Open `/developer/docs`. | Guides (Authentication, Pagination, Errors, Idempotency, Webhooks, Rate limits, Versioning), curl/Python/JavaScript samples, Changelog. | P2 | No | |
| TP-E27-045 | OpenAPI and Postman downloads | Owner | — | 1. Download OpenAPI and Postman collection. | OpenAPI lists public operations only with `x-scopes`; Postman v2.1 imports cleanly. | P2 | backend: `tutortrack/developer/tests/test_auth.py::test_public_schema_contains_only_public_operations`; `test_postman_changelog_and_connectors` | |
| TP-E27-046 | Interactive reference | Owner | — | 1. Open `/api/v1/redoc/`. | ReDoc loads. | P3 | No | |
| TP-E27-047 | Zapier and Make manifests | Owner | — | 1. `GET /api/v1/developer/connectors/zapier` and `/make`. | Triggers (new enquiry, new client, lesson completed/cancelled, invoice issued/paid, payment received, report submitted, application received), actions and searches listed. | P2 | backend: `tutortrack/developer/tests/test_auth.py::test_postman_changelog_and_connectors` | |
| TP-E27-048 | REST hook subscribe and unsubscribe | API client (Zapier app token) | Partner apps from `manage.py ensure_partner_apps` | 1. `POST /api/v1/webhook-endpoints` with one event using a Zapier OAuth token.<br>2. `DELETE` it. | Endpoint created with `source=zapier`, then removed. Sample from `/webhook-event-types/<type>/sample`. | P2 | backend: `tutortrack/developer/tests/test_webhooks.py::test_rest_hook_subscribe_and_unsubscribe_with_a_token`; `test_zapier_tokens_tag_their_subscriptions` | |
| TP-E27-049 | Marketplace | Owner | — | 1. Open Integrations (`/settings/marketplace`). | Native integrations with status (Stripe, messaging, accounting, calendars, video…), Zapier/Make partner apps; connected ones marked. | P2 | backend: `tutortrack/developer/tests/test_oauth.py::test_partner_apps_show_in_the_marketplace` | |

## Sandboxes (T09)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E27-050 | Create a sandbox | Owner | — | 1. Sandboxes → Create sandbox.<br>2. Open sandbox. | `brightminds-sandbox` org with the same country, timezone, currency, settings and demo data; you are the owner; a sandbox banner shows on Overview; no payment/calendar/accounting connections. | P1 | backend: `tutortrack/developer/tests/test_webhooks.py::test_create_sandbox_copies_settings_and_loads_sample_data` | |
| TP-E27-051 | Sandbox limits | Owner | 3 sandboxes | 1. Create a 4th.<br>2. Inside a sandbox, try to create a sandbox. | Both refused with a clear message. | P2 | backend: same | |

## Permissions

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E27-052 | Only owners/admins manage keys, webhooks, apps, sandboxes | Coordinator; Finance; Tutor | — | 1. Open `/developer` as each. | No access to manage (no `developer.*` permissions); API returns 403. | P1 | backend: `tutortrack/developer/tests/test_auth.py::test_member_without_permission_cannot_manage_keys`; `tutortrack/developer/tests/test_webhooks.py::test_webhook_view_permission_is_required` | |
| TP-E27-053 | Admin manages developer settings | Admin | — | 1. As office@, create a key and an endpoint. | Allowed. | P2 | No | |

## Tenant isolation

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E27-054 | A key used on another organisation's host | API client | Bright Minds key | 1. `GET http://northside.localhost:8010/api/v1/clients` with the Bright Minds key. | 404; no Northside data. | P1 | backend: `tutortrack/developer/tests/test_auth.py::test_key_on_another_organisations_address_is_404` | |
| TP-E27-055 | Key sees only its organisation | API client | Bright Minds key | 1. `GET /api/v1/students?q=Noah`. | No Noah Northside. | P1 | backend: `tutortrack/developer/tests/test_auth.py::test_key_reads_public_endpoint_in_its_organisation` | |
| TP-E27-056 | Webhooks only for own events | Owner (Northside) | Endpoint in Northside | 1. Complete a lesson in Bright Minds. | Northside's endpoint receives nothing. | P1 | No | |
| TP-E27-057 | Another tenant's private OAuth app is unknown | API client | Bright Minds app client id | 1. Start an authorisation on Northside's host with it. | Error "unknown client". | P2 | backend: `tutortrack/developer/tests/test_oauth.py::test_other_tenants_private_app_is_unknown_here` | |

## Errors and edge cases

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E27-058 | Deprecation headers | API client | When an endpoint is declared deprecated | 1. Call it. | `Deprecation`, `Sunset` and `Link` headers. (None declared yet — check after the first deprecation.) | P3 | backend: `tutortrack/developer/tests/test_auth.py::test_deprecated_endpoints_announce_sunset` | |
| TP-E27-059 | Endpoint receiver times out | Owner | Bin that sleeps > 10 s | 1. Send test event. | Attempt logged as timeout after 10 s; retried. | P3 | No | |
| TP-E27-060 | Redirects are not followed | Owner | Endpoint that returns 302 | 1. Send test event. | Attempt recorded as failed (3xx), not followed. | P3 | No | |

## Gap batch G6 (as built 2026-10-14)

Built by gap batch G6 ([ADR 0034](../adr/0034-gap-batch-g6-consent-capture-account-deletion-and-platform-tools.md)); see the epic's *Gap backlog* notes. Signup now requires `accept_terms: true` (the terms checkbox).

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E27-061 | New event types are offered and documented | Developer (owner) | — | 1. Developer → Webhooks → new endpoint → event list. | Types added after E27 (reviews, referrals, packages, bookings, homework, lesson feedback...) are listed with `payload_fields`; safeguarding, consent and security types are never listed. | P1 | backend: `test_event_types_added_after_e27_are_offered`, `test_never_types_are_never_offered` | |
| TP-E27-062 | Ids-only events never leak content | Developer | Endpoint subscribed to `background_check.*` | 1. Complete a background check. | The delivery carries only the listed ids (no result, no flags). | P1 | backend: `test_background_check_results_and_safeguarding_flags_never_leave` | |
| TP-E27-063 | Reviews need the `reviews` scope | Developer | API key with and without `reviews:read` | 1. `GET /api/v1/reviews` with each key. | Without the scope 403; with it the reviews list. | P2 | backend: `test_reviews_need_the_reviews_scope` | |
| TP-E27-064 | Form submissions in the public API | Developer | Key with `enquiries:read` | 1. `GET /api/v1/form-submissions?form=<slug>`. | Submissions listed without IP or browser; POST is refused (read-only). | P2 | backend: `test_form_submissions_are_listed_without_ip_or_browser`, `test_form_submissions_are_read_only` | |
| TP-E27-065 | Marketplace live status | Owner | Xero connected, Zoom not | 1. Settings → **Integrations**. | Xero shows Connected (with a detail line), Zoom Available; payroll, marketing, banking and screening categories appear. | P2 | backend: `test_marketplace_reports_live_status` | |
