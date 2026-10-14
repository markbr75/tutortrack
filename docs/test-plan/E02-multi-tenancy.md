# E02 — Multi-tenancy, organisations and branches: manual tests

**Scope.** Organisation and branch records, tenant resolution (subdomain, former slug, `X-Organisation` header, last active organisation), Postgres row-level security and database roles, organisation and branch settings (incl. terminology), self-serve signup with email verification and session handoff, the onboarding wizard, demo data, the organisation switcher, suspension and closure (with the Temporal `OrganisationClosureWorkflow`). Spec: [E02](../epics/E02-multi-tenancy.md).

**Built differently from the spec:** former slugs redirect with **308**; closed organisations return **410**; suspended organisations are read-only for owners/admins (423) except billing paths, and other members get 403; RLS uses a session-level `set_config` wrapper, not `SET LOCAL`; the onboarding wizard publishes each step and the owning epics apply them (E06 first service, E03 tutor invites, E05 first family, E11 Stripe, E04 trial); closure records the decision at once and the export, 30-day grace (`privacy.closure_grace_days`, min 1), reactivation and deletion run in Temporal; a signed-in user can create further organisations without credentials; the wizard e2e test was not built.

**Common preconditions.** Seeded stack, Mailpit at http://localhost:8025, Temporal UI at http://localhost:8233, Celery worker and Temporal worker running (`manage.py temporal_worker --task-queue all`). brightminds is an **agency** created by the seed (not through the wizard), so the `multi_branch` flag is **off** until a platform override turns it on (see TP-E01-034). Turnstile is skipped locally (empty keys).

## Signup and email verification

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E02-001 | Sign up a new business | Anonymous | Unused email, e.g. `tester+e02@example.com` | 1. Open http://localhost:5173/signup.<br>2. Enter first/last name, email, a strong password, business name "Lakeside Learning", country United Kingdom, type Sole trader; check the web address preview.<br>3. **Create account**. | Account and organisation are created; you continue on `http://lakeside-learning.localhost:5173` already signed in (handoff), at the onboarding wizard. | P1 | backend: `tutortrack/tenancy/tests/test_signup.py` | |
| TP-E02-002 | Verification email works once | New owner | After TP-E02-001 | 1. Open Mailpit and the verification email.<br>2. Follow the link.<br>3. Follow it again. | First click verifies the email; the second shows the link is used or invalid. | P1 | backend: `tutortrack/tenancy/tests/test_signup.py` | |
| TP-E02-003 | Resend verification | New owner | Unverified account | 1. Use the resend option (banner or account page). | A new email arrives; the old link no longer works. | P3 | backend: `tutortrack/tenancy/tests/test_signup.py` | |
| TP-E02-004 | Existing email must sign in instead | Anonymous | Use `admin@tutortrack.localhost` | 1. Sign up with that email. | 422 with "sign in instead" guidance; no organisation created. | P2 | backend: `tutortrack/tenancy/tests/test_signup.py` | |
| TP-E02-005 | Reserved and taken subdomains are refused | Anonymous | — | 1. Try web address `www`, `api` or `admin`.<br>2. Try `brightminds`. | Reserved: refused. Taken: refused with alternative suggestions that are free. | P2 | backend: `tutortrack/tenancy/tests/test_organisations.py` | |
| TP-E02-006 | Weak password is refused | Anonymous | — | 1. Sign up with `password1`. | Field error asking for a stronger password; nothing created. | P2 | backend: `tutortrack/tenancy/tests/test_signup.py` | |
| TP-E02-007 | Signup is rate-limited | Anonymous | `THROTTLE_SIGNUP` default 10/hour | 1. Submit 11 signups from the same IP within an hour (curl loop). | The 11th returns 429 with `Retry-After`. | P3 | backend: `tutortrack/tenancy/tests/test_signup.py` | |
| TP-E02-008 | Turnstile is enforced when configured | Anonymous | `TURNSTILE_SITE_KEY`/`SECRET_KEY` set to Cloudflare test keys | 1. Submit signup without completing the check. | "Please complete the security check."; with keys set and Cloudflare unreachable, signup fails closed. | P3 | backend: `tutortrack/tenancy/tests/test_signup.py` | |
| TP-E02-009 | Handoff token is single-use and organisation-bound | Tester | Capture the `continue_url` from the signup response | 1. Open the continue URL in a private window after it was used. | "Your sign-in link has expired. Please sign in to continue." | P2 | backend: `tutortrack/tenancy/tests/test_signup.py` | |
| TP-E02-010 | Signed-in user adds a second organisation | Owner | Signed in as admin@ on the root host | 1. Open http://localhost:5173/signup while signed in.<br>2. Enter only the business details. | A second organisation is created with admin@ as owner; no password needed. | P2 | backend: `tutortrack/tenancy/tests/test_signup.py` | |

