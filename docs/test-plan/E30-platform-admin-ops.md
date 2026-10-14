# E30 — Platform Administration, Support & Operations: manual tests

**Scope.** The TutorTrack staff console at `/platform` (organisations list and detail, tenant actions, entitlement overrides, feature flags, operations with dead-letter replay and status notices, support "View as" impersonation with tenant grants), observability and DR artefacts (Part 1); and the tenant-facing help panel, product tours, setup checklist, support chat, first-party product analytics, tenant health scores, NPS/CSAT and SaaS metrics (Part 2). Spec: [E30](../epics/E30-platform-admin-ops.md).

**Built differently from the spec (Implementation notes win):**
- Help articles and "What's new" are markdown files in the repo (`backend/tutortrack/success/help/`), not a headless CMS or Intercom. Support chat is built in (no third-party widget).
- Product analytics are first-party (`POST /analytics/events`), only for consenting staff; families and students are never tracked.
- Daily logical backups are replaced by cross-account snapshot copies; `manage.py tenant_dump <slug>` restores one organisation's rows.
- There is no plans-and-prices screen (API `/api/v1/platform/plans` only), no MRR filter on the tenant list, and the console has no workflow (processes) page — use the API (`/api/v1/processes/<id>/terminate|restart`) and the Temporal UI.
- SaaS metrics are computed from nightly subscription snapshots (no Stripe backfill; no currency conversion). The route is `/platform/metrics`.
- Support-access grants are owner-only; admins can view sessions.

**Common preconditions.**
- Console: http://localhost:5173/platform (root host, no tenant). Sign in as **admin@tutortrack.localhost** (superuser, platform staff) or **platform@tutortrack.localhost** (platform staff only, no organisation).
- Access needs a 2FA-verified session (`PLATFORM_REQUIRE_MFA`, default true) and an allowed IP (`PLATFORM_IP_ALLOWLIST`, empty = any). For day-to-day local testing either set up TOTP for the staff user on `/account` first, or set `PLATFORM_REQUIRE_MFA=false` in `.env` and restart the backend; run TP-E30-001 with it true.
- Console pages: Organisations `/platform`, organisation `/platform/tenants/<id>`, Feature flags `/platform/flags`, Operations `/platform/operations`, Health `/platform/health`, SaaS metrics `/platform/metrics`, Feedback and usage `/platform/feedback`, Support `/platform/support`.
- Seed: Bright Minds health score for today and 6 month-end subscription snapshots; setup checklist evaluated; support conversation "Invoice runs" from admin@. Northside Learning is a second organisation.
- Health/metrics nightly run: Temporal Schedule `schedule:platform-insights:platform` (03:30 UTC), created by `manage.py ensure_platform_schedules` (the worker container runs it on start). "Recalculate now" starts it at once.

## Console access (T01)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E30-001 | Platform staff need 2FA | Platform staff | `PLATFORM_REQUIRE_MFA=true`; platform@ without TOTP | 1. Sign in as platform@ and open `/platform`.<br>2. Set up TOTP on `/account`, sign out and in with the code, open `/platform`. | 1: "The console is for TutorTrack staff with two-factor authentication." 2: console opens. | P1 | backend: `tutortrack/platform_admin/tests/test_platform.py::test_only_platform_staff_with_2fa_from_allowed_networks` | |
| TP-E30-002 | Organisation users can't open the console | Owner; Coordinator; Parent | — | 1. Sign in as coordinator@ (or owner@northside) and open http://localhost:5173/platform and `/api/v1/platform/tenants`. | "The console is for TutorTrack staff." / 403. Tenant owners are not platform staff. | P1 | backend: `tutortrack/platform_admin/tests/test_part2.py::test_console_needs_platform_staff`; e2e: `e2e/platform.spec.ts` | |
| TP-E30-003 | IP allowlist | Platform staff | `PLATFORM_IP_ALLOWLIST=203.0.113.0/24` | 1. Open the console from localhost. | Refused. Adding 127.0.0.1/32 allows it. | P2 | backend: `tutortrack/platform_admin/tests/test_platform.py::test_network_allowlist` | |
| TP-E30-004 | Organisations list across tenants | Platform staff | Seed | 1. Open Organisations.<br>2. Search "north"; filter Status = Active, Plan; sort by Last active. | Bright Minds and Northside both listed with plan, status, MRR estimate, members, last active; filters and search work. | P1 | backend: `tutortrack/platform_admin/tests/test_platform.py::test_tenant_list_spans_organisations`; e2e: `e2e/platform.spec.ts` | |
| TP-E30-005 | Organisation detail | Platform staff | Seed | 1. Open Bright Minds. | Organisation info, subscription (trial ends), overrides, usage, members (verified, 2FA, last active), recent errors (failed webhooks, billing events, messages), dead letters, last 25 audit entries, Health card. | P1 | backend: `tutortrack/platform_admin/tests/test_platform.py::test_tenant_detail` | |

