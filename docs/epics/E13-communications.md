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
- [ ] **E13-T01** Notification type registry, org settings, recipient resolvers.
- [ ] **E13-T02** Template model, sandboxed renderer, variable whitelist per type, preview/test send.
- [ ] **E13-T03** Email channel (Postmark) with delivery webhooks, bounces, suppressions.
- [ ] **E13-T04** SMS channel (Twilio), credits deduction, STOP handling, quiet hours.
- [ ] **E13-T05** Event → notification subscribers for the MVP catalogue; dedupe keys.
- [ ] **E13-T06** Lesson reminder scheduler (multiple offsets, per-recipient tz).
- [ ] **E13-T07** Preferences and unsubscribe.
- [ ] **E13-T08** In-app notifications with realtime feed.
- [ ] **E13-T09** Frontend: notification settings, template editor, message log on timelines.
- [ ] **E13-T10** (Phase 2) Broadcasts with segments and tracking.
- [ ] **E13-T11** (Phase 2) Conversations inbox (email/SMS inbound, in-app chat, assignment).
- [ ] **E13-T12** (Phase 2) WhatsApp channel; custom sender domains; Mailchimp/Brevo sync.

## Temporal workflows (E32)

Implement these processes as Temporal workflows following the rules in [E32](E32-workflow-orchestration-temporal.md) (deterministic workflow code, side effects in tenant-scoped activities that call services, tenant-prefixed workflow IDs, signals for human decisions). Where the requirements above mention sweeper tasks, `next_*_at` / `resume_at` columns or retry schedules, the workflow replaces them.

- [ ] **E13-TW1** Broadcast workflow (requires E32).

| Workflow | Started by | Steps, timers and signals | Replaces |
|---|---|---|---|
| `BroadcastWorkflow` `broadcast:{org}:{id}` | Broadcast scheduled or sent | Wait for scheduled time → resolve segment → send in throttled batches (activities enqueue Celery sends) → collect stats. Signals `pause`, `resume`, `cancel` | Scheduled-broadcast beat job |
