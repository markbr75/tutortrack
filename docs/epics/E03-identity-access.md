# E03 — Identity, Authentication & Access Control

| | |
|---|---|
| **Phase** | MVP (custom roles in Phase 2) |
| **Depends on** | E01, E02 |
| **Parity** | TutorCruncher 2FA, Google/Apple SSO, role types; TutorBird custom roles and permissions |

## 1. Summary
Global user identities, memberships in organisations, authentication (password, magic link, SSO, 2FA, passkeys), invitations, RBAC with data scopes and field-level visibility, sessions, and API authentication primitives.

## 2. Functional requirements

### FR-03-1 User identity
- `User`: email (unique, case-insensitive), email_verified_at, phone (E.164), phone_verified_at, first/last/preferred name, pronouns (optional), avatar, locale, timezone, password hash (Argon2), is_platform_staff, last_login, MFA settings.
- One login per email across the platform; the same user may be a tutor in Org A and a parent in Org B.
- **Children without email:** Students can have portal logins with a **username + password managed by the guardian** (username unique per org), or no login at all.

### FR-03-2 Authentication methods
- Email + password (zxcvbn strength ≥ 3; HaveIBeenPwned k-anonymity check).
- Magic link sign-in (15-minute single-use token), the default for clients and parents.
- SSO: Google, Microsoft (Entra ID), Apple via `django-allauth`. Enterprise SAML/OIDC per org (plan-gated) via allauth SAML.
- 2FA: TOTP (authenticator apps), WebAuthn/passkeys, 10 recovery codes. Org setting to **enforce 2FA for staff roles**.
- Passkey-only login supported (WebAuthn discoverable credentials).
- Account lockout: progressive delay after 5 failures; alert email on new-device login.
- **AC:** an Owner who enables "require 2FA for staff" forces staff without 2FA into enrolment on next login; API requests from their sessions return 403 `mfa_enrolment_required` until enrolled.

### FR-03-3 Sessions
- Server-side sessions (Redis), HttpOnly, Secure, SameSite=Lax cookies; CSRF for unsafe methods.
- Idle timeout (org setting, default 8h for staff, 30 days for portal "remember me").
- Active sessions list with revoke; "sign out all devices".

### FR-03-4 Memberships and invitations
- `Membership(user, organisation, status: invited|active|suspended|removed, roles[], branch_scope: all|selected, branches[], title, joined_at)`.
- Invite flow: staff enters email and role(s) → email with a 7-day token → the recipient creates a password or uses SSO → membership active. Resend and revoke.
- Client and student portal invitations are sent from E05 records (Contact/Student) using the same mechanism.
- Bulk invite (CSV, or "invite all contacts without a login").
- Removing a membership revokes sessions for that org and reassigns open tasks.

### FR-03-5 Roles and permissions (RBAC)
- Permission registry: each app declares codenames with a description and category, e.g. `people.client.view`, `people.client.edit`, `billing.invoice.issue`, `billing.rates.view_pay`, `payroll.payrun.approve`.
- **Built-in roles** (non-editable, cloneable):

| Role | Summary |
|---|---|
| Owner | Everything, including subscription and org close. At least one is required. |
| Admin | Everything except subscription/ownership transfer |
| Branch Manager | Admin rights within assigned branches |
| Coordinator | People, jobs, scheduling, comms, leads; no finance settings; can view invoices |
| Finance | Billing, payments, payroll, accounting integrations, reports |
| Tutor | Own schedule, own students' profiles (limited fields), lesson reports, own pay, own expenses, availability |
| Client (Contact) | Portal: own household's students, lessons, invoices, payments, reports |
| Student | Portal: own lessons, homework, resources, reports (if shared) |
| Affiliate | Affiliate portal |

- **Custom roles** (Phase 2): clone and edit a permission matrix UI grouped by category; assign one or more roles per membership (union of permissions).
- **Data scopes** per permission: `all`, `branch`, `own`. E.g. Tutor has `scheduling.lesson.view:own`. Scopes are evaluated in selectors via `scope_queryset(user, qs, permission)`.
- **Field-level permissions:** `billing.rates.view_charge`, `billing.rates.view_pay`, `people.student.view_sensitive` (DOB, medical/SEN notes), `people.safeguarding.view`. Serializers use `FieldPermissionMixin` to drop fields.
- **AC:** a Tutor calling `GET /api/v1/lessons/{id}` for another tutor's lesson gets 404 (not 403, to avoid leaking existence).
- **AC:** a Tutor never sees `charge_rate` in any payload; a Coordinator without `billing.rates.view_pay` never sees `pay_rate`.

### FR-03-6 Tutor-specific access settings (org-configurable)
- Tutors may: view client contact details (none/phone only/full); message clients directly or only via platform; create lessons; reschedule lessons; cancel lessons; edit rates (never by default); see other tutors' calendars; add new students. These toggles map to permissions on the Tutor role (TutorCruncher and TutorBird both offer these).

