# E13 — Communications & Notifications

| | |
|---|---|
| **Phase** | MVP (email, SMS, templates, reminders); Phase 2 (WhatsApp, inbox, push, broadcasts with segments) |
| **Depends on** | E01 (outbox), E05 |
| **Parity** | TutorCruncher email definitions (toggleable), SMS, broadcasts, branded templates; TutorBird reminders (custom timing), bulk email/SMS. **Beyond:** two-way inbox, WhatsApp, push, per-recipient preferences |

## 1. Summary
A unified messaging system: transactional notifications driven by domain events, configurable templates per channel, lesson reminders, broadcasts to segments, a two-way conversation inbox (email replies, SMS replies, in-app chat), delivery tracking, preferences and quiet hours.

## 2. Functional requirements

### FR-13-1 Channels and providers
- Email (Postmark transactional, SES bulk), SMS (Twilio; alphanumeric sender IDs where allowed), WhatsApp (Twilio WhatsApp Business, pre-approved templates; Phase 2), in-app notifications (bell + realtime via SSE/WebSocket), web push (E16).
- Tenant sender identity: `From: "Bright Minds Tutoring" <noreply@mail.tutortrack.app>` with reply-to routing, or **custom sending domain** with DKIM/SPF/DMARC verification wizard (plan-gated).
- SMS consumption deducted from E04 credits; per-country pricing table.

### FR-13-2 Notification types (catalogue)
A registry of notification types, each with: key, trigger event, recipients resolver (client contacts by preference, student, tutor(s), staff by role/assignee), default channels, default template, default enabled flag, configurable timing (for reminders), and category (for preferences). Initial catalogue:
- **Scheduling:** lesson booked/confirmed, lesson changed, lesson cancelled, lesson reminder (X hours before; up to 3 reminders), series created (schedule summary), booking request received/approved/declined, tutor assigned (to client and to tutor), daily agenda for tutors (morning digest), weekly schedule for clients.
- **Delivery:** report shared, report due/overdue (tutor), unconfirmed lesson nudge, low attendance alert.
- **Billing:** invoice issued, invoice reminder (each schedule step), payment received/receipt, payment failed, payment request, low balance/package low, card expiring, statement.
- **Payroll:** pay run paid/remittance, expense approved/rejected, payout failed.
- **People/Account:** portal invitation, welcome, password reset, magic link, new device login.
- **Leads/Recruitment:** enquiry received (auto-acknowledge + staff alert), application received, interview invitation, compliance document expiring.
- **Staff alerts:** task assigned, mention, new message in inbox, dispute opened.
- **AC:** an admin can disable "lesson reminder SMS" org-wide while keeping email reminders, and set reminder timing to 24h and 2h.

### FR-13-3 Templates
- Per notification type × channel × locale, with an org override of the platform default; branch override optional.
- Editor: subject, rich body (email: block editor with branding header/footer; SMS: plain with character/segment counter; WhatsApp: mapped approved template), **merge variables** with autocomplete (e.g. `{{ student.first_name }}`, `{{ lesson.start|datetime:"short" }}`, `{{ invoice.pay_url }}`), conditional blocks, preview with sample or real record, send test.
- Rendering: sandboxed Jinja2 (no attribute access to private fields; whitelisted variables per type), auto-escaping, tenant terminology.
- Template versioning and revert.

### FR-13-4 Delivery pipeline
- `send_notification(type, subject_obj, context)` → resolve recipients → check preferences/quiet hours/consent → render → enqueue per channel → provider send → track status (`queued, sent, delivered, opened, clicked, bounced, failed, complained`) via provider webhooks.
- De-duplication key (type + subject + recipient + time bucket) so retries/events never double-send.
- Quiet hours (org setting; e.g. no SMS 21:00–08:00 recipient local time) → defer.
- Bounce/complaint handling: mark email invalid, show warning on contact, suppress future sends.
- `MessageLog` visible on record timelines (E05).

### FR-13-5 Recipient preferences
- Per contact/student/tutor: channel preferences per category (scheduling, billing, reports, marketing), language, opt-outs. Transactional legally-required messages (invoices) can't be fully disabled but can switch channel.
- Unsubscribe links on marketing (one-click, RFC 8058 List-Unsubscribe).
- SMS STOP handling.

