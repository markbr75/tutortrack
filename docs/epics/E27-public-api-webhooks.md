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
- [ ] **E27-T01** Public/internal tagging of endpoints; scope enforcement layer mapping scopes → permissions.
- [ ] **E27-T02** API keys UI/API (branch scope, IP allowlist, rotation) and rate limiting.
- [ ] **E27-T03** Webhook endpoints, SSRF guard, signing, delivery worker, retries, auto-disable, logs, redeliver, test event.
- [ ] **E27-T04** OAuth2 provider: app registration, consent, connected apps management.
- [ ] **E27-T05** Developer portal (docs, guides, Postman), changelog and deprecation headers.
- [ ] **E27-T06** Zapier app (triggers, actions, searches).
- [ ] **E27-T07** Make app.
- [ ] **E27-T08** Integrations marketplace page.
- [ ] **E27-T09** Sandbox organisations.
