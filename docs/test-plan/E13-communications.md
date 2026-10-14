# E13 — Communications: manual tests

**Scope.** The notification catalogue and org settings, template editor (sandboxed rendering, preview, test send, revert), the delivery pipeline (dedupe, preferences, quiet hours, suppressions, Postmark and Twilio webhooks), lesson reminders, unsubscribe, in-app bell, and the Phase 2 broadcasts (segments, consent, batching workflow), conversations inbox (inbound email, SMS, WhatsApp, portal chat, assignment, SLA, safeguarding flags), WhatsApp templates, custom sending domains, phone numbers and Mailchimp/Brevo sync. Spec: [E13](../epics/E13-communications.md).

**Built differently from the spec (Implementation notes win):**
- The bell polls every 30 seconds (no realtime SSE/WebSockets). The inbox also polls every 30 seconds. Daily digest emails are not built.
- Branch and locale template overrides are not built. Students have no direct channel (adult learners via their contact).
- Without Twilio credentials texts are **recorded, not sent** (see the message log). WhatsApp, Postmark domains, Mailchimp and Brevo use fakes without keys.
- Inbound inbox email needs `COMMS_REPLY_DOMAIN` and `COMMS_INBOUND_TOKEN` in `.env`; Postmark delivery webhooks need `POSTMARK_WEBHOOK_TOKEN`. Inbound SMS/WhatsApp go to `/webhooks/twilio/inbound` (with no Twilio token the signature header must be `X-Twilio-Signature: fake-signature`).
- WhatsApp Cloud API (Meta direct) is not built; template approval is recorded by staff. Unsubscribes made in Mailchimp/Brevo don't sync back.
- Broadcast events are not offered as public webhooks yet.