## Onboarding wizard and demo data

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E02-011 | Wizard steps and progress | New owner | New organisation from TP-E02-001 | 1. Walk through **Your business**, **Language, currency and timezone**, **Logo and colour**, **Your first service**, **Your first student**, **Take card payments**, **How you invoice**, then **Finish setup**. | "Step N of M" updates; "You're all set!" at the end. Sole traders do not see **Invite your tutors**. | P1 | backend: `tutortrack/tenancy/tests/test_onboarding.py` | |
| TP-E02-012 | Wizard results land in the owning modules | New owner | After TP-E02-011 with service "Maths" 60 min £40, student "Leo Smith" / parent email | 1. Open Catalogue, Clients, Settings → Billing & plan, Settings. | A service exists; a family with the student exists; a 30-day trial is running; invoicing style matches the choice; timezone/currency/locale saved. | P1 | backend: `tutortrack/tenancy/tests/test_onboarding.py` | |
| TP-E02-013 | Tutors step for agencies sends invitations | New owner | New org with type Agency | 1. On **Invite your tutors**, enter two emails, one per line.<br>2. Check Mailpit. | Two invitation emails arrive; they show under Team → Pending invitations. | P2 | backend: `tutortrack/identity/tests/test_team.py` | |
| TP-E02-014 | Steps can be skipped and revisited | New owner | Mid-wizard | 1. Skip a step.<br>2. Reload the page.<br>3. Go back to the skipped step. | Progress is saved across reload; the skipped step can be completed later. | P2 | backend: `tutortrack/tenancy/tests/test_onboarding.py` | |
| TP-E02-015 | Logo must be an uploaded file | New owner | — | 1. On **Logo and colour**, upload a PNG and pick a colour. | Logo shows in the app header; colour applied. Invalid files are refused. | P3 | backend: `tutortrack/tenancy/tests/test_onboarding.py` | |
| TP-E02-016 | Load and wipe demo data | New owner | New org | 1. Press **Explore with demo data**.<br>2. Browse Clients/Students/Calendar.<br>3. Settings → Demo data → **Wipe demo data**. | "Demo data loaded…" message and sample records appear; wipe removes only the sample records. | P2 | backend: `tutortrack/tenancy/tests/test_switcher_and_demo.py` | |
| TP-E02-017 | Only managers can change onboarding | Coordinator | coordinator@ on brightminds | 1. Open `/onboarding`. | Steps can't be saved (403); no change to the organisation. | P3 | backend: `tutortrack/tenancy/tests/test_onboarding.py` | |

