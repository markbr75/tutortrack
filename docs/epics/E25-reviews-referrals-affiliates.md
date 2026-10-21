# E25 — Reviews, Referrals & Affiliates

| | |
|---|---|
| **Phase** | Scale (Phase 3) |
| **Depends on** | E05, E09, E10, E11, E12, E24 |
| **Parity** | TutorCruncher reviews API and Agents (affiliates with commission) |

## 1. Summary
Growth tools: collect reviews and ratings of tutors and the business, publish testimonials, run a client referral programme (give/get credit), and manage affiliates/partners (schools, bloggers, other agencies) who earn commission on revenue from referred clients.

## 2. Functional requirements

### FR-25-1 Reviews and ratings
- Request reviews after N completed lessons or on trial completion (automation recipe), via email/SMS link.
- Review: rating 1–5 (overall + optional criteria), text, reviewer (contact/student), tutor, publish consent; moderation queue (approve/hide/respond); tutor sees reviews about them (configurable).
- Aggregates: tutor average rating & count (used in matching E19 and directory E24); org average.
- Google review prompt: on 4–5★ internal reviews, invite the client to also review on Google Business Profile (link).

### FR-25-2 Client referral programme
- Each client gets a referral link/code; referred enquiry is attributed (cookie + code).
- Rewards configurable: referrer gets £X credit (E10 credit adjustment) / free lesson when the referee pays first invoice or completes N lessons; referee gets a discount (E06 promo).
- Referral dashboard for clients in portal (status of referrals, rewards earned).
- Fraud guards: same address/email/payment fingerprint checks, max rewards per period.

### FR-25-3 Affiliates (agents)
- Affiliate records (individual or organisation) with portal login: tracking links/codes, referred clients list (privacy-limited), commission statements, payout details.
- Commission rules: % of collected revenue from referred clients (for N months or lifetime), fixed bounty per converted client, tiered rates; per-affiliate overrides.
- Commission calculation on `payment.succeeded` allocations (clawback on refunds) → commission items → monthly affiliate statements → payouts via E12 payout mechanisms (bank file/Stripe Connect/manual).
- **AC:** a client referred by an affiliate with 10% for 12 months who pays a £200 invoice generates a £20 commission item; if £50 is later refunded, a −£5 adjustment is created.

### FR-25-4 Tutor referral bonuses
- Tutors refer other tutors (E18 applications attributed) or clients; configurable bonus → E12 pay item on milestone.

## 3. Data model
`ReviewRequest`, `Review(rating, criteria JSONB, text, status, tutor, client, student, response)`, `ReferralProgram`, `ReferralCode`, `Referral(referrer, referee client, status, reward_status)`, `Affiliate`, `AffiliateLink`, `CommissionRule`, `CommissionItem`, `AffiliateStatement`.

## 4. Events
`review.requested/submitted/published`, `referral.created/converted/rewarded`, `commission.earned/clawed_back`, `affiliate_statement.issued`.

## 5. Delivery plan
- [x] **E25-T01** Review requests, submission page, moderation, aggregates.
- [x] **E25-T02** Testimonials publishing (widget E24) and Google review prompt.
- [x] **E25-T03** Client referral programme with codes, attribution and credit rewards.
- [x] **E25-T04** Affiliate records, links, attribution, portal.
- [x] **E25-T05** Commission engine with clawbacks, statements, payouts.
- [x] **E25-T06** Tutor referral bonuses.

## Temporal workflows (E32)

Implement these processes as Temporal workflows following the rules in [E32](E32-workflow-orchestration-temporal.md) (deterministic workflow code, side effects in tenant-scoped activities that call services, tenant-prefixed workflow IDs, signals for human decisions). Where the requirements above mention sweeper tasks, `next_*_at` / `resume_at` columns or retry schedules, the workflow replaces them.

- [x] **E25-TW1** Referral and review workflows (requires E32).

| Workflow | Started by | Steps, timers and signals | Replaces |
|---|---|---|---|
| `ReferralRewardWorkflow` `referral:{org}:{id}` | `referral.created` | Wait for the referee's first paid invoice / N completed lessons (signals) up to the programme deadline → fraud checks → issue credit to the referrer and discount to the referee | Milestone polling |
| `ReviewRequestWorkflow` | Trigger rule (e.g. N lessons completed) | Send request → reminder → stop on `submitted` | Reminder job |

