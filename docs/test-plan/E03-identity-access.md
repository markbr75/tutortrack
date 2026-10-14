# E03 — Identity, authentication and access control: manual tests

**Scope.** Users, password / magic-link / Google and Microsoft SSO sign-in, TOTP 2FA with recovery codes and the "require 2FA for staff" setting, passkeys (Phase 2), sessions (idle timeout, remember me, revoke), lockout, invitations and team management, built-in roles with data scopes (`all`/`branch`/`own`) and field permissions, tutor access toggles, impersonation ("View as"), custom roles (Phase 2) and per-organisation SAML/OIDC SSO (Phase 2). Spec: [E03](../epics/E03-identity-access.md).

**Built differently from the spec:** built-in roles live in code (`backend/tutortrack/identity/roles.py`), one role per membership (custom roles replace the built-in grants with their union); Google/Microsoft/Apple SSO uses OIDC on PyJWT (no allauth); Apple needs an https `APP_URL` and `APPLE_*` credentials, so locally it is tested with the fake in the automated tests; MFA is TOTP plus passkeys (no SMS); lockout is a progressive delay (429 with `Retry-After`) after 5 failures in 15 minutes; tutor toggles and security settings have no admin form yet, so they are set through `PATCH /api/v1/settings/tutor_access` and `/api/v1/settings/security`; passkeys don't work on custom domains (E24); guardian-managed username + PIN logins for children under 13 are set up by the guardian in the portal (E15, gap G2); SAML encrypted assertions, IdP-initiated SAML, single logout and SCIM are not supported.

**Common preconditions.** Seeded accounts (see [README](README.md)); password `tutortrack`. Admin app http://brightminds.localhost:5173; portal http://brightminds.localhost:5174/portal/ (the session cookie is shared across ports on the same host, so a portal user can sign in at the admin `/login` and then open the portal, or use the portal's emailed sign-in link). Mailpit for emails. An authenticator app (or `oathtool --totp -b <secret>`) for TOTP. Chrome DevTools → WebAuthn virtual authenticator for passkeys.

## Sign-in, sign-out and passwords

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E03-001 | Password sign-in | Owner | — | 1. Open `/login`, enter admin@tutortrack.localhost / tutortrack, **Sign in**. | Lands on **Welcome**; nav reflects Owner permissions. | P1 | backend: `tutortrack/identity/tests/test_auth.py`; e2e: `e2e/smoke.spec.ts` | |
| TP-E03-002 | Each seeded staff role can sign in | Admin, Branch Manager, Coordinator, Finance, Tutor | — | 1. Sign in as office@, manager@, coordinator@, finance@, tutor@ in turn. | Each reaches the app; the nav differs per role (see Permissions). | P1 | e2e: `e2e/roles.spec.ts` | |
| TP-E03-003 | Wrong password gives a uniform error | Anonymous | — | 1. Sign in with admin@ and a wrong password.<br>2. Sign in with `nobody@example.com`. | Same generic error both times (no "user not found"); attempts recorded under Account → Recent sign-ins as "Failed attempt". | P1 | backend: `tutortrack/identity/tests/test_auth.py`; e2e: `e2e/roles.spec.ts` | |
| TP-E03-004 | Progressive lockout | Anonymous | A throwaway user | 1. Enter a wrong password 6 times within 15 minutes.<br>2. Try the right password straight away. | After 5 failures the API returns 429 with `Retry-After` (30 s doubling, max 15 min); the right password works once the delay passes. | P1 | backend: `tutortrack/identity/tests/test_auth.py` | |
| TP-E03-005 | Sign out | Coordinator | Signed in | 1. Open the user menu → **Sign out**.<br>2. Press Back. | Returned to sign-in; protected pages and API calls now fail with 401/403. | P1 | backend: `tutortrack/identity/tests/test_auth.py`; e2e: `e2e/roles.spec.ts` | |
| TP-E03-006 | Magic-link sign-in | Parent | parent@ | 1. On `/login` press **Email me a sign-in link** with parent@tutortrack.localhost.<br>2. Open the link from Mailpit. | "Signing you in…" then signed in. A second click: "This sign-in link is invalid or has expired." | P1 | backend: `tutortrack/identity/tests/test_auth.py` | |
| TP-E03-007 | Magic link expires after 15 minutes | Parent | — | 1. Request a link, wait 16 minutes, open it. | Invalid/expired message. | P3 | backend: `tutortrack/identity/tests/test_auth.py` | |
| TP-E03-008 | Unknown emails get the same response | Anonymous | — | 1. Request a magic link and a password reset for `nobody@example.com`. | Same "If an account exists…" message; no email sent. | P2 | backend: `tutortrack/identity/tests/test_auth.py` | |
| TP-E03-009 | Password reset | Coordinator | — | 1. **Forgot your password?** → coordinator@ → **Send reset link**.<br>2. Open the link, choose a new strong password, **Save password**.<br>3. Sign in with it. Reset back afterwards. | "Your password has been changed…"; all other sessions are signed out; the link can't be reused; expires after 1 hour. | P1 | backend: `tutortrack/identity/tests/test_auth.py` | |
| TP-E03-010 | Weak and breached passwords are refused | Coordinator | Network access for HIBP (`PWNED_PASSWORDS_CHECK=true`) | 1. Account → change password to `qwerty123`.<br>2. Try `Password123!` (known breached). | Both refused with a clear reason (strength score < 3 / seen in a breach). | P2 | backend: `tutortrack/identity/tests/test_auth.py` | |
| TP-E03-011 | Change password keeps only this session | Coordinator | Signed in on two browsers | 1. Account → **Change password** in browser A. | "Password changed. Other devices have been signed out."; browser B is signed out. | P2 | backend: `tutortrack/identity/tests/test_auth.py` | |
| TP-E03-012 | New-device alert | Coordinator | — | 1. Sign in from a new browser profile. | "New sign-in" email in Mailpit. | P3 | backend: `tutortrack/identity/tests/test_auth.py` | |
| TP-E03-013 | Email is case-insensitive | Owner | — | 1. Sign in as `ADMIN@TutorTrack.Localhost`. | Works. | P3 | backend: `tutortrack/identity/tests/test_user.py` | |

