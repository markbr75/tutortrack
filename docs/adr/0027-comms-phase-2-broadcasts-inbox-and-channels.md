# ADR 0027: Communications Phase 2: broadcasts on Temporal, one inbox for every channel, WhatsApp and senders inside `comms`

- **Status:** Accepted
- **Date:** 2026-10-14
- **Epic:** E13 Phase 2 (T10–T12, TW1) and E15-T09. Builds on ADR 0002 (Temporal), the E13 MVP pipeline (notes in E13), ADR 0023 (Web Push as an E13 channel) and the E22 integration framework.

## Context
E13 Phase 2 adds four features:
- broadcasts to segments, with tracking;
- a two-way conversations inbox (email and text replies, WhatsApp, portal chat, assignment);
- WhatsApp, custom sending domains and Mailchimp/Brevo sync.

E15-T09 needs portal messaging on the same inbox. E31 will later build suggested replies and summaries on it.

The constraints:
- Bulk sending must be throttled, pausable and cancellable, without a beat job.
- Marketing must respect E29 consent and unsubscribes.
- Webhooks arrive before any tenant is known.
- Inbound webhooks must be authenticated.
- Tenant-influenced URLs must go through `core.net`.
- Nothing may double-send when providers or the outbox redeliver.

## Decision
1. **Everything stays in `comms`** (no parallel app). New tenant tables, all with RLS: `Segment`, `Broadcast`, `BroadcastRecipient`, `Thread`, `ThreadParticipant`, `ThreadMessage`, `CannedReply`, `WhatsAppTemplate`, `PhoneNumber` and `SenderDomain`. `Message` gains `thread` and `meta`. One platform table, `InboundRoute`, routes inbound texts like `payments.AccountRoute` routes payment webhooks.
2. **Free-form messages reuse the delivery pipeline.**
   - A new `services.queue_message` creates a `Message` with a dedupe key and dispatches it like a notification: suppressions, quiet hours, provider sends, delivery webhooks.
   - Broadcasts and inbox replies use hidden registry types (`broadcast_marketing`, `broadcast_operational`, `inbox_reply`). The existing channel code, unsubscribe headers and tracking apply without copies.
3. **`BroadcastWorkflow` owns timing.**
   - It waits for the scheduled time, snapshots recipients once into `BroadcastRecipient` (with skip reasons), queues batches with a pause between them, and waits out quiet hours using the workflow clock.
   - Activities hand each message to the Celery send task after commit.
   - Pause, resume and cancel are signals sent by the services after commit. The workflow also re-reads the database state when a batch finds the broadcast isn't sending.
4. **Consent is checked in bulk at resolution time.**
   - Marketing needs the E29 consent for the channel's category (`marketing_email`; `marketing_sms` for texts and WhatsApp). An organisation without that consent type falls back to the contact's "receives marketing" flag.
   - The person's preference for the new `marketing` category must also allow the channel. Unsubscribe links switch that preference off and are counted per broadcast.
   - WhatsApp always needs an explicit opt-in (a preference naming it).
5. **One thread model for every channel.**
   - Inbound email, text, WhatsApp and portal chat become `ThreadMessage`s; internal notes are entries too. A unique `provider_ref` dedupes webhook retries.
   - Snooze is evaluated when read (`snoozed_until <= now` counts as open), so there is no sweeper.
   - The SLA is `awaiting_reply_since` plus a setting.
   - Tutors get `comms.inbox.*:own` through participation.
6. **Inbound authentication and routing.**
   - Twilio requests are signature-checked, as before.
   - Postmark inbound has no signature. It uses its own reply domain and server with a secret URL token (constant-time compare). Thread addresses carry an HMAC of the organisation and thread, so a guessed address can't inject into a conversation.
   - Texts route by the organisation's own number, else to the organisation that last texted that phone from the shared sender within 30 days.
7. **Providers have fake twins.** Twilio WhatsApp, Postmark Domains, Mailchimp and Brevo are used only with platform keys. Mailchimp's data-centre host comes from the tenant's key, so it is pattern-checked and opened through `safe_urlopen`.
8. **Mailchimp and Brevo are E22 credential providers** (capability `marketing`), like E23's accounting providers.
   - Sync is short and stateless: one contact per consent change or contact edit (Celery), and "Sync now" in pages. It doesn't need a workflow.
   - Consented contacts are upserted with their family's tags; the rest are unsubscribed.
9. **Portal messaging (E15-T09) is the inbox.** Families, students (when allowed) and tutors post into threads through portal endpoints scoped to their household or tutor profile. Staff see everything. Optional contact-detail blocking and flagging cover safeguarding.
10. **Seam for E31:** `selectors.thread_transcript` and `selectors.thread_digest` return plain data, and broadcast rendering is a service function. AI features can read conversations and draft copy without touching models.

## Consequences
- Broadcast statistics are computed from the messages each time they are read (a snapshot is stored at the end). Very large broadcasts may want cached counters later.
- Daily digest emails of unread messages aren't built; a per-thread, per-hour dedupe keeps notifications calm. Realtime updates are polling, as in the MVP.
- WhatsApp templates are recorded by staff (no sync with Twilio Content approvals), and only Twilio's WhatsApp API is supported. Sender domains are checked when staff ask (no polling workflow).
- Unsubscribes made in Mailchimp or Brevo aren't pulled back yet.
- The new events are internal (not offered as webhook event types) until E27 decides how to expose conversations.