## Implementation notes (as built 2026-10-14)
- **App:** `growth` (the name in `docs/02-architecture.md`). Every table has RLS: `ReviewRequest`, `Review`, `ReferralProgram`, `ReferralCode`, `Referral`, `Affiliate`, `AffiliateLink`, `AffiliateReferral` (a client attributed to an affiliate; not in the spec's data model, but needed for the referred-clients list), `CommissionRule`, `CommissionItem`, `AffiliateStatement` and `TutorReferral`. See ADR 0026.
  - Settings (area `growth`): review after N lessons (default 5, 0 = off), review after trials, reminder days, link expiry days, rating criteria, whether tutors see their reviews, auto-testimonials, the Google review link, public ratings in the directory, referrals on/off, attribution days, clawback days, the statement schedule (manual or monthly), the tutor bonus amounts and the tutor milestone (lessons).
  - Permissions: `growth.review.view/manage`, `growth.referral.view/manage`, `growth.affiliate.view/manage`, `growth.commission.manage`, `growth.tutor_referral.view/manage`, `portal.client.refer`, `portal.affiliate.view/profile`.
  - Role grants: coordinators manage reviews, referrals and tutor referrals and view affiliates. Finance manages affiliates, commission and tutor referrals and views referrals. Tutors see their own approved reviews and their own tutor referrals. Clients get `portal.client.refer` and affiliates `portal.affiliate.*` through their existing patterns.
- **Reviews (T01):**
  - The `lesson.completed` handler counts completed lessons per family and tutor (new `scheduling.selectors.completed_lesson_count`). At N it creates one `lessons` request per pair.
  - `trial_lesson.completed` creates a `trial` request. E14 gets a "Ask for a review" action (client, student, enquiry or lesson) and a "Trial lesson: ask for a review" recipe.
  - Staff can also send a request by hand (`POST /review-requests`) and cancel it.
  - The email link is signed with the request id and the organisation (`django.signing`), so no token is stored. The public page is `/review/{token}` in the admin app (`GET`/`POST /api/v1/public/review/{token}`).
  - A review has 1-5 stars, optional criteria (from the setting), a comment checked by the E24 profanity filter, the name to show and consent to publish.
  - Reviews go to a moderation queue (`?status=pending`): approve, hide and reply. Staff can also type a review in (`POST /reviews`).
  - Aggregates: `GET /reviews/summary` (organisation or `?tutor=`). Approved ratings feed E19 matching and take precedence over E18 referee ratings.
  - E24 directory cards gain `rating` and `review_count`, through a new `sites.selectors.register_rating_provider`, only when `growth.show_ratings_publicly` is on.
- **Testimonials and the Google prompt (T02):**
  - Publishing an approved review that the family agreed to publish, with a comment, creates or updates an E24 `Testimonial` through `sites.services.save_testimonial`. `<tt-reviews>` and the testimonials block then show it.
  - Hiding the review unpublishes the testimonial. With `growth.auto_testimonial`, approving a 4-5 star review with consent publishes it.
  - When the Google link is set, 4-5 star reviewers get it back on the thanks page (`google_prompted` is recorded).
- **Client referrals (T03):**
  - Each client (and tutor) gets an 8-character code on first use. Codes are unique across client, tutor and affiliate codes.
  - The website runtime counts `?ref=CODE` visits (`POST /public/ref`) and keeps the code for the session. A `tt_ref` cookie is set for `growth.attribution_days` only with marketing consent (deviation: the spec says "cookie"; this follows E29 consent).
  - Enquiry forms send the code as `utm.ref`; E17 now keeps that key. The `enquiry.received` handler creates the `Referral`. New families only: one referral per family, and not if the family has already paid.
  - `ReferralRewardWorkflow` (TW1) waits for the first successful payment or N completed lessons, then runs the fraud checks:
    - the same email (normalised, including Gmail dots and `+tags`), phone, billing address or saved-card fingerprint;
    - the referrer's maximum rewards per period.
  - If no check fails, it rewards:
    - The referrer gets credit through an E10 ledger adjustment, applied to open invoices. Deviation: "free lesson" is credit of the programme's reward amount, labelled as a free lesson.
    - The referee gets a percentage E06 client discount for `referee_discount_days`. Deviation: this is a client discount rule, not a promo code, so it applies without the family typing anything.
  - Referrals held by the checks wait for staff ("Reward anyway" or cancel).
  - The client portal has a "Refer a friend" page (`/portal/referrals`): link, code, offer, families referred (shortened names) and rewards earned. It is shown when a programme is active (`features.referrals`).
- **Affiliates (T04):**
  - An affiliate is an individual or organisation. It has a payout method (bank transfer file or manual) and bank details encrypted with the E12 validators.
  - A "Main link" is created with each affiliate, and more tracking links can be added (code, landing path, visit count).
  - `invite` sends an E03 invitation with the Affiliate role. The `user.joined` handler links the login.
  - An affiliate link on an enquiry attributes the client (first affiliate wins). Staff can also attribute by hand (`assign-client`).
  - The partner portal (portal app, affiliate shell) shows totals and links with copy buttons, referred clients (shortened names, dates and commission only), statements with their lines, and payout details.
- **Commission (T05):**
  - Handlers on `payment.succeeded` and `payment.refunded` add commission items. The base is the payment's collected amount (deviation: allocations aren't traced, so prepayments also count).
  - Rules: a percentage for N months (or lifetime) from attribution, with tiers by converted clients; or a fixed bounty on the client's first payment. An affiliate's own rules replace the defaults of the same kind.
  - Refunds within `growth.clawback_days` claw back at the original rate, capped at what was earned. Bounties are not clawed back.
  - Items are immutable. Corrections are `adjust` items (a financial POST).
  - Statements (`AFS-000001`) are issued from staff (`POST /affiliate-statements/issue`) or by an optional monthly Temporal Schedule. A net negative balance carries forward. They are paid with an E12 bank file (`bank-file`, new `payroll.services.external_bank_file`) or marked paid by hand.
  - Deviation: Stripe Connect payouts for affiliates are not built, because E12's Connect accounts belong to tutors.
  - The AC is tested: 10% for 12 months, a £200 payment earns £20, and a £50 refund creates −£5.
