# E22 — Calendar sync and online lesson integrations: manual tests

**Scope.** The integration framework (OAuth with PKCE, encrypted tokens, refresh, health, disconnect), two-way calendar sync with Google, Microsoft 365 and iCloud (CalDAV), busy blocks in conflicts and availability, online meeting rooms (Zoom, Teams, Google Meet, Lessonspace, built-in Daily/Whereby), and join links with timed enablement. Phase 3: video attendance, recordings and the embedded classroom (T10). Spec: [E22](../epics/E22-calendar-video-integrations.md); decisions in [ADR 0015](../adr/0015-integration-framework-and-calendar-sync.md).

**Built differently from the spec (Implementation notes win):**
- No per-provider Celery queues (one `integrations` queue).
- Re-creating deleted events and proposing moves happen only with two-way sync on. A moved event becomes an E08 reschedule request when the owner can't edit lessons.
- Google Meet uses the Meet REST API (`spaces`), not calendar conference data.
- With no provider account, online lessons get the built-in room (no error).
- Only lessons are pushed to calendars, not other calendar events.

**Common preconditions.**
- Stack running and seeded (see [README](README.md)); admin http://brightminds.localhost:5173, tutor portal http://brightminds.localhost:5174/portal/tutor. Password: `SEED_ADMIN_PASSWORD` (default `tutortrack`).
- **Fakes:** with the provider keys in `.env` empty, every provider is an in-memory fake (state in Redis). The fake OAuth consents instantly: clicking **Connect** returns straight to the app connected as `<random>@example.com`. CalDAV and Lessonspace accept any password or API key unless it contains the word `wrong` (then "Those details weren't accepted."). The UI says the provider is simulated.
- **Simulating a personal calendar event** (busy time) needs a Django shell (`cd backend && uv run python manage.py shell`):
  ```python
  from datetime import datetime; from zoneinfo import ZoneInfo
  from tutortrack.core.context import tenant_context
  from tutortrack.tenancy.models import Organisation
  from tutortrack.integrations.models import IntegrationConnection
  from tutortrack.integrations.providers.fake import FakeCalendar, fail, revoke
  org = Organisation.objects.get(slug="brightminds")
  with tenant_context(org):
      conn = IntegrationConnection.objects.filter(provider="google").latest("created_at")
  cal = FakeCalendar(conn.external_account_id)
  tz = ZoneInfo("Europe/London")
  evt = cal.add_event(datetime(2026, 10, 21, 17, 0, tzinfo=tz), datetime(2026, 10, 21, 18, 0, tzinfo=tz), title="Dentist")
  ```
  Then click **Sync now** (or wait for the 5-minute poll). `cal.move_event(...)`, `cal.delete_event(evt)`, `fail("google", 3)` and `revoke(conn.external_account_id)` simulate moves, deletions, outages and revoked access.
