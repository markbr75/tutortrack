# E06 — Service Catalogue, Pricing & Rates

| | |
|---|---|
| **Phase** | MVP (pay tiers, premiums, discounts in Phase 2) |
| **Depends on** | E02, E05 |
| **Parity** | TutorCruncher charge/pay rates (job and lesson overrides); TutorBird per lesson/hour/month pricing; Teachworks wage tiers and cost premiums |

## 1. Summary
Defines what the business sells and how prices (to clients) and pay (to tutors) are calculated: subjects/levels, services, locations/rooms, tax rates, a **rate resolution engine**, pay tiers, premiums/surcharges, discounts, package templates and fees.

## 2. Functional requirements

### FR-06-1 Subjects and levels
- Two-level taxonomy (`Subject` → `Level`, e.g. Maths → KS2, KS3, GCSE Foundation, GCSE Higher, A-Level, IB HL, SAT, University). Seeded per country (UK, US, AU, CA, IE, NZ) on org creation; fully editable; archivable; ordering.
- Optional `Category` grouping (Academic, Music, Languages, Test Prep, Coding).
- Exam boards as an optional attribute list (AQA, Edexcel, OCR, IB, College Board).

### FR-06-2 Services
- Fields: name, description (internal and public), category, subject/level (optional; a generic service like "Tuition" may span subjects), format (`one_to_one | small_group | class`), max students (group), delivery mode (`in_person | online | hybrid`), default duration, allowed durations, **pricing unit** (`per_hour | per_lesson | per_student_per_lesson | per_month | per_term`), default charge rate, default pay rate (or pay % of charge), tax rate, revenue account code (E23), branch availability, bookable online (E15/E24), colour (calendar), active.
- **AC:** with a per-hour service at £40/h and a 90-minute lesson, the charge is £60.00; at per-lesson £45 a 90-minute lesson is £45.00.

### FR-06-3 Tax rates
- Org tax settings: prices inclusive or exclusive, registered for VAT/GST/sales tax, tax number.
- Tax rates: name, %, country/region, default flag, exempt reason code. UK tuition VAT exemptions are supported by the "Exempt" rate. Multiple rates per org.

### FR-06-4 Rate resolution engine
A single service function `resolve_rates(lesson_context) -> RateQuote` that returns per-attendee **charge** lines and per-tutor **pay** lines, with an explanation trace. Precedence (most specific wins):

**Charge rate:**
1. Lesson attendee manual override
2. Job student override (per student on a job)
3. Job charge rate
4. Client-specific price list (e.g. a school contract)
5. Service rate for the tutor's **pay tier** (if "tier affects charge" is on)
6. Service default charge rate
Then apply modifiers: group pricing (per-student vs split), **premiums** (FR-06-6), **discounts** (FR-06-7), duration scaling per pricing unit.

**Pay rate:**
1. Lesson tutor manual override
2. Job tutor override
3. Tutor personal rate for this service
4. Service rate for the tutor's pay tier
5. Service default pay rate, or % of charge (net of discounts? configurable)
Modifiers: premiums (pay side), group bonuses (per extra student), travel pay (E12).

- `RateQuote` is **snapshotted** onto `LessonAttendee` and `LessonTutor` when a lesson is created and re-resolved on edit until the lesson is locked (invoiced or paid).
- **AC:** the trace explains each step, e.g. `["job rate £40/h", "weekend premium +10%", "sibling discount -5%"]`, and admins see it in a lesson's "pricing" popover.
- **AC:** changing a service's default rate never changes locked lessons; for unlocked future lessons, the admin is asked "apply to future lessons? (N affected)".