- **Tutor referral bonuses (T06):**
  - Tutors share their code from the tutor portal (`/portal/tutor/referrals`): a link for families and one for tutors (`/vacancies?ref=`).
  - Vacancy applications pass `ref` (E18 public apply now accepts it), and the `application.submitted` handler records the `TutorReferral`. Enquiries with a tutor's code record a client referral. Staff can also record and pay one by hand.
  - The bonus becomes an E12 `referral` pay item, created once through the new `source_key` on `create_manual_item`:
    - for a referred tutor: on E18 approval, or after `growth.tutor_referral_milestone_lessons` completed lessons;
    - for a referred client: on the client's first payment.
  - Amounts come from settings (whole currency units; 0 = staff decide).
- **Workflows (TW1):**
  - `ReviewRequestWorkflow` (`review-request:{org}:{request}`) sends, reminds once and expires. The `submitted` and `cancelled` signals stop it.
  - `ReferralRewardWorkflow` (`referral:{org}:{referral}`) waits until the deadline. The `milestone` signal makes it check again (an activity), so redelivered payments are harmless. `cancel` ends it.
  - `AffiliateStatementRunWorkflow` is the monthly schedule. It is synced when `growth.statement_schedule` changes.
  - Replay histories are recorded in `backend/tests/workflow_histories/`.
- **Events:** `review.requested/submitted/published`, `referral.created/converted/rewarded`, `commission.earned/clawed_back`, `affiliate_statement.issued`. They are added to the catalogue and offered as E27 webhook types like every event.
- **Notifications (E13):** `review_request` (email/SMS to the family; the reminder uses the same type) and `affiliate_statement_issued` (email to the affiliate, sent after commit).
- **Admin UI:** "Reviews & referrals" (`/growth`) has tabs for reviews (queue, approve, hide, reply, show on website), review requests, the referral programme and referrals (with fraud flags), affiliates (with links and commission rules), statements (issue, mark paid, bank file), tutor referrals and settings.
- **Not built:**
  - `demo.py` (in-product demo data), as for E20. Dev seed data is in `growth/seeds.py`.
  - E26 referral, affiliate and review reports (built later in gap batch G5; see below).
  - Portal clients can't leave reviews unprompted. Reviews come from requests or staff.

## Gap backlog (as built 2026-10-21)

Batch G5d of `docs/05-gap-backlog.md` (reporting). Details are in E26's *Gap backlog (as built 2026-10-21)* notes.

- **Referral, affiliate and review reports (FR-26-2; E25:121):** E26 standard reports `referral_performance`, `affiliate_performance` and `review_scores` in the sales family (`reporting/reports/growth.py`). They read growth data only through `growth.selectors` (`referrals`, `affiliates`, `affiliate_links`, `affiliate_referrals`, `commission_items`, `reviews`, `review_requests`), so the growth permission's data scope (all / branch via the client's branch / own) applies on top of the report family.
- No growth models, services or permissions changed.
