# E27 — Public API, Webhooks & Integration Platform

| | |
|---|---|
| **Phase** | Agency (Phase 2) |
| **Depends on** | E01 (API conventions, outbox), E03 (tokens/OAuth) |
| **Parity** | TutorCruncher REST API with OpenAPI/Swagger/ReDoc, per-branch integration tokens, HMAC-SHA256 signed webhooks for create/update/delete; Zapier for both competitors. **Beyond:** OAuth apps, Make, event versioning, delivery logs and replays |

## 1. Summary
Open the platform to tenants and partners: a documented, versioned REST API (the same one our apps use), API keys and OAuth2 apps with scopes, signed webhooks with retries and logs, official Zapier and Make apps, and a developer portal.

## 2. Functional requirements

### FR-27-1 Public API surface
- All `/api/v1/` resources documented as **public** unless marked `internal`. Public resources at launch: clients, contacts, students, tutors, services, jobs, lessons (+ attendance, complete, cancel), lesson reports (read), availability/slots, invoices (read, issue), charges/ad hoc charges, payment requests, payments (read, record manual), pay items (read), enquiries (create/read/update), form submissions, tags, custom fields, notes, tasks, reviews, branches, webhook endpoints.
- Developer docs portal: generated from OpenAPI (ReDoc/Scalar) + guides (auth, pagination, errors, idempotency, webhooks, rate limits, versioning), code samples (curl, Python, JS), Postman collection.
- Versioning: URI major version; additive changes only within v1; deprecations announced with `Sunset` headers and changelog.

