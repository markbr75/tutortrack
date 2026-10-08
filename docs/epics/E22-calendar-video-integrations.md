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
- [ ] **E22-T01** Integration framework: OAuth flows, encrypted tokens, refresh, health, UI to connect/disconnect.
- [ ] **E22-T02** Google Calendar: write lessons (outbox-driven), busy read via watch + sync tokens, busy blocks in conflict/availability.
- [ ] **E22-T03** Google two-way edit handling (reschedule proposals; delete protection).
- [ ] **E22-T04** Microsoft Graph calendar sync.
- [ ] **E22-T05** CalDAV (iCloud) polling sync.
- [ ] **E22-T06** OnlineMeeting abstraction; Zoom provider.
- [ ] **E22-T07** Google Meet and Teams providers.
- [ ] **E22-T08** Lessonspace provider; Daily.co/Whereby built-in rooms.
- [ ] **E22-T09** Join links in portals/reminders with timed enablement.
- [ ] **E22-T10** (Phase 3) Video attendance ingestion, recordings, embedded classroom.

## Temporal workflows (E32)

Implement these processes as Temporal workflows following the rules in [E32](E32-workflow-orchestration-temporal.md) (deterministic workflow code, side effects in tenant-scoped activities that call services, tenant-prefixed workflow IDs, signals for human decisions). Where the requirements above mention sweeper tasks, `next_*_at` / `resume_at` columns or retry schedules, the workflow replaces them.

- [ ] **E22-TW1** Calendar connection and meeting provisioning workflows (requires E32).

| Workflow | Started by | Steps, timers and signals | Replaces |
|---|---|---|---|
| `CalendarConnectionWorkflow` `calendar:{org}:{connection}` (long-running, `continue_as_new`) | Integration connected | Renew push channels before expiry → incremental sync on `changed` signals (from provider webhooks) with polling fallback timer → token refresh and error backoff. Signal `disconnect` ends it | Watch-renewal and polling beat jobs |
| `OnlineMeetingProvisioningWorkflow` | Online lesson scheduled, moved or cancelled | Create/update/delete the meeting at the provider with retries → store links → notify if provisioning ultimately fails | Ad hoc retries |
