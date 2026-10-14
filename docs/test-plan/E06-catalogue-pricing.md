# E06 — Service catalogue, pricing and rates: manual tests

**Scope.** Subjects and levels (seeded per country), services with pricing units and default charge/pay, tax rates, locations and rooms, fees and products, package templates, the rate engine with its explanation trace and the **Price check**, and the Phase 2 pricing rules: pay tiers and tutor rates (grid + CSV), premiums and holiday calendars, discounts and promo codes, price lists, and re-pricing of unlocked lessons. Spec: [E06](../epics/E06-catalogue-pricing.md).

**Built differently from the spec:** exam boards are a list on the subject (no ExamBoard model); nothing is deleted — taxonomy/locations are archived, services/products/packages deactivated; a service has either a pay rate or a pay percentage plus a `pay_unit` (per hour / per lesson); group services choose "each student pays" or "split"; per-month and per-term services aren't charged per lesson (E10 recurring fees); percentage pay is on the gross charge unless `pricing.pay_percent_basis` says net; lesson-level manual overrides are final (no premium/discount applies); traces are English strings; holiday import covers GB (England and Wales) and US federal holidays only.

**Common preconditions.** brightminds seeded catalogue: GB subjects/levels/tax rates (default "Exempt (education)"); services **GCSE Maths 1:1** (per hour, £45/h charge, £28/h pay, 60 or 90 min), **Piano lesson** (per lesson £25, 30 min, pay 60%), **11+ group class** (class, max 8, £20 per student per lesson, pay £35 per lesson); locations **Leeds Centre** (centre, capacity 40) and **Online**; fee **Registration fee** £30; package **10 hours of tuition** £420, valid 180 days. Admin app → **Catalogue** (`/catalogue`).

## Subjects, levels and tax

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E06-001 | Country starter data | Owner | New GB org (E02 signup) and a new US org | 1. Catalogue → **Subjects**, **Tax rates** in each. | GB: Maths with KS2, KS3, GCSE Foundation/Higher, A level…, exam boards AQA/Edexcel/OCR, default tax "Exempt (education)". US: US list (SAT etc.) and its tax rates. | P1 | backend: `tutortrack/catalogue/tests/test_catalogue.py` | |
| TP-E06-002 | Add a subject and level | Owner | — | 1. Subjects → **New subject** "Computer Science".<br>2. **Add level** "GCSE". | Listed with its level, in order. | P2 | backend: `tutortrack/catalogue/tests/test_catalogue.py` | |
| TP-E06-003 | Archive a subject archives its levels | Owner | Computer Science | 1. **Archive Computer Science**. | Subject and its levels hidden from pickers; existing records keep their link. | P2 | backend: `tutortrack/catalogue/tests/test_catalogue.py` | |
| TP-E06-004 | One default tax rate | Finance | — | 1. Tax rates → **New tax rate** "VAT 20%", 20.<br>2. **Make VAT 20% the default**. | VAT becomes Default and Exempt loses the badge (only one default). | P2 | backend: `tutortrack/catalogue/tests/test_catalogue.py` | |
| TP-E06-005 | Tax-inclusive vs exclusive prices | Finance | VAT 20% on a test service at £60; `billing.prices_include_tax` on, then off | 1. Run a price check each way. | Inclusive: line £60.00 incl. £10.00 tax. Exclusive: £60.00 + £12.00 tax. Rounded half-up per line. | P1 | backend: `tutortrack/catalogue/tests/test_rates.py` | |

