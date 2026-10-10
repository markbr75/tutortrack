# E22 — Calendar Sync & Online Lesson Integrations

| | |
|---|---|
| **Phase** | Agency (Phase 2) |
| **Depends on** | E08, E27 (integration framework) |
| **Parity** | TutorBird two-way Google/Apple/Outlook sync; TutorCruncher Google Calendar, iCal, Zoom, Teams, Daily.co, Lessonspace. **Fixes:** TutorBird users want more frequent sync |

## 1. Summary
Connect tutors' and staff's personal calendars (two-way, near-real-time) and automatically create online meeting rooms for online lessons with Zoom, Microsoft Teams, Google Meet, Lessonspace and a built-in fallback (Daily.co/Whereby embedded room).

## 2. Integration framework (shared with E23/E27)
- `IntegrationConnection(org, user nullable, provider, scopes, access_token enc, refresh_token enc, expires_at, status, external_account_id, settings JSONB, last_sync_at, error)`.
- OAuth2 flows with PKCE where supported; token refresh; disconnection; health checks; error surfacing to the user and admin.
- Rate-limit aware provider clients with retry/backoff; per-provider Celery queue.

## 3. Functional requirements

### FR-22-1 Google Calendar two-way sync
- Per-user connection; choose which calendars to read as **busy** (free/busy only by default; privacy) and which calendar to **write** TutorTrack lessons into (default: a dedicated "TutorTrack" calendar created by us).
- Push lessons/events: create/update/delete on our changes (via outbox events) with stable `extendedProperties` linking ids; include title format setting (e.g. "Maths – Sam P."), location/join link, description (no sensitive data by default).
- Read busy: watch channels (Google push notifications) + incremental sync tokens; fall back to polling every 5 minutes. Busy blocks stored as `ExternalBusyBlock` used in conflict checks and availability (E08).
- **Two-way edits (optional setting):** moving a TutorTrack lesson in Google proposes a reschedule in TutorTrack (creates a reschedule request or applies directly if the user has permission); deletion in Google does **not** cancel lessons (it re-creates them with a warning) to avoid accidental cancellations.
- **AC:** a personal event created in a connected Google calendar appears as a busy block in TutorTrack within 2 minutes (push) and blocks booking in that slot.

### FR-22-2 Microsoft 365/Outlook sync
- Same capabilities via Microsoft Graph (subscriptions/webhooks + delta queries).

### FR-22-3 Apple iCloud / CalDAV
- CalDAV connection with app-specific password (stored encrypted), polling every 10 minutes; plus our iCal subscribe feeds (E08 FR-08-11) for read-only use.