**How to trigger in dev.**
- Emails: Mailpit http://localhost:8025.
- Inbound SMS: `curl -X POST http://localhost:8010/webhooks/twilio/inbound -H 'X-Twilio-Signature: fake-signature' -d 'From=+447700900123&To=<org number>&Body=Can we move Thursday?'` (`Body=STOP` to opt out).
- Inbound email: `POST /webhooks/inbound/email?token=<COMMS_INBOUND_TOKEN>` with a Postmark inbound JSON body (`From`, `To` = `inbox+brightminds@<COMMS_REPLY_DOMAIN>` or a thread's reply address, `Subject`, `TextBody`, `MessageID`).
- Postmark delivery events: `POST /webhooks/postmark?token=<POSTMARK_WEBHOOK_TOKEN>` with `RecordType` Delivery / Open / Click / Bounce / SpamComplaint and the message metadata.
- Broadcasts: Temporal UI http://localhost:8233, workflow `broadcast:<org>:<id>`.

**Common preconditions.** Stack with Celery beat, worker and Temporal worker; seed loaded. Seed data: segment "Active families", draft broadcast "Half-term timetable", canned replies "Thanks, we'll call you" and "Tutor confirmed", and an inbox conversation "Thursday's lesson" from Priya Patel. Screens: `/settings/notifications`, `/broadcasts`, `/inbox`, `/settings/messaging`, the bell in the top bar; portal `/portal/messages`, `/portal/tutor/messages`.

## Notification settings and templates (FR-13-2, FR-13-3, T01, T02, T09)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E13-001 | Disable SMS reminders, keep email; set timing (epic AC) | Owner (admin@) | — | 1. `/settings/notifications` → Lesson reminder.<br>2. Untick **Text**, keep **Email**.<br>3. **Hours before** "24, 2".<br>4. **Save**. | "Saved." Next reminders go by email only at 24 h and 2 h before. | P1 | backend: `test_disable_sms_reminders_and_set_timing` | |
| TP-E13-002 | Edit wording with variables and preview | Owner | — | 1. Lesson reminder → **Edit wording**.<br>2. Change the subject to include `{{ student.first_name }}`.<br>3. **Preview**. | Preview renders with sample data; variables list shown ("You can use:"). | P1 | backend: `test_template_override_preview_revert_and_test_send` | |
| TP-E13-003 | Send me a test and versioning | Owner | TP-E13-002 | 1. **Save wording**, **Send me a test**.<br>2. Edit again and save. | "Test sent." (Mailpit). "Your version 2" shows. | P2 | backend: `test_template_override_preview_revert_and_test_send` | |
| TP-E13-004 | Revert to standard wording | Owner | Override saved | 1. **Use the standard wording**. | Platform default used again. | P2 | backend: `test_template_override_preview_revert_and_test_send` | |
| TP-E13-005 | Templates are sandboxed | Owner | — | 1. Enter `{{ ''.__class__.__mro__ }}` or `{{ student.user.password }}` and preview. | Rendering refused or blank; no internals leak. Output is HTML-escaped. | P1 | backend: `test_templates_are_sandboxed` | |
| TP-E13-006 | SMS part counter | Owner | SMS template | 1. Type 200 characters. | "2 text messages". | P3 | No | |
| TP-E13-007 | Merge filters localise dates and money | Owner | Invoice issued template with `{{ invoice.total|money }}` and `{{ lesson.start|datetime }}` | 1. Preview. | Money as £45.00; date/time in the org (or lesson) timezone in en-GB format. | P2 | No | |

## Delivery pipeline, reminders and preferences (FR-13-4, FR-13-5, T03–T07)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E13-008 | Cancellation notifies family and tutor once | Coordinator | Arjun lesson | 1. Cancel with notify on.<br>2. Re-run the event (e.g. retry). | Mailpit: one email to Priya and one to Nia; no duplicates (dedupe key). | P1 | backend: `test_cancellation_notifies_family_and_tutor_once` | |
| TP-E13-009 | Lesson reminders at each offset once | Coordinator | Lesson in ~25 h; beat running | 1. Wait for the reminder windows (or set the lesson 2.5 h ahead). | One reminder per offset; a lesson booked after a reminder's moment skips that reminder. | P1 | backend: `test_reminders_at_each_offset_once` | |
| TP-E13-010 | Message log on the record timeline | Coordinator | Messages sent to Priya | 1. Open the Patel client → timeline. | Message entries with channel and status. | P2 | backend: `test_message_log_and_timeline` | |
| TP-E13-011 | Preferences and transactional fallback | Parent (parent@) | — | 1. Portal → Profile → turn off email for Billing.<br>2. Issue an invoice. | Invoice email still arrives (transactional falls back to email). Turning off Lessons stops reminders. | P1 | backend: `test_preferences_suppressions_and_transactional_fallback` | |
| TP-E13-012 | One-click unsubscribe | Parent | Non-transactional email | 1. Click the unsubscribe link (or use the `List-Unsubscribe` header). | That category's email is turned off; confirmation page. | P2 | backend: `test_unsubscribe_link_turns_off_that_category` | |
| TP-E13-013 | Bounce adds a suppression | Owner | `POSTMARK_WEBHOOK_TOKEN` set | 1. Post a hard Bounce webhook for Priya's message.<br>2. Send another email to her. | Message status Bounced; address suppressed; contact shows a warning; later sends skipped. Status never moves backwards. | P1 | backend: `test_delivery_webhooks_update_status_and_suppress_bounces` | |
| TP-E13-014 | Postmark webhook without the token | Owner | — | 1. Post without `?token=`. | Rejected (403/404). | P2 | backend: `test_delivery_webhooks_update_status_and_suppress_bounces` | |
| TP-E13-015 | SMS quiet hours, STOP and credits | Owner | Quiet hours 21:00–08:00; a text due at 22:00 | 1. Trigger a text at 22:00 local.<br>2. Send inbound `Body=STOP` from that number. | Text held until 08:00. STOP opts the number out (platform-wide for the shared sender); START opts back in. | P1 | backend: `test_sms_quiet_hours_stop_and_credits` | |
| TP-E13-016 | Twilio status callback | Owner | Text sent | 1. Post a signed status callback to `/webhooks/twilio/status`. | Message status updates. | P3 | backend: `test_twilio_status_callback` | |

## In-app notifications (FR-13-8, T08)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E13-017 | Bell shows staff alerts | Coordinator | Assign a task to the coordinator | 1. Wait up to 30 s.<br>2. Open the bell. | "Notifications (1 new)"; item deep-links to the task. | P1 | backend: `test_in_app_bell_and_staff_alerts` | |
| TP-E13-018 | Mark all read | Coordinator | Unread items | 1. **Mark all read**. | Count clears; "Nothing new." when empty. | P2 | backend: `test_in_app_bell_and_staff_alerts` | |

## Broadcasts (FR-13-6, T10, TW1)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E13-019 | Check who a broadcast reaches | Owner | Seed draft "Half-term timetable" | 1. `/broadcasts` → open the draft.<br>2. **Check who it reaches**. | "Reaches N of M people." with sample names and skip reasons (no address, duplicate, suppressed...). | P1 | backend: `test_segments_filter_contacts_by_status_tags_students_and_primary` | |
| TP-E13-020 | Send now (operational email) | Owner | Draft | 1. **Send now**. | Status Sending → Sent; Mailpit has one email per family contact with the merge fields filled ("Hello Priya"). Stats: People, Sent, Delivered... | P1 | backend: `test_a_broadcast_sends_in_batches_and_tracks_delivery` | |
| TP-E13-021 | Build a segment by tag and main contact | Coordinator | Tag VIP on Patel | 1. **New broadcast** → **Choose people below**: Family contacts, Tags VIP, **Only the main contact of each family**.<br>2. Check reach. | Only Priya. | P2 | backend: `test_segments_filter_contacts_by_status_tags_students_and_primary` | |
| TP-E13-022 | Segment from a class, job, saved view or pipeline stage | Coordinator | Saturday 10am class with enrolments | 1. Segment by class; another by an E17 pipeline stage. | Recipients are the class families / open enquiries. | P2 | backend: `test_segments_use_saved_views_and_pipeline_stages` | |
| TP-E13-023 | Marketing needs consent | Owner | Priya without marketing consent | 1. New broadcast, **Kind of message**: Marketing.<br>2. Check reach. | Priya skipped: "hasn't agreed to marketing". Recording consent (E29) includes her. | P1 | backend: `test_marketing_needs_consent_and_respects_opt_outs_and_suppressions` | |
| TP-E13-024 | Marketing email unsubscribe counted | Parent | Marketing broadcast received | 1. Click unsubscribe. | Broadcast stats Unsubscribed +1; future marketing skipped "unsubscribed". | P2 | backend: `test_marketing_email_has_unsubscribe_and_counts_it` | |
| TP-E13-025 | Marketing texts say how to stop | Owner | Marketing SMS | 1. Send; open the message log. | Text ends with "Reply STOP to opt out". | P2 | backend: `test_marketing_texts_say_how_to_stop` | |
| TP-E13-026 | Schedule, pause, resume, cancel | Owner | — | 1. **Send at** tomorrow 09:00 → **Schedule**.<br>2. **Cancel broadcast** before then.<br>3. Another: send now with a small batch size, **Pause**, **Resume**. | "goes out <when>"; cancelled sends nothing; paused stops between batches and resumes. Temporal history shows the signals. | P2 | backend: `test_pause_resume_and_cancel`, `test_cancel_before_the_scheduled_time`, `test_pause_and_resume` | |
| TP-E13-027 | Texts wait for quiet hours | Owner | SMS broadcast at 22:00 | 1. Send now. | Held until quiet hours end. | P3 | backend: `test_texts_wait_for_quiet_hours_to_end` | |
| TP-E13-028 | Email attachments | Owner | 2 MB PDF | 1. Attach to an email broadcast and send. | Attachment present in Mailpit; over 10 MB in total is refused. | P3 | No | |
| TP-E13-029 | WhatsApp broadcast needs opt-in and template | Owner | Approved WhatsApp template | 1. New broadcast **Send by** WhatsApp, **Choose an approved template**.<br>2. Check reach. | Only people who chose WhatsApp; others "haven't chosen WhatsApp". | P2 | backend: `test_whatsapp_broadcasts_need_opt_in_and_an_approved_template` | |
| TP-E13-030 | Send failures are skipped, not fatal | Owner | A recipient whose template fails | 1. Send. | That recipient "failed (template error)"; others sent. | P3 | backend: `test_send_failures_are_skipped_not_fatal` | |

## Conversations inbox (FR-13-7, T11)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E13-031 | Reply to a portal conversation with a canned reply | Coordinator (coordinator@) | Seed conversation "Thursday's lesson" | 1. `/inbox` → Open → the conversation.<br>2. **Insert a canned reply** → "Thanks, we'll call you".<br>3. **Send**. | Reply appears in the thread; Priya sees it in portal Messages; family notified once per hour max. | P1 | backend: `test_canned_replies`; e2e: `e2e/inbox.spec.ts` | |
| TP-E13-032 | Internal note stays with staff | Coordinator | Thread | 1. **Add internal note**. | Shown as "Internal note (staff only)"; not in the portal. | P1 | backend: `test_notes_assignment_snooze_close_and_counts`; e2e: `e2e/inbox.spec.ts` | |
| TP-E13-033 | Assign, snooze, close, reopen | Owner | Thread | 1. **Assigned to** coordinator.<br>2. **Snooze until** tomorrow.<br>3. **Close**; then **Reopen**. | Folders Mine/Unassigned/Snoozed/Closed counts update; assignee notified. A new inbound message reopens a closed thread. | P1 | backend: `test_notes_assignment_snooze_close_and_counts` | |
| TP-E13-034 | SLA timer | Coordinator | `comms.inbox_sla_hours` 4; unanswered inbound message | 1. Look at the thread. | "reply by <time>", then "Reply overdue" / "reply was due <time>". | P2 | backend: `test_sla_timer` | |
| TP-E13-035 | Inbound email opens a family thread | Coordinator | Inbox email configured | 1. Post inbound email from priya.patel@example.com to `inbox+brightminds@...`. | Thread for the Patel family; attachments stored and scanned; unknown senders get "Unknown sender". | P2 | backend: `test_email_to_the_inbox_address_opens_a_family_thread`, `test_inbound_email_attachments_are_stored_and_scanned` | |
| TP-E13-036 | Email replies carry the thread address | Coordinator | Email thread | 1. Reply by email.<br>2. Post an inbound email to that reply address. | Reply-To is `reply+brightminds.<thread>.<hmac>@`; the answer lands in the same thread; a forged address is dropped. | P2 | backend: `test_replies_by_email_carry_the_thread_address` | |
| TP-E13-037 | Inbound SMS routes to the org | Coordinator | Org number in Settings → Messaging → Numbers | 1. Post an inbound SMS to that number.<br>2. Reply by text. | Thread created; reply sent from the org's number. | P2 | backend: `test_texts_route_by_number_and_reply_route`, `test_staff_text_replies_use_the_organisations_number` | |
| TP-E13-038 | WhatsApp free text only within 24 h | Coordinator | WhatsApp thread with last inbound >24 h ago | 1. Try **Send by** WhatsApp. | Refused; template message needed. | P3 | backend: `test_whatsapp_free_replies_only_within_24_hours` | |
| TP-E13-039 | Staff start a portal conversation | Coordinator | — | 1. Start a conversation with the Patel family from the inbox. | Appears in portal Messages. | P2 | backend: `test_staff_start_a_portal_conversation` | |
| TP-E13-040 | Safeguarding flags and contact blocking | Tutor, Coordinator | `comms.block_contact_sharing` on; tutor–family thread | 1. Tutor sends "call me on 07700 900123".<br>2. Turn the setting off and send a message with bad language. | Blocked with a message. Otherwise flagged: "Flagged for review: contact details / bad language"; visible in the Flagged folder. | P1 | backend: `test_safeguarding_flags_and_blocking` | |
| TP-E13-041 | AI suggested reply in the inbox | Coordinator | AI features on (fake) | 1. Open a thread; use the AI suggested reply. | A deterministic suggested draft is inserted for editing, not sent automatically (E31). | P2 | e2e: `e2e/inbox.spec.ts` | |

## Channels: WhatsApp, domains, numbers, marketing sync (T12)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E13-042 | Add a custom sending domain | Owner | Plan with `custom_domain` | 1. `/settings/messaging` → **Sending domain** → **Add domain** brightminds.example.<br>2. **Check DNS** (fake verifies).<br>3. **Send from this domain**. | DNS records listed (DKIM, return path; SPF and DMARC "Recommended"); Verified; emails now come From that domain. | P2 | backend: `test_sender_domain_wizard_and_from_address` | |
| TP-E13-043 | Domain on a plan without the feature | Owner | Plan without custom domain | 1. Try to add a domain. | Upgrade prompt; refused. | P2 | backend: `test_sender_domain_failures_and_validation` | |
| TP-E13-044 | Numbers are unique per org | Owner | — | 1. **Add number** +447700900123 in Bright Minds.<br>2. Add the same in Northside. | Second refused. | P2 | backend: `test_phone_numbers_are_unique_and_route_replies` | |
| TP-E13-045 | WhatsApp template placeholders | Owner | — | 1. **Add template** with `{{1}}`, `{{2}}` and only one value. | Validation error until values match placeholders. | P3 | backend: `test_whatsapp_templates_validate_placeholders` | |
| TP-E13-046 | Notifications by WhatsApp with opt-in | Parent, Owner | Template mapped to lesson reminder; WhatsApp on for the type; Priya prefers WhatsApp | 1. Trigger a reminder. | WhatsApp message recorded; STOP to the WhatsApp sender suppresses it. | P3 | backend: `test_notifications_go_by_whatsapp_with_opt_in_and_a_template`, `test_whatsapp_stop_suppresses` | |
| TP-E13-047 | Mailchimp sync (fake) | Owner | — | 1. **Mailchimp and Brevo** → enter an API key → **Connect** → **Choose an audience** → **Sync now**. | "Synced: N added or updated, M unsubscribed". Only contacts with marketing consent are added; tags and status included. | P2 | backend: `test_mailchimp_sync`, `test_mailchimp_host_comes_from_the_key_safely` | |
| TP-E13-048 | Brevo needs an audience | Owner | — | 1. Connect Brevo without choosing an audience; Sync now. | Clear error. | P3 | backend: `test_brevo_sync_needs_an_audience` | |

## Permissions

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E13-049 | Tutors see only their conversations | Tutor | Threads with and without Nia | 1. Portal → tutor Messages. | Only threads Nia takes part in. | P1 | backend: `test_tutors_see_only_their_conversations` | |
| TP-E13-050 | Finance has no inbox or broadcasts | Finance | — | 1. Check nav; open `/inbox`, `/broadcasts`. | Not shown; no access. | P1 | e2e: `e2e/roles.spec.ts` | |
| TP-E13-051 | Coordinator can broadcast but not manage channels | Coordinator | — | 1. Open `/broadcasts` and `/settings/messaging`. | Broadcasts allowed; channel settings refused. | P2 | backend: `test_broadcast_permissions`, `test_channel_settings_need_permission` | |

## Tenant isolation

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E13-052 | Inbox, broadcasts and messages are per org | Owner of Northside | Bright Minds data exists | 1. Open `/inbox`, `/broadcasts`, `/settings/notifications` on northside.localhost.<br>2. GET a Bright Minds thread id. | Only Northside data; 404. | P1 | backend: `tutortrack/comms/tests/test_inbox.py`, `test_broadcasts.py` (TenantIsolationTestMixin) | |
| TP-E13-053 | Inbound SMS reaches only the right org | Owner | Each org has its own number | 1. Post inbound SMS to Bright Minds' number. | Thread only in Bright Minds. | P2 | backend: `test_texts_route_by_number_and_reply_route` | |

## Errors and edge cases

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E13-054 | Unknown sender and malformed webhooks | Owner | — | 1. Post an inbound email from an unknown address; post a malformed body. | Unknown sender thread created (or dropped per setting); malformed → 400, nothing stored. | P2 | backend: `test_unknown_senders_and_bad_requests` | |
| TP-E13-055 | No PII in logs | Security reviewer | — | 1. Send messages; read the backend log. | No email bodies, phone numbers or tokens in logs. | P2 | No | |

## Gap batch G4 (2026-10-14): realtime, template versions, students, digests, account emails, unsubscribes, new types

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E13-056 | The bell updates live | Admin | Production-like stack on ASGI (see `docs/runbooks/realtime-notifications.md`) | 1. Open the admin app.<br>2. In another browser assign a task to this admin. | The bell count changes within a second, without waiting for the 30-second poll. | P1 | backend: `test_new_notifications_are_published_to_the_users_channel`, `test_stream_delivers_only_its_own_users_organisation`; frontend: `comms/G4.test.tsx` | |
| TP-E13-057 | Bell falls back to polling | Admin | Stack on `runserver`/gunicorn, or Redis stopped | 1. Stop Redis; open the admin app; assign a task. | The stream reports unavailable; the bell still updates within 30 seconds. | P2 | backend: `test_stream_says_when_realtime_is_unavailable` | |
| TP-E13-058 | Stream needs a member of the organisation | Signed-out user; member of another org | — | 1. Open `/api/v1/notifications/stream` signed out, then as a member of Northside on brightminds. | 401/403; no events. | P1 | backend: `test_stream_needs_a_signed_in_member` | |
| TP-E13-059 | A French version of a template | Admin | Contact with language `fr` | 1. Settings → Notifications → Lesson booked → Edit wording.<br>2. Language `fr`, save a French subject.<br>3. Book a lesson for that family. | The French contact gets the French subject; others get the English one. The version list shows "fr". | P1 | backend: `test_overrides_resolve_by_language_then_branch`, `test_a_french_speaking_contact_gets_the_french_template`, `test_template_api_scopes_and_variants` | |
| TP-E13-060 | A branch version of a template | Admin | Two branches | 1. Choose branch North, save a version.<br>2. Book lessons in North and South. | North lessons use the North version; South lessons the organisation's. Revert returns North to the organisation's. | P2 | backend: `test_overrides_resolve_by_language_then_branch` | |
| TP-E13-061 | Students get lesson messages themselves | Admin | Setting "Students get lesson messages themselves" = 13 and over; a 15-year-old with a login; an 11-year-old | 1. Book a lesson for each. | The 15-year-old gets the email; the 11-year-old doesn't (only the family). | P1 | backend: `test_students_get_lesson_messages_only_when_allowed`, `test_lesson_booked_reaches_a_teen_but_never_marketing` | |
| TP-E13-062 | Never marketing to under-18s, never direct to under-13s | Admin | As above | 1. Send a marketing broadcast reaching the 15-year-old.<br>2. Send anything addressed straight to the 11-year-old. | Both are recorded as suppressed with the children's rule as the reason. | P1 | backend: `test_nothing_goes_straight_to_an_under_13`, `test_lesson_booked_reaches_a_teen_but_never_marketing` | |
| TP-E13-063 | Tutor daily agenda at the tutor's time | Admin, tutor | Turn on "Daily agenda for tutors"; tutor in Europe/London with a lesson tomorrow | 1. Tutor sets 06:30 in Notifications → Digest emails.<br>2. Wait for 06:30 (or run `send_scheduled_comms`). | One email between 06:30 and 07:30 listing the day's lessons; no second email that day. Turning it off stops it. | P1 | backend: `test_due_follows_the_persons_timezone_and_day`, `test_tutor_agenda_is_sent_once_at_their_time`, `test_a_tutor_can_choose_their_agenda_time_or_switch_it_off` | |
| TP-E13-064 | Weekly schedule for families | Admin, client | Turn on "Weekly schedule for families"; lessons next week | 1. Family picks Sunday 18:00 on their profile.<br>2. Run the task on Sunday 18:05. | One email listing next week's lessons. | P2 | backend: `test_weekly_schedule_goes_to_families_on_their_day`; frontend: `tutor/G4.test.tsx` (digest choices) | |
| TP-E13-065 | Daily digest of unread messages | Admin | Turn on "Daily digest of unread messages"; unread inbox notifications | 1. Leave messages unread until 17:00. | One email listing them. | P2 | backend: `test_message_digest_lists_unread_messages` | |
| TP-E13-066 | Account emails are branded, editable and hide secrets | Admin | — | 1. Ask for a magic link on brightminds.<br>2. Edit "Sign-in link" wording; ask again.<br>3. Open Messages log. | Email has the organisation's branding; the edited wording is used; the log shows "[link hidden]" instead of the link. The "Password reset" switch can't be turned off. | P1 | backend: `test_account_emails_inside_an_organisation_are_branded_logged_and_hide_links`, `test_account_emails_can_be_edited_but_not_switched_off`; frontend: `comms/G4.test.tsx` | |
| TP-E13-067 | Platform emails without an organisation | User | Platform sign-in (no organisation) | 1. Ask for a password reset on the platform host. | The platform text in the user's language; nothing logged in any organisation. | P2 | backend: `test_platform_account_emails_use_the_platform_template` | |
| TP-E13-068 | Mailchimp unsubscribe flows back | Admin | Mailchimp connected, audience chosen, webhook address added in Mailchimp | 1. A contact unsubscribes in a Mailchimp email. | Their marketing email consent is withdrawn (source `mailchimp:unsubscribe`), marketing broadcasts skip them, invoices still go. | P1 | backend: `test_mailchimp_unsubscribe_webhook_withdraws_consent`, `test_brevo_webhook_json` | |
| TP-E13-069 | Cleaned or spam addresses are suppressed | Admin | As above | 1. Mailchimp cleans an address (hard bounce) or the person reports spam. | The address is suppressed for email. | P2 | backend: `test_cleaned_and_spam_reports_suppress_the_address` | |
| TP-E13-070 | Sync now never re-subscribes people who left | Admin | A contact unsubscribed in Mailchimp before the webhook was set up | 1. Settings → Messaging → Sync now. | "1 person had unsubscribed there"; they stay unsubscribed in Mailchimp. | P1 | backend: `test_sync_now_reads_unsubscribes_back_first` | |
| TP-E13-071 | Forged or old webhook addresses do nothing | — | — | 1. Post to the webhook with a changed token, another provider's path, or after reconnecting. | 403 (or 200 with no change for a disconnected account). | P2 | backend: `test_mailchimp_unsubscribe_webhook_withdraws_consent` | |
| TP-E13-072 | New notification types | Admin, tutor, client | — | 1. Approve and reject an expense.<br>2. Decline an online booking.<br>3. Use a package down to its low level.<br>4. A card expiring next month (09:00 check).<br>5. 1st of the month with a balance (statement on).<br>6. A student missing lessons. | The tutor hears about each decision; the booker gets "Booking declined"; the family gets "Package running low" and "Card about to expire"; the statement arrives with a PDF; staff get "Low attendance" once a week. | P1 | backend: `test_new_types_are_registered_with_templates`, `test_card_expiry_and_statement_checks_run_once_a_day`, `test_low_attendance_alerts_staff_once_a_week`, `test_booking_declined_tells_the_new_family` | |
| TP-E13-073 | Digest choices are per organisation | User in two orgs | — | 1. Turn a digest off in Northside; open Bright Minds. | Bright Minds shows the defaults. | P2 | backend: `TestDigestPreferenceIsolation`, `TestTemplateVariantIsolation` | |