## Sessions

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E03-014 | Active sessions list and revoke | Owner | Signed in on two browsers | 1. Account → **Where you're signed in**.<br>2. **Sign out** the other session.<br>3. **Sign out of all other devices**. | Sessions list with "This device" and last active; the revoked browser is signed out on its next request. | P1 | backend: `tutortrack/identity/tests/test_auth.py` | |
| TP-E03-015 | Idle timeout | Coordinator | `PATCH /api/v1/settings/security` `staff_idle_timeout_hours: 1` | 1. Sign in without "Keep me signed in", stay idle over an hour (or edit `UserSession.last_seen_at` in the DB). | Signed out on the next request. With **Keep me signed in on this device** the session lasts 30 days. | P3 | backend: `tutortrack/identity/tests/test_auth.py` | |

## Two-factor authentication and passkeys

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E03-016 | Turn on TOTP 2FA | Owner | Authenticator app | 1. Account → **Set up authenticator app**, scan the QR code.<br>2. Enter the 6-digit code → **Turn on**.<br>3. Save the recovery codes. | "Two-factor authentication is on."; 10 recovery codes shown once. | P1 | backend: `tutortrack/identity/tests/test_auth.py` | |
| TP-E03-017 | Sign in with 2FA | Owner | 2FA on | 1. Sign out, sign in with password.<br>2. Enter the code on **Two-factor authentication** → **Verify**. | Signed in only after the code. A reused code in the same 30-s step is refused. | P1 | backend: `tutortrack/identity/tests/test_auth.py` | |
| TP-E03-018 | Recovery code works once | Owner | 2FA on | 1. Sign in using a recovery code instead of the app code.<br>2. Try the same code again. | First works; second refused. **New recovery codes** replaces the set. | P2 | backend: `tutortrack/identity/tests/test_auth.py` | |
| TP-E03-019 | Turn off 2FA needs the password | Owner | 2FA on | 1. Account → **Turn off**, enter the password. | 2FA off; without the right password it is refused. | P2 | backend: `tutortrack/identity/tests/test_auth.py` | |
| TP-E03-020 | Enforced 2FA for staff | Owner, Coordinator | `PATCH /api/v1/settings/security` `require_mfa_for_staff: true`; coordinator@ without 2FA | 1. Sign in as coordinator@.<br>2. Try any page other than Account. | Forced into 2FA enrolment; API calls return 403 `mfa-enrolment-required` until enrolled. | P1 | backend: `tutortrack/identity/tests/test_auth.py` | |
| TP-E03-021 | Enforced 2FA does not affect portal users | Parent | As above | 1. Sign in as parent@ and open the portal. | Portal works without 2FA. | P2 | backend: `tutortrack/identity/tests/test_auth.py` | |
| TP-E03-022 | Add a passkey | Coordinator | Chrome with a virtual authenticator (DevTools → WebAuthn) | 1. Account → Passkeys → **Add a passkey**, name "Work laptop". | Passkey listed with "Not used yet"; MFA turns on and recovery codes are issued for the first passkey. | P2 | backend: `tutortrack/identity/tests/test_phase2.py` | |
| TP-E03-023 | Passkey-only sign-in | Coordinator | Passkey registered | 1. Sign out; on `/login` press **Sign in with a passkey**. | Signed in without a password; "Last used" updates. | P2 | backend: `tutortrack/identity/tests/test_phase2.py` | |
| TP-E03-024 | Passkey as the second factor | Coordinator | Passkey + password | 1. Sign in with the password.<br>2. On the 2FA step press **Use a passkey instead**. | Signed in. | P3 | backend: `tutortrack/identity/tests/test_phase2.py` | |
| TP-E03-025 | Removing the last passkey turns MFA off | Coordinator | One passkey, no TOTP | 1. **Remove** the passkey. | MFA status changes to off. | P3 | backend: `tutortrack/identity/tests/test_phase2.py` | |