### FR-22-4 Video meeting providers
- Org-level and user-level connections: **Zoom** (OAuth app; create meeting per lesson or use tutor's personal room; settings: waiting room, passcode, recording), **Microsoft Teams** (online meetings via Graph), **Google Meet** (conference data on Calendar event), **Lessonspace** (API: create space per job or per lesson, with student/tutor-specific join URLs and recording/playback retrieval), **Daily.co** or **Whereby** as built-in rooms requiring no tutor account.
- Default provider per org/service/job/tutor; auto-create on lesson creation for online lessons; update/delete on reschedule/cancel.
- Join links: role-specific (host vs participant), surfaced in portals and reminders; join button enabled N minutes before start.
- Attendance from video (Phase 3): ingest participant join/leave events (Zoom/Lessonspace webhooks) to pre-fill attendance and actual duration.
- Recordings (Phase 3): link recordings to lessons; access controlled by permissions; retention policy; safeguarding note on recording consent.

### FR-22-5 Embedded classroom (Phase 3)
- Optional in-app classroom page wrapping Daily/Lessonspace iframe with whiteboard, shared resources (E21), and a safeguarding banner; recording consent prompt.

## 4. Data model
`IntegrationConnection`, `CalendarSyncSettings(user, read_calendar_ids, write_calendar_id, two_way, title_format)`, `ExternalEventLink(lesson/event, provider, external_id, etag)`, `ExternalBusyBlock(user, start, end, source, external_id)`, `SyncState(connection, sync_token, channel_id, channel_expiry)`, `OnlineMeeting(lesson, provider, external_id, host_url, join_url, passcode enc, recording_urls)`.

## 5. Events
`integration.connected/disconnected/error`, `calendar.busy_updated`, `online_meeting.created/updated/deleted`, `online_meeting.participant_joined/left`, `recording.available`.

## 6. Delivery plan
- [x] **E22-T01** Integration framework: OAuth flows, encrypted tokens, refresh, health, UI to connect/disconnect.
- [x] **E22-T02** Google Calendar: write lessons (outbox-driven), busy read via watch + sync tokens, busy blocks in conflict/availability.
- [x] **E22-T03** Google two-way edit handling (reschedule proposals; delete protection).
- [x] **E22-T04** Microsoft Graph calendar sync.
- [x] **E22-T05** CalDAV (iCloud) polling sync.
- [x] **E22-T06** OnlineMeeting abstraction; Zoom provider.
- [x] **E22-T07** Google Meet and Teams providers.
- [x] **E22-T08** Lessonspace provider; Daily.co/Whereby built-in rooms.
- [x] **E22-T09** Join links in portals/reminders with timed enablement.
- [ ] **E22-T10** (Phase 3) Video attendance ingestion, recordings, embedded classroom.

## Temporal workflows (E32)

Implement these processes as Temporal workflows following the rules in [E32](E32-workflow-orchestration-temporal.md) (deterministic workflow code, side effects in tenant-scoped activities that call services, tenant-prefixed workflow IDs, signals for human decisions). Where the requirements above mention sweeper tasks, `next_*_at` / `resume_at` columns or retry schedules, the workflow replaces them.

- [x] **E22-TW1** Calendar connection and meeting provisioning workflows (requires E32).

| Workflow | Started by | Steps, timers and signals | Replaces |
|---|---|---|---|
| `CalendarConnectionWorkflow` `calendar:{org}:{connection}` (long-running, `continue_as_new`) | Integration connected | Renew push channels before expiry → incremental sync on `changed` signals (from provider webhooks) with polling fallback timer → token refresh and error backoff. Signal `disconnect` ends it | Watch-renewal and polling beat jobs |
| `OnlineMeetingProvisioningWorkflow` | Online lesson scheduled, moved or cancelled | Create/update/delete the meeting at the provider with retries → store links → notify if provisioning ultimately fails | Ad hoc retries |

## Implementation notes (as built 2026-10-10)
- **Apps (ADR 0015):**
  - `integrations` is the reusable framework that E23 (accounting) and E27 build on: `IntegrationConnection` (personal or organisation level; access/refresh tokens and an app password or API key in `EncryptedField`s, never serialised), OAuth2 with PKCE, token refresh, health check, error and status bookkeeping, disconnect, and a provider registry (`integrations.providers`).
  - `calendar_sync` holds calendar sync and online meetings: `CalendarSyncSettings`, `SyncState`, `ExternalEventLink`, `ExternalBusyBlock`, `OnlineMeeting` and `MeetingPreference`. Every table has RLS.
- **Framework (T01):**
  - OAuth: `POST /integrations/oauth/start` returns the provider's URL. `state` is a signed, 15-minute token naming the organisation, user, provider, level and return path. The PKCE verifier is an HMAC of the state's nonce, so it is never stored and never passes through the browser.
  - The provider calls back to the fixed URL on the root host (`/api/v1/integrations/oauth/callback`, the only URL that can be registered). That forwards the browser to the organisation's app, which posts `code` and `state` to `/oauth/complete`. Completion only works for the same signed-in user and organisation.
  - CalDAV and Lessonspace connect with credentials (`POST /integrations/connections`). They are verified at the provider first; a CalDAV server URL is SSRF-checked and called only through `core.net.safe_urlopen`.
  - Reconnecting the same account updates the connection in place and signals the workflow (`reconnected`). Connecting a different account replaces the old connection.
  - Tokens refresh three minutes before expiry, under a row lock. A revoked grant sets `needs_reconnect`; any other failure sets `error` and the next success clears it. On each status change the owner (or `integrations.manage` holders, for organisation connections) gets an `integration_problem` notification, and `integration.error` is published.
  - Disconnecting revokes at the provider (best effort, after commit), clears the secrets and publishes `integration.disconnected`.
  - Permissions: `integrations.view`, `integrations.manage` and `integrations.personal`. Tutors and coordinators get `personal`; coordinators also get `view`. Admins see every connection with its health and last error; everyone else sees their own.
  - Providers: Google (Calendar + Meet), Microsoft 365 (Graph calendars + Teams), CalDAV/iCloud, Zoom and Lessonspace, plus built-in rooms (Daily.co, or Whereby with `INTEGRATIONS_BUILTIN_ROOMS=whereby`) on TutorTrack's own account. Each has a thin real client and an in-memory fake, used when the provider's keys are empty (`settings.INTEGRATIONS`). Fake state lives in the Django cache, so web and workers share it in development. CalDAV and Lessonspace use their fakes unless `INTEGRATIONS_CREDENTIAL_PROVIDERS_LIVE` is set (the default in production).
  - Provider HTTP (`providers/http.py`) retries 429 (honouring `Retry-After`) and 5xx briefly, then raises `RateLimited` or `ProviderError`. Longer waits belong to Celery or the workflow.
  - Deviation: no per-provider Celery queues. Pushes run on the existing `integrations` queue (task names under `tutortrack.integrations.*`).
- **Push (T02):**
  - The outbox handlers for `lesson.scheduled`, `rescheduled`, `updated`, `cancelled` and `lesson_series.created`/`updated` queue `sync_lesson`. That reconciles each lesson with its tutors' write calendars: create, update only when a content hash changes, delete when the lesson is cancelled or a tutor leaves it.
  - Planned lessons deleted outright publish no event, so a `pre_delete` receiver removes their events and meeting rooms after commit.
  - Events carry the lesson id in provider metadata (Google `extendedProperties.private`, a Graph single-value extended property, CalDAV `X-TUTORTRACK-LESSON`).
  - The default write calendar is a dedicated "TutorTrack" calendar we create. The title format is the org setting `integrations.calendar_title_format` (default "{service} – {students}"), overridable per user. Descriptions carry no notes unless `integrations.calendar_details` is on. The location is the join link (the tutor's host link) or the location's name.
  - Only lessons are pushed: calendar events (meetings, training) publish no domain events.
- **Busy (T02):**
  - Busy time is read with incremental sync tokens (Google), delta links (Graph) or a full time-range listing (CalDAV), over 1 day back to 120 days ahead. It is stored as `ExternalBusyBlock` with times only: no titles, attendees or descriptions. Free/transparent events, cancelled events and our own lesson events never become blocks. An expired token falls back to a full sync.
  - Dependency direction: scheduling doesn't import integrations. `scheduling/external.py` defines busy-source and join-link hooks, and `calendar_sync` registers both in `ready()`.
  - `conflicts.check` adds a hard `tutor_external_busy` conflict. `availability.busy_intervals` (free slots) and `interval_fit` (matching) include external busy time. Blocks of disconnected or broken connections are ignored, and disconnecting deletes them.
  - AC: an event added in the fake Google calendar becomes a block after a push notification or the 5-minute poll, and blocks booking (tests).
- **Two-way (T03):** this is opt-in per user (`two_way`) and needs the org setting `integrations.calendar_two_way` (on by default). The write calendar is then also watched.
  - A moved TutorTrack event is applied with `update_lesson` when the calendar's owner holds `scheduling.lesson.edit` and there is no hard conflict.
  - Otherwise there is no reschedule-request model, so we create a CRM task "Reschedule request: …" (assigned to the job's account manager, due at the lesson). We publish `calendar.reschedule_proposed`, put the event back at the lesson's time, and tell the tutor (`calendar_notice`). The proposal is remembered so it isn't repeated.
  - An event deleted outside never cancels the lesson: it is re-created and the tutor warned. For CalDAV, an event missing from a full listing counts as deleted.
  - Deviation: re-creating deleted events and proposing moves only happen with two-way on, because one-way sync doesn't read the write calendar.
- **Microsoft (T04):** Graph delta queries on the calendar view and subscriptions (2.5-day lifetime, renewed early). The webhook answers the `validationToken` handshake and checks `clientState`.
- **CalDAV (T05):** an iCloud app-specific password, stored encrypted, with a polling interval of 10 minutes. There are no push channels. The E08 iCal feeds remain for read-only use.
- **Webhooks:** `/webhooks/google-calendar` and `/webhooks/microsoft-graph` (root URLs, like Stripe's). The channel token is `org.state.hmac`, short enough for Graph's 128-character `clientState` and checkable before any lookup. It is matched against the stored channel id before signalling `changed`.
- **Meetings (T06-T08):** `calendar_sync.meetings.reconcile` makes the provider match the lesson. A planned online lesson gets a meeting; a move updates it; cancelling, going in-person or typing a link by hand removes ours (a hand-typed link is never replaced).
  - Provider order: the lesson's `meeting_provider`, then the job's, the tutor's `MeetingPreference`, the per-service map `integrations.video_provider_by_service`, and finally the org default `integrations.video_provider` (default `builtin`).
  - Account: the tutor's own connection for that provider, else the organisation's. With neither, the built-in room is used (deviation: no error, so online lessons always get a room).
  - Zoom: a meeting per lesson or the tutor's personal room, with waiting room, passcode and recording settings. The passcode is encrypted.
  - Teams: Graph `onlineMeetings`.
  - Google Meet: deviation, uses the Meet REST API `spaces` rather than conference data on the calendar event, so meetings don't depend on calendar write settings. The link still reaches the calendar event via the lesson.
  - Lessonspace: one space per job (default) or per lesson, with leader and per-student launch URLs.
  - The participant link is written to `Lesson.meeting_url`/`meeting_provider` (via `update_lesson`, `notify=False`). Our own `lesson.updated` is recognised by its workflow actor and doesn't start another provisioning.
  - Staff can re-run provisioning with `POST /online-meetings/provision`.
- **Join links (T09):**
  - `scheduling.external.join_link(lesson, role, person)` gives tutors the host link and students their own link (Lessonspace) or the participant link, with `opens_at` = start − `integrations.join_window_minutes` (default 10).
  - Portal lesson cards and the tutor's day carry `join_url`/`join_opens_at`. The tutor lesson page uses `GET /lessons/{id}/join`, which has an `open` flag. A shared `JoinButton` stays disabled ("Join opens at 15:50") until the window opens.
  - Reminders and other lesson notifications get a per-recipient `lesson.join_url`, and the default templates use it.
- **Workflows (TW1):**
  - `CalendarConnectionWorkflow` `calendar:{org}:{connection}` (queue `integrations`) is started by `integration.connected` for personal calendar connections. Each loop runs `prepare` (refresh the token, create the TutorTrack calendar, renew channels within 12 hours of expiry), then backfill on the first loop of each run, then an incremental sync. It then waits for `changed` (webhooks, settings changes, "Sync now") or the polling fallback, whichever is first.
  - Failures back off exponentially (2 minutes doubling, at most 1 hour). `needs_reconnect` waits for `reconnected`. `disconnect` tears down (stops channels, deletes blocks and links) and ends it. The workflow continues as new every 200 loops.
  - `OnlineMeetingProvisioningWorkflow` `online-meeting:{org}:{lesson or series}:{event}` reconciles each lesson with retries (10 seconds doubling, at most 10 minutes, 6 attempts). On final failure it marks the meeting failed, publishes `online_meeting.failed` and alerts staff (`staff_meeting_failed`). The id includes the event because Temporal ids can't be reused.
  - Replay histories are in `backend/tests/workflow_histories/`. The continue-as-new test runs on the local dev server (`temporal_local_env`), because the time-skipping test server kept its time lock after a continue-as-new and stalled timers in later tests.
- **Frontend:**
  - Admin `/settings/integrations` lists your connections (status, last sync, errors, check, disconnect, sync settings: busy calendars, write calendar, two-way, title format), your video provider, and the organisation's connections with their owners and errors. It also connects organisation-level Zoom and Lessonspace and sets the video defaults.
  - Tutor portal `/portal/tutor/calendar` connects Google, Microsoft, iCloud and Zoom and holds the sync settings and video preference.
  - OAuth returns to the page, which completes the connection.
- **Events:** `integration.connected`, `integration.disconnected`, `integration.error`, `calendar.busy_updated`, `calendar.settings_changed`, `calendar.reschedule_proposed`, `online_meeting.created`, `online_meeting.updated`, `online_meeting.deleted` and `online_meeting.failed`.
- **Not built:** T10 is Phase 3: video attendance ingestion (`online_meeting.participant_joined/left`), recordings (`recording.available`) and the embedded classroom (FR-22-5).
