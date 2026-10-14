# ADR 0023: Tutor PWA: service worker, idempotent offline outbox and Web Push

- **Status:** Accepted
- **Date:** 2026-10-13
- **Epics:** E16 (T08, T09). Builds on ADR 0003 (database roles and RLS), E13 (communications
  pipeline), E24 (tenant branding and manifest) and the `Idempotency-Key` middleware
  (docs/02-architecture.md §8).

## Context
Tutors work in places with poor signal: in students' homes, on transport, in school
basements. FR-16-3 asks that the next 7 days of lessons be on the phone, and that registers
and reports can be done offline and synced later. Conflicts must be resolved on the server,
with a "your changes need review" message. FR-16-9 asks for Web Push with preferences per
category. The client and tutor portals are one Vite app served at `/portal/` on each
tenant's host, and the family portal must stay online-only. A replay must never record a
completion twice. Push endpoints are capability URLs that come from browsers, so they are
secrets and also an SSRF vector.

## Decision
1. **A small hand-written service worker, built by a Vite plugin.** `src/sw/sw.ts` is
   compiled after the app build into `/portal/sw.js` (IIFE). The plugin injects the build's
   precache list and a version hash. We did not use vite-plugin-pwa/Workbox. The worker
   needs four behaviours: precache, network-first with a cache fallback, Background Sync of
   our own queue, and push. Workbox's background-sync queue stores opaque `Request`s, so
   the page could not show or explain them. One file with no new dependencies is easier to
   check and merge. The worker has its own `tsconfig.sw.json` (WebWorker lib). The scope is
   `/portal/`, so the admin app is not affected.
2. **Cache tutor data by allowlist only.** API reads are cached only for paths in
   `offline/routes.ts`: the tutor's lessons, reports, Today and the offline pack. Family
   data, billing and other API reads are never cached. Sign-out, or a different user
   signing in on the device, clears the cache and the outbox.
3. **The offline pack is a read model, not side effects.** `GET /api/v1/tutor/offline`
   returns the lessons of the coming week, each with the tutor's report or, if there is
   none yet, the template fields it would get. We don't open reports just to cache their
   forms.
4. **Our own outbox, shared by the page and the worker.** Offline changes are typed items
   (`lesson.complete`, `report.save`) in IndexedDB. The page replays them on start-up and on
   `online`. The worker replays them on a `sync` event when the app is closed. Idempotency
   comes from the server: each request carries `Idempotency-Key` = the item id, and this is
   the same key as the failed online attempt. A replay of a request that already arrived is
   answered from the stored response. Items for one lesson replay in order. Report saves
   merge to the latest answers.
5. **Conflicts use HTTP preconditions.** Lesson reports now send an `ETag`. `PUT` and
   `submit` accept `If-Match` and return 412 when the report changed. Any other refusal
   (for example a lesson already completed by the office) is also kept and shown for
   review, with the server's reason. Nothing is overwritten silently or dropped.
6. **Web Push is an E13 channel.** `push` joins email, SMS and in-app. It is available
   wherever `in_app` is, it is on by default for the FR-16-9 types, and it uses the in-app
   wording unless an organisation edits a push template. It goes through the same pipeline
   (settings, recipient preferences, dedupe keys, message log). A push is created only when
   the user has a device. Subscriptions (`comms.PushSubscription`) are tenant-scoped,
   visible only to their owner, and encrypted at rest (endpoint and keys), with a SHA-256
   hash for upserts.
7. **The crypto comes from a library, the HTTP stays ours.** `pywebpush` (pinned 2.5.0)
   encrypts with aes128gcm and `py_vapid` signs with VAPID. The request is made by
   `core.net.safe_urlopen`, after a check that the endpoint is https on a known push service.
   Push errors never include the endpoint. Without a VAPID private key, `FakePush` records
   pushes for development and tests.

## Consequences
- Tutors can take a register and write reports with no signal. The office sees each change
  once. Edits that compete with office edits are shown to the tutor and never lost.
- `/portal/sw.js` has its own CloudFront behaviour with caching turned off
  (`infra/terraform/frontend.tf`). Otherwise devices would keep an old worker after a deploy.
- Report reads carry ETags. API clients may now send `If-Match`. Without it nothing changes.
- Two more Python dependencies (`pywebpush`, which pulls `aiohttp`, `http-ece`, `py-vapid`).
  The frontend has no new dependencies.
- Organisations that customised a notification type's channels before this release don't
  get push for that type until they add it.
- iOS shows pushes only from the Home Screen app (16.4+). The notifications page explains
  this.
- Native shells (T11, Capacitor) are Phase 3. They can reuse the API, the outbox protocol
  and the push channel. Native pushes would need an APNs/FCM sender behind the same
  `PushProvider` protocol.
