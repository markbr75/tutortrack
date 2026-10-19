---
version: 1
slug: "apps-admin-src-layout-appshell-tsx"
primary_target: "apps/admin/src/layout/AppShell.tsx"
related_targets: ["apps/admin/src/routes/HomePage.tsx"]
---

# Admin app shell and Home

Mode: Operate. Scope: the admin app's shell (navigation, top bar, settings area, mobile menu) and Home; later stages carry the same world to the Calendar, list screens and the portal.

Audience and job: owners and coordinators at a desk for long sessions, moving between ~60 modules; find a module without scanning a flat list, see today's lessons and what needs action (unmarked lessons, money owed) the moment they arrive.

Constraints: every route and feature stays (owner, 2026-10-19); nav stays permission-gated and hides modules a tenant hasn't switched on; i18n keys for all labels; WCAG 2.2 AA in light and dark; the tenant brand colour still reaches primary buttons and accents (E24 FR-24-1); `data-route` nav sections in docs/guides stay in step (`manage.py guides --check`).

Must not feel: cold enterprise software, or a generic SaaS template.

## Direction contract

THESIS: The register is where the money starts: marking a lesson is what bills it and pays for it. Refuses the category's grey sidebar + white cards + one blue accent, and its flat list of every module.

OWN-WORLD: Bookcloth-green shell (#1E3F35) with grouped, small-caps section labels; near-white register stock ground; blue-black ink text; register-blue rules for every table and divider; one red margin rule as the signature accent (current page, "now", needs-marking); Source Sans 3 as the single family (owner chose it over Atkinson Hyperlegible Next, whose slashed zeros read badly on dates and invoices), five fixed sizes, tabular figures. Columns never move; every person carries one name plate (name, then one line of context).

STORY: The coordinator lands, sees today's register and who still needs marking, trusts the totals, and acts (mark, chase, book) without hunting through menus.

FIRST VIEWPORT: Left green rail: org name, Home, then the user guide's job groups (People, Scheduling, Lessons and learning, Money, Sales and recruitment, Communication, Insight); one Settings entry at the foot opens a settings area with its own grouped sub-menu (the admin guide's order). Top bar: search ⌘K as a field, Ask AI ⌘J, Help, notifications, account menu (Account, Sign out); on phones the rail opens as a drawer from a menu button. Home: greeting and date with Book a lesson (primary, right); one ruled money strip (revenue, outstanding, next pay run; comparison in words, no tiles or sparklines); "Today's register" table with marks and the red NOW rule separating done from to come; right column "Needs marking" and "Overdue invoices" as ruled lists (no coloured side borders).

FORM: The teacher's register and mark book, position 4 of 7 on the ordered list (assigned by the roll). seed:b87aee1c88d3986e

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance

## Signature move

Register marks: one glyph vocabulary for lesson state everywhere it appears (✓ completed in ink blue, ○ missed in red, dashed circle still to mark, struck for cancelled), plus the red margin rule marking now (today's register, the calendar's time line) and things overdue for marking.

## Raised from declined challengers

- Columns never move: tables keep a fixed order and width; values update in place (split-flap board).
- One name plate per person everywhere (character catalogue).
- Comparisons share one fixed scale and baseline across the dashboard (botanical folio).
- One family carries the whole hierarchy in five fixed sizes (bitmap specimen).
- One work area leads each screen; side panels stay subordinate (guide map).

## Stages

1. Tokens, type, shell: grouped sidebar, top bar, settings area with sub-navigation, mobile menu; Home as in the sketch.
2. Shared components (buttons, inputs, tables, cards, page headers) and the list screens (Clients, Students, Tutors…).
3. Calendar.
4. Portal shells for parents, students, tutors and affiliates (phone first, tenant brand).

Decision sketch: `.impeccable/mocks/decision/assigned.html`.