## Single sign-on

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E03-026 | Google / Microsoft buttons only when configured | Anonymous | `GOOGLE_CLIENT_ID` empty (default) | 1. Open `/login`. | No "Continue with Google/Microsoft" buttons; `/api/v1/auth/sso/google/start` is 404. | P2 | backend: `tutortrack/identity/tests/test_sso.py` | |
| TP-E03-027 | Google sign-in links an existing user | Owner | Real Google OAuth client (needs credentials) | 1. Press **Continue with Google** with a Google account whose verified email is a member. | Signed in to the organisation via the handoff; account linked; users with 2FA still asked for the code. | P3 | backend: `tutortrack/identity/tests/test_sso.py` | |
| TP-E03-028 | Configure organisation SSO (OIDC) | Owner | `sso_saml` entitlement (Enterprise plan or platform override); a test IdP (e.g. a local Keycloak) | 1. **Single sign-on** (`/settings/sso`): Protocol OIDC, Issuer URL, Client ID, Client secret, Email domains `school.org`, Add new people automatically.<br>2. **Turn on single sign-on**, **Save**. | Saved; secret shows "A secret is saved…". Login page shows the organisation's SSO button. | P2 | backend: `tutortrack/identity/tests/test_phase2.py` | |
| TP-E03-029 | Configure organisation SSO (SAML) | Owner | As above, SAML IdP | 1. Choose SAML; enter IdP entity ID, sign-in URL and PEM certificate.<br>2. Copy Entity ID and Reply URL (ACS) into the IdP.<br>3. Sign in through the IdP. | Member signs in; SP metadata at `/api/v1/auth/org-sso/metadata`; a tampered assertion is rejected. | P3 | backend: `tutortrack/identity/tests/test_phase2.py` | |
| TP-E03-030 | Enforced SSO blocks passwords for the domain | Anonymous | "Require single sign-on for these domains" on | 1. Try password and magic-link sign-in with an address in the SSO domain. | Refused with `sso-required` and pointed to the SSO button; other domains still use passwords. | P2 | backend: `tutortrack/identity/tests/test_phase2.py` | |
| TP-E03-031 | SSO needs the entitlement | Owner | Plan without `sso_saml` | 1. Try to turn SSO on. | Upgrade prompt (`upgrade_required`). | P3 | backend: `tutortrack/identity/tests/test_phase2.py` | |

