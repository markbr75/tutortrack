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
- [x] **E06-T01** Subjects/levels/categories with country seed data.
- [x] **E06-T02** Services, service prices and tax rates.
- [x] **E06-T03** Locations (rooms model stubbed for Phase 2).
- [x] **E06-T04** Rate resolution engine v1 (overrides + service defaults + duration/pricing units + group modes) with trace and quote API.
- [x] **E06-T05** Products/fees catalogue.
- [x] **E06-T06** Package templates.
- [ ] **E06-T07** (Phase 2) Pay tiers, tutor service rates, bulk edit/CSV.
- [ ] **E06-T08** (Phase 2) Premium rules and holiday calendars.
- [ ] **E06-T09** (Phase 2) Discounts and promo codes; price lists.
- [ ] **E06-T10** (Phase 2) Rooms and resources.
- [x] **E06-T11** Frontend settings pages for catalogue, rates grid and quote preview.

## Implementation notes (as built 2026-10-09)
- **App:** `catalogue` holds `Category`, `Subject`, `Level`, `TaxRate`, `Service`, `ServicePrice`, `Location`, `Room` (Phase 2 stub), `Product` and `PackageTemplate`. All are `TenantModel` with RLS. Nothing is deleted: taxonomy and locations are archived (archiving a subject archives its levels), and services, products and packages are deactivated.
- **Exam boards** are a list attribute on `Subject` (`exam_boards`), not a separate `ExamBoard` model.
- **Starter data:** an `organisation.created` handler seeds categories, subjects, levels and tax rates for the organisation's country (GB, US, AU, CA, IE, NZ; other countries get the US list). Seeding is idempotent. In GB the default tax rate is "Exempt (education)". Organisations created before E06 are seeded by `make seed` (demo) or by calling `catalogue.services.seed_catalogue()` (there are no production tenants yet).
- **Tax settings:** `billing.prices_include_tax` and `billing.tax_registered` are organisation settings. The tax number stays the encrypted organisation field from E29.
- **Rates:** `RateField` (4 decimal places) for charge and pay rates. A service has one currency, set by its charge rate. `ServicePrice` adds prices in other currencies, and the quote API's `currency` picks one. A service has *either* a pay rate *or* a pay percentage (DB check constraint), plus a `pay_unit` (per hour or per lesson) that the spec didn't name. Group services choose `group_charge`: each student pays the rate, or the rate is split between students.
- **Rate engine v1** (`catalogue/rates.py`): `resolve_rates(RateContext) -> RateQuote`. Charge precedence: lesson attendee override → job student override → job charge rate → service price. Pay precedence: lesson tutor override → job tutor override → service pay rate or % of the lesson charge (shared between tutors). Per-hour pricing scales with duration. Per-lesson and per-student-per-lesson pricing does not. Per-month and per-term services are not charged per lesson (E10 subscriptions). Lines are rounded half-up per line. Split group charges use largest-remainder allocation, so the lines add up to the lesson total exactly. Tax is shown per line (inclusive or exclusive per the setting). Traces are human-readable strings in English (e.g. `"job rate £42.00/h", "90 minutes"`). `RateQuote.as_dict()` is the JSON snapshot E08 stores on lessons. Overrides arrive as inputs now. E07/E08 feed them from jobs and lessons.
- **Deferred to Phase 2 (T07–T10):** pay tiers, tutor personal rates, client price lists, premiums and holiday calendars, discounts and promo codes, and rooms. They slot into the precedence chain where the spec puts them. Percentage pay is currently based on the gross charge (there are no discounts yet).
- **Permissions:** `catalogue.view`/`catalogue.manage`, and `rates.manage` for tax rates and default service rates. Changing a service's charge or pay rate through the API needs `rates.manage`. `billing.rates.view_charge`/`view_pay` hide rate fields and the matching half of a quote. Coordinators and tutors get `catalogue.view`. Finance also gets `rates.manage`.
- **Events:** `service.created`, and `service.updated` with `rate_changed`. E08 uses `rate_changed` to offer "apply to future lessons? (N affected)". Locked lessons are never re-priced.
- **E05 follow-up:** `TutorSubject` gained nullable `catalogue_subject`/`catalogue_level` links. They are set by case-insensitive name match, or from `subject_id`/`level_id` in the subjects input. Free-text subjects remain valid. Student subjects stay as names.
- **OpenAPI fix:** money `amount` is now documented as a decimal string, which is what the API sends and accepts.
- **Frontend:** a Catalogue page with tabs for services (rates editable with `rates.manage`), subjects/levels, tax rates, locations, fees and products, packages, and a price check. The price check runs the quote API and shows charge and pay lines with their trace. There is a new shared accessible `Tabs` component in the ui package.

