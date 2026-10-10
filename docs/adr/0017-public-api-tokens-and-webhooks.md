# ADR 0017: Public API tokens, scopes and webhooks in a `developer` app

- **Status:** Accepted
- **Date:** 2026-10-10
- **Epic:** E27

## Context
E27 opens the existing `/api/v1/` API to tenants' scripts and partner apps (Zapier, Make). The design had to meet these constraints:
- Bearer tokens (API keys and OAuth2 access tokens) must work next to session authentication without changing it. Session requests use CSRF; token requests can't.
- The tenant normally comes from the subdomain. For a token, it must come from the token, and a token must never reach another tenant.
- Every tenant table uses Postgres RLS. A token has to be found *before* we know its tenant.
- Scopes must narrow what a token can do. They must never grant more than the role of the person behind the token.
- Webhooks must be signed, retried for about 72 hours and SSRF-safe. They must reuse the outbox, without a wildcard subscriber and without a `next_attempt_at` sweeper (CLAUDE.md 4a).
- E22 is being built at the same time in an `integrations` app. That app holds *outbound* OAuth connections to providers such as Google and Zoom.

## Decision
1. **A separate `developer` app for the inbound platform.** It holds API keys, OAuth clients, grants and tokens, webhook endpoints, deliveries and attempts, sandboxes, the scope catalogue and the marketplace registry.
   - E22's `integrations` app owns `IntegrationConnection`: OAuth *client* connections from TutorTrack to providers. The developer app is the OAuth *server* for apps that connect to TutorTrack.
   - The two never share tables. The marketplace page is the only meeting point: integrations register a status callback through `developer.marketplace.register` or their own `marketplace.py`.
2. **Tokens identify their tenant through a platform routing table.**
   - Every token embeds a random 12-character prefix (`ttk_<prefix>_<secret>`).
   - `CredentialRoute(prefix → organisation_id)` has no RLS, like `payments.AccountRoute`, and is the only lookup made before a tenant is known. The key or token row itself is then read inside `tenant_context`, under RLS. Only SHA-256 hashes of tokens are stored.
   - `OAuthApplication` is also platform-level, because clients are identified by `client_id` on the token endpoint and partner apps serve every tenant. Tenant-registered apps carry `owner_organisation_id`; selectors and `application_for` filter to it.
3. **Authentication is a middleware plus a DRF authenticator.**
   - `ApiTokenMiddleware` (before `TenantMiddleware`) authenticates the token, sets `request.user` and applies the per-token rate limit.
   - `developer.auth.resolve` (`TENANT_RESOLVER`) makes the token's organisation the tenant and resolves to "unknown" (404) when the token is used on another tenant's address.
   - `ApiTokenAuthentication` is first in DRF's authentication classes and simply returns the middleware's user. Token requests therefore never reach `SessionAuthentication` or its CSRF check, and session requests behave exactly as before.
4. **A token acts as a person, narrowed by scopes.**
   - API keys act as their creator and OAuth tokens as the consenting user, so audit actors, data scopes (all/branch/own) and field permissions keep working unchanged.
   - Scopes map to permission patterns. `core.permissions.has_perm`, `scope_queryset` and `permission_scope` additionally require a codename to match `user.token_permissions` when that attribute is present: a few lines in core and no change in any app.
   - On top of this, `process_view` refuses internal views and checks the resource scope (read for safe methods, write for others). Public views are declared by class path in `developer/scopes.py`, so apps don't change, and the OpenAPI schema is tagged from the same registry.
5. **Own OAuth2 provider, not django-oauth-toolkit.** DOT's grant and token tables are global and keyed by user, which fits neither RLS nor per-organisation grants, and adding it would change shared dependencies during a parallel merge. The provider is small: authorisation code with PKCE, rotating refresh tokens with reuse detection, and RFC 7009 revocation. It reuses the same token format and routing as API keys.
6. **Webhook delivery is a Temporal workflow per delivery.**
   - An outbox subscriber, registered for each public event type by name, creates a `WebhookDelivery` with a frozen payload for each matching endpoint (idempotent per endpoint and event), then starts `WebhookDeliveryWorkflow`.
   - The workflow makes up to 15 attempts with backoff timers over about 72 hours. Activities sign, POST through `core.net.safe_urlopen` and log each attempt using the workflow's clock.
   - Endpoint health (`failing_since`, auto-disable after three days, admin email) is updated in the attempt activity.
   - Celery Beat keeps only the 30-day log purge, which is global housekeeping.
7. **Rate limits use the shared cache.** Fixed per-minute and per-second windows are keyed by token prefix in the Django cache (Redis in production). This avoids a new dependency, and every token response carries `X-RateLimit-*` headers.

## Consequences
- A key stops working when its creator leaves or loses a permission. This is safer, and it matches how personal access tokens behave elsewhere. Organisations that want a durable integration should create the key as a dedicated service member.
- Adding a public endpoint is a one-line registry change plus its scope mapping. A test checks that every scope pattern matches a registered permission and that every public view path resolves.
- One workflow per delivery means many short workflows for busy endpoints. The delivery log shows each delivery's timeline, and nothing needs a sweeper. If volume demands it later, deliveries can be batched per endpoint behind the same API.
- The Zapier and Make packages are generated from a served manifest, outside this repo.
- Sandboxes are separate organisations. Provider connections are not copied, so no sandbox action can reach a live payment, calendar or accounting account.
