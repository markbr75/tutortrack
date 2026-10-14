# ADR 0026: Reviews, referrals and affiliate commission in a `growth` app; money through E10/E06/E12 services; timing on Temporal

- **Status:** Accepted
- **Date:** 2026-10-14
- **Epic:** E25. Builds on ADR 0002 (Temporal), ADR 0007 (client ledger), ADR 0019 (sites registries) and ADR 0022 (billing and payments Phase 2).

## Context
E25 adds four growth tools: reviews of tutors and the business, a give/get client referral programme, affiliates who earn commission on the revenue of clients they bring, and referral bonuses for tutors.

Each tool touches money or another app's records:
- referral rewards are client credit (E10) and a discount (E06);
- testimonials are E24 records shown by `<tt-reviews>`;
- commission depends on E11 payments and refunds;
- affiliate payouts and tutor bonuses are E12 business.

The rules that had to hold:
- Apps write other apps' data only through services.
- Money is `Decimal`, rounded half-up per line, and financial records are never edited.
- Waiting ("after the first payment", "remind in four days") happens in Temporal, not in `next_*_at` columns and sweepers.
- A visitor's referral code must survive from the landing page to the enquiry form.

## Decision
1. **One app, `growth`** (the name in `docs/02-architecture.md`), owns `ReviewRequest`, `Review`, `ReferralProgram`, `ReferralCode`, `Referral`, `Affiliate`, `AffiliateLink`, `AffiliateReferral`, `CommissionRule`, `CommissionItem`, `AffiliateStatement` and `TutorReferral`. All of them are tenant tables with RLS.
2. **Money goes through the owning app's service:**
   - The referrer's reward is a negative E10 ledger adjustment (`billing.services.adjust_ledger`), then applied to open invoices. A "free lesson" reward is the same credit with a different label.
   - The referee's discount is an E06 client discount rule with a validity window (`catalogue.services.save_discount`).
   - A tutor's bonus is an E12 `referral` pay item. `payroll.services.create_manual_item` gains an optional `source_key`, so the bonus is created once.
   - Affiliate bank files use E12's bank-file writers through a new `payroll.services.external_bank_file` (payees that aren't tutors).
3. **Commission is an append-only ledger of `CommissionItem`s:**
   - Each item has a unique `source_key` (`payment:<id>:<rule>`, `bounty:<referral>:<rule>`, `refund:<refund>:<item>`), so redelivered events never double-count.
   - The base is the payment's collected amount.
   - A refund within `growth.clawback_days` creates a negative item at the original rate, capped at what is left of that commission.
   - Items are immutable (only the statement link may be set). Statements group a month's items per affiliate and currency. A net negative balance carries forward.
   - The arithmetic is pure (`growth.commission`) and property-tested with Hypothesis.
4. **Rules:** a rule with no affiliate is the default. An affiliate's own active rules replace the defaults of the same kind. Tiered rates use the affiliate's number of converted clients. "For N months" counts calendar months from attribution.
5. **Temporal (TW1):**
   - `ReviewRequestWorkflow` sends the link, reminds once and expires the request. The `submitted` and `cancelled` signals stop it.
   - `ReferralRewardWorkflow` waits for the milestone until the programme's deadline. `payment.succeeded` and `lesson.completed` send it a `milestone` signal, which makes it check again; the check is an activity. It then runs the fraud checks and gives the rewards.
   - Monthly statements are an optional per-organisation Temporal Schedule (`AffiliateStatementRunWorkflow`).
6. **Attribution:**
   - Codes are unique across client, tutor and affiliate codes, and links carry `?ref=CODE`.
   - The website runtime counts the visit (`POST /public/ref`) and keeps the code for the session. It keeps the code in a cookie for the attribution window only with marketing consent.
   - Enquiry forms send the code as `utm.ref` (E17 now keeps that key). Vacancy applications send it as `ref` (E18).
   - Handlers on `enquiry.received` and `application.submitted` create the referral, the affiliate attribution or the tutor referral. The first affiliate wins, and a family can be referred once.
7. **Testimonials reuse E24:** publishing an approved review that the family agreed to publish creates or updates a `sites.Testimonial`. Hiding the review unpublishes it. This can happen automatically for 4 and 5 star reviews with `growth.auto_testimonial`. Approved ratings feed E19 matching (they take precedence over referee ratings) and, by setting, the E24 directory through a new `sites.selectors.register_rating_provider`.

## Consequences
- No other app's tables are written. Each other app gained a small, generic, additive hook: `scheduling.selectors.completed_lesson_count`, the `payroll` additions, the `ref` UTM key, the directory rating provider and the portal feature flag.
- Affiliates are paid by bank file or manually. Stripe Connect payouts for affiliates would need connected accounts outside E12's tutor model, so they are not built.
- Commission is earned on collected cash, including prepayments. Allocations aren't traced.
- Fraud checks compare normalised emails, phone numbers, billing address and saved-card fingerprints. A held referral waits for staff ("reward anyway" or cancel).
