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
- [ ] **E03-T01** User model, Argon2, email/password login, logout, sessions, password reset.
- [ ] **E03-T02** Magic link login; new-device alerts; lockout and rate limiting.
- [ ] **E03-T03** Membership model, branch scope, invitations (staff), org switcher integration.
- [ ] **E03-T04** Permission registry, built-in roles, `has_perm(user, codename, obj)` and `scope_queryset`; DRF permission classes.
- [ ] **E03-T05** Field-level permission serializer mixin; charge/pay rate visibility tests.
- [ ] **E03-T06** TOTP 2FA, recovery codes, enforce-2FA org setting.
- [ ] **E03-T07** Google/Microsoft/Apple SSO via allauth.
- [ ] **E03-T08** WebAuthn/passkeys.
- [ ] **E03-T09** Tutor access toggles (settings → permissions mapping).
- [ ] **E03-T10** Impersonation with banner and audit.
- [ ] **E03-T11** (Phase 2) Custom roles UI and permission matrix.
- [ ] **E03-T12** (Phase 2/Enterprise) SAML/OIDC per org.
- [ ] **E03-T13** Frontend: login, MFA, account settings, team and invitations pages.
