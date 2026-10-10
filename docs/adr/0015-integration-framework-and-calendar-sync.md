# ADR 0015: A reusable integration framework; calendars and meetings sync by reconciliation

- **Status:** Accepted
- **Date:** 2026-10-10
- **Epic:** E22 (framework reused by E23 and E27)

## Context
Tutors want their lessons in Google, Outlook or iCloud. Their personal commitments should
block bookings, and online lessons should get a meeting room automatically. Accounting
(E23) and the public API (E27) need the same plumbing for connected accounts:
- OAuth with refresh;
- encrypted secrets;
- health checks and errors shown to the right person;
- disconnecting.

There are no provider credentials in development or CI, so every flow has to run end to
end without them. Calendar data is personal, and providers deliver changes out of order,
twice, or not at all.

## Decision
1. **Two apps.**
   - `integrations` is the generic framework: the `IntegrationConnection` model, OAuth, refresh, health and errors, disconnect, and the provider registry.
   - `calendar_sync` holds everything about lessons and external calendars or meeting rooms.

   E23 adds an `accounting` app on top of `integrations`. Other apps react to `integration.connected/disconnected/error` events; they never write connections.
2. **Connections.** A connection belongs to a user (personal) or to the organisation.
   - Tokens, app passwords and API keys are `EncryptedField`s, audited as sensitive and never serialised.
   - There is at most one live connection per (user or organisation, provider). Reconnecting the same account updates it in place.
   - Status is `active`, `error` (retrying; the next success clears it), `needs_reconnect` (the grant was revoked) or `disconnected`. People are notified only when the status changes.
3. **OAuth without server-side state.** The `state` parameter is a signed, short-lived token naming the organisation, user, provider, level and return path. The PKCE verifier is `HMAC(SECRET_KEY, nonce)`, so it is neither stored nor exposed.
   - Providers call back to one fixed URL on the root host, the only one that can be registered. It forwards to the organisation's app, which completes the exchange while signed in.
   - Completion checks that the signed-in user and organisation are the ones in `state`. This stops someone attaching their calendar to another person's account, or the reverse.
4. **Provider registry with fakes.** Each provider registers a `ProviderSpec` (capabilities, auth type, levels, credential fields, polling interval) and factories for OAuth, credential, calendar and meeting clients.
   - When the platform keys are empty, a fake twin keeps its state in the Django cache. Fakes consent instantly, simulate failures (`fake.fail`) and revoked grants (`fake.revoke`), and act as the user's calendar in tests (`FakeCalendar`).
   - Real clients are thin. Provider hosts are constants. CalDAV server URLs are user input and go through `core.net.safe_urlopen`.
5. **Reconciliation, not commands.** Pushing a lesson (`sync_lesson`) and provisioning a meeting (`meetings.reconcile`) look at the lesson's current state and make the outside world match it:
   - create, update or delete;
   - skip when a content hash is unchanged.

   Duplicate, retried or reordered events are therefore harmless, and the same function serves outbox handlers, retries, backfills and the "re-provision" button.
6. **Scheduling stays independent.** `scheduling/external.py` defines two extension points:
   - **Busy sources**, used by conflicts (a hard `tutor_external_busy` conflict), free slots and matching's batched fit.
   - **Join-link resolvers**, used by portals and reminders.

   `calendar_sync` registers both. Scheduling never imports the integration apps.
7. **Privacy.** Busy blocks keep times only, never titles, attendees or descriptions. Our own events go to a dedicated "TutorTrack" calendar by default, without notes unless the organisation opts in.
8. **Two-way edits are proposals by default.** An event moved outside is applied only if its owner may edit the lesson. Otherwise it becomes a CRM reschedule task and the event is put back. An event deleted outside is re-created, never cancelled.
9. **Temporal for the long-running parts.**
   - `CalendarConnectionWorkflow` (one per connection, continue-as-new) owns token refresh, channel renewal, the polling fallback, `changed` signals from push webhooks, error backoff and teardown. This replaces beat jobs and `next_*_at` columns.
   - `OnlineMeetingProvisioningWorkflow` retries provisioning with backoff and alerts staff on final failure.
   - Calendar pushes are short, stateless Celery tasks on the `integrations` queue.
   - Webhook tokens are `org.state.hmac`, which is short enough for Graph's `clientState` and verified before any database lookup.

## Consequences
- E23 and E27 get connections, OAuth, refresh, health and the admin "Integrations" page without new plumbing; they register providers and react to the events.
- Everything runs locally and in CI with fakes. Production needs the provider apps (Google and Microsoft redirect URI `$APP_URL/api/v1/integrations/oauth/callback`, with calendar and meeting scopes) and a publicly reachable `INTEGRATIONS_WEBHOOK_BASE_URL` for push.
- Without a reschedule-request model, proposals are CRM tasks; a proper request flow (E15 or later) can replace them in one place (`_propose_move`).
- Disconnecting leaves already-written events in the user's calendar, because the tokens are gone. Reconnecting creates new events.
- Google Meet uses the Meet REST API (spaces) rather than calendar conference data, so meetings don't depend on calendar write settings.
- The time-skipping Temporal test server keeps its time lock after a continue-as-new. The continue-as-new test therefore runs on the local dev server.
