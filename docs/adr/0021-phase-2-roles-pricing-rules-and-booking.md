# ADR 0021: Phase 2 of identity, pricing and scheduling: custom roles, passkeys and org SSO; pricing rules outside a pure engine; room exclusion, holds and request workflows

- **Status:** Accepted
- **Date:** 2026-10-12
- **Epics:** E03 (T08, T11, T12), E06 (T07–T10), E08 (T12–T15, TW1). Builds on ADR 0002, ADR 0004, ADR 0015.

## Context
Phase 1 left out custom roles, passkeys and per-organisation SSO (E03); pay tiers, premiums,
discounts, price lists and rooms (E06); and rooms, reschedule requests, self-booking and
time-off approval (E08). These touch the permission check on every request, the price of every
lesson and the double-booking rules, so the choices below favour predictable behaviour and
small changes to code that many apps call.

## Decision
1. **Custom roles are explicit grant lists, used instead of the built-in role.**
   A `Role` stores `"codename:scope"` grants (cloned from a built-in role by expanding its
   patterns), and a membership with custom roles gets their union. `Membership.role` stays: it
   still decides staff vs portal, the 2FA-for-staff rule and tutor toggles. Custom roles carry
   no denies, so `rbac.grants_for` keeps its signature (comms staff alerts use it unchanged).
2. **Passkeys use `py_webauthn` with the relying party at `TENANT_BASE_DOMAIN`.**
   One passkey works on every organisation subdomain. A passkey is a second factor after a
   password, or a full sign-in on its own (discoverable credential, user verification
   required). Custom domains can't use passkeys.
3. **Per-organisation SSO is implemented, not delegated to allauth.**
   OIDC uses PyJWT (as ADR 0004) with discovery, token and JWKS fetches through
   `core.net.safe_urlopen`. SAML 2.0 uses `signxml` (pure Python on `lxml`) and reads only
   the signed element. Flows run on the organisation's own host. People match by IdP subject,
   then by an email in the organisation's domains. `enforce` turns off passwords there.
4. **The rate engine stays pure; rules are loaded beside it.**
   `rates.resolve_rates` gets an optional `PricingRules` (price lists, tiers, tutor rates,
   premiums, discounts, lesson and student facts). `pricing_rules.load_rules` reads the
   database; scheduling supplies each student's history because it owns lessons. Without
   rules the engine is v1, so existing callers and tests are unchanged.
5. **Modifier semantics:** priority order; a non-stackable first match applies alone;
   premiums before discounts; percentages on the line's base; lesson-level manual overrides
   are final; amounts are rounded half-up per step and never negative. Discounts are
   reported on the snapshot (`discounts`, `undiscounted_amount`) so billing can net them or
   show them as lines (`pricing.discount_display`) without the engine knowing about invoices.
6. **Room double-booking is a database constraint.**
   A GiST exclusion constraint on `(room_id, tstzrange(start, end))` for non-cancelled
   lessons, added in two migrations (nullable column first, then `btree_gist` and the
   constraint). The conflict engine reports room clashes as hard and not overridable; a race
   that reaches the database becomes the same 422.
7. **Booking holds are rows, guarded by row locks and a workflow, not a Redis lock.**
   A `BookingHold` blocks the tutor's time for slots and for staff scheduling. Holding locks
   the candidate tutors' rows. `BookingHoldWorkflow` waits for submission, payment
   (`payment_request.paid` from billing) and approval, and releases on timeout. Payment at
   booking uses the E11 hook `payments.services.request_booking_payment` (a payment request
   and the pay page), and `billing.selectors.booking_block` stops clients in collections from
   booking. No billing or payments code changed here.
8. **Requests are workflows with deadlines.**
   `RescheduleRequestWorkflow` and `TimeOffApprovalWorkflow` remind at half the window and
   decline at the deadline. Approved time off flags lessons and opens an E19 cover request
   through `matching.create_cover`. Calendar moves (E22) become reschedule requests.

## Consequences
- New dependencies: `webauthn` (with `cbor2`, `pyOpenSSL`, `pyasn1`) and `signxml` (with
  `lxml`). `uv.lock` changed.
- A cloned custom role doesn't pick up permissions that later apps add; admins add them in
  the matrix.
- Series pricing becomes per-occurrence when date-dependent rules exist. This is slower for
  long series with rules; without rules the one-batch fast path stays.
- Volume discounts apply from the lesson that reaches the threshold; earlier lessons in the
  month are not re-priced automatically (`POST /lessons/reprice` does it on request).
- SAML: encrypted assertions, IdP-initiated sign-in and single logout are not supported.
- E10 still nets discounts into `charge_amount`; showing them as separate invoice lines is
  E10's to build from the snapshot.