## Services

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E06-006 | Create a per-hour service | Owner | — | 1. Services → **New service**: name "A level Chemistry 1:1", subject Chemistry / A level, Format One to one, pricing **Per hour**, Charge rate 50, Tutor pay **Fixed rate** 30 per hour, Lesson length 60, tax default.<br>2. **Create service**. | Listed as Active with "£50.00 per hour"; pay shown to roles with view_pay. | P1 | backend: `tutortrack/catalogue/tests/test_catalogue.py`; e2e: `e2e/catalogue.spec.ts` | |
| TP-E06-007 | Per-hour scales with duration (AC) | Owner | Service at £40/h | 1. Price check: 90 minutes. | Charge £60.00; trace includes "90 minutes". | P1 | backend: `tutortrack/catalogue/tests/test_rates.py` | |
| TP-E06-008 | Per-lesson ignores duration (AC) | Owner | Service per lesson £45 | 1. Price check: 90 minutes. | Charge £45.00. | P1 | backend: `tutortrack/catalogue/tests/test_rates.py` | |
| TP-E06-009 | Percentage pay | Owner | Piano lesson (£25, 60%) | 1. Price check Piano with tutor Nia. | Charge £25.00; pay £15.00 ("60% of charge"). | P1 | backend: `tutortrack/catalogue/tests/test_rates.py` | |
| TP-E06-010 | Group: each student pays | Owner | 11+ group class (£20 per student per lesson) | 1. Price check with 3 students. | Three charge lines of £20.00; pay one line £35.00 per lesson. | P1 | backend: `tutortrack/catalogue/tests/test_rates.py` | |
| TP-E06-011 | Group: split the rate | Owner | Small-group service, per lesson £50, **Split the rate between students** | 1. Price check with 3 students. | Lines £16.67, £16.67, £16.66 — total exactly £50.00. | P1 | backend: `tutortrack/catalogue/tests/test_rates.py` | |
| TP-E06-012 | Service validation | Owner | — | 1. Create a service with both pay rate and pay % / a negative rate / a level from another subject / max students 0 for a group. | Each refused with a field message. | P2 | backend: `tutortrack/catalogue/tests/test_catalogue.py` | |
| TP-E06-013 | Price in another currency | Finance | Add a EUR price to GCSE Maths 1:1 (`ServicePrice`) | 1. `POST /api/v1/rates/quote` with `currency: "EUR"`. | Quote uses the EUR price; GBP stays the default. | P3 | backend: `tutortrack/catalogue/tests/test_catalogue.py` | |
| TP-E06-014 | Changing a default rate offers re-pricing | Owner | GCSE Maths 1:1 with future unlocked lessons (Arjun's series) and some invoiced ones | 1. Edit charge rate to £48 and save.<br>2. Answer "apply to future lessons?" (or `POST /api/v1/lessons/reprice` dry run then apply). | Dry run reports N affected unlocked lessons; applying re-prices only those; invoiced/paid lessons unchanged. | P1 | backend: `tutortrack/catalogue/tests/test_pricing_phase2.py` | |
| TP-E06-015 | Deactivate a service | Owner | Test service | 1. Edit → status Inactive. | Hidden from new-lesson and job pickers; existing jobs keep it. | P2 | No | |

## Locations, rooms, fees and packages

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E06-016 | Add a location | Owner | — | 1. Locations → **New location** "Harrogate Library", type School, address, capacity 10. | Listed; address geocoded in the background. | P2 | backend: `tutortrack/catalogue/tests/test_catalogue.py` | |
| TP-E06-017 | Rooms with resources (Phase 2) | Owner | Leeds Centre | 1. **Rooms** → **New room** "Room 1", Location Leeds Centre, Capacity 6, Resources "Piano, Whiteboard" → **Create room**.<br>2. Try a room on **Online**. | Room listed with resources; filter by resource "Piano" finds it. Online locations can't have rooms. | P2 | backend: `tutortrack/catalogue/tests/test_pricing_phase2.py` | |
| TP-E06-018 | Fee with tutor share | Finance | — | 1. **Fees and products** → **New fee or product** "Travel fee", category Travel fee, price £8, Tutor share 100%. | Listed; available for ad hoc invoice lines (E10) and the tutor share flows to pay (E12). | P2 | backend: `tutortrack/catalogue/tests/test_catalogue.py` | |
| TP-E06-019 | Package template | Finance | — | 1. **Packages** → **New package** "5 piano lessons", Made of Lessons, Quantity 5, price £115, Valid for 90 days. | Listed as "5 lessons", "90 days"; usable for purchases in E10. | P2 | backend: `tutortrack/catalogue/tests/test_catalogue.py` | |

## Rate engine and price check

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E06-020 | Price check with trace | Owner | — | 1. **Price check**: service GCSE Maths 1:1, tutor Nia Adeyemi, student Arjun, 90 minutes → **Check price**. | **Charged to clients** £67.50 and **Paid to tutors** £42.00, each with a trace (e.g. "service rate £45.00/h", "90 minutes"). | P1 | backend: `tutortrack/catalogue/tests/test_catalogue.py`; e2e: `e2e/catalogue.spec.ts` | |
| TP-E06-021 | Job rate beats the service rate | Owner | — | 1. Price check with **Job rate (GBP)** £40, 60 min. | Charge £40.00; trace starts "job rate £40.00/h". | P1 | backend: `tutortrack/catalogue/tests/test_rates.py` | |
| TP-E06-022 | Charge precedence table | Owner | Lesson override, job student override, job rate, price list, tier charge, service | 1. Remove the most specific source one at a time (lesson override → job student → job → price list → tier (with `pricing.tier_affects_charge`) → service) and price check. | The most specific remaining source wins each time and the trace names it. | P1 | backend: `tutortrack/catalogue/tests/test_rates_phase2.py` | |
| TP-E06-023 | Pay precedence table | Owner | Lesson override, job tutor override, tutor's own rate, tier, service | 1. As above for pay. | Order: lesson → job tutor → tutor rate → tier → service rate/%. | P1 | backend: `tutortrack/catalogue/tests/test_rates_phase2.py` | |
| TP-E06-024 | Quote validation | Owner | Swagger | 1. `POST /api/v1/rates/quote` without duration; with a student from northside. | 400 "duration required"; foreign student 404. | P3 | backend: `tutortrack/catalogue/tests/test_catalogue.py` | |

## Pay tiers and tutor rates (Phase 2)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E06-025 | Create tiers and edit the grid | Finance | — | 1. **Pay tiers** → **New tier** "Associate", "Senior".<br>2. In "Pay by service and tier" set GCSE Maths 1:1: Associate £25, Senior £32 → **Save rates**. | Grid saved; cells labelled "Pay for GCSE Maths 1:1 (Senior)". | P2 | backend: `tutortrack/catalogue/tests/test_pricing_phase2.py` | |
| TP-E06-026 | CSV round trip | Finance | Grid with values | 1. **Download CSV**, change one value, **Import CSV** → **Import**.<br>2. Import a file with a bad row. | Good file: "N rates updated." Bad file: "Nothing was saved. Check rows …" and no change. | P2 | backend: `tutortrack/catalogue/tests/test_pricing_phase2.py` | |
| TP-E06-027 | Assign a tier with an effective date and re-price | Finance | Nia, future unlocked lessons | 1. Assign Nia to Senior from next Monday with recalculate (`POST /api/v1/catalogue/tier-assignments`). | Lessons from that date pay £32/h; earlier ones unchanged; locked lessons untouched. | P2 | backend: `tutortrack/catalogue/tests/test_pricing_phase2.py` | |
| TP-E06-028 | Tutor's own rate beats the tier | Finance | Tutor rate for Nia £30 on GCSE Maths | 1. Price check with Nia. | Pay £30/h; trace names the tutor rate. | P2 | backend: `tutortrack/catalogue/tests/test_pricing_phase2.py` | |

## Premiums and holidays (Phase 2)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E06-029 | Weekend premium | Owner | — | 1. **Premiums and holidays** → **New premium** "Weekend", Days Sat+Sun, Charge premium 10%, Pay premium 10% → **Create premium**.<br>2. Price check a Saturday 10:00 lesson (send `starts_at`). | Charge and pay +10%; trace "weekend premium +10%". A weekday lesson has no premium. | P1 | backend: `tutortrack/catalogue/tests/test_pricing_phase2.py` | |
| TP-E06-030 | Evening and short-notice premiums | Owner | — | 1. Premium "Late" Lessons starting from 19:00, +£5 charge.<br>2. Premium "Short notice" < 24 h, +15%. | Each applies only when its condition is met; overnight windows work. | P2 | backend: `tutortrack/catalogue/tests/test_rates_phase2.py` | |
| TP-E06-031 | Stacking and priority | Owner | Two matching premiums, the top-priority one not stackable | 1. Price check a lesson matching both. | Only the non-stackable top-priority premium applies; with both stackable, both apply. | P2 | backend: `tutortrack/catalogue/tests/test_rates_phase2.py` | |
| TP-E06-032 | Import public holidays and holiday premium | Owner | — | 1. **New holiday calendar** "England" → **Add 2026 public holidays**.<br>2. Premium "Bank holiday" **Only on public holidays** +25%.<br>3. Price check 25 December. | GB holidays added; the premium applies on holidays only. | P2 | backend: `tutortrack/catalogue/tests/test_pricing_phase2.py` | |
| TP-E06-033 | Holiday calendar skips series dates | Coordinator | Calendar marked skip lessons | 1. Create a weekly series over a bank holiday with "skip holidays". | No lesson on the holiday. | P2 | backend: `tutortrack/catalogue/tests/test_pricing_phase2.py` | |
| TP-E06-034 | Premium validation | Owner | — | 1. Create a premium with no effect, or a negative %. | Refused with a message. | P3 | backend: `tutortrack/catalogue/tests/test_pricing_phase2.py` | |

## Discounts, promo codes and price lists (Phase 2)

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E06-035 | Sibling discount | Owner | Patel family (Arjun older record, Maya second) | 1. **Discounts** → **New discount** type Sibling, 5% from the 2nd student.<br>2. Price check Maya. | Maya's charge −5% ("sibling discount -5%"); Arjun pays full price. | P1 | backend: `tutortrack/catalogue/tests/test_pricing_phase2.py` | |
| TP-E06-036 | First lesson / trial price | Owner | — | 1. Discount First lesson / trial, Trial lesson price £20.<br>2. Price check a student with no lessons, then one with lessons. | £20 for the first lesson only. | P2 | backend: `tutortrack/catalogue/tests/test_pricing_phase2.py` | |
| TP-E06-037 | Volume discount | Owner | Discount Volume: 8 lessons a month, 10% | 1. Price the 8th lesson in a month for one client. | 8th and later lessons in that month −10%; earlier lessons not re-priced. | P2 | backend: `tutortrack/catalogue/tests/test_rates_phase2.py` | |
| TP-E06-038 | Promo code rules | Owner | Promo code "SPRING10", 10%, max uses 1, new clients only | 1. Quote with `promo_code: "spring10"` for a new client.<br>2. Redeem it, then quote again; try with an existing client. | Normalised to upper case; applies once; refused for existing clients and after max uses. | P2 | backend: `tutortrack/catalogue/tests/test_pricing_phase2.py` | |
| TP-E06-039 | Discounts never raise a price | Owner | Premium + discount on one lesson | 1. Price check. | Discount applied after the premium; no line below £0; manual lesson override ignores both. | P1 | backend: `tutortrack/catalogue/tests/test_rates_phase2.py` | |
| TP-E06-040 | Discount display setting | Finance | `pricing.discount_display` = separate, then netted | 1. Issue an invoice for a discounted lesson (E10). | Separate: a negative discount line. Netted: one net line. | P3 | No | |
| TP-E06-041 | Price list for a client | Finance | — | 1. **Price lists** → **New price list** "Hillside contract", GCSE Maths 1:1 £38, client Okafor family, dates this year → **Create price list**.<br>2. Price check for Ada, inside and outside the dates. | £38/h inside the dates; service rate outside; a job rate still beats the price list. | P2 | backend: `tutortrack/catalogue/tests/test_rates_phase2.py` | |

## Permissions

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E06-042 | Catalogue is read-only without manage | Coordinator | coordinator@ | 1. Open Catalogue; try **New service**, edit a rate. | Can view (charge rates visible, pay hidden); no add/edit; API 403. | P1 | backend: `tutortrack/catalogue/tests/test_catalogue.py`; e2e: `e2e/catalogue.spec.ts` | |
| TP-E06-043 | Rates need `rates.manage` | Finance, Coordinator | — | 1. As finance@ change GCSE Maths charge rate.<br>2. As coordinator@ try the same via API. | Finance allowed; coordinator 403. | P1 | backend: `tutortrack/catalogue/tests/test_catalogue.py` | |
| TP-E06-044 | Price check hides sides by permission | Tutor, Coordinator | — | 1. Run a quote as coordinator@ and as tutor@. | Coordinator: charge side only. Tutor: pay side only (or "You can't see charge or pay rates."). | P1 | backend: `tutortrack/catalogue/tests/test_catalogue.py` | |
| TP-E06-045 | Phase 2 pricing endpoints need `rates.manage` | Coordinator | — | 1. `POST /api/v1/catalogue/premiums`, `/discounts`, `/tier-rates`. | 403. | P2 | backend: `tutortrack/catalogue/tests/test_pricing_phase2.py` | |

## Tenant isolation

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E06-046 | Catalogue lists only own organisation | Owner | Add a service "Northside Only" in northside | 1. On brightminds open every catalogue tab. | "Northside Only" and northside's rules never appear. | P1 | backend: `tutortrack/catalogue/tests/test_pricing_phase2.py` | |
| TP-E06-047 | Quote with a foreign service is 404 | Owner | Northside service ID | 1. `POST /api/v1/rates/quote` on brightminds with it. | 404. | P2 | backend: `tutortrack/catalogue/tests/test_catalogue.py` | |

## i18n, currency and edge cases

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E06-048 | Rounding is half-up per line | Owner | Per-hour £45.55, 45 minutes | 1. Price check. | £34.16 (34.1625 rounded half-up at line level), never float artefacts. | P1 | backend: `tutortrack/catalogue/tests/test_rates.py` | |
| TP-E06-049 | Zero-decimal currency | Owner | An org in JPY (or a JPY service price) | 1. Price check. | Whole yen, no decimals. | P3 | backend: `tutortrack/core/tests/test_money.py` | |
| TP-E06-050 | Per-month service is not charged per lesson | Owner | Service per month | 1. Price check. | No per-lesson charge line; billed by recurring fees (E10). | P2 | backend: `tutortrack/catalogue/tests/test_rates.py` | |
| TP-E06-051 | Currency labels follow the org | Owner | USD org | 1. Open Services. | "Default rates (USD)", $ formatting. | P3 | No | |