- Temporal worker running: `CalendarConnectionWorkflow` (`calendar:<org>:<connection>`) and `OnlineMeetingProvisioningWorkflow` are visible at http://localhost:8233.
- Tutor login tutor@ = Nia Adeyemi (Arjun's weekly Tuesday 16:30 lessons).

## Framework and connections (§2, T01)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E22-001 | Provider list shows capabilities and simulation | Admin | Fakes | 1. Open **Settings → Integrations** (`/settings/integrations`). | Google, Microsoft 365, iCloud (CalDAV), Zoom, Lessonspace and built-in rooms listed with what they do; each marked as simulated. | P2 | backend: `tutortrack/integrations/tests/test_integrations.py::test_providers_lists_capabilities_and_simulated_flag` | |
| TP-E22-002 | Connect Google (OAuth with PKCE) | Tutor | tutor@ | 1. Portal **Calendar** (`/portal/tutor/calendar`), **Connect Google**. | Returns to the page connected; status healthy; a "TutorTrack" calendar is created; `integration.connected` starts the connection workflow. Tokens are never shown in API responses. | P1 | backend: `tutortrack/integrations/tests/test_integrations.py::test_oauth_flow_with_pkce_connects_and_encrypts_tokens` | |
| TP-E22-003 | OAuth completion bound to the starting user | Tutor, Coordinator | Start OAuth as tutor@ and copy the callback URL | 1. Paste the callback URL into a browser signed in as coordinator@. | Completion refused; no connection for the coordinator. | P2 | backend: `tutortrack/integrations/tests/test_integrations.py::test_completion_is_bound_to_the_user_who_started` | |
| TP-E22-004 | Connect iCloud with an app password | Tutor | tutor@ | 1. Connect iCloud with username and an app-specific password.<br>2. Try again with password `wrong-pass`. | 1 connects (password stored encrypted). 2: "Those details weren't accepted." | P1 | backend: `tutortrack/integrations/tests/test_integrations.py::test_caldav_connects_with_an_encrypted_app_password` | |
| TP-E22-005 | CalDAV server URL is SSRF-checked | Tutor | Live CalDAV mode (`INTEGRATIONS_CREDENTIAL_PROVIDERS_LIVE=true`) | 1. Connect with server URL `http://127.0.0.1:8010/` or `http://169.254.169.254/`. | Refused by the SSRF guard. | P2 | No | |
| TP-E22-006 | Reconnect the same account | Tutor | Google connected | 1. Click **Connect Google** again (same fake account). | The existing connection is updated in place, not duplicated; the workflow receives `reconnected`. | P3 | backend: `tutortrack/integrations/tests/test_integrations.py::test_reconnecting_the_same_account_updates_in_place` | |
| TP-E22-007 | Token refresh before expiry | Tutor | Google connected (fake tokens last 1 hour) | 1. Leave connected over an hour, then **Sync now**. | Token refreshed silently; status stays healthy. | P3 | backend: `tutortrack/integrations/tests/test_integrations.py::test_tokens_refresh_before_expiry` | |
| TP-E22-008 | Revoked access needs reconnecting | Tutor | Shell: `revoke(conn.external_account_id)` | 1. **Sync now**. | Status **needs reconnect**; Nia gets an `integration_problem` notification; busy blocks from that connection stop counting. Reconnecting clears it. | P1 | backend: `tutortrack/integrations/tests/test_integrations.py::test_revoked_grant_needs_reconnect_and_tells_the_owner` | |
| TP-E22-009 | Errors surface and clear | Tutor | Shell: `fail("google", 1)` | 1. **Sync now**; then **Sync now** again. | First shows an error with a readable message; the next success clears it. | P2 | backend: `tutortrack/integrations/tests/test_integrations.py::test_errors_surface_and_a_success_clears_them` | |
| TP-E22-010 | Health check and disconnect | Tutor | Connected | 1. Click **Check**.<br>2. Click **Disconnect**. | Check reports healthy. Disconnect revokes, clears secrets, deletes busy blocks and event links; `integration.disconnected`; the workflow ends. | P1 | backend: `tutortrack/integrations/tests/test_integrations.py::test_health_check_endpoint_and_disconnect` | |
| TP-E22-011 | Admin sees every connection's health | Admin | Nia connected | 1. Admin **Settings → Integrations**. | Organisation connections and members' connections with owner, status, last sync and last error. Secrets never shown. | P2 | backend: `tutortrack/integrations/tests/test_integrations.py::test_people_only_see_and_manage_their_own_connections` | |

## Calendar push (FR-22-1, T02)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E22-012 | Lessons written to the TutorTrack calendar | Tutor | Google connected for Nia | 1. In the shell, list `cal.events("<TutorTrack calendar id>")` (or check the connection's sync status in the UI). | Nia's upcoming lessons (Arjun, Tuesdays 16:30) exist as events titled per the format ("GCSE Maths 1:1 – Arjun P."), carrying the lesson id; no notes in the description. | P1 | backend: `tutortrack/calendar_sync/tests/test_calendar_sync.py::test_lessons_are_written_to_a_dedicated_calendar_with_the_lesson_id` | |
| TP-E22-013 | Moves, cancellations and removed tutors follow | Coordinator | TP-E22-012 | 1. Move next Tuesday's lesson to 17:00.<br>2. Cancel the following one.<br>3. Replace Nia on a later lesson. | Event moved; cancelled lesson's event deleted; Nia's event deleted where she was removed. Unchanged lessons are not pushed again. | P1 | backend: `tutortrack/calendar_sync/tests/test_calendar_sync.py::test_moves_cancellations_and_removed_tutors_follow_the_lesson`, `::test_unchanged_lessons_are_not_pushed_again` | |
| TP-E22-014 | Title format and details setting | Tutor, Admin | Connected | 1. Change the personal title format to "{service} ({students})".<br>2. Admin turns `integrations.calendar_details` on. | Event titles update; descriptions include details only with the setting on. | P3 | backend: `tutortrack/calendar_sync/tests/test_calendar_sync.py::test_title_format_placeholders` | |
| TP-E22-015 | Deleting a planned lesson removes its event | Coordinator | Planned lesson | 1. Delete it outright. | Its event and meeting room are removed after commit. | P3 | backend: `tutortrack/calendar_sync/tests/test_calendar_sync.py::test_deleting_a_lesson_removes_its_event` | |
| TP-E22-016 | Failed push marks the connection | Tutor | Shell: `fail("google", 5)` | 1. Move a lesson. | Connection shows an error; push retried later. | P2 | backend: `tutortrack/calendar_sync/tests/test_calendar_sync.py::test_a_failed_push_marks_the_connection` | |

## Busy blocks (FR-22-1 AC, T02)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E22-017 | Personal event becomes a busy block and blocks booking | Tutor, Coordinator | Shell: add "Dentist" next Wednesday 17:00–18:00 to Nia's primary calendar | 1. Click **Sync now** (or wait ≤ 5 minutes).<br>2. As coordinator, book a lesson for Nia next Wednesday 17:30. | Busy block stored (times only, no title). Booking refused with a hard `tutor_external_busy` conflict; Nia's free slots exclude 17:00–18:00. (AC FR-22-1) | P1 | backend: `tutortrack/calendar_sync/tests/test_calendar_sync.py::test_personal_events_become_busy_blocks_that_block_booking` | |
| TP-E22-018 | Busy time feeds availability and matching | Coordinator | TP-E22-017 | 1. Open Nia's availability / matching for a Wednesday 17:00 slot. | Availability lower for that slot. | P2 | backend: `tutortrack/calendar_sync/tests/test_calendar_sync.py::test_busy_blocks_feed_free_slots_and_batched_fit` | |
| TP-E22-019 | Free, moved, deleted events | Tutor | Shell | 1. Add a free (`busy=False`) event; move the Dentist; delete it; sync after each. | Free events never block; moves update the block; deletes remove it. | P2 | backend: `tutortrack/calendar_sync/tests/test_calendar_sync.py::test_incremental_sync_handles_moves_deletes_and_free_events` | |
| TP-E22-020 | Our own lesson events are never busy | Tutor | Connected | 1. Sync. | Lessons pushed by TutorTrack don't create busy blocks. | P1 | backend: `tutortrack/calendar_sync/tests/test_calendar_sync.py::test_our_own_lesson_events_are_never_busy` | |
| TP-E22-021 | Choose busy calendars | Tutor | Connected | 1. In sync settings untick "Personal" as a busy calendar; sync. | Its blocks are removed; a settings change triggers a sync. | P2 | backend: `tutortrack/calendar_sync/tests/test_calendar_sync.py::test_sync_settings_api` | |
| TP-E22-022 | Disconnected calendars stop blocking | Tutor | Busy block exists | 1. Disconnect. | Booking in that slot is allowed again. | P1 | backend: `tutortrack/calendar_sync/tests/test_calendar_sync.py::test_disconnected_calendars_stop_blocking` | |
| TP-E22-023 | Push webhook validates its token | Anonymous | None | 1. `POST http://localhost:8010/webhooks/google-calendar` with a bad `X-Goog-Channel-Token`. | Rejected; nothing signalled. A valid token signals `changed` on the workflow. | P2 | backend: `tutortrack/calendar_sync/tests/test_calendar_sync.py::test_google_webhook_validates_the_token_and_signals` | |

## Two-way edits (FR-22-1, T03)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E22-024 | Moving a lesson in the calendar proposes a reschedule | Tutor, Coordinator | Nia: two-way on; org setting `integrations.calendar_two_way` on | 1. Shell: `cal.find_lesson("<lesson id>")`, then `move_event` it by one hour on the TutorTrack calendar; sync. | An E08 reschedule request (requester calendar) appears in **Requests**; the event is put back; Nia gets `calendar_notice`. The same move isn't proposed twice. | P1 | backend: `tutortrack/calendar_sync/tests/test_calendar_sync.py::test_moving_a_lesson_in_google_proposes_a_reschedule` | |
| TP-E22-025 | Moves apply directly for staff who may edit lessons | Admin | Admin connected with two-way on and a lesson | 1. Move the event; sync. | Lesson rescheduled directly when there is no hard conflict. | P2 | backend: `tutortrack/calendar_sync/tests/test_calendar_sync.py::test_moves_apply_directly_when_the_owner_may_edit_lessons` | |
| TP-E22-026 | Deleting in the calendar doesn't cancel | Tutor | Two-way on | 1. `delete_event` a lesson event; sync. | The lesson stays planned; the event is re-created; Nia is warned. | P1 | backend: `tutortrack/calendar_sync/tests/test_calendar_sync.py::test_deleting_a_lesson_in_google_recreates_it_with_a_warning` | |
| TP-E22-027 | Two-way needs the org setting | Admin | Setting off | 1. Try to enable two-way as Nia. | Not available/ignored. | P3 | backend: `tutortrack/calendar_sync/tests/test_calendar_sync.py::test_two_way_needs_the_org_setting` | |

## Microsoft and CalDAV (FR-22-2, FR-22-3, T04, T05)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E22-028 | Microsoft 365 sync | Tutor | Connect Microsoft (fake) | 1. Repeat TP-E22-012 and TP-E22-017 with provider `microsoft`. | Lessons pushed; busy blocks read via delta. | P1 | backend: `tutortrack/calendar_sync/tests/test_calendar_sync.py::test_microsoft_calendar_pushes_and_reads_busy` | |
| TP-E22-029 | Graph subscription handshake | Anonymous | None | 1. `POST http://localhost:8010/webhooks/microsoft-graph?validationToken=abc`. | Responds with `abc` as plain text; notifications with a wrong `clientState` are ignored. | P2 | backend: `tutortrack/calendar_sync/tests/test_calendar_sync.py::test_graph_subscription_handshake_and_notifications` | |
| TP-E22-030 | iCloud polls every 10 minutes | Tutor | iCloud connected | 1. Add an event (shell, provider `caldav`) and watch the workflow. | Picked up on the 10-minute poll (no push channel); an event missing from a full listing counts as deleted. | P2 | backend: `tutortrack/calendar_sync/tests/test_calendar_sync.py::test_caldav_polls_every_ten_minutes_without_channels` | |
| TP-E22-031 | iCal feed still works | Tutor | E08 iCal feed URL | 1. Open `/ical/<token>.ics`. | Read-only feed of Nia's lessons. | P3 | No | |

## Online meetings (FR-22-4, T06–T08)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E22-032 | Built-in room with no account | Coordinator | No video connections; org default `builtin` | 1. Create an online lesson for Arjun with Nia. | A Daily room is created; the lesson's meeting link is set; the provisioning workflow succeeds. | P1 | backend: `tutortrack/calendar_sync/tests/test_meetings.py::test_online_lessons_get_a_built_in_room_without_any_account` | |
| TP-E22-033 | In-person and hand-typed links are left alone | Coordinator | Lessons | 1. Create an in-person lesson.<br>2. Type a link by hand on an online lesson. | No room for in-person; the typed link is never replaced. | P2 | backend: `tutortrack/calendar_sync/tests/test_meetings.py::test_in_person_lessons_and_manual_links_are_left_alone` | |
| TP-E22-034 | Zoom with the tutor's account | Tutor | Nia connects Zoom; video preference Zoom | 1. Create an online lesson. | A Zoom meeting with waiting room/passcode settings; Nia gets the host link, the family the participant link; passcode stored encrypted. | P1 | backend: `tutortrack/calendar_sync/tests/test_meetings.py::test_zoom_with_the_tutors_account_and_role_specific_links` | |
| TP-E22-035 | Personal Zoom room | Tutor | Preference "personal room" | 1. Create an online lesson. | The tutor's personal room link is used. | P3 | backend: `tutortrack/calendar_sync/tests/test_meetings.py::test_a_personal_zoom_room_can_be_the_default` | |
| TP-E22-036 | Teams and Meet | Tutor | Nia connected to Microsoft or Google; preference Teams / Meet | 1. Create an online lesson for each. | Teams online meeting / Meet space created with the tutor's account. | P2 | backend: `tutortrack/calendar_sync/tests/test_meetings.py::test_teams_and_meet_use_the_tutors_microsoft_or_google_account` | |
| TP-E22-037 | Lessonspace per job with per-student links | Admin | Org Lessonspace connected (any API key) | 1. Set Lessonspace for the GCSE Maths service.<br>2. Create online lessons for the job. | One space per job; tutor gets the leader link; each student their own link. | P2 | backend: `tutortrack/calendar_sync/tests/test_meetings.py::test_lessonspace_gives_each_student_their_own_link` | |
| TP-E22-038 | Provider resolution order | Admin | Lesson, job, tutor, service and org preferences set differently | 1. Create lessons and check the provider used. | Lesson → job → tutor preference → service map → org default. Without an account for the chosen provider, the built-in room. | P2 | backend: `tutortrack/calendar_sync/tests/test_meetings.py::test_provider_resolution_order`, `::test_without_an_account_the_built_in_room_is_used` | |
| TP-E22-039 | Reschedule updates, cancel deletes | Coordinator | Online lesson with Zoom | 1. Move it.<br>2. Cancel it.<br>3. Switch another to in person. | Meeting updated; deleted on cancel; room and link removed when no longer online. | P1 | backend: `tutortrack/calendar_sync/tests/test_meetings.py::test_reschedule_updates_and_cancel_deletes_the_meeting`, `::test_switching_off_online_removes_the_room_and_link` | |
| TP-E22-040 | Provisioning failures retry, then alert staff | Coordinator | Shell: `fail("zoom", 2)`, then `fail("zoom", 10)` | 1. Create an online lesson each time. | 2 failures: retried and succeeds. 10: meeting marked failed after 6 attempts, `online_meeting.failed`, staff get `staff_meeting_failed`. | P2 | backend: `tutortrack/calendar_sync/tests/test_workflows.py::test_provisioning_retries_transient_failures`, `::test_provisioning_that_keeps_failing_tells_staff` | |
| TP-E22-041 | Staff re-run provisioning | Coordinator | Failed meeting | 1. Re-provision (`POST /api/v1/online-meetings/provision`). | Meeting created. | P3 | backend: `tutortrack/calendar_sync/tests/test_meetings.py::test_staff_can_reprovision_a_meeting` | |

## Join links (T09)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E22-042 | Join button opens 10 minutes before | Parent, Tutor | Online lesson today in 30 minutes | 1. Portal lesson card (parent@) and tutor lesson page (tutor@). | Disabled button "Join opens at HH:MM" (start − 10 min, UK time); enabled after; parent gets the participant link, tutor the host link. | P1 | backend: `tutortrack/calendar_sync/tests/test_meetings.py::test_portal_and_tutor_views_show_role_specific_links_with_timed_enablement`, `::test_family_portal_lesson_card_gets_the_participant_link` | |
| TP-E22-043 | Reminders carry each recipient's link | Parent | Online lesson with a reminder | 1. Open the reminder in Mailpit. | Contains the recipient's own join link. | P2 | backend: `tutortrack/calendar_sync/tests/test_meetings.py::test_reminders_carry_each_recipients_own_join_link` | |
| TP-E22-044 | Tutor sets their video preference | Tutor | Portal **Calendar** | 1. Choose a preferred video provider and save. | Saved; next online lesson uses it. | P3 | backend: `tutortrack/calendar_sync/tests/test_meetings.py::test_meeting_preference_api` | |

## Video attendance, recordings and embedded classroom (FR-22-4 Phase 3, FR-22-5, T10 — Phase 3)

Verify after the Phase 3 merge.

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E22-045 | Attendance pre-filled from video events | Tutor | Verify after the Phase 3 merge. Online Zoom or Lessonspace lesson; simulate participant join/leave webhooks (fake) | 1. Simulate the tutor and student joining at start and leaving after 55 minutes.<br>2. Open the lesson to complete it. | Attendance pre-filled (present) and actual duration ~55 minutes; the tutor can correct before saving. `online_meeting.participant_joined/left` recorded. | P2 | No (Phase 3) | |
| TP-E22-046 | Student never joins | Tutor | Verify after the Phase 3 merge | 1. Simulate only the tutor joining. | Student suggested as absent/no-show; nothing finalised without the tutor confirming. | P2 | No (Phase 3) | |
| TP-E22-047 | Recording linked to the lesson | Admin | Verify after the Phase 3 merge. Simulate `recording.available` | 1. Open the lesson. | Recording link shown to permitted roles only (staff with permission, the lesson's tutor); not to other tutors. | P2 | No (Phase 3) | |
| TP-E22-048 | Recording retention | Admin | Verify after the Phase 3 merge. Retention policy set | 1. Check a recording older than the policy. | Removed or hidden per the policy; audited. | P3 | No (Phase 3) | |
| TP-E22-049 | Recording consent and safeguarding note | Parent, Tutor | Verify after the Phase 3 merge | 1. Join a recorded session. | Consent prompt / safeguarding note shown before recording. | P2 | No (Phase 3) | |
| TP-E22-050 | Embedded classroom page | Tutor, Student | Verify after the Phase 3 merge. Built-in or Lessonspace provider | 1. Open the in-app classroom for an online lesson. | Iframe room with safeguarding banner, shared resources (E21), recording consent; keyboard accessible. | P3 | No (Phase 3) | |
| TP-E22-051 | Webhook authenticity | Anonymous | Verify after the Phase 3 merge | 1. Post a participant webhook with a bad signature. | Rejected; attendance unchanged. | P2 | No (Phase 3) | |

## Permissions

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E22-052 | Org-level connections need `integrations.manage` | Coordinator | coordinator@ | 1. Try to connect organisation Zoom / set video defaults. | Refused; personal connections allowed. | P1 | backend: `tutortrack/integrations/tests/test_integrations.py::test_org_level_connections_need_manage_permission` | |
| TP-E22-053 | People see only their own connections | Tutor | Two tutors connected | 1. As Nia list connections (API). | Only her own. | P1 | backend: `tutortrack/integrations/tests/test_integrations.py::test_people_only_see_and_manage_their_own_connections` | |
| TP-E22-054 | Families can't see host links | Parent | Online lesson | 1. Inspect portal lesson data. | Participant link only. | P1 | No | |

## Tenant isolation

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E22-055 | Connections, busy blocks and meetings per organisation | Owner (Northside) | owner@northside.localhost | 1. List integrations and online meetings in Northside; request brightminds ids. | None of brightminds' data; 404. A webhook channel token for one organisation can't signal another's workflow. | P1 | backend: `tutortrack/integrations/tests/test_integrations.py::TestConnectionIsolation`, `tutortrack/calendar_sync/tests/test_calendar_sync.py::TestBusyBlockIsolation`, `tutortrack/calendar_sync/tests/test_meetings.py::TestOnlineMeetingIsolation` | |

## i18n, time zones and currency

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E22-056 | Events keep local time over the clock change | Tutor | Lessons either side of the last Sunday in October | 1. Inspect pushed events. | 16:30 UK local time on both sides (UTC offset changes). | P1 | No | |

## Errors and edge cases

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E22-057 | Expired sync token falls back to full sync | Tutor | Connected | 1. Force an expired token (fake) and sync. | Full sync runs; blocks correct. | P3 | backend: `tutortrack/calendar_sync/tests/test_calendar_sync.py::test_expired_sync_token_falls_back_to_a_full_sync` | |
| TP-E22-058 | Errors back off and recover | Tutor | Shell: `fail("google", 3)` | 1. Watch the workflow in the Temporal UI. | Backoff (2 minutes doubling) then recovery without manual action. | P3 | backend: `tutortrack/calendar_sync/tests/test_workflows.py::test_sync_errors_back_off_and_recover` | |
