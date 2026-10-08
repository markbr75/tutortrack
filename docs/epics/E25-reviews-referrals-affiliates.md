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
- [ ] **E25-T01** Review requests, submission page, moderation, aggregates.
- [ ] **E25-T02** Testimonials publishing (widget E24) and Google review prompt.
- [ ] **E25-T03** Client referral programme with codes, attribution and credit rewards.
- [ ] **E25-T04** Affiliate records, links, attribution, portal.
- [ ] **E25-T05** Commission engine with clawbacks, statements, payouts.
- [ ] **E25-T06** Tutor referral bonuses.