## Team and invitations

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E03-032 | Invite a staff member | Owner | Unused email `newcoord@example.com` | 1. **Team** → **Invite someone**, email, role Coordinator → **Send invitation**. | "Invitation sent to …"; listed under Pending invitations with an expiry 7 days ahead; email in Mailpit with a link on brightminds.localhost. | P1 | backend: `tutortrack/identity/tests/test_team.py` | |
| TP-E03-033 | New person accepts the invitation | Invitee | After TP-E03-032 | 1. Open the email link.<br>2. "Join Bright Minds Tutoring" → create a password → **Accept invitation**. | Signed in as Coordinator; email marked verified; member listed as Active. | P1 | backend: `tutortrack/identity/tests/test_team.py` | |
| TP-E03-034 | Existing user must sign in to accept | Invitee | Invite owner@northside.localhost to brightminds | 1. Open the link signed out. | "You already have an account. Sign in as … " — after signing in as that email the invitation is accepted. Signed in as another email: refused. | P2 | backend: `tutortrack/identity/tests/test_team.py` | |
| TP-E03-035 | Resend and revoke | Owner | Pending invitation | 1. **Resend**: old link stops working, new one works.<br>2. **Revoke** another invitation and open its link. | Revoked/expired links show "This invitation is invalid or has expired." | P2 | backend: `tutortrack/identity/tests/test_team.py` | |
| TP-E03-036 | Bulk invite | Owner | Swagger | 1. `POST /api/v1/invitations/bulk` with three emails. | Three invitations created; duplicates reported, not re-sent. | P3 | backend: `tutortrack/identity/tests/test_team.py` | |
| TP-E03-037 | Change role and branch scope | Owner | Member newcoord@ | 1. Team → change role to Finance; for Branch Manager pick selected branches. | Change saved and audited; the member's nav changes on next load. Selected scope requires at least one branch. | P1 | backend: `tutortrack/identity/tests/test_team.py` | |
| TP-E03-038 | Remove a member ends access immediately | Owner | newcoord@ signed in elsewhere | 1. Team → **Remove**. | The removed member's next request fails; their open tasks are reassigned. | P1 | backend: `tutortrack/identity/tests/test_team.py` | |
| TP-E03-039 | Last owner and self protection | Owner | Only one owner | 1. Try to remove yourself or change your own role.<br>2. Try to remove the only owner. | Refused with a clear message. | P2 | backend: `tutortrack/identity/tests/test_team.py` | |
| TP-E03-040 | Only team managers can invite | Coordinator, Tutor | — | 1. As coordinator@ open Team: no **Invite someone**.<br>2. As tutor@ call `POST /api/v1/invitations`. | Coordinator can view the team (`team.view`) but not invite; tutor gets 403. | P1 | backend: `tutortrack/identity/tests/test_team.py` | |
| TP-E03-041 | Tutor limit on invitations | Owner | Org on Solo plan with one tutor | 1. Invite a second tutor. | Upgrade dialog (`upgrade_required`, Team plan). After upgrading, the invite succeeds without a reload. | P2 | backend: `tutortrack/subscriptions/tests/test_subscriptions.py` | |

## Roles, scopes and field permissions

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E03-042 | Navigation per role | All staff roles | — | 1. Sign in as each staff account and note the nav. | Owner/Admin: everything (Admin has no subscription management; Safeguarding only for DSLs). Coordinator: people, jobs, calendar, enquiries, inbox, courses, learning; Billing view only; no Payroll, no Audit log. Finance: Billing, Payroll, Reports, Billing & plan (view); no Calendar edit, no Jobs. Tutor: own calendar, availability, lesson reports, tasks. | P1 | backend: `tutortrack/identity/tests/test_rbac.py`; e2e: `e2e/roles.spec.ts` | |
| TP-E03-043 | Admin can't manage the subscription | Admin | office@ | 1. Open Settings → Billing & plan. | Plan visible; change plan, cancel and buy credits are not offered (owner-only); API returns 403. | P1 | backend: `tutortrack/identity/tests/test_rbac.py` | |
| TP-E03-044 | Tutor sees only their own records | Tutor | tutor@ = Nia Adeyemi | 1. `GET /api/v1/lessons` and `/api/v1/students`.<br>2. Open a lesson of Sam Clarke by ID (`/api/v1/lessons/<id>`). | Only Nia's lessons and students on her jobs (Arjun). Another tutor's lesson is **404**, not 403. | P1 | backend: `tutortrack/identity/tests/test_rbac.py` | |
| TP-E03-045 | Tutors never see charge rates | Tutor | tutor@ | 1. Inspect `/api/v1/lessons`, `/api/v1/jobs/<Arjun's job>`, `/api/v1/catalogue/services` responses. | No `charge_rate` / charge amounts anywhere; pay is visible only on own lessons. | P1 | backend: `tutortrack/identity/tests/test_rbac.py` | |
| TP-E03-046 | Coordinators without view_pay never see pay rates | Coordinator | coordinator@ (no `billing.rates.view_pay`) | 1. Open a job page and Catalogue → Services; inspect the API. | Charge rates visible (`view_charge`), pay rates absent; sending a pay rate in a PATCH is ignored/refused. | P1 | backend: `tutortrack/identity/tests/test_rbac.py` | |
| TP-E03-047 | Branch Manager limited to their branches | Branch Manager | manager@ scoped to MAIN; `multi_branch` on with a second branch | 1. Open Clients, Students, Calendar, Jobs. | Only MAIN-branch records; no Settings → Branches management; no Audit log. | P1 | backend: `tutortrack/identity/tests/test_rbac.py` | |
| TP-E03-048 | Permission registry and roles API | Owner | Swagger | 1. `GET /api/v1/permissions` and `/api/v1/roles`. | Every app's codenames with descriptions; built-in and custom roles listed. | P3 | backend: `tutortrack/identity/tests/test_rbac.py` | |

