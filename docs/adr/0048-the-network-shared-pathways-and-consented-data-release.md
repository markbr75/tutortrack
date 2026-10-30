# ADR 0048: The network: shared pathways, consented data release and party-scoped tables

- **Status:** Proposed (to be confirmed in E34-T04 against what is built)
- **Date:** 2026-10-30
- **Epic:** [E34](../epics/E34-network.md)
- **Builds on:** ADR 0003 (RLS and database roles), ADR 0013 (matching offers), ADR 0028
  (privacy registry and regional stacks), ADR 0031 (signed public links), ADR 0041 and 0045
  (sole traders), ADR 0047 (workflow designer)

## Context

The owner wants TutorTrack to feel like a network:

- a tutoring business shares jobs and processes with its own tutors, with other businesses
  (including sole traders) and with tutors who aren't on TutorTrack;
- a tutor applying for a posted job, or joining a job, follows a process the business sets;
- client and student information is shared only after consent.

Three facts shape the design:

- **Data isolation is strict.** Every tenant table has RLS on `app.current_org`. Only
  `platform_admin` may use the BYPASSRLS role.
- **A sole trader is already a business** (solo mode, one tutor). So sharing with a sole trader
  is sharing between two businesses.
- **The parts exist.** E19 has anonymised offers in waves, the job board, cover and shared
  shortlists. E18 has checklists, checks and click-to-sign. E29 has consent records and the
  erasure registry. E12 has self-billing statements and E28 has imported invoices.

## Decision

1. **Businesses stay separate; the network carries copies.**
   - A shared job is never one record that two businesses edit. The sharing business keeps its
     job. The partner gets its own copy, written by the partner's own services in its own
     tenant context.
   - An `Engagement` links the two by id only; there are no foreign keys across businesses.
   - Changes travel as idempotent deliveries keyed by the source event id.
2. **Network tables are party-scoped by RLS, not bypassed.**
   - A new helper, `enable_party_rls(columns)`, shows a row only when the current organisation
     is one of its parties, or in its audience.
   - Each side reads and writes network rows in its own tenant context, so no new code uses
     BYPASSRLS or `all_tenants`.
   - Personal data crosses in an encrypted `Delivery` payload, which the receiving side applies
     and then clears.
3. **Pathways are a separate engine from workflows.** (The owner's "shared processes" are
   called **pathways**, because "Processes" already names the E32 run timelines.)
   - ADR 0047 kept the workflow designer a timed sequence with no approval or human-task steps.
   - Shared pathways are checklists of human tasks, from several parties, with gates. They get
     their own simple model: a template made of stages and steps, step types from a registry,
     and one `PathwayRunWorkflow` per run.
   - A run lives in the **owning** business. Participants act on it from their own place: the
     tutor app, a partner's Network area, or a guest workspace. Partners see a projection
     (`SharedTask`) with no personal data.
   - Pathways publish events, so E33 workflows add timing and messages around them.
   - E18 recruitment stages and onboarding checklists may move onto the engine later. E34 does
     not migrate them.
4. **Release of information is a grant backed by consent.**
   - Family data has typed categories. Each `DataShareGrant` names the recipient, the job, the
     categories and the expiry, and points at E29 consent records.
   - One function, `privacy.sharing.visible`, decides what every tutor-facing and
     partner-facing serializer may return. A test checks that every such serializer uses it.
   - Ending a grant erases the partner's copies through the provider registry.
   - Consent is required across businesses even where the partner only processes data for the
     sharing business (owner decision). It is optional, per organisation, for a business's own
     tutors.
5. **Subcontracting, with money recorded but not moved.**
   - The sharing business keeps the family and pays the partner through its pay run and a
     self-billing statement. That statement becomes an imported invoice in the partner's books,
     and the payout becomes a payment. The partner's copy uses a new billing method,
     `self_billed_by_client`, so it never invoices the sharing business as well.
   - Stripe Connect transfers between businesses are out of scope.
   - Handoff for a finder's fee comes last (E34-T11).
6. **Partners and guests are tutor records of a new kind.**
   - In the sharing business, a partner is a `TutorProfile` with `kind=partner` and no
     membership. Matching, the calendar, payroll and reports therefore work unchanged.
   - A guest tutor is `kind=guest`, with a passwordless login on a new **Guest tutor** role.
7. **One region, one network.** Connections, listings and passports stay inside a regional
   stack (ADR 0028). There is no cross-region network.
8. **The open network comes last and is for verified members only.** It is free to start, behind
   a `network` plan feature, so it can be priced later.

## Consequences

- New apps `pathways` and `network`, and a new core RLS helper. Every network table needs a
  party-isolation test, in the style of `TenantIsolationTestMixin`, for both parties and a third
  business.
- Every tutor-facing serializer must route covered fields through `privacy.sharing.visible`.
  This is the widest change in the epic, and the field-coverage test guards it.
- The tutor app gains Tasks; solo mode gains a Network menu item.
- Two sets of books must agree for every engagement lesson. A Hypothesis test over attendance
  outcomes and rates guards this.
- If the engine behind pathways changes, only the interpreter and the step registry are
  affected, as with ADR 0047.