### FR-27-2 Authentication
- **API keys** (org-level, optionally branch-scoped like TutorCruncher's per-branch integrations): name, scopes (`clients:read`, `lessons:write`, …), IP allowlist, expiry, created by; secret shown once; rotation with overlap.
- **OAuth2** (authorization code + PKCE) for third-party apps: app registration (by platform partners or tenants), consent screen listing scopes, refresh tokens, revoke; tenant admin sees and revokes connected apps.
- Rate limits: default 600 req/min per token, burst 100/s; `X-RateLimit-*` headers; 429 with `Retry-After`.

### FR-27-3 Webhooks
- Tenant registers endpoints: URL (HTTPS only; private/internal IP ranges blocked to prevent SSRF), subscribed event types (any from the catalogue, wildcard per aggregate), branch filter, active flag, secret.
- Payload: event envelope (`02-architecture.md §5`) with `data` = public API representation of the resource (versioned by `api_version` pinned per endpoint).
- Signature: `Webhook-Signature: t=<timestamp>,v1=<HMAC-SHA256(secret, t + "." + body)>` (replay window 5 min) + `Webhook-Id`, `Webhook-Event` headers.
- Delivery: async from outbox, 10s timeout, retries with exponential backoff for 72h (≈ 15 attempts), ordering not guaranteed (consumers use `occurred_at`/version), auto-disable endpoint after 3 days of continuous failure with an email to admins.
- Delivery log (30 days): request/response (truncated), status, latency; manual **redeliver** and "send test event".
- **AC:** a `lesson.completed` webhook verifies with the documented algorithm using the endpoint secret; a 500 response is retried at increasing intervals and appears in the delivery log with each attempt.

### FR-27-4 Zapier and Make apps
- Triggers (REST hooks via our webhook subscriptions API): new enquiry, new client, lesson completed/cancelled, invoice issued/paid, payment received, report submitted, application received.
- Actions: create/update client & student, create enquiry, create lesson, add note/task, create ad hoc charge, add tag.
- Searches: find client/student/tutor by email/name.

### FR-27-5 Integration marketplace (in-app)
- Settings → Integrations page listing native integrations (payments, accounting, calendar, video, messaging, marketing, Zapier/Make) with connect status, plus partner OAuth apps.

### FR-27-6 Sandbox
- Tenants can create a **sandbox organisation** (copy of settings + sample data) for testing integrations without affecting live data; providers in test mode.

## 3. Data model
`ApiKey(hash, prefix, scopes, branch, ip_allowlist, expires_at, last_used_at)`, `OAuthApplication`, `OAuthGrant/AccessToken/RefreshToken` (django-oauth-toolkit), `WebhookEndpoint(url, events, secret enc, api_version, status, failure_since)`, `WebhookDelivery(endpoint, event_id, attempt, status_code, response_snippet, duration_ms, next_attempt_at)`.

## 4. Delivery plan
- [x] **E27-T01** Public/internal tagging of endpoints; scope enforcement layer mapping scopes → permissions.
- [x] **E27-T02** API keys UI/API (branch scope, IP allowlist, rotation) and rate limiting.
- [x] **E27-T03** Webhook endpoints, SSRF guard, signing, delivery worker, retries, auto-disable, logs, redeliver, test event.
- [x] **E27-T04** OAuth2 provider: app registration, consent, connected apps management.
- [x] **E27-T05** Developer portal (docs, guides, Postman), changelog and deprecation headers.
- [x] **E27-T06** Zapier app (triggers, actions, searches).
- [x] **E27-T07** Make app.
- [x] **E27-T08** Integrations marketplace page.
- [x] **E27-T09** Sandbox organisations.

## Temporal workflows (E32)

- [x] **E27-TW1** Webhook delivery with retries (added while building; the workflow replaces the spec's `next_attempt_at`).

| Workflow | Started by | Steps, timers and signals | Replaces |
|---|---|---|---|
| `WebhookDeliveryWorkflow` `webhook-delivery:{org}:{delivery}` | A delivery is created (an event matched an endpoint, a test event or a redelivery) | POST the signed payload. On failure, wait 30s, 2m, 5m, 15m, 30m, 1h, 2h, 4h, 6h, 8h, 10h, 12h, 14h and 15h between attempts (15 attempts, about 72h), then mark the delivery failed. The signal `retry_now` cuts a wait short. A paused, disabled or deleted endpoint ends the workflow as cancelled | `next_attempt_at` + retry sweeper |

## Implementation notes (as built 2026-10-10)
- **App:** `tutortrack.developer` (the `developer/` folder in 02-architecture).
  - Tenant tables with RLS: `ApiKey`, `OAuthGrant`, `OAuthToken`, `WebhookEndpoint`, `WebhookDelivery`, `WebhookAttempt` and `Sandbox`.
  - Two platform tables are read before a tenant is known. `CredentialRoute` maps a token prefix to its organisation, like `payments.AccountRoute`. `OAuthApplication` holds partner apps, which serve every organisation, and tenant apps, which carry `owner_organisation_id` and are filtered to it.
  - See ADR 0017.
- **Scopes and public surface (T01):**
  - `developer/scopes.py` maps scopes (`clients:read`, `lessons:write`, …) to permission patterns; `write` implies `read`. It also lists the public views by class (`PUBLIC_VIEWS`).
  - A token request must pass three checks:
    1. the endpoint is public;
    2. the token has a scope for the endpoint's resource (checked in `ApiTokenMiddleware.process_view`);
    3. every permission the view checks is granted by the token user's role *and* covered by the token's scopes. `core.permissions.has_perm`, `scope_queryset` and `permission_scope` consult `user.token_permissions` for this.
  - Internal endpoints answer 403 `endpoint-not-public`.
  - OpenAPI operations carry `x-visibility` and `x-scopes`; public ones also list the `apiToken` bearer scheme. This comes from `developer.schema.AutoSchema`, now the `DEFAULT_SCHEMA_CLASS`.
  - Public resources at launch:
    - people and CRM: clients and contacts, students, tutors, tags, custom fields, notes, tasks;
    - catalogue: services, subjects, levels, categories, locations;
    - scheduling and delivery: jobs, lessons (with the attendance, complete and cancel actions), lesson reports, availability and slots;
    - money: invoices, charges, payment requests, payments, pay items (read only);
    - other: enquiries, branches (read only), webhook endpoints, deliveries and event types.
  - **Deviations:** form submissions are not public because they have no list endpoint yet; creating an enquiry covers that use. Reviews (E25) are not public because they don't exist yet.
- **Authentication (T02):**
  - Token formats: API keys are `ttk_<prefix>_<secret>`; OAuth tokens use `tta_`, `ttr_` and `ttc_`. Only SHA-256 hashes are stored, and each secret is shown once.
  - A key acts as the person who created it, for both the audit actor and the data scope. It stops working when that person's membership is no longer active.
  - `ApiTokenMiddleware` runs before the tenant middleware. The tenant resolver (`developer.auth.resolve`, set as `TENANT_RESOLVER`) makes the token's organisation the tenant. A token used on another organisation's subdomain gets 404.
  - `ApiTokenAuthentication` comes first in DRF's authentication classes. Token requests therefore skip session authentication and its CSRF check; session requests are unchanged.
  - Branch-scoped keys narrow the branch context. IP allowlists accept single addresses and CIDR ranges.
  - Rotation issues a new key; the old key expires after `developer.api_key_rotation_overlap_hours` (default 24).
- **Rate limits:**
  - Limits are per token, counted in fixed windows in the shared cache (Redis in production).
  - Per minute: `DEVELOPER_API.RATE_LIMIT_PER_MINUTE` (default 600), or the key's own `rate_limit_per_minute`. Burst: `BURST_PER_SECOND` (default 100).
  - Every token response carries `X-RateLimit-Limit`, `X-RateLimit-Remaining` and `X-RateLimit-Reset`. A 429 problem response also carries `Retry-After`.
- **Webhooks (T03):**
  - Endpoint URLs are validated with `core.net.safe_url` (https only, public addresses only, no credentials in the URL). Deliveries use `safe_urlopen` with a 10-second timeout and don't follow redirects.
  - The catalogue is the registered domain events of business aggregates (`catalogue.PUBLIC_AGGREGATES`); 135 event types today.
  - Endpoints subscribe to explicit types or to `<aggregate>.*`, never to `*`. The outbox subscriber `developer.webhooks` registers for each catalogue type by name from `DeveloperConfig.ready`; the app is last in `INSTALLED_APPS` so every event type exists by then.
  - Payload: the event envelope plus `api_version`, which is pinned per endpoint (`2026-10-01`).
    - `data` is the public serializer's representation of the subject, rendered with the field permissions of the endpoint's creator. If the subject has no public representation, `data` falls back to the event's own data.
    - `event_data` keeps the event's own fields.
    - The payload is frozen when the delivery is created, so every retry sends the same body.
  - Headers: `Webhook-Id` (the event id, unchanged on redelivery), `Webhook-Event`, `Webhook-Attempt` and `Webhook-Signature: t=…,v1=…`. For 24 hours after a secret rotation, both secrets sign each delivery (two `v1` values). `developer.signing.verify` implements the documented receiver check, with a 5-minute window.
  - Retries run on `WebhookDeliveryWorkflow` (TW1). Each attempt is logged as a `WebhookAttempt` (status, error, the first 2,000 characters of the response, latency, request headers), timestamped with the workflow's clock.
  - Three days of continuous failure disable the endpoint. `failing_since` tracks this and any success clears it. Disabling publishes `webhook_endpoint.disabled` and emails staff who hold `developer.webhook.manage`, using the editable `webhook_endpoint_disabled` notification.
  - With this retry schedule, a delivery's 15th attempt lands just after 72 hours. An endpoint that never answers is therefore disabled at the last attempt of its first event.
  - The delivery log keeps 30 days. `purge_all_webhook_deliveries` runs daily on Celery Beat, once per organisation, and keeps deliveries that are still retrying.
  - API actions: redeliver, retry now (sends the `retry_now` signal) and send test event (`webhook.test`).
- **OAuth2 (T04):**
  - We built our own provider instead of using django-oauth-toolkit, whose tables are not tenant-scoped (ADR 0017).
  - Flow: authorisation code with PKCE (S256), required for public clients and whenever a challenge is sent.
  - Lifetimes: codes 10 minutes and single-use; access tokens 1 hour; refresh tokens 90 days, rotated on each use.
  - Reusing a code or a rotated refresh token revokes all of the grant's tokens.
  - Endpoints:
    - `GET` and `POST /api/v1/oauth/authorize` back the admin app's `/oauth/authorize` consent page and need `developer.app.connect`;
    - `POST /api/v1/oauth/token` and `POST /api/v1/oauth/revoke` use the RFC 6749/7009 error format and accept form or JSON bodies.
  - Connected apps are listed and revoked under Developer → Apps. Tenants register their own apps with `developer.app.manage`.
- **Developer portal (T05):**
  - The admin page `/developer/docs` has guides (authentication, pagination, errors, idempotency, webhooks with Python and Node verification samples, rate limits, versioning) and curl, Python and JavaScript samples.
  - Downloads: the public OpenAPI (`/api/v1/developer/openapi.json`, public operations only, cached per process) and a Postman v2.1 collection (`/api/v1/developer/postman.json`).
  - The changelog is served at `/api/v1/developer/changelog`.
  - The full interactive reference stays at `/api/v1/redoc/`.
  - Deprecations are declared in `developer/deprecations.py` and add `Deprecation`, `Sunset` and `Link` headers. None are declared yet.
- **Zapier and Make (T06/T07):**
  - **Deviation:** this repo does not contain the platform-side packages (the Zapier CLI app and the Make custom-app JSON). They are generated from a manifest served at `/api/v1/developer/connectors/{zapier|make}` and published from each partner's console.
  - The manifest covers the spec's triggers, actions and searches:
    - triggers are REST hooks: subscribe is `POST /webhook-endpoints` with one event, unsubscribe is `DELETE`, and samples come from `GET /webhook-event-types/{type}/sample`;
    - searches use `?q=` on clients, students and tutors.
  - The partner OAuth apps are created by `manage.py ensure_partner_apps` (and by the dev seed). Endpoints they create are tagged `source=zapier` or `source=make`.
- **Marketplace (T08):**
  - Served by `GET /api/v1/developer/marketplace` and shown on the admin page **`/settings/marketplace`** ("Integrations" in the nav).
  - Native integrations register in `developer/marketplace.py`, or in their own app's `marketplace.py` (autodiscovered), with a status callback.
  - Stripe and messaging report their real status. GoCardless, Xero, QuickBooks, calendars and video show "Coming soon" until E22 and E23 register their providers.
  - Published partner apps show as connected when the organisation has an active grant.
- **Sandboxes (T09):**
  - `POST /api/v1/developer/sandboxes` creates `<slug>-sandbox` with the same country, timezone, currency and locale. It copies every settings area, loads the demo data and makes the requester the owner.
  - Limits: at most 3 sandboxes per organisation, and a sandbox can't create sandboxes.
  - **Deviation:** the spec's "providers in test mode" is met by not copying provider connections (payments, calendars, accounting), so nothing in a sandbox reaches a live account.
  - The `developer.sandbox_of` setting flags a sandbox, and the Developer overview shows a banner.
- **Permissions:** `developer.apikey.manage`, `developer.webhook.view`, `developer.webhook.manage`, `developer.app.manage`, `developer.app.connect` and `developer.sandbox.manage`. Owner and Admin get them through `*`.
- **Events:** `api_key.created/revoked`, `oauth_app.connected/disconnected`, `webhook_endpoint.created/disabled`, `webhook_delivery.failed` and `sandbox.created`. None of these are webhook event types.
- **Frontend:**
  - `/developer` has six areas:
    - an overview with usage and rate limits;
    - API keys: scopes, IP allowlist, expiry, rotate, revoke, and secrets shown once;
    - webhooks: event picker, test send, pause, secret rotation;
    - a delivery log with attempts, payload, redeliver and retry now;
    - OAuth apps and connected apps;
    - sandboxes.
  - Other pages: `/developer/docs`, `/settings/marketplace` and `/oauth/authorize`.