## Tenant resolution

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E02-018 | Subdomain selects the organisation | Owner | — | 1. Open http://brightminds.localhost:5173 and sign in.<br>2. Open http://northside.localhost:5173 and sign in as owner@northside.localhost. | Each app shows its own organisation name and data. | P1 | backend: `tutortrack/tenancy/tests/test_resolution.py`; e2e: `e2e/roles.spec.ts` | |
| TP-E02-019 | Unknown subdomain is 404 | Anonymous | — | 1. `curl -i http://nosuchorg.localhost:8010/api/v1/features`. | 404 problem response. | P2 | backend: `tutortrack/tenancy/tests/test_resolution.py` | |
| TP-E02-020 | Changing the slug keeps a 90-day redirect | Owner | A throwaway org (not brightminds) | 1. Settings → Organisation profile → change **Web address**.<br>2. Open the old address. | Old host redirects with 308 to the new one; the hint says the old address keeps working for 90 days. | P2 | backend: `tutortrack/tenancy/tests/test_organisations.py` | |
| TP-E02-021 | `X-Organisation` header on the root host | Owner | curl with session cookie for admin@ on `localhost:8010` | 1. `GET /api/v1/clients` with `X-Organisation: brightminds`.<br>2. Repeat with `X-Organisation: northside`. | 1: brightminds clients. 2: 403/404, admin@ is not a member of northside. | P2 | backend: `tutortrack/tenancy/tests/test_resolution.py` | |
| TP-E02-022 | Header is ignored on a tenant subdomain | Owner | — | 1. On brightminds.localhost send `X-Organisation: northside`. | brightminds data is returned; the header is ignored. | P2 | backend: `tutortrack/tenancy/tests/test_resolution.py` | |
| TP-E02-023 | Root host uses the last active organisation | Owner | admin@ is member of two orgs (TP-E02-010) | 1. Use org B, then open http://localhost:5173. | The app opens in org B. | P3 | backend: `tutortrack/tenancy/tests/test_resolution.py` | |

## Organisation switcher

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E02-024 | Switch between organisations | Owner | admin@ in two orgs | 1. Open **Switch organisation** in the header.<br>2. Choose the other org. | Most recently used first, current one marked "current"; switching moves to that org's subdomain and data. | P2 | backend: `tutortrack/tenancy/tests/test_switcher_and_demo.py` | |
| TP-E02-025 | Closed and inactive memberships are hidden | Owner | One org closed, one membership removed | 1. Open the switcher. | Closed organisations and removed memberships are not listed. | P3 | backend: `tutortrack/tenancy/tests/test_switcher_and_demo.py` | |

## Settings and terminology

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E02-026 | Edit the organisation profile | Owner | — | 1. Settings → change Legal name, Contact email, Contact phone, Timezone, Brand colour.<br>2. Save and reload. | Values persist; an audit entry is written. | P1 | backend: `tutortrack/tenancy/tests/test_settings_api.py` | |
| TP-E02-027 | Default lesson length | Owner | — | 1. Settings → General → Default lesson length 45.<br>2. Open **New lesson** in the calendar. | New lessons default to 45 minutes where no service default applies. | P3 | backend: `tutortrack/tenancy/tests/test_settings_api.py` | |
| TP-E02-028 | Terminology overrides rename the UI | Owner | — | 1. Settings → Terminology: Tutor → Teacher (singular/plural), Lesson → Session.<br>2. Reload; open nav and calendar. | Labels use "Teacher(s)" and "Session(s)" where the terminology hook is used. | P2 | backend: `tutortrack/tenancy/tests/test_settings_api.py` | |
| TP-E02-029 | Invalid settings values are refused per field | Owner | Swagger | 1. `PATCH /api/v1/settings/general` with `default_lesson_duration: -5`. | 400 with a per-key error; nothing saved. | P3 | backend: `tutortrack/tenancy/tests/test_settings_api.py` | |
| TP-E02-030 | Settings permissions | Coordinator, Tutor | — | 1. As coordinator@, open Settings: fields read-only, save refused.<br>2. As tutor@, `PATCH /api/v1/organisation`. | Coordinator can view (`org.settings.view`) but not change; tutor gets 403. | P1 | backend: `tutortrack/tenancy/tests/test_settings_api.py` | |