### FR-13-6 Broadcasts (bulk messages)
- Compose email/SMS to a **segment**: saved view of clients/contacts/students/tutors (E05 filters), or recipients of a class/job/tag/pipeline stage (fixes the TutorCruncher reviewer complaint).
- Schedule send, preview recipients count, exclude opted-out, track opens/clicks, attachments (email).
- Marketing vs operational flag (affects consent rules).

### FR-13-7 Conversations inbox (Phase 2)
- Two-way threads per client/tutor: email replies (inbound parse to a thread-specific reply address), SMS replies (Twilio number per org/branch), WhatsApp, in-app chat from portals.
- Shared team inbox with assignment, status (open/snoozed/closed), internal notes, canned replies, SLA timer.
- **Tutor ↔ parent messaging** through the platform (safeguarding: all messages logged and visible to staff; a setting forbids direct contact sharing; profanity/contact-detail detection flags; E29).
- Notifications of new messages via push/email digests.

### FR-13-8 In-app notifications
- Bell feed per user with read/unread, deep links, "mark all read"; realtime updates (Django Channels or SSE via Redis pub/sub).

### FR-13-9 Mailchimp/marketing sync (Phase 2)
- Sync contacts with marketing consent and tags to Mailchimp/Brevo audiences (via E27 integration framework).

## 3. Data model
`NotificationType` (registry in code + `OrgNotificationSetting(type, enabled, channels, timing JSONB)`), `MessageTemplate(type, channel, locale, branch, subject, body, version, is_active)`, `Message(channel, to, from, subject, body_rendered, status, provider_ref, related object, thread, dedupe_key, scheduled_for)`, `MessageEvent` (delivery events), `CommunicationPreference(person generic, category, channels)`, `Suppression(address, reason)`, `Broadcast(segment definition, channel, content, status, stats)`, `Thread`, `ThreadParticipant`, `InboundMessage`, `InAppNotification`, `SenderDomain(dns records, verified)`, `PhoneNumber(provider, number, branch)`.

## 4. API
`/api/v1/notification-settings`, `/message-templates` (+ preview, test-send), `/messages` (log), `/broadcasts`, `/threads` (+ messages, assign, close), `/notifications` (in-app), `/me/preferences`, `/sender-domains`, `/webhooks/{postmark,ses,twilio}`, `/inbound/email`, `/inbound/sms`.

## 5. Events
`message.queued/sent/delivered/bounced/failed/opened/clicked`, `message.received`, `thread.assigned/closed`, `broadcast.sent`.

## 6. Permissions
`comms.settings.manage`, `comms.template.manage`, `comms.broadcast.send`, `comms.inbox.{view,reply,assign}`, `comms.message.view_log`; tutors: threads involving them only.

## 7. Delivery plan
- [x] **E13-T01** Notification type registry, org settings, recipient resolvers.
- [x] **E13-T02** Template model, sandboxed renderer, variable whitelist per type, preview/test send.
- [x] **E13-T03** Email channel (Postmark) with delivery webhooks, bounces, suppressions.
- [x] **E13-T04** SMS channel (Twilio), credits deduction, STOP handling, quiet hours.
- [x] **E13-T05** Event → notification subscribers for the MVP catalogue; dedupe keys.
- [x] **E13-T06** Lesson reminder scheduler (multiple offsets, per-recipient tz).
- [x] **E13-T07** Preferences and unsubscribe.
- [x] **E13-T08** In-app notifications with realtime feed.
- [x] **E13-T09** Frontend: notification settings, template editor, message log on timelines.
- [x] **E13-T10** (Phase 2) Broadcasts with segments and tracking.
- [x] **E13-T11** (Phase 2) Conversations inbox (email/SMS inbound, in-app chat, assignment).
- [x] **E13-T12** (Phase 2) WhatsApp channel; custom sender domains; Mailchimp/Brevo sync.

## Temporal workflows (E32)

Implement these processes as Temporal workflows following the rules in [E32](E32-workflow-orchestration-temporal.md) (deterministic workflow code, side effects in tenant-scoped activities that call services, tenant-prefixed workflow IDs, signals for human decisions). Where the requirements above mention sweeper tasks, `next_*_at` / `resume_at` columns or retry schedules, the workflow replaces them.