## Tutor access toggles

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E03-049 | Client contact details for tutors | Tutor | `PATCH /api/v1/settings/tutor_access` `client_contact_details`: none → phone → full | 1. After each change, as tutor@ open Arjun's family contact (portal → Students, or API). | none: no phone/email; phone: phone only; full: phone and email. | P1 | backend: `tutortrack/identity/tests/test_rbac.py` | |
| TP-E03-050 | Create / cancel lesson toggles | Tutor | `create_lessons` and `cancel_lessons` off (default), then on | 1. As tutor@ try to create a lesson and cancel one of Nia's lessons (portal or API). | Off: refused (403). On: allowed for own lessons only. Toggles never affect other roles. | P2 | backend: `tutortrack/identity/tests/test_rbac.py` | |
| TP-E03-051 | Reschedule toggle (default on) and edit rates (default off) | Tutor | Defaults | 1. As tutor@ move one of Nia's lessons; try to change its rate. | Move allowed; rate change refused. | P2 | backend: `tutortrack/identity/tests/test_rbac.py` | |

## Impersonation ("View as")

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E03-052 | Admin views as a tutor, read-only | Admin | office@; tutor@ is a member | 1. Team → Nia Adeyemi → **View as**.<br>2. Try to write a lesson report. | Banner "You're viewing as Nia Adeyemi. Read-only." with **Stop viewing as**; writes refused. | P1 | backend: `tutortrack/identity/tests/test_impersonation.py` | |
| TP-E03-053 | Impersonated actions are audited | Owner | Owner enabled write (`impersonation.write`) | 1. View as parent@ with write on and change a profile field.<br>2. Open Audit log. | The entry shows the impersonator as well as the user. | P2 | backend: `tutortrack/identity/tests/test_impersonation.py` | |
| TP-E03-054 | Who can be impersonated | Admin | — | 1. Try **View as** on an Owner, another Admin, a Coordinator. | Only tutor, client and student members can be impersonated; tutors can't impersonate anyone. | P2 | backend: `tutortrack/identity/tests/test_impersonation.py` | |

## Custom roles (Phase 2)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E03-055 | Clone a built-in role | Owner | — | 1. **Roles** (`/team/roles`) → Role name "Senior coordinator", Start from Coordinator → **Create role**. | Matrix grouped by category, each permission set to No / Their own / Their branches / Everyone as in Coordinator. | P2 | backend: `tutortrack/identity/tests/test_phase2.py` | |
| TP-E03-056 | Edit the matrix and assign a member | Owner | Role from TP-E03-055 | 1. Give `billing.rates.view_pay` → Everyone, **Save changes**.<br>2. Assign the role to coordinator@ (Team).<br>3. Sign in as coordinator@ and open a job. | Pay rates now visible; the member's permissions are the union of their custom roles instead of Coordinator. | P2 | backend: `tutortrack/identity/tests/test_phase2.py` | |
| TP-E03-057 | Custom role rules | Owner | — | 1. Try to give a custom role to an Owner or a portal user.<br>2. Try to grant `subscription.manage`.<br>3. Change your own roles. | All refused. | P2 | backend: `tutortrack/identity/tests/test_phase2.py` | |
| TP-E03-058 | Archive a custom role | Owner | Role assigned to a member | 1. **Archive** the role. | Removed from members, who fall back to their built-in role. | P3 | backend: `tutortrack/identity/tests/test_phase2.py` | |