## Tenant actions (T02)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E30-006 | Extend trial | Platform staff | Northside on trial | 1. Extend trial by 14 days with a reason. | "Trial extended."; new trial end date; Northside's audit log shows the action with the staff member as actor. | P1 | backend: `tutortrack/platform_admin/tests/test_platform.py::test_tenant_actions_are_applied_and_audited_in_the_tenant` | |
| TP-E30-007 | Grant and remove an entitlement override | Platform staff | Northside | 1. Grant `ai_assistant` = on until next month, with a reason.<br>2. Try without a reason.<br>3. Remove it. | Granted (shown with expiry); no reason refused; removing takes effect on the next request. | P1 | backend: `tutortrack/platform_admin/tests/test_platform.py::test_overrides_need_a_reason` | |
| TP-E30-008 | Suspend and lift | Platform staff | Northside | 1. Suspend with a reason.<br>2. Sign in as owner@northside.localhost.<br>3. Lift the suspension. | Owner sees the suspended screen; Northside schedules paused; lifting returns to trial/active and resumes schedules. | P1 | backend: `tutortrack/platform_admin/tests/test_platform.py::test_tenant_actions_are_applied_and_audited_in_the_tenant`; `tutortrack/workflows/tests/test_runtime.py::test_schedules_pause_with_the_organisation` | |
| TP-E30-009 | Set plan with a note | Platform staff | Northside | 1. Set plan = Agency, note "Manual contract", activate manually billed. | "Plan changed."; entitlements change; subscription active. | P1 | backend: same | |
| TP-E30-010 | Resend owner verification | Platform staff | Owner unverified | 1. Resend owner verification. | "Verification email sent."; Mailpit has the email. | P2 | backend: same | |
| TP-E30-011 | Request data export | Platform staff | Northside | 1. Request data export. | "Export requested."; Northside owners get the `data_export_ready` email when built (E28). | P2 | backend: same | |
| TP-E30-012 | Schedule deletion needs the subdomain | Platform staff | A throwaway org (sign up "Delete Me Ltd") | 1. Schedule deletion typing the wrong slug.<br>2. Type the right slug. | Wrong slug refused; then "Deletion scheduled." and `OrganisationClosureWorkflow` starts (30-day grace; Django admin "Reopen" reactivates). | P1 | backend: `tutortrack/platform_admin/tests/test_platform.py::test_scheduling_deletion_needs_the_subdomain` | |
| TP-E30-013 | Plans API | Platform staff | — | 1. `PATCH /api/v1/platform/plans/team` (description). | Saved; Plan page in tenants reflects it. | P3 | backend: `tutortrack/platform_admin/tests/test_platform.py::test_plans_can_be_edited` | |