## Branches

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E02-031 | Branch UI hidden while `multi_branch` is off | Owner | Seed default | 1. Open Settings. | No Branches section; records use the default branch "Bright Minds Tutoring" (MAIN). | P2 | backend: `tutortrack/tenancy/tests/test_settings_api.py` | |
| TP-E02-032 | Add a branch | Owner | `multi_branch` on (platform override) and plan allows branches | 1. Settings → Branches → **Add branch**: name "Harrogate", code "HGT".<br>2. Save. | Branch appears, inherits the org timezone/currency/locale. Duplicate code is refused. | P1 | backend: `tutortrack/tenancy/tests/test_organisations.py` | |
| TP-E02-033 | Default branch can't be archived | Owner | — | 1. Try **Archive** on the default branch. | Refused with a message; archive works on Harrogate. | P2 | backend: `tutortrack/tenancy/tests/test_settings_api.py` | |
| TP-E02-034 | Branch overrides for settings | Owner | Harrogate exists | 1. Set a different default lesson length for Harrogate (`PATCH /api/v1/settings/general?branch=<id>`). | Harrogate uses its own value; MAIN keeps the org value. | P3 | backend: `tutortrack/tenancy/tests/test_settings_api.py` | |
| TP-E02-035 | Branch-restricted manager sees only their branch | Branch Manager | manager@ scoped to MAIN; a student created in Harrogate | 1. Sign in as manager@.<br>2. Open Students, search for the Harrogate student; open Calendar. | Harrogate student and lessons never appear; creating a record in Harrogate is refused (403 cross-branch write). | P1 | backend: `tutortrack/tenancy/tests/test_branch_scoping.py` | |
| TP-E02-036 | Branch limit enforced by the plan | Owner | Org on Team plan (no `multi_branch`) | 1. Try to add a branch. | Upgrade dialog with `upgrade_required` naming the plan needed. | P2 | backend: `tutortrack/subscriptions/tests/test_subscriptions.py` | |

## Suspension and closure

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E02-037 | Suspended organisation is read-only for owners/admins | Owner, Admin | Suspend a throwaway org via /platform (Suspend with a reason) | 1. Sign in as its owner; try to edit a client.<br>2. Open Settings → Billing & plan. | "Your account is suspended" banner; writes refused (423 read-only); billing pages still work. | P1 | backend: `tutortrack/tenancy/tests/test_lifecycle.py` | |
| TP-E02-038 | Other members and portal users are locked out when suspended | Coordinator, Parent | As above, with a coordinator and a portal parent | 1. Sign in as each. | Staff other than owner/admin and portal users get a suspended message (403). | P2 | backend: `tutortrack/tenancy/tests/test_lifecycle.py` | |
| TP-E02-039 | Lift a suspension | Platform staff | Suspended org | 1. /platform → organisation → **Lift suspension**. | Writes work again; banner gone. | P2 | backend: `tutortrack/tenancy/tests/test_lifecycle.py` | |
| TP-E02-040 | Close account needs owner, password and slug | Owner, Admin | Throwaway org | 1. As an Admin, open Settings → Close account.<br>2. As the Owner, type the slug, enter password and a reason, press **Close account permanently**. | Admin: section absent or refused. Owner: "Your account has been closed."; API now returns 410; sign-in and switcher still work. | P1 | backend: `tutortrack/tenancy/tests/test_lifecycle.py` | |
| TP-E02-041 | Closure workflow runs the grace period | Platform staff | After TP-E02-040; Temporal worker running | 1. Open Temporal UI, search workflow `org-closure:<org id>`.<br>2. Check the email in Mailpit. | Workflow is in the grace-period step with deletion due in `privacy.closure_grace_days` (30) days; the owner gets the export link email. | P2 | backend: `tutortrack/tenancy/tests/test_closure_workflow.py` | |
| TP-E02-042 | Reopen during the grace period | Platform staff | As above | 1. /platform → organisation → reopen/reactivate. | Workflow completes without deleting; the org is active again. | P2 | backend: `tutortrack/tenancy/tests/test_closure_workflow.py` | |

## Permissions

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E02-043 | Branch management by role | Owner, Admin, Branch Manager, Finance | `multi_branch` on | 1. Sign in as each and open Settings → Branches. | Owner/Admin can add and archive; Branch Manager sees branches but can't manage (`org.branch.manage` denied); Finance can view only. | P2 | backend: `tutortrack/tenancy/tests/test_settings_api.py` | |
| TP-E02-044 | Only the owner can close the account | Admin | office@ | 1. `POST /api/v1/organisation/close`. | 403. | P1 | backend: `tutortrack/tenancy/tests/test_lifecycle.py` | |

