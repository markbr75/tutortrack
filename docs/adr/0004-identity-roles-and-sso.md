# ADR 0004 — Built-in roles as grant patterns, and OIDC SSO without django-allauth

- **Status:** Accepted
- **Date:** 2026-10-09
- **Epic:** E03

## Context
E03 asks for RBAC with data scopes (`all` / `branch` / `own`) and built-in roles, with
custom roles in Phase 2, and for Google/Microsoft/Apple SSO "via django-allauth". Most
domain apps (billing, scheduling, payroll...) do not exist yet, so their permission
codenames are unknown when roles are defined.

## Decision
1. **Roles are sets of grant patterns.** A grant is `"<codename pattern>:<scope>"` matched
   with shell wildcards against codenames (`"*"`, `"billing.*"`,
   `"scheduling.lesson.view:own"`), plus `denies`. Built-in roles live in code
   (`identity/roles.py`); permissions declared later by new apps are covered automatically.
   Phase 2 custom roles will be database rows in the same format.
2. **One built-in role per membership in Phase 1** (`Membership.role`). Multiple roles per
   membership arrive with custom roles.
3. **RBAC sits behind `core.permissions`** (`has_perm`, `scope_queryset`) through a Django
   auth backend, so call sites never import identity.
4. **SSO is implemented directly on OpenID Connect** (authorization code + PKCE, nonce,
   JWKS-verified ID tokens via PyJWT) for Google and Microsoft. The flow runs on the root
   app host with a single registered redirect URI and hands the session to the tenant host
   with the E02 handoff token.

## Consequences
- Adding an app never requires editing role definitions; reviewing a role means reading
  its patterns (the `/roles` endpoint lists them, `/permissions` lists every codename).
- A broad pattern can grant more than intended as apps grow; `denies` and tests of key
  rules (e.g. tutors never see charge rates) guard against that.
- We own ~200 lines of OIDC code instead of allauth's account/social models. Apple sign-in
  (signed client-secret JWT) and per-org SAML (Phase 2) need more provider code; allauth
  can be reconsidered then.