### FR-03-7 Impersonation ("log in as")
- Owners/Admins can view the portal **as** a client, student or tutor in their own org (read-only by default, with a write toggle for the Owner); platform staff via E30 with reason capture.
- Banner shown; every action is audited with `impersonator_user_id`.

### FR-03-8 API authentication primitives
- Personal access tokens and org API keys (E27 builds the UI). Hashed storage (prefix shown, secret shown once), scopes, expiry, last used.
- OAuth2 provider (`django-oauth-toolkit`) for third-party apps (E27).

### FR-03-9 Account self-service
- Profile edit, change email (verify new + notify old), change password, manage 2FA/passkeys, connected SSO accounts, notification preferences (E13), data download request (E29).

## 3. Data model
`User`, `Membership`, `Role(org nullable for built-in, name, key, is_builtin)`, `RolePermission(role, permission_codename, scope)`, `MembershipRole`, `MembershipBranch`, `Invitation(token_hash, email, roles, expires_at, accepted_at, target_object generic)`, `MFADevice`, `RecoveryCode`, `WebAuthnCredential`, `LoginEvent(user, ip, ua, success, method, created_at)`, `ApiKey`.

## 4. API
`/api/v1/auth/{login,logout,magic-link,magic-link/verify,password/reset,password/reset/confirm,mfa/verify,mfa/totp/setup,webauthn/*,sso/{provider}}`, `/api/v1/me`, `/api/v1/me/sessions`, `/api/v1/memberships`, `/api/v1/invitations`, `/api/v1/roles`, `/api/v1/permissions` (registry), `/api/v1/impersonate`.

## 5. Events
`user.invited`, `user.joined`, `user.logged_in`, `user.login_failed`, `user.mfa_enabled`, `membership.role_changed`, `membership.deactivated`, `impersonation.started/ended`.

## 6. Non-functional and security
- OWASP ASVS L2 auth controls; rate limits on all auth endpoints; uniform error messages (no user enumeration).
- Password reset tokens single-use with a 1h expiry.
- Audit all role and permission changes.