## Tenant isolation

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E02-045 | Another organisation's data never appears | Owner | brightminds and northside seeded | 1. As admin@ on brightminds, search (⌘K) for "Northside" and "Noah".<br>2. As owner@northside.localhost on northside, search for "Patel". | No results either way. | P1 | backend: `tutortrack/tenancy/tests/test_resolution.py`; e2e: `e2e/roles.spec.ts` | |
| TP-E02-046 | Direct URL to another tenant's record is 404 | Owner | ID of Noah Northside | 1. On brightminds open `/students/<Noah's id>`. | Not found; nothing leaks. | P1 | backend: `tutortrack/core/tests/test_rls.py` | |
| TP-E02-047 | Non-members can't use another tenant's subdomain | Owner | admin@ is not a northside member | 1. Sign in at brightminds, then open http://northside.localhost:5173. | Asked to sign in / no access; northside data is not shown. | P1 | backend: `tutortrack/tenancy/tests/test_resolution.py` | |
| TP-E02-048 | Demo data stays in its organisation | Owner | Demo data loaded in a throwaway org | 1. Check brightminds lists. | No demo records leak into brightminds. | P2 | backend: `tutortrack/tenancy/tests/test_switcher_and_demo.py` | |

## i18n, time zones and currency

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E02-049 | Country drives defaults | Anonymous | — | 1. Sign up with country United States, then Australia. | US org: USD, America/New_York (or browser tz), en-US, Sunday week start; AU: AUD, Australia/Sydney, en-AU. | P2 | backend: `tutortrack/tenancy/tests/test_organisations.py` | |
| TP-E02-050 | Invalid timezone is refused | Owner | Swagger | 1. `PATCH /api/v1/organisation` with `timezone: "Mars/Base"`. | "Unknown timezone." field error. | P3 | backend: `tutortrack/tenancy/tests/test_organisations.py` | |

## Gap batch G2 (2026-10-14): in-product demo data

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E02-051 | Explore with demo data fills a fresh organisation | New owner | A new organisation from TP-E02-001 with no records | 1. In the onboarding wizard choose **Explore with demo data** (or `POST /api/v1/demo-data`).<br>2. Open Clients, Students, Tutors, Services, Calendar, Lesson reports, Invoices, Payments, Enquiries, Courses, Learning and Reviews. | Three sample families (Patel, Okafor, Hughes; four students), two sample tutors, two "(sample)" services, weekly lessons at fixed local times (Tue 16:30, Wed 16:00, Thu 17:00) for the last three and next four weeks, completed past lessons with reports (one draft per job), a draft, a paid and an overdue part-paid invoice numbered `DEMO-…`, two payments, four enquiries (one lost), a term with a Saturday 10:00 class and two enrolments, homework, a goal and an approved review. People records carry the "Sample data" tag. | P1 | backend: `tutortrack/tenancy/tests/test_demo_providers.py` | |
| TP-E02-052 | Sample data sends nothing and starts nothing | Owner | TP-E02-051 just loaded; Mailpit open | 1. Check Mailpit and the comms message log.<br>2. Open the Temporal UI (http://localhost:8233).<br>3. If a webhook endpoint or accounting connection exists, check its log. | No emails or SMS to the sample people, no new workflows for sample lessons or invoices, no webhook deliveries or accounting syncs for sample records (the events are handled only by billing, pay and reporting). | P1 | backend: `tutortrack/tenancy/tests/test_demo_providers.py` | |
| TP-E02-053 | Clear demo data removes it all and keeps real records | Owner | TP-E02-051; add one real family by hand first | 1. Settings → **Clear demo data** (or `DELETE /api/v1/demo-data`).<br>2. Check every list again; issue a real invoice. | Every sample record is gone (lists back to what they were, including charges, ledger entries and report rows); the real family stays; the real invoice gets the next real number (no gap from the `DEMO-` invoices). Loading demo data again works. | P1 | backend: `tutortrack/tenancy/tests/test_demo_providers.py` | |
| TP-E02-054 | Sandbox organisations get the sample data | Owner | Developer settings; sandbox limit not reached | 1. Developer → **Create sandbox**.<br>2. Open the sandbox. | The sandbox has the same sample dataset; the live organisation is unchanged. | P2 | backend: `tutortrack/developer/tests/` (sandbox), backend: `tutortrack/tenancy/tests/test_demo_providers.py` | |