## Tenant isolation

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E03-059 | Permissions never carry across organisations | Owner | admin@ (brightminds owner) | 1. Call `GET /api/v1/clients` on northside.localhost:8010 with admin@'s session. | 403/404; owning brightminds gives nothing in northside. (admin@ is also platform superuser: test with office@ for a clean result.) | P1 | backend: `tutortrack/identity/tests/test_rbac.py`; e2e: `e2e/roles.spec.ts` | |
| TP-E03-060 | Can't impersonate another organisation's member | Admin | office@ | 1. `POST /api/v1/impersonate` with a northside user ID. | Refused (404). | P1 | backend: `tutortrack/identity/tests/test_impersonation.py` | |
| TP-E03-061 | Invitation acceptance runs in its own tenant | Invitee | Invitation from northside | 1. Open a northside invitation link while on brightminds. | The link points to northside.localhost; accepting creates the membership only in northside. | P2 | backend: `tutortrack/identity/tests/test_team.py` | |

## i18n and edge cases

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E03-062 | Profile timezone and names | Coordinator | — | 1. Account → set Preferred name, Pronouns, Phone, Timezone America/New_York.<br>2. Open the calendar. | Saved; lesson times show in New York time for this user. | P2 | No | |
| TP-E03-063 | Auth endpoints are rate-limited | Anonymous | — | 1. Hit `/api/v1/auth/magic-link` 11 times in an hour for one address/IP. | 429 after the limit (10/hour); login limit 30/minute. | P2 | backend: `tutortrack/identity/tests/test_auth.py` | |
| TP-E03-064 | Users without a membership can still sign in on the root host | Platform staff | platform@tutortrack.localhost (no organisation) | 1. Sign in at http://localhost:5173/login. | Signed in; no organisation data; the platform console is reachable (after 2FA). | P2 | backend: `tutortrack/identity/tests/test_auth.py` | |

## Gap batch G2 (2026-10-14): Sign in with Apple and change email

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E03-065 | Continue with Apple | Anonymous / existing user | Staging with https `APP_URL` and `APPLE_CLIENT_ID`, `APPLE_TEAM_ID`, `APPLE_KEY_ID`, `APPLE_PRIVATE_KEY`; the callback `https://<app>/api/v1/auth/sso/apple/callback` registered at Apple | 1. `/login` → **Continue with Apple**; sign in at Apple (share or hide the email).<br>2. Repeat with `intent=signup` for a new Apple ID. | 1: an existing user with that verified email is signed in and linked. 2: a new account is created with the name Apple sends the first time (a private-relay address is accepted). Apple posts back to the callback; errors return to `/login?error=sso_…`. | P2 | backend: `tutortrack/identity/tests/test_sso_apple.py` | |
| TP-E03-066 | Apple hidden without credentials | Anonymous | Local dev without `APPLE_*` | 1. Open `/login`.<br>2. Open `/api/v1/auth/sso/apple/start`. | No Apple button; the start URL is 404. | P3 | backend: `tutortrack/identity/tests/test_sso_apple.py` | |
| TP-E03-067 | Change email: link to the new address, notice to the old | Admin | Mailpit; signed in on two browsers | 1. Account → **Email address**: new address and current password → **Change email**.<br>2. Check Mailpit.<br>3. Open the link from the new address's email in browser A. | 1: "We've sent a link to …". 2: a confirmation link to the new address and a "change requested" notice to the old one. 3: "Your email address is now …"; browser B is signed out; the old address gets a "has changed" notice; you sign in with the new address. Audit shows `email_change_requested` and `email_change`. | P1 | backend: `tutortrack/identity/tests/test_email_change.py` | |
| TP-E03-068 | Change email rules | Admin | — | 1. Wrong password.<br>2. An address another account uses.<br>3. Open the same confirmation link twice; open an expired or edited link. | 1: refused. 2: "Another account uses this email address." 3: the second and tampered links say the link is invalid or has expired; nothing changes. | P2 | backend: `tutortrack/identity/tests/test_email_change.py` | |

## Gap batch G4 (2026-10-14): account emails on comms templates

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E03-069 | Identity emails use the organisation's branding and wording | Owner | Edited "Invitation to join" wording | 1. Invite a tutor; request a password reset; change email; sign in from a new device. | Each email carries the organisation's branding and sender; edited wording is used; secret links never appear in the message log. | P1 | backend: `comms/tests/test_g4.py` account email tests; identity tests (`test_auth.py`, `test_email_change.py`, `test_team.py`) | |