## 7. Delivery plan
- [x] **E03-T01** User model, Argon2, email/password login, logout, sessions, password reset.
- [x] **E03-T02** Magic link login; new-device alerts; lockout and rate limiting.
- [x] **E03-T03** Membership model, branch scope, invitations (staff), org switcher integration.
- [x] **E03-T04** Permission registry, built-in roles, `has_perm(user, codename, obj)` and `scope_queryset`; DRF permission classes.
- [x] **E03-T05** Field-level permission serializer mixin; charge/pay rate visibility tests.
- [x] **E03-T06** TOTP 2FA, recovery codes, enforce-2FA org setting.
- [x] **E03-T07** Google/Microsoft/Apple SSO via allauth.
- [ ] **E03-T08** WebAuthn/passkeys. *(Phase 2: not in the roadmap's Phase 1 scope for E03.)*
- [x] **E03-T09** Tutor access toggles (settings → permissions mapping).
- [x] **E03-T10** Impersonation with banner and audit.
- [ ] **E03-T11** (Phase 2) Custom roles UI and permission matrix.
- [ ] **E03-T12** (Phase 2/Enterprise) SAML/OIDC per org.
- [x] **E03-T13** Frontend: login, MFA, account settings, team and invitations pages.

## 8. Implementation notes (as built, 2026-10-09)

Where the build differs from, or adds to, the requirements above. Later epics should treat
these as the source of truth. Decisions: [ADR 0004](../adr/0004-identity-roles-and-sso.md).

| Area | As built | Why |
|---|---|---|
| Scope | Phase 1 per the roadmap: T01–T07, T09, T10, T13. **T08 passkeys, T11 custom roles, T12 SAML/OIDC per org are Phase 2** | Roadmap scope |
| Roles (FR-03-5) | Built-in roles are defined **in code** (`identity/roles.py`) as grant patterns `"<codename pattern>:<scope>"` (`*`, `billing.*`, `scheduling.lesson.view:own`) plus `denies`. One role per membership (`Membership.role`, from E02). No `Role`/`RolePermission`/`MembershipRole` tables yet: they arrive with custom roles (T11) using the same grant format | Patterns let later apps' permissions flow into roles without edits; no DB rows to keep in sync for built-ins |
| Permission registry | Each app declares `PERMISSIONS = {codename: description}` in `<app>/permissions.py`; `core.permission_registry.all_permissions()`; `/api/v1/permissions`, `/api/v1/roles` | |
| has_perm / scopes | `core.permissions.has_perm(user, codename, obj)` → `identity.backends.RBACBackend` → `identity.rbac`. Object checks: `branch` uses `obj.branch_id`; `own` uses `obj.is_owned_by(user)` or the model's `own_scope_q(user)`. `core.permissions.scope_queryset(user, qs, codename)` for selectors. Superusers (platform staff) hold everything | |
| Field permissions (FR-03-5) | `BaseModelSerializer` honours `Meta.field_permissions = {field: codename}`; hidden fields are dropped from output **and** input | |
| Sessions (FR-03-3) | Every login (API, admin, tests) creates a `UserSession`; `SessionSecurityMiddleware` signs out revoked or idle sessions (8h default; org setting `security.staff_idle_timeout_hours`; "remember me" 30 days). DB session engine in tests, Redis cache sessions in dev/prod | Sessions in the cache can't be listed, so tracking is a separate table |
| MFA (FR-03-2) | TOTP only (pyotp), secrets in `core.crypto.EncryptedField`, codes usable once per step, 10 hashed recovery codes, QR as server-rendered SVG (segno). Org setting `security.require_mfa_for_staff` → staff get 403 `mfa-enrolment-required` except `/me` and `/auth/*` | |
| Encryption | **`core.crypto.EncryptedField` pulled forward from E29**: Fernet/MultiFernet with `FIELD_ENCRYPTION_KEYS` (newest first) and `rotate_field()`. E29 moves keys to KMS | MFA secrets must not be stored in plaintext |
| Passwords | Django validators + zxcvbn (score ≥ 3) + HIBP k-anonymity (fails open on outage; disabled in tests via `PWNED_PASSWORDS_CHECK`) | |
| Lockout | Progressive delay after 5 failures in 15 min (30s doubling, max 15 min), returned as 429 with `Retry-After`; failures are recorded outside the request transaction | |
| Magic link / reset | Magic link: 15 min, single use, hashed `LoginToken`, link on the requesting host. Reset: Django token generator (1h, invalidated by the password change), signs out every session | |
| SSO (FR-03-2) | **Google and Microsoft via OIDC on PyJWT, not django-allauth**. Start/callback on the root app host (one registered redirect URI), state in a signed HttpOnly cookie, PKCE, nonce, JWKS signature check; matching by linked subject, then verified email; new users only with `intent=signup`; continues to the org with the E02 handoff token. Apple is Phase 2 | allauth's account models and flows overlap the API-first auth |
| Invitations (FR-03-4) | Hashed tokens, 7 days, link on the organisation's own address (so acceptance runs in that tenant's RLS context); resend rotates the token; bulk endpoint; existing users must be signed in as the invited email. Removing a member ends access immediately (memberships are checked per request) | |
| Impersonation (FR-03-7) | Owners/admins view as tutor/client/student of their own org; read-only unless the owner enables write (`impersonation.write`); bounded to the organisation; `impersonator_id` in request context → audit; banner from `/me.impersonator`. Platform-staff impersonation is E30 | |
| Tutor toggles (FR-03-6) | Org settings `tutor_access.*` (registered in `identity/org_settings.py`) add grants to the Tutor role (`identity/tutor_access.py`) | |
| Frontend | `/login` (password, magic link, SSO, 2FA step), `/login/magic`, `/forgot-password`, `/reset-password`, `/auth/continue`, `/accept-invite`, `/account`, `/team`; nav gated by `/me.permissions`; impersonation banner. `/me` replaced the `/features` probe and the Django-admin sign-in | |
| New events | `user.mfa_enabled`, `impersonation.started/ended` emitted; `user.login_failed` is a `LoginEvent` row, not an outbox event | Failed logins are high volume |

### Verified
- Backend: 370 tests (all under RLS as the app role), ruff, mypy, migrations check, `check --deploy`, OpenAPI with `--fail-on-warn` (now also a pytest test).
- Frontend: lint, typecheck, 19 admin tests (27 total across packages), production builds.
- Live smoke on the local stack: password login → `/me` → TOTP enrolment → second login requiring 2FA (recovery code) → sessions → disable 2FA → logout.

### Carried forward
- **E05:** contact/student portal invitations use `services.invite(..., target_type=, target_id=)`; implement `own_scope_q` on people models.
- **E08/E09:** lessons implement `own_scope_q`/`is_owned_by` for the Tutor `own` scope.
- **E13:** move the identity emails (verification, magic link, reset, new device, invitation) onto comms templates.
- **E27:** API keys/OAuth tokens (FR-03-8) and `X-Organisation` for token clients.
- **E29:** KMS-managed `FIELD_ENCRYPTION_KEYS`.
- **E30:** platform-staff impersonation with reason capture.
- **Phase 2:** passkeys (T08), custom roles (T11), SAML (T12), Apple sign-in.
- Not built: Playwright E2E for login/onboarding (CI's e2e job only runs on `main` pushes; add with the next e2e pass).