## Feature flags (T03)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E30-014 | Flags list | Platform staff | Seed flags multi_branch, payroll, pipeline, courses, ai_assistant | 1. Open Feature flags. | All listed, off for everyone. | P2 | backend: `tutortrack/platform_admin/tests/test_platform.py::test_flag_targeting_by_plan_rollout_and_organisation` | |
| TP-E30-015 | Target by plan, rollout and organisation | Platform staff | New flag `beta_x` | 1. Add the flag; set Plans "agency"; Rollout 50%; Turn on for organisation (Northside's id).<br>2. `GET /api/v1/features` as each org. | Evaluation follows targeting; rollout is stable per organisation across reloads. | P2 | backend: `tutortrack/platform_admin/tests/test_platform.py::test_rollout_is_stable_per_organisation` | |

## Operations and observability (T04, T06, T07)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E30-016 | Operations overview | Platform staff | Celery and worker running | 1. Open Operations. | Events waiting, outbox lag (s), dead letters, queue depths, payment and billing webhook backlogs. | P1 | No | |
| TP-E30-017 | Dead letters replay | Platform staff | Force a dead letter (stop the worker so a handler fails repeatedly, or a test handler) | 1. Select events → Replay n events. | Events are re-dispatched; dead-letter count drops. | P1 | backend: `tutortrack/platform_admin/tests/test_platform.py::test_dead_letters_are_listed_and_replayed` | |
| TP-E30-018 | Outage banner | Platform staff | — | 1. Post notice: severity Outage, message "Payments delayed".<br>2. Open the admin app and the portal as tenant users.<br>3. End the notice. | Banner in both apps with a link to the status page; disappears when ended. | P1 | backend: `tutortrack/platform_admin/tests/test_platform.py::test_outage_banner_reaches_every_app` | |
| TP-E30-019 | Metrics in embedded metric format | Developer | Celery Beat running | 1. Watch the backend logs for one minute. | A metrics record (outbox lag, dead letters, queue depth, backlogs) every minute. | P3 | backend: `tutortrack/platform_admin/tests/test_platform.py::test_metrics_are_written_in_embedded_metric_format` | |
| TP-E30-020 | Single-organisation dump | Developer | — | 1. `uv run python manage.py tenant_dump brightminds > /tmp/bm.json`. | Only Bright Minds rows; no Northside data. | P2 | backend: `tutortrack/platform_admin/tests/test_platform.py::test_tenant_dump_contains_only_that_organisation` | |
| TP-E30-021 | Runbooks present | Reviewer | — | 1. Open `docs/runbooks/`. | Deploy, rollback, DB restore, single-organisation restore, alerts, provider outage, incident comms, quarterly drill. (Dry-run steps in non-functional.md.) | P3 | No | |

## Support impersonation (T05)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E30-022 | View as needs a reason | Platform staff | Bright Minds detail → members | 1. View as coordinator@ without a reason; then with reason and ticket.<br>2. Open account (single-use link). | Refused without a reason; with one, a single-use 5-minute link signs the staff member in on brightminds.localhost with "You're viewing as … Read-only." banner. | P1 | backend: `tutortrack/platform_admin/tests/test_platform.py::test_support_access_needs_a_reason` | |
| TP-E30-023 | Read-only by default | Platform staff | TP-E30-022 | 1. Try to edit a client. | Refused (read-only). | P1 | backend: `tutortrack/platform_admin/tests/test_platform.py::test_support_session_is_read_only_and_visible_to_the_owner` | |
| TP-E30-024 | Link is single-use and expires | Platform staff | A link | 1. Open it twice; open another after 5 minutes. | Second use and expired link refused. | P2 | No | |
| TP-E30-025 | Stop viewing as | Platform staff | TP-E30-022 | 1. Select Stop viewing as. | Session ends; console is not reachable while impersonating. | P2 | No | |
| TP-E30-026 | Owner sees support access | Owner | TP-E30-022 | 1. As admin@ (owner) open Settings → support access. | "Support accessed your account on …" with reason, staff and time. Admins can view; holders of `support.access.view` get an in-app notice. | P1 | backend: `tutortrack/platform_admin/tests/test_platform.py::test_admins_see_support_access_but_only_owners_grant` | |
| TP-E30-027 | Require a grant; write grants | Owner → Platform staff | Owner sets "support access requires a grant" | 1. Staff try View as (refused).<br>2. Owner creates a time-limited grant with allow write.<br>3. Staff View as and edit a client. | Refused without grant; with an allow-write grant, edits work and are audited with the staff actor. | P1 | backend: `tutortrack/platform_admin/tests/test_platform.py::test_organisations_can_require_a_grant_and_allow_writes` | |
| TP-E30-028 | Admins can't create grants | Admin | — | 1. As office@ try to create a grant. | Not allowed (owner-only). | P2 | backend: `tutortrack/platform_admin/tests/test_platform.py::test_admins_see_support_access_but_only_owners_grant` | |

## Help panel, tours, checklist, support chat (T08)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E30-029 | Help panel opens and closes accessibly | Coordinator | — | 1. Select Help in the header.<br>2. Press Escape. | Dialog opens with focus inside; tabs Articles, What's new, Tours, Chat with support, Usage data; Escape closes and focus returns to Help. | P1 | No | |
| TP-E30-030 | Suggested articles for the page | Owner | — | 1. Open `/billing`, then Help. | "Suggested for this page" lists "Send invoices". | P2 | backend: `tutortrack/success/tests/test_success.py::test_help_panel_suggests_articles_for_the_page` | |
| TP-E30-031 | Search articles | Owner | — | 1. Search "invite team". | "Invite your team" ranked first; every word must match; "Back to articles" works. | P2 | backend: `tutortrack/success/tests/test_success.py::test_search_ranks_title_matches_first_and_needs_every_word` | |
| TP-E30-032 | Safe markdown rendering | Owner | — | 1. Open an article with links and lists. | Headings, lists, bold; links only same-site or https; no raw HTML. | P2 | backend: `tutortrack/success/tests/test_success.py::test_help_articles_are_markdown_with_front_matter` | |
| TP-E30-033 | What's new unread dot | Owner | Changelog entries unseen | 1. Note the dot on Help ("n new items").<br>2. Open What's new. | Dot clears and stays cleared after reload. | P2 | backend: `tutortrack/success/tests/test_success.py::test_whats_new_is_unread_until_seen` | |
| TP-E30-034 | Welcome tour offered once | New staff member | Invite a new coordinator and sign in | 1. Open the dashboard.<br>2. Step through with Next/Back, then Done. | "Step n of m" announced; focus moves to each step heading; Escape closes; not offered again. Reduced motion: no smooth scrolling. | P1 | backend: `tutortrack/success/tests/test_success.py::test_tours_are_remembered_per_person` | |
| TP-E30-035 | Calendar and billing tours | Owner | — | 1. Help → Tours → Start "Schedule lessons"; then the billing tour. | Steps highlight elements; missing elements show without highlight; "Taken" afterwards; "Take again" works. | P3 | No | |
| TP-E30-036 | Setup checklist ticks from data | Owner | Seed (service, students, lessons exist) | 1. Open Home → Get started card. | Set up a service, Add a student, Schedule a lesson ticked; Connect Stripe and Send your first invoice not ticked; "3 of 5 done". | P1 | backend: `tutortrack/success/tests/test_success.py::test_checklist_finds_existing_data` | |
| TP-E30-037 | Checklist ticks itself from events | Owner | — | 1. Connect the fake Stripe account (Settings → Payments).<br>2. Issue an invoice. | Steps tick without reload; at 5 of 5 `setup_checklist.completed`. | P1 | backend: `tutortrack/success/tests/test_success.py::test_checklist_ticks_itself_from_domain_events` | |
| TP-E30-038 | Only owners/admins hide the checklist | Coordinator; Owner | — | 1. As coordinator look for Hide checklist.<br>2. As owner hide it. | Coordinator can't; owner hides it for the organisation. | P2 | backend: `tutortrack/success/tests/test_success.py::test_only_managers_hide_the_checklist` | |
| TP-E30-039 | Staff start a support chat | Coordinator | — | 1. Help → Chat with support → subject, question → Send. | Conversation "Waiting for TutorTrack" with the page recorded. | P1 | backend: `tutortrack/success/tests/test_success.py::test_staff_open_and_continue_a_support_chat` | |
| TP-E30-040 | Platform staff answer | Platform staff | TP-E30-039 and seeded "Invoice runs" | 1. Support → Waiting for us → open the chat → Assign to me → Reply. | Reply appears for the coordinator (dot on Help, "New reply"); appears in Bright Minds' audit log with the staff actor. | P1 | backend: `tutortrack/platform_admin/tests/test_part2.py::test_support_inbox_spans_organisations_and_replies_in_tenant_context`; e2e: `e2e/platform.spec.ts` | |
| TP-E30-041 | Rate an answered chat once | Coordinator | TP-E30-040 | 1. Rate 4.<br>2. Try again. | "You rated this chat 4 out of 5."; only once, by the author. | P2 | backend: `tutortrack/success/tests/test_success.py::test_csat_rates_a_support_chat_once_by_its_author` | |
| TP-E30-042 | Who sees which chats | Coordinator; Owner | Chats by coordinator and finance | 1. Open Chat with support as each. | Coordinator/finance see only their own; owner and admin see all in the org. | P2 | backend: `tutortrack/success/tests/test_success.py::test_members_see_their_own_chats_and_owners_see_all` | |

## Product analytics, health, NPS, SaaS metrics (T09, T10)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E30-043 | No consent, no tracking | Coordinator | Fresh browser, no `tt_consent` | 1. Click around; watch the Network tab. | No `POST /analytics/events`. | P1 | backend: `tutortrack/success/tests/test_success.py::test_no_consent_no_tracking` | |
| TP-E30-044 | Consent in the help panel | Coordinator | — | 1. Help → Usage data → Share anonymous usage data on.<br>2. Navigate. | Events sent with route patterns (`/clients/$id`) and no names, emails or ids. | P1 | backend: `tutortrack/success/tests/test_success.py::test_consented_events_are_pseudonymous_and_stripped_of_pii`; `test_routes_become_patterns` | |
| TP-E30-045 | Families, students and support never tracked | Parent; Platform staff | Consent given | 1. Use the portal as parent@.<br>2. Use "View as" a consenting staff member. | No events recorded in either case. | P1 | backend: `tutortrack/success/tests/test_success.py::test_tracking_needs_the_organisation_and_a_staff_role` | |
| TP-E30-046 | Organisation can turn analytics off | Owner | Setting `privacy.product_analytics` off | 1. Navigate with consent given. | No events. | P2 | backend: same | |
| TP-E30-047 | Feedback and usage page | Platform staff | Events exist | 1. Open Feedback and usage. | Top events and pages for the window; onboarding funnel from checklists; NPS/CSAT tiles. | P2 | backend: `tutortrack/platform_admin/tests/test_part2.py::test_usage_and_onboarding_funnel` | |
| TP-E30-048 | Health worklist | Platform staff | Seed score for today | 1. Open Health; filter Risk = At risk / Watch / Healthy. | Lowest scores first; components Usage, Tutors, Payments, Reliability, Support, NPS; risk bands 70+/40–69/<40. | P1 | backend: `tutortrack/platform_admin/tests/test_part2.py::test_health_worklist_lowest_first_with_history`; e2e: `e2e/platform.spec.ts` | |
| TP-E30-049 | Recalculate now | Platform staff | Temporal worker running | 1. Select Recalculate now.<br>2. Check Temporal UI for `PlatformInsightsWorkflow`. | Workflow runs; scores for every non-cancelled org (Northside included) for today; organisation page Health card updated. | P1 | backend: `tutortrack/platform_admin/tests/test_part2.py::test_insights_run_now_starts_the_workflow`; `test_insights_workflow_scores_every_organisation` | |
| TP-E30-050 | At-risk alert once per day | Platform staff | Make Northside at risk (no usage) | 1. Recalculate twice. | One email to platform staff about organisations that became at risk. | P2 | backend: `tutortrack/platform_admin/tests/test_part2.py::test_churn_alert_goes_to_platform_staff_once` | |
| TP-E30-051 | Nightly schedule exists | Developer | Worker started | 1. Temporal UI → Schedules. | `schedule:platform-insights:platform` at 03:30 UTC; not paused by suspending an org. | P2 | backend: `tutortrack/platform_admin/tests/test_part2.py::test_the_nightly_schedule_is_a_platform_schedule` | |
| TP-E30-052 | NPS prompt rules | Staff member joined ≥ 14 days ago | Backdate a membership's `joined_at` (Django shell) | 1. Open the admin app.<br>2. Answer 9 with a comment; or Not now. | Non-modal corner prompt that never takes focus; after answering, not asked for 90 days; "Not now" rests 30 days. | P2 | backend: `tutortrack/success/tests/test_success.py::test_nps_is_asked_after_two_weeks_then_rests`; `test_nps_dismissal_snoozes_and_scores_are_checked` | |
| TP-E30-053 | NPS off and portal users | Owner | `privacy.satisfaction_surveys` off | 1. Reload as an eligible staff member; also as parent@. | No prompt. | P3 | backend: `tutortrack/success/tests/test_success.py::test_nps_respects_the_organisation_setting_and_roles` | |
| TP-E30-054 | NPS summary | Platform staff | Some answers | 1. Feedback and usage → NPS. | NPS, promoters/passives/detractors, by plan and month, recent comments with org and role only (never the respondent). | P2 | backend: `tutortrack/platform_admin/tests/test_part2.py::test_nps_summary_across_organisations` | |
| TP-E30-055 | SaaS metrics | Platform staff | Seed snapshots (first month trialing, then active) | 1. Open SaaS metrics; currency GBP; 6 months. | Tiles MRR, ARR, Paying customers, ARPA, NRR, churn, In trial, MRR past due; MRR by month; movements table where end = start + net new; trial conversion by sign-up month; cohort retention. | P1 | backend: `tutortrack/platform_admin/tests/test_part2.py::test_saas_metrics_from_snapshots`; `tutortrack/platform_admin/tests/test_metrics_math.py`; e2e: `e2e/platform.spec.ts` | |
| TP-E30-056 | MRR rounding | Platform staff | Annual plan | 1. Check an annual subscription's MRR. | Annual price / 12, rounded half-up to pennies. | P2 | backend: `tutortrack/platform_admin/tests/test_metrics_math.py::test_mrr_is_rounded_and_never_negative` | |

## Tenant isolation

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E30-057 | Support chats stay in their organisation | Owner (Northside) | Bright Minds chats exist | 1. Open Chat with support on northside.localhost. | Only Northside chats. | P1 | backend: `tutortrack/success/tests/test_success.py` isolation classes | |
| TP-E30-058 | Tenant actions land in the right audit log | Platform staff | TP-E30-006 | 1. Check Bright Minds' audit log. | Northside's actions don't appear in Bright Minds. | P1 | No | |

## i18n, time zones and currency

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E30-059 | Help articles fall back to en-GB | Owner (en-US) | Account language English (US) | 1. Open Help articles. | en-GB articles shown (fallback), UI chrome in en-US spelling. | P3 | No | |
| TP-E30-060 | Metrics in one currency at a time | Platform staff | Orgs in GBP and USD | 1. Switch SaaS metrics currency. | Figures per currency; never converted or summed across currencies. | P2 | No | |

## Errors and edge cases

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E30-061 | Erasure removes usage and anonymises chats | Owner | A staff member with events and chats | 1. Erase the member (E29). | Their events deleted; chats anonymised. | P2 | backend: `tutortrack/success/tests/test_success.py::test_erasure_removes_usage_and_anonymises_chats` | |
| TP-E30-062 | Old usage events purged | Owner | Retention `product_usage` 395 days | 1. Run a purge. | Older events deleted. | P3 | backend: `tutortrack/success/tests/test_success.py::test_old_usage_events_are_purged` | |
