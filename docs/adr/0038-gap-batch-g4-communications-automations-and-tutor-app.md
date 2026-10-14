# ADR 0038: Realtime notifications, template versions, digests, account emails and the tutor app (gap batch G4)

- **Status:** Accepted
- **Date:** 2026-10-14
- **Epics:** E13 (FR-13-1/2/3/5/7/8/9), E14 (FR-14-1/3/6), E16 (FR-16-2/3/4/9); E02/E03
  carried-forward account emails; gap batch G4. Builds on ADR 0027 (E13 Phase 2), ADR 0014
  (automations) and ADR 0023 (PWA and Web Push).

## Context
Gap batch G4 covers thirteen items deferred inside done tickets. Six needed decisions:
1. FR-13-8 asks for a realtime bell "via SSE or WebSockets"; the deploy runs gunicorn with
   sync WSGI workers.
2. FR-13-3 asks for template overrides per language and per branch; `MessageTemplate` had a
   `locale` column that was always `en-GB` and meant "the organisation's override".
3. Digests (tutor daily agenda, family weekly schedule, message digest) must arrive at each
   person's local time, with their own choices, and without `next_*_at` columns.
4. Account emails (verification, magic link, reset, invitation, email change, security
   notices, closure) were plain Django templates from the platform sender; some carry
   single-use tokens, and some are sent before any organisation exists.
5. Mailchimp and Brevo don't sign webhooks, and the existing sync upserts members as
   `subscribed`, which would re-subscribe people who left there.
6. Students have no address of their own; E29 forbids marketing to under-18s and wants
   under-13s reached only through their guardians.

## Decision

### 1. SSE over Redis pub/sub, ASGI-ready, polling as fallback
- In-app notifications (and "marked read") publish a small JSON message after commit on
  `comms:inapp:<org>:<user>`. `GET /api/v1/notifications/stream` (authenticated,
  `HasOrganisation`) subscribes to exactly that channel, taken from the request's
  organisation and user, so a stream can't see another tenant or person.
- The view returns an async generator under ASGI (`redis.asyncio`) and a sync generator
  under WSGI; streams end after 5 minutes with an SSE `retry:` so the browser reconnects,
  and send keep-alive comments. Redis failures degrade to an `unavailable` event.
- The bell keeps its 30-second poll whenever the stream isn't live. Production needs ASGI
  for many open streams; the switch (uvicorn worker, proxy settings) is documented in
  `docs/runbooks/realtime-notifications.md` and is not part of this change.
- Rejected: Django Channels/WebSockets (a new dependency and a channel layer for a
  one-way feed).

### 2. Template versions by language, then branch
- `MessageTemplate.locale` now means "for this language" (blank = every language; a data
  migration turns the old `en-GB` rows into blank) and a nullable `branch` is added; two
  partial unique constraints keep one active version per slot.
- Resolution: the recipient's locale (exact, then language: `fr-CA` → `fr`), branch version
  before organisation-wide, then any-language versions (branch, then organisation), then
  the platform default. Language wins over branch because a reader in the wrong language is
  worse than the wrong branch's wording. Recipients carry their locale (contact language,
  the user's locale); the branch comes from the notification's record (`branch_id`).
- The editor addresses a slot with `?locale=&branch=`; `/variants` lists the versions.

### 3. Digests: a 15-minute fan-out, dedupe per local date
- Three notification types (off by default, editable like any other) and a
  `DigestPreference(person, kind, enabled, send_time, weekday)` table; no row means the
  organisation's defaults (`comms.digest_*`).
- A Celery beat task runs every 15 minutes per organisation (`fan_out_per_org`, like lesson
  reminders) and sends each digest to people whose local time is within an hour after their
  chosen time (and on their day, for the weekly one). The dedupe key is the person's local
  date, so each digest goes once a day and a missed run is caught by the next. Times come
  from the clock and the person's timezone (user timezone, else the organisation's); there
  is nothing to sweep and no `next_*_at`.
- Rejected: a Temporal Schedule per organisation (schedule life-cycle for every
  organisation, for what is a short, stateless, idempotent send like the reminder task).
- The same task runs the once-a-day checks from 09:00 organisation time: cards expiring this
  or next month (once per card and expiry month) and, on the 1st, last month's statement
  (PDF attached) to clients who owe money.

### 4. Account emails as locked comms types
- Ten `account_*` types (category `account`, `locked`: editable but can't be switched off).
  Inside an organisation the email is sent with its branding, sender name and verified
  domain, using the organisation's version if there is one, else the translated platform
  text; it is logged with every secret link replaced by "[link hidden]". With no
  organisation (platform host, a new account) the translated platform template is sent from
  the platform sender and nothing is logged.
- The identity and tenancy tasks take an optional `organisation_id`, captured by the caller
  when it queues the task (`identity.tasks.current_org()`), so old queued tasks still work.

### 5. Unsubscribes flow back through signed webhook URLs and a read-back
- Webhook URLs carry a token signed with our secret naming the organisation, provider and
  connection (a reconnect gives a new URL); events for another audience are ignored.
- "Sync now" first reads who left the audience (`opted_out` on each client) and applies them
  before upserting, so nobody is re-subscribed.
- Unsubscribe: withdraw the E29 marketing email consent (method `import`, source
  `<provider>:unsubscribe`) and drop email from the E13 `marketing` preference: service
  emails still go. Spam report: the same plus an email suppression. Cleaned / hard bounce:
  suppression only. Only contacts currently opted in are changed, so our own unsubscribes
  don't create records.

### 6. Students as recipients, guarded twice
- `comms.student_direct` (off / adults / 13 and over) adds the student to lesson messages,
  reached at their own login or, for adult learners, the contact who is the student; an
  address that already gets the message as a family contact isn't duplicated.
- A comms pre-send hook blocks anything addressed straight to a student under 13 (or of
  unknown age) unless a guardian is on the conversation, and any marketing to a student under
  18 regardless of `privacy.child_defaults`; E29's own hook still runs.

## Smaller choices
- New notification types live in `comms/g4_types.py` (card expiring, monthly statement,
  low attendance, expense approved/rejected, booking declined, package running low).
- Automations: actions "Send the lesson feedback survey" (E09 rules apply), "Add to a
  mailing list" (a client tag used by segments, plus a consent-respecting Mailchimp/Brevo
  sync), "Send a WhatsApp message" (approved utility template, opted-in recipients; marketing
  templates belong in broadcasts) and "Send a saved message" (a canned reply rendered with
  the record's variables); a `package` subject with four triggers and the "Package under 2
  hours" recipe (`package.low` plus conditions on hours left).
- Tutor app: tutors book lessons on their own jobs (`tutor_access.create_lessons`) and move
  their lessons (`scheduling.lesson.reschedule`) through the scheduling services; conflict
  feedback is a dry run of the E08 engine; tutors can't override conflicts; without the
  permission the app sends a reschedule request. Previous report and lesson history read
  through `scope_queryset` (own lessons and reports). Dictation uses the browser's Web
  Speech API where available; nothing is sent to TutorTrack.
- Push by default for `conversation_message_tutor`, `conversation_message_family` and
  `inbox_new_message`.

## Consequences
- Realtime works under `runserver` and the current deploy for a handful of users; it needs
  the ASGI switch before wide use. The bell is never worse than before.
- Existing template overrides keep applying to every language and branch.
- Organisations must switch digests and statements on; card notices, expense decisions,
  booking declines, low-package and low-attendance alerts are on by default.
- Mailchimp/Brevo customers should paste the webhook address shown in Settings → Messaging.