- [x] **E13-TW1** Broadcast workflow (requires E32).

| Workflow | Started by | Steps, timers and signals | Replaces |
|---|---|---|---|
| `BroadcastWorkflow` `broadcast:{org}:{id}` | Broadcast scheduled or sent | Wait for scheduled time → resolve segment → send in throttled batches (activities enqueue Celery sends) → collect stats. Signals `pause`, `resume`, `cancel` | Scheduled-broadcast beat job |

## Implementation notes (as built 2026-10-09)
- **App:** `comms` with `OrgNotificationSetting`, `MessageTemplate` (versioned overrides), `Message` (+ `MessageEvent`), `CommunicationPreference`, `Suppression` and `InAppNotification`, all with RLS. There is also a platform `SmsOptOut` table for STOP replies to the shared sender, which applies to every organisation.
- **Registry (T01):** types are defined in code (`catalogue.py`), each with category, audience, supported and default channels, a recipient resolver, whitelisted variables, sample data, transactional flag, timing (reminders), attachments and an in-app link. The MVP catalogue covers: lesson booked/moved/cancelled/reminder, series summary, tutor assigned; report shared/due/overdue, unconfirmed lesson; invoice issued (PDF attached), payment reminder, receipt (PDF), payment failed, payment request, low credit; staff alerts (report escalated, completion blocked, payment failed after retries, dispute) and task assigned. Recipients are client contacts (using their `receives_reminders`/`receives_invoices`/`receives_reports` flags, falling back to the billing or primary contact), tutors (email, mobile, in-app when they have an active login) and staff holding the relevant permission. Students have no direct channel yet (adult learners are reached through their contact). The daily tutor agenda, weekly client schedule, booking requests and account emails stay with identity (E03), and E16 adds digests.
- **Templates (T02):** sandboxed Jinja2 (`SandboxedEnvironment`; contexts are plain dicts, never models) with `|datetime`, `|time`, `|date` and `|money` filters, localised with Babel and shown in the lesson's or organisation's timezone. Platform defaults live in `defaults.py`. Organisations override per type and channel; each save is a new version and revert returns to the default. Preview renders the sample data or a draft; test-send goes to your own email or bell. Branch and locale overrides are left for later (the model has `locale`).
- **Pipeline (T03..T05):** `notify(type, subject, key=...)` → setting (enabled, channels) → recipients → channels the recipient has, filtered by their preferences (transactional types fall back to email rather than going silent) → suppression check → render → `Message` with a unique dedupe key (type, occurrence, recipient, channel), so redelivered events never double-send. Messages are sent by a Celery task; texts in quiet hours (`comms.quiet_hours_start/end`, organisation timezone) are held until they end. Email uses Django mail (Postmark over SMTP in production) with an HTML alternative, the sender name and reply-to from settings, metadata headers for webhooks, and RFC 8058 `List-Unsubscribe` on non-transactional mail. Postmark webhooks (`/webhooks/postmark?token=`) record delivered, opened, clicked, bounced and complained events without moving backwards; hard bounces and complaints add a suppression. SMS uses Twilio's REST API (a fake records texts without credentials), with signed status callbacks and STOP/START handling at `/webhooks/twilio/inbound`. SMS credits use a meter hook that E04 fills (unlimited until then). Invoice emails (E10) and receipts (E11) now go through comms.
- **Reminders (T06):** a 5-minute beat task (the reminder dispatch listed in the architecture's Celery section) sends each configured offset (default 24h and 2h) for lessons whose reminder fell due in the last hour. Dedupe keys make repeats harmless; a lesson booked after a reminder's moment skips that reminder. Times follow the lesson's timezone.
- **Preferences (T07):** channels per person and category (`/communication-preferences`); one-click unsubscribe links (signed, one year) remove email for that category.
- **In-app (T08):** a bell with an unread count, a list and "mark all read". It polls every 30 seconds, instead of the spec's realtime SSE/WebSockets (that needs ASGI). Realtime is a follow-up.
- **Frontend (T09):** Settings → Notifications (per type: on/off, channels, reminder hours; template editor with variables, preview, SMS part count, test send, revert), the bell in the app shell, and messages on record timelines (`message` kind through a new CRM timeline provider hook).
- **Deferred (Phase 2):** broadcasts and BroadcastWorkflow (T10, TW1), conversations inbox (T11), WhatsApp, custom sending domains, and Mailchimp/Brevo sync (T12).

## Phase 2 implementation notes (as built 2026-10-14)
Everything is in the existing `comms` app (models in one migration, RLS on every tenant table); see ADR 0027.

- **Broadcasts (T10):**
  - `Segment` (saved, reusable) and `Broadcast` hold a segment *definition*: client contacts or tutors, filtered by status, branch, tags, a saved E05 list view (clients, students or tutors), a class (E20 enrolments or teachers), a job, a pipeline stage (open E17 enquiries) and "main contact only". A student audience is reached through student statuses or a saved student view (their families' contacts); students have no channel of their own yet.
  - Recipients are resolved once, when sending starts, into `BroadcastRecipient` rows with a skip reason: `no_address`, `duplicate` (same address twice), `suppressed` (bounce, complaint, STOP), `no_consent`, `opted_out`, `no_opt_in` (WhatsApp).
  - **Marketing vs operational:** marketing needs E29 consent (`marketing_email` for email, `marketing_sms` for texts and WhatsApp; the contact's "receives marketing" flag where the organisation has no such consent type) and a marketing preference that allows the channel. Marketing emails carry RFC 8058 unsubscribe headers for the new `marketing` category; marketing texts end with "Reply STOP to opt out". Service announcements skip consent but still respect suppressions.
  - Each recipient is a normal `Message` (types `broadcast_marketing`/`broadcast_operational`, hidden from the settings screen), so Postmark delivery, open, click and bounce webhooks track them. Statistics are counted live from those messages, plus unsubscribes (the unsubscribe token now carries the message id); a snapshot is stored when the broadcast finishes.
  - Email attachments (stored files, up to 10 MB together). The audience preview (`/segments/preview`, `/broadcasts/{id}/audience`) shows who it reaches and why others are skipped.
- **BroadcastWorkflow (TW1):** `broadcast:{org}:{id}`, started by `broadcast.scheduled`. It waits for the scheduled time, resolves recipients, then queues batches of `comms.broadcast_batch_size` every `comms.broadcast_batch_pause_seconds` (each message is sent by the Celery send task after commit) and finishes with `broadcast.sent`. Texts and WhatsApp messages wait for quiet hours to end; the quiet-hours check gets the workflow's clock. Signals `pause`, `resume` and `cancel` come from the API through the services, and the workflow also re-reads the database state when a batch finds the broadcast isn't sending. Recorded histories: sent, paused, cancelled, quiet hours and retried.
- **Inbox (T11):**
  - `Thread` (branch-scoped; kind `client`, `tutor`, `tutor_family` or `other`), `ThreadParticipant` and `ThreadMessage` (direction inbound, outbound or internal note; channel email, sms, whatsapp, chat or note). Deviation: the spec's `InboundMessage` is a `ThreadMessage` with direction `inbound`; its unique `provider_ref` makes webhook retries harmless.
  - **Inbound email:** a separate Postmark inbound server on `COMMS_REPLY_DOMAIN` posts to `/webhooks/inbound/email?token=` (the spec's `/inbound/email`; the E17 `enquiries+` address keeps `/webhooks/inbound-email`). `reply+<subdomain>.<thread>.<hmac>@` goes to that thread (a forged address is dropped); `inbox+<subdomain>@` opens or reuses a thread for the sender, matched to a contact or tutor by email. Attachments are stored and virus-scanned like uploads. Postmark doesn't sign inbound webhooks, so the URL token is compared in constant time.
  - **Inbound texts and WhatsApp:** the existing signed `/webhooks/twilio/inbound` (the spec's `/inbound/sms`) still handles STOP/START and now passes other messages to the inbox. The organisation is found through the platform table `InboundRoute`: its own number (`PhoneNumber`, kind `number`), or the organisation that last messaged that phone from the shared sender within 30 days (kind `reply`, recorded on every shared-sender text).
  - **Replies:** by the thread's channel or another one: email with the thread's reply address as Reply-To, text from the organisation's number, WhatsApp free text only within 24 hours of their last WhatsApp message, or portal chat. Internal notes stay with staff. Emails outside threads now reply to `inbox+<subdomain>@` when inbound email is set up and no `comms.reply_to` is chosen.
  - **Team inbox:** assignment (to people with `comms.inbox.reply`), snooze (a snoozed thread counts as open again once its time passes, worked out when it is read, so there is no sweeper), close and reopen, a new message reopens, box counts, canned replies, unread counts, and an SLA timer: `awaiting_reply_since` plus `comms.inbox_sla_hours`, shown as due or overdue.
  - **Safeguarding (FR-13-7):** every message is kept and staff see all of them. Messages with email addresses, phone numbers or bad language (a small built-in word list) are flagged on the message and the thread. `comms.block_contact_sharing` refuses contact details in tutor-family messages.
  - **Notifications:** `message.received` alerts the assignee (else whoever can assign) through `inbox_new_message`. Portal chat replies notify the family (`conversation_message_family`) or the tutor (`conversation_message_tutor`). Dedupe keys allow one per thread and person per hour, a light digest; daily digest emails are not built. The admin inbox polls every 30 seconds (realtime is the E13 MVP follow-up).
  - **Tutors:** `comms.inbox.view:own` and `comms.inbox.reply:own` in the Tutor role: they see threads they take part in. Admin page: Inbox (`/inbox`).
- **Channels (T12):**
  - **WhatsApp:** Twilio WhatsApp Business (`TWILIO_WHATSAPP_FROM`, a fake without it). WhatsApp Cloud API (Meta direct) is not built. Every text-capable notification can also go by WhatsApp (off by default). It needs an approved `WhatsAppTemplate` mapped to the type (Twilio content SID, `{{1}}` placeholders filled by sandboxed Jinja expressions) and the recipient's opt-in: a preference that names WhatsApp, never the default. Template approval is recorded by staff (no Content API sync). STOP to the WhatsApp sender suppresses WhatsApp. WhatsApp isn't metered against SMS credits.
  - **Custom sending domains:** plan feature `custom_domain` (the E24 one). Postmark's Domains API (a fake without `POSTMARK_ACCOUNT_TOKEN`) returns the DKIM and return-path records; we add SPF and DMARC as recommendations. "Check DNS" verifies, and the verified default domain becomes every email's From address. There is no automatic re-check workflow.
  - **Numbers:** `PhoneNumber` per channel with a default; a number belongs to one organisation only.
  - **Mailchimp and Brevo (FR-13-9):** credential providers on the E22 framework (`marketing` capability, fakes in tests). Mailchimp's host comes from the key's data centre, so it is validated and opened through `core.net.safe_urlopen`. Contacts with marketing email consent who haven't unsubscribed from marketing are upserted into the chosen audience, with their family's tags and status (Brevo: a `TAGS` attribute). Everyone else is unsubscribed there. A consent change or contact edit queues a one-contact Celery sync; "Sync now" pages through everyone. Unsubscribes made in Mailchimp or Brevo don't come back yet (no inbound webhook).
  - Admin pages: Settings → Messaging (domains, numbers, WhatsApp templates, canned replies, Mailchimp and Brevo) and Broadcasts (`/broadcasts`).
- **Seams for E31:** `selectors.thread_transcript` and `selectors.thread_digest` return plain data for suggested replies, intent and summaries; `broadcasts.render_for` and `broadcasts.preview` render copy for a recipient.
- **Events:** `broadcast.scheduled/sent/cancelled`, `message.received`, `thread.assigned/closed` and `sender_domain.verified`. They aren't offered as webhook event types yet (not in `developer.catalogue.PUBLIC_AGGREGATES`). `message.queued/sent/delivered...` remain message-log entries.
- **Shared-file edits:** `identity/roles.py` (tutor inbox grants), `config/settings/base.py` (`COMMS`, `TWILIO["WHATSAPP_FROM"]`, enum names), `config/urls.py` (inbound email webhook) and `scheduling/services.py` (makeup credits in self-booking, E15-T09).