### FR-06-5 Pay tiers (wage tiers)
- Tiers (e.g. Associate, Senior, Expert) with an order. Per service × tier: pay rate (and optionally charge rate).
- Tutors are assigned a tier with an effective date; tier changes apply to lessons on or after the effective date (unlocked ones), with an optional retroactive recalculation tool for unlocked lessons.
- Bulk edit via grid and CSV import/export (fixing Teachworks' limitation).

### FR-06-6 Premiums and surcharges
- Rules with conditions: day of week, time window, public holidays (holiday calendar per country/branch), short notice booking (< N hours), location type (in-person travel zone), online, specific subjects/levels, student count.
- Effect: charge +% or +fixed, and/or pay +% or +fixed. Stackable flag and priority.

### FR-06-7 Discounts
- Types: sibling (Nth student in the same client), volume (≥ N lessons in a month), first-lesson/trial price, promo codes (for online booking), client-specific % discount, scholarship/bursary.
- Discounts show as separate negative lines on invoices or are netted into the rate (org setting).

### FR-06-8 Package templates
- Template: name, services eligible, quantity in **hours** or **lessons** (or monetary credit), price, validity (days from purchase or fixed end date), tax, transferable between siblings, refundable policy, bookable online, auto-renew option (re-purchase on depletion).
- Purchase and consumption live in E10.

### FR-06-9 Fees and products
- Product/fee catalogue for ad hoc charges: registration fee, materials, books, exam entry, late-cancel fee, travel fee; price, tax, account code, category (TutorCruncher ad hoc charge categories). Optional **tutor share** (e.g. the tutor gets 100% of travel fee).

### FR-06-10 Locations and rooms
- Locations: name, type (`centre | client_home | tutor_home | school | online | other`), address, timezone, branch, capacity, opening hours.
- Rooms (Phase 2): within a location: name, capacity, resources (whiteboard, piano), bookable. Used by E08 for conflict checks.
- Client home location is derived from the student's address.

### FR-06-11 Price lists (contracts)
- Named price lists that override service rates for specific clients (e.g. a local authority contract at fixed rates), with an effective date range.

### FR-06-12 Currency
- Services can define prices per currency for multi-currency orgs; fallback is the branch currency. No automatic FX on client prices.

## 3. Data model
`Category`, `Subject`, `Level`, `ExamBoard`, `Service`, `ServicePrice(service, currency, charge_rate, pay_rate, pay_percent)`, `TaxRate`, `PayTier`, `ServiceTierRate(service, tier, pay_rate, charge_rate nullable)`, `TutorPayTierAssignment(tutor, tier, effective_from)`, `TutorServiceRate(tutor, service, pay_rate)`, `PremiumRule`, `DiscountRule`, `PromoCode`, `PackageTemplate`, `Product`, `Location`, `Room`, `RoomResource`, `PriceList`, `PriceListItem`, `HolidayCalendar`, `Holiday`.

## 4. API
CRUD for each; `POST /api/v1/rates/quote` (dry-run resolution for UI previews: given service, job, tutor, students, start/end, location → RateQuote with trace).

## 5. Permissions
`catalogue.manage`, `catalogue.view`, `rates.manage`, `billing.rates.view_charge`, `billing.rates.view_pay`.

## 6. Testing
- Table-driven tests covering each precedence level and modifier combination.
- Hypothesis tests: totals are non-negative and correctly rounded; group splits sum to the total.

## 7. Delivery plan
- [ ] **E06-T01** Subjects/levels/categories with country seed data.
- [ ] **E06-T02** Services, service prices and tax rates.
- [ ] **E06-T03** Locations (rooms model stubbed for Phase 2).
- [ ] **E06-T04** Rate resolution engine v1 (overrides + service defaults + duration/pricing units + group modes) with trace and quote API.
- [ ] **E06-T05** Products/fees catalogue.
- [ ] **E06-T06** Package templates.
- [ ] **E06-T07** (Phase 2) Pay tiers, tutor service rates, bulk edit/CSV.
- [ ] **E06-T08** (Phase 2) Premium rules and holiday calendars.
- [ ] **E06-T09** (Phase 2) Discounts and promo codes; price lists.
- [ ] **E06-T10** (Phase 2) Rooms and resources.
- [ ] **E06-T11** Frontend settings pages for catalogue, rates grid and quote preview.
